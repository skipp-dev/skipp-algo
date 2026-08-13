"""Contract tests for the live-overlay Grafana dashboard JSON.

The dashboard is currently stored in legacy Grafana v1 format (top-level
``panels``). These tests also accept the Grafana v2 shape
(apiVersion: dashboard.grafana.app/v2), where panel data lives in
``spec.elements`` (a dict keyed by "panel-N"), panel type is at
``vizConfig.group``, and options are at ``vizConfig.spec.options``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from tests._guard_corpus import live_overlay_bridge_names

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DASHBOARD_JSON = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
_ALERT_RULES_YAML = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"


def _alert_rule(uid: str) -> dict:
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    for group in rules_doc["groups"]:
        for rule in group["rules"]:
            if rule.get("uid") == uid:
                return rule
    raise AssertionError(f"missing alert rule {uid!r}")


def _iter_legacy_panels(panels: list[dict]) -> list[dict]:
    out: list[dict] = []
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        out.append(panel)
        nested = panel.get("panels")
        if isinstance(nested, list):
            out.extend(_iter_legacy_panels(nested))
    return out


def _dashboard_panels(dashboard: dict) -> list[dict]:
    """Return panel list from either Grafana v2 or legacy v1 dashboard shape."""
    if isinstance(dashboard.get("spec", {}).get("elements"), dict):
        elements = dashboard["spec"]["elements"]
        return [v["spec"] for v in elements.values() if v.get("kind") == "Panel"]
    if isinstance(dashboard.get("panels"), list):
        return _iter_legacy_panels(dashboard["panels"])
    return []


def _field_override_properties(panel: dict, field_name: str) -> dict[str, object]:
    """Return Grafana override properties keyed by property id."""
    for override in panel.get("fieldConfig", {}).get("overrides", []):
        matcher = override.get("matcher", {})
        if matcher.get("id") == "byName" and matcher.get("options") == field_name:
            return {prop["id"]: prop.get("value") for prop in override.get("properties", [])}
    return {}


# (Removed 2026-07-22: test_active_alerts_panel_no_data_filter_disabled. The
# Active Alerts panel never shipped a stateFilter, so the test only ever
# skipped — a guard that cannot fail. Post-audit the DELIBERATE contract is
# the opposite: no_data rows stay visible (a vanished series is a signal, not
# noise); README §Grafana dashboard documents this.)


def test_alert_rules_include_dedicated_news_snapshot_series_missing_rule() -> None:
    """NoData-equivalent for news snapshot must be captured by explicit absent() rule."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    groups = rules_doc["groups"]
    warning_group = next(g for g in groups if g.get("name") == "live-overlay-warning")
    rule = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-series-missing")

    assert rule["labels"]["severity"] == "warning"
    expr = rule["data"][0]["model"]["expr"]
    assert "absent(live_overlay_provider_news_snapshot_loaded" in expr
    assert "absent(live_overlay_provider_news_snapshot_age_seconds" in expr


def test_alert_rules_split_news_snapshot_missing_and_stale_coverage() -> None:
    """Both halves of the news-snapshot alert must stay present.

    Until 2026-07-31 this guarded a single combined rule
    ``lo-news-snapshot-stale-or-missing`` and skipped when it was absent. #2882
    (2026-06-21) deliberately SPLIT that rule into ``lo-news-snapshot-unavailable``
    (snapshot missing) and ``lo-news-snapshot-stale`` (snapshot too old), so the
    guard skipped for six weeks and enforced nothing. Re-anchored on the two
    successors; the severities are the ones the split actually chose — missing is
    high, stale is warning — not the combined rule's uniform warning.
    """
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    groups = rules_doc["groups"]
    warning_group = next(g for g in groups if g.get("name") == "live-overlay-warning")
    by_uid = {r.get("uid"): r for r in warning_group["rules"]}

    missing = by_uid.get("lo-news-snapshot-unavailable")
    stale = by_uid.get("lo-news-snapshot-stale")
    assert missing is not None, "snapshot-missing half of the news-snapshot alert vanished"
    assert stale is not None, "snapshot-stale half of the news-snapshot alert vanished"

    assert missing["labels"]["severity"] == "high"
    assert stale["labels"]["severity"] == "warning"
    assert "live_overlay_provider_news_snapshot_loaded" in missing["data"][0]["model"]["expr"]
    stale_expr = stale["data"][0]["model"]["expr"]
    assert "live_overlay_provider_news_snapshot_loaded" in stale_expr
    assert "live_overlay_provider_news_snapshot_age_seconds" in stale_expr


def test_state_timeline_panels_hide_threshold_range_legend() -> None:
    """State-timeline legends render threshold ranges (e.g. '< 1', '1+') as
    duplicate-looking entries; they must stay hidden since cell states already
    convey the value mappings.

    In v2 format: vizConfig.group == 'state-timeline' identifies the panel type;
    legend settings live at vizConfig.spec.options.legend.showLegend. Legacy v1
    panels carry type == 'state-timeline' and options.legend directly; both
    shapes are read below, so the pin holds for either format.

    Both former escape hatches were removed 2026-07-31: a v1-only skip (the
    dashboard has been v1 all along, so the pin never once executed) and an
    empty-list skip. Measured at removal: 7 state-timeline panels, all with
    showLegend false — the guarantee held, it was simply never checked.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    timelines = [
        p
        for p in panels
        if p.get("vizConfig", {}).get("group") == "state-timeline" or p.get("type") == "state-timeline"
    ]
    assert timelines, "no state-timeline panel found — legend pin would pass vacuously"
    for panel in timelines:
        options = panel.get("vizConfig", {}).get("spec", {}).get("options", panel.get("options", {}))
        legend = options["legend"]
        assert legend.get("showLegend") is False, panel.get("title")


def test_dashboard_has_top_level_description() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    assert dashboard.get("description"), "dashboard must have a top-level description"


def test_dashboard_panel_titles_are_unique() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    titles = [p.get("title") for p in panels if p.get("title")]
    duplicates = {t for t in titles if titles.count(t) > 1}
    assert not duplicates, f"duplicate panel titles found: {duplicates}"


def test_dashboard_panels_have_descriptions() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    missing = [p.get("title") for p in panels if p.get("type") != "row" and not p.get("description")]
    assert not missing, f"panels missing description: {missing}"


def test_market_open_request_health_uses_us_session_metric() -> None:
    """The traffic-health panel follows live_overlay_market_us_open.

    Traffic, feed and health are US-gated; the broader live_overlay_market_open
    display gauge is only for headline market-status display.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "External Consumer Traffic")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_market_us_open" in expr, expr
    assert "live_overlay_market_open" not in expr, expr


def test_market_status_description_matches_major_session_metric() -> None:
    """The Market Status panel already uses live_overlay_market_open; its
    description must not claim it is US-only.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Market Status")
    expr = panel["targets"][0]["expr"]
    description = panel.get("description", "")
    assert "live_overlay_market_open" in expr, expr
    assert "US regular" not in description or "Europe" in description, description


def test_dashboard_railway_metrics_bridge_query_shows_state_mapping() -> None:
    """Railway Metrics Bridge must distinguish DISABLED, SCRAPE ERROR, OK."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert 'bridge="railway_metrics"' in expr
    assert "or on(job) label_replace(vector(0)" in expr
    mappings = {
        int(k): v["text"]
        for m in panel["fieldConfig"]["defaults"].get("mappings", [])
        for k, v in (m.get("options") or {}).items()
    }
    assert mappings.get(0) == "DISABLED"
    assert mappings.get(1) == "SCRAPE ERROR"
    assert mappings.get(2) == "OK"


def test_dashboard_market_open_request_health_uses_fixed_rate_range() -> None:
    """stat panels must not use $__rate_interval because it depends on time range."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "External Consumer Traffic")
    expr = panel["targets"][0]["expr"]
    assert "$__rate_interval" not in expr, "stat panel must use a fixed range vector"
    assert "[5m]" in expr
    assert 'live_overlay_market_us_open{job=~"$job"}' in expr
    assert 'live_overlay_expected_market_traffic{job=~"$job"}' in expr
    assert 'live_overlay_smc_live_requests_total{job=~"$job"}[5m]' in expr
    assert "or live_overlay_market_open" not in expr
    assert "rate(live_overlay_smc_live_requests_total[5m])" not in expr


def test_dashboard_bridge_scrapes_aggregates_by_job_and_gates_enabled() -> None:
    """External Checks should use the generic bridge contract and aggregate by job."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "External Checks")
    expr = panel["targets"][0]["expr"]
    assert "min by (job)" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert "live_overlay_bridge_enabled" in expr
    assert 'bridge=~"uptimerobot|github_workflow"' in expr
    assert 'or on(job) label_replace(vector(-1), "job", "live_overlay", "", "")' in expr
    assert panel["targets"][0]["legendFormat"] == "{{job}}"
    mappings = {
        int(k): v["text"]
        for m in panel["fieldConfig"]["defaults"].get("mappings", [])
        for k, v in (m.get("options") or {}).items()
    }
    assert mappings.get(-1) == "NO CHECKS CONFIGURED"
    assert mappings.get(0) == "SCRAPE ERROR"
    assert mappings.get(1) == "OK"


def test_dashboard_railway_bridge_state_uses_enabled_plus_success() -> None:
    """Railway state panel must add enabled + scrape_success without inverted comparisons."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]

    assert 'live_overlay_bridge_enabled{job=~"$job",bridge="railway_metrics"}' in expr
    assert 'live_overlay_bridge_scrape_success{job=~"$job",bridge="railway_metrics"}' in expr
    assert "== 0" not in expr
    assert "== 1" not in expr


def test_alert_rules_include_expected_traffic_missing_alert() -> None:
    """Expected traffic alert must fire when expected traffic is absent during US open."""
    rule = _alert_rule("lo-request-rate-absent-open")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_expected_market_traffic" in expr
    assert "live_overlay_market_us_open" in expr
    assert "live_overlay_uptime_seconds" in expr
    assert "live_overlay_smc_live_requests_total" in expr
    assert "increase(" not in expr
    assert rule.get("for") in ("10m", "10")
    # Regression pin (#3096 sibling bug class): the uptime and request-rate
    # guards must gate multiplicatively. Chaining `and on(job)` with a
    # `> bool`/`< bool` operand never gates, because a bool comparison is
    # always a present series and `and` matches on series presence, not truth —
    # the rule then fired continuously through every US session regardless of
    # real traffic. Mirror the sibling `lo-request-rate-drop-open` product form.
    assert "and on(" not in expr
    assert "*" in expr
    assert "> bool 600" in expr
    assert "< bool 0.001" in expr


def test_alert_rules_arm_consumer_reminder_for_the_verified_client() -> None:
    """The reminder is active now that a real /smc_live consumer is verified.

    It was paused 2026-07-16 because no supported external client existed. On
    2026-07-23 production /metrics showed sustained traffic while the flag still
    read 0 (110 requests over 1707s uptime, 3.9 req/min measured, auth_denied=0,
    errors=0), so lo-request-rate-absent-open was gated off by
    ``expected_market_traffic == 0`` and could not have reported a client outage.
    LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC is now 1 in production, which makes this
    rule quiet; its job from here is to catch the flag being reverted to 0 while
    the consumer is still live.

    Re-pausing it is a deliberate act (the consumer was retired) and must edit
    this test in the same PR, keeping the audit trail the paused version had.
    """
    rule = _alert_rule("lo-expected-traffic-not-armed")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_expected_market_traffic" in expr
    assert "== bool 0" in expr
    assert rule["labels"]["severity"] == "warning"
    assert rule.get("for") == "15m"
    assert rule.get("isPaused") is False, (
        "a verified external consumer is live; a paused reminder cannot catch "
        "LIVE_OVERLAY_EXPECT_MARKET_TRAFFIC being reverted to 0 underneath it"
    )


def test_multi_target_stat_panels_use_field_specific_units() -> None:
    """Known mixed-unit rates must never inherit one global Grafana unit."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    assert panels, "dashboard exposes no panel — the unit checks below would pass vacuously"
    for panel in panels:
        if panel.get("type") != "stat" or len(panel.get("targets", [])) < 2:
            continue
        expected: dict[str, str] = {}
        for target in panel["targets"]:
            expr = target.get("expr", "")
            legend = target.get("legendFormat", "")
            if "rate(" in expr and "_bytes_total" in expr:
                expected[legend] = "binBps"
            elif "rate(" in expr and "_requests_total" in expr:
                expected[legend] = "reqps"
        if len(set(expected.values())) < 2:
            continue
        for field_name, unit in expected.items():
            props = _field_override_properties(panel, field_name)
            assert props.get("unit") == unit, f"{panel.get('title')}:{field_name} must use {unit}"


def test_heterogeneous_stat_panels_do_not_share_numeric_thresholds() -> None:
    """Age, count, and state fields may not share one numeric health threshold."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    heterogeneous = ("Magnitude Ledger Age (days)", "TradingView Binding Status")
    for title in heterogeneous:
        panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == title)
        defaults = panel.get("fieldConfig", {}).get("defaults", {})
        steps = defaults.get("thresholds", {}).get("steps", [])
        assert not any(step.get("value") is not None for step in steps), (
            f"{title} applies a global numeric threshold to heterogeneous fields"
        )


def test_dashboard_freshness_thresholds_match_alert_rules() -> None:
    """Dashboard red thresholds must match the alert rules users are paged on."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}

    ledger_rule_expr = _alert_rule("lo-evidence-ledger-stale")["data"][0]["model"]["expr"]
    ledger_seconds = int(re.search(r">\s*(\d+)", ledger_rule_expr).group(1))
    ledger_props = _field_override_properties(panels["Magnitude Ledger Age (days)"], "ledger age (d)")
    ledger_red = next(
        step["value"]
        for step in ledger_props["thresholds"]["steps"]
        if step.get("color") == "red"
    )
    assert ledger_red == ledger_seconds / 86400

    binding_rule_expr = _alert_rule("lo-tv-binding-snapshot-stale")["data"][0]["model"]["expr"]
    binding_seconds = int(re.search(r"> bool\s*(\d+)", binding_rule_expr).group(1))
    age_props = _field_override_properties(panels["TradingView Binding Status"], "Snapshot age")
    binding_red = next(
        step["value"] for step in age_props["thresholds"]["steps"] if step.get("color") == "red"
    )
    assert binding_red == binding_seconds / 3600

    library_rule_expr = _alert_rule("lo-pine-library-data-stale")["data"][0]["model"]["expr"]
    library_seconds = int(re.search(r"> bool\s*(\d+)", library_rule_expr).group(1))
    library_props = _field_override_properties(panels["Pine library data freshness"], "Micro-profile data age")
    library_red = next(
        step["value"] for step in library_props["thresholds"]["steps"] if step.get("color") == "red"
    )
    assert library_red == library_seconds / 86400


def test_tradingview_binding_health_fields_have_independent_colours() -> None:
    """A failed load, incomplete check, drift, or mismatch must never stay green."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(
        p for p in _dashboard_panels(dashboard) if p.get("title") == "TradingView Binding Status"
    )
    loaded = _field_override_properties(panel, "Snapshot loaded")
    loaded_mappings = loaded["mappings"][0]["options"]
    assert loaded_mappings["0"] == {"text": "NOT LOADED", "color": "red"}
    assert loaded_mappings["1"] == {"text": "LOADED", "color": "green"}

    checked = _field_override_properties(panel, "Bindings checked")
    checked_steps = checked["thresholds"]["steps"]
    assert checked_steps == [
        {"color": "red", "value": None},
        {"color": "green", "value": 108},
    ]
    for field_name in ("Drift", "Mismatches"):
        steps = _field_override_properties(panel, field_name)["thresholds"]["steps"]
        assert steps == [
            {"color": "green", "value": None},
            {"color": "red", "value": 1},
        ]

    source_known = _field_override_properties(panel, "Source check known")
    source_mappings = source_known["mappings"][0]["options"]
    assert source_mappings["0"] == {"text": "MISSING", "color": "red"}
    assert source_mappings["1"] == {"text": "VERIFIED", "color": "green"}

    source_checked = _field_override_properties(panel, "Sources checked")
    assert source_checked["thresholds"]["steps"] == [
        {"color": "red", "value": None},
        {"color": "green", "value": 8},
    ]
    assert _field_override_properties(panel, "Source drift")["thresholds"]["steps"] == [
        {"color": "green", "value": None},
        {"color": "red", "value": 1},
    ]


def test_fmp_quota_panel_thresholds_match_alert_rules() -> None:
    """The estimated quota tile and warning/critical alert ratios stay in lock-step."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(
        p for p in _dashboard_panels(dashboard) if p.get("title") == "Estimated FMP Quota Used (%)"
    )
    steps = panel["fieldConfig"]["defaults"]["thresholds"]["steps"]
    panel_thresholds = {step["color"]: step["value"] for step in steps if step.get("value") is not None}
    warning_expr = _alert_rule("lo-fmp-bandwidth-approaching")["data"][0]["model"]["expr"]
    critical_expr = _alert_rule("lo-fmp-bandwidth-critical")["data"][0]["model"]["expr"]
    assert panel_thresholds["yellow"] == float(re.search(r">\s*(0\.\d+)", warning_expr).group(1)) * 100
    assert panel_thresholds["red"] == float(re.search(r">\s*(0\.\d+)", critical_expr).group(1)) * 100


def test_hotspot_panels_explain_empty_state_and_use_request_rate_units() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in ("Most Requested Symbols", "Most Requested Timeframes"):
        panel = panels[title]
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults.get("unit") == "reqps"
        assert defaults.get("noValue") == "NO CLIENT REQUESTS"
        assert "Empty means no external client requests" in panel.get("description", "")


def test_bar_cache_panel_and_alert_use_timeframe_specific_readiness() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(
        p
        for p in _dashboard_panels(dashboard)
        if p.get("title") == "Bar cache depth and cap churn"
    )
    expressions = "\n".join(target["expr"] for target in panel["targets"])
    assert "live_overlay_requested_bar_history_readiness_ratio" in expressions
    assert "live_overlay_requested_bars_per_symbol" in expressions
    assert "live_overlay_requested_bar_symbols" in expressions

    alert_expr = _alert_rule("lo-bar-cache-depth-low")["data"][0]["model"]["expr"]
    assert "live_overlay_requested_bar_history_readiness_ratio" in alert_expr
    assert "< bool 1" in alert_expr
    assert "live_overlay_requested_bar_history_symbols" in alert_expr


def test_alert_rules_guard_uptimerobot_monitor_count_and_down_total() -> None:
    """UptimeRobot monitor alerts must gate on the generic bridge contract."""
    count_rule = _alert_rule("lo-uptimerobot-monitor-count-mismatch")
    count_expr = count_rule["data"][0]["model"]["expr"]
    assert (
        'live_overlay_bridge_enabled{job="live_overlay",bridge="uptimerobot"}'
        in count_expr
    )
    assert "live_overlay_uptimerobot_bridge_enabled" not in count_expr
    assert "live_overlay_uptimerobot_monitors_total" in count_expr
    assert "live_overlay_uptimerobot_monitors_expected" in count_expr
    assert "!= bool on(job)" in count_expr
    assert "!= bool 5" not in count_expr

    down_rule = _alert_rule("lo-uptimerobot-monitor-down")
    down_expr = down_rule["data"][0]["model"]["expr"]
    assert (
        'live_overlay_bridge_enabled{job="live_overlay",bridge="uptimerobot"}'
        in down_expr
    )
    assert "live_overlay_uptimerobot_bridge_enabled" not in down_expr
    assert "live_overlay_uptimerobot_monitors_down_total" in down_expr
    assert "> bool 0" in down_expr
    assert down_rule["labels"]["severity"] == "critical"


def test_uptimerobot_panel_shows_configured_expected_count() -> None:
    """The operator view must show actual and allowlist-derived monitor counts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(
        item
        for item in _dashboard_panels(dashboard)
        if item.get("title") == "UptimeRobot Monitors"
    )
    expressions = {target.get("expr") for target in panel.get("targets", [])}
    assert 'live_overlay_uptimerobot_monitors_total{job=~"$job"}' in expressions
    assert 'live_overlay_uptimerobot_monitors_expected{job=~"$job"}' in expressions


def test_alert_rules_use_generic_bridge_last_success_age_for_external_staleness() -> None:
    """Bridge stale alerts should use the generic last-success metric family."""
    cases = {
        "lo-uptimerobot-snapshot-stale": (
            "uptimerobot",
            "live_overlay_uptimerobot_snapshot_age_seconds",
        ),
        "lo-github-workflow-snapshot-stale": (
            "github_workflow",
            "live_overlay_github_workflow_snapshot_age_seconds",
        ),
    }
    for uid, (bridge, legacy_metric) in cases.items():
        expr = _alert_rule(uid)["data"][0]["model"]["expr"]

        assert (
            f'live_overlay_bridge_last_success_age_seconds{{job="live_overlay",bridge="{bridge}"}}'
            in expr
        )
        assert f'live_overlay_bridge_enabled{{job="live_overlay",bridge="{bridge}"}}' in expr
        assert legacy_metric not in expr


def test_dashboard_bridge_snapshot_age_panels_use_generic_contract() -> None:
    """Bridge snapshot-age panels should consume the generic last-success family."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    cases = (
        ("UptimeRobot Snapshot Age", "uptimerobot", "live_overlay_uptimerobot_snapshot_age_seconds"),
        (
            "GitHub Workflow Snapshot Age",
            "github_workflow",
            "live_overlay_github_workflow_snapshot_age_seconds",
        ),
        ("Railway Metrics Snapshot Age", "railway_metrics", "live_overlay_railway_metrics_age_seconds"),
    )
    for title, bridge, legacy_metric in cases:
        expr = panels[title]["targets"][0]["expr"]
        assert "live_overlay_bridge_last_success_age_seconds" in expr, expr
        assert f'bridge="{bridge}"' in expr, expr
        assert legacy_metric not in expr, expr


def test_alert_rules_use_railway_memory_ratio_thresholds() -> None:
    """Railway memory alerts should use usage/limit ratio instead of only static RSS."""
    warning = _alert_rule("lo-railway-memory-ratio-high")
    warning_expr = warning["data"][0]["model"]["expr"]
    assert "live_overlay_railway_service_memory_used_ratio" in warning_expr
    assert "> bool 0.75" in warning_expr
    assert "service_id" in warning_expr
    assert warning["labels"]["severity"] == "warning"

    critical = _alert_rule("lo-railway-memory-ratio-critical")
    critical_expr = critical["data"][0]["model"]["expr"]
    assert "live_overlay_railway_service_memory_used_ratio" in critical_expr
    assert "> bool 0.90" in critical_expr
    assert "service_id" in critical_expr
    assert critical["labels"]["severity"] == "critical"


def _memory_threshold(rule: dict) -> float:
    """Extract the static RSS byte-threshold (in MiB) from a threshold rule."""
    for datum in rule["data"]:
        model = datum["model"]
        if model.get("type") == "threshold":
            return float(model["conditions"][0]["evaluator"]["params"][0])
    raise AssertionError(f"no threshold condition in rule {rule.get('uid')!r}")


# Measured 7d RSS envelope per service (Railway MEMORY_USAGE_GB, 600s samples,
# probed 2026-07-15). The static thresholds below are cut ABOVE these maxima so
# legitimate steady state can never fire them.
_OBSERVED_MAX_MIB = {"signals_producer": 1514, "live_overlay": 920, "alloy": 326}


def test_signals_producer_memory_alerts_are_regression_detectors_not_oom_alarms() -> None:
    """2026-07-15: the static RSS thresholds must sit ABOVE the measured envelope.

    The 512 MiB and 768 MiB predecessors were both derived as a fraction of a
    "~1 GiB Railway tier" that never applied to this service. The real limit is
    8 GB (Railway MEMORY_LIMIT_GB=8.00 for every service in the project),
    independently corroborated by the producer sustaining >1024 MiB for ~2 days
    (2026-07-09..11, peak 1514 MiB) with no OOM — impossible under a 1 GiB
    cgroup cap, where memory.current can never exceed memory.max. Each fictional
    -tier threshold therefore landed just above legitimate steady state (~880
    MiB on 2026-07-15) and fired continuously, exactly like its predecessor.

    So these are footprint-REGRESSION detectors cut above the observed envelope.
    OOM risk is owned exclusively by the ratio alerts, which anchor to the limit
    Railway actually reports (0.75 of 8 GB ≈ 6144 MiB — 8x the old "aligned"
    768 MiB static value, which is what exposed the incoherence).
    """
    warning = _alert_rule("sp-memory-high")
    assert warning["labels"]["severity"] == "warning"
    assert _memory_threshold(warning) == 2048
    assert "2048" in warning["title"]

    critical = _alert_rule("sp-memory-critical")
    assert critical["labels"]["severity"] == "critical"
    assert _memory_threshold(critical) == 3072
    assert "3072" in critical["title"]

    for rule in (warning, critical):
        assert _memory_threshold(rule) > _OBSERVED_MAX_MIB["signals_producer"], rule["uid"]


def test_live_overlay_memory_alerts_sit_above_measured_envelope() -> None:
    """The live-overlay RSS alerts follow the same regression-detector policy
    (measured 7d envelope: p95 259 MiB, max 920 MiB)."""
    warning = _alert_rule("lo-memory-high")
    assert warning["labels"]["severity"] == "warning"
    assert _memory_threshold(warning) == 2048
    assert "2048" in warning["title"]

    critical = _alert_rule("lo-memory-critical")
    assert critical["labels"]["severity"] == "critical"
    assert _memory_threshold(critical) == 3072
    assert "3072" in critical["title"]

    for rule in (warning, critical):
        assert _memory_threshold(rule) > _OBSERVED_MAX_MIB["live_overlay"], rule["uid"]


def test_alloy_memory_alerts_sit_above_measured_envelope() -> None:
    """Alloy's 256 MiB warning sat BELOW its measured 7d p95 (310 MiB, max 326
    MiB), so it false-fired against legitimate steady state — the "Alloy should
    use < 100 MB normally" claim it rested on was never measured. Same
    fictional-anchor bug class as sp/lo; re-cut above the real envelope."""
    warning = _alert_rule("alloy-memory-high")
    assert warning["labels"]["severity"] == "warning"
    assert _memory_threshold(warning) == 1024
    assert "1024" in warning["title"]

    critical = _alert_rule("alloy-memory-critical")
    assert critical["labels"]["severity"] == "critical"
    assert _memory_threshold(critical) == 1536
    assert "1536" in critical["title"]

    for rule in (warning, critical):
        assert _memory_threshold(rule) > _OBSERVED_MAX_MIB["alloy"], rule["uid"]


def test_no_static_memory_alert_reintroduces_the_one_gigabyte_tier() -> None:
    """Regression guard: the "1 GB free tier" premise is false (real limit 8 GB)
    and produced two successive permanently-firing thresholds (512 -> 768). No
    static RSS rule may reintroduce it, and "OOM kill imminent" framing belongs
    only to the ratio alerts that anchor to the limit Railway reports."""
    for uid in (
        "sp-memory-high", "sp-memory-critical",
        "lo-memory-high", "lo-memory-critical",
        "alloy-memory-high", "alloy-memory-critical",
    ):
        text = json.dumps(_alert_rule(uid))
        assert "1 GB limit" not in text, uid
        assert "1 GiB" not in text, uid
        assert "free tier" not in text, uid
        assert "OOM kill imminent" not in text, uid


def test_dashboard_memory_thresholds_align_with_alert_policy() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}

    # 2026-07-15: 768/900 MiB -> 2048/3072 MiB, tracking the alert re-cut off the
    # fictional 1 GiB tier onto the measured envelope (real Railway limit: 8 GB).
    memory_steps = panels["Process Resident Memory"]["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert memory_steps[1]["value"] == 2048 * 1024 * 1024
    assert memory_steps[2]["value"] == 3072 * 1024 * 1024

    ratio_steps = panels["Railway Memory Used Ratio"]["fieldConfig"]["defaults"]["thresholds"]["steps"]
    assert ratio_steps[1]["value"] == 0.75
    assert ratio_steps[2]["value"] == 0.90


def test_alert_rules_include_alloy_remote_write_failure_guard() -> None:
    """Alloy must alert when remote-write starts dropping samples."""
    rule = _alert_rule("alloy-remote-write-failures")
    expr = rule["data"][0]["model"]["expr"]

    assert "increase(prometheus_remote_storage_samples_failed_total" in expr
    assert '{job="alloy"}[10m]' in expr
    assert "> 0" not in expr
    assert rule["noDataState"] == "OK"
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_include_generic_bridge_failure_alert() -> None:
    """Generic bridge failure alert must use enabled + scrape_success without configured gate."""
    rule = _alert_rule("lo-bridge-scrape-failed")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert "on(job, bridge)" in expr
    assert "== bool 1" in expr
    assert "== bool 0" in expr
    assert "live_overlay_bridge_configured" not in expr


def test_alert_rules_include_generic_bridge_stale_alert() -> None:
    """Generic bridge stale alert must return explicit zeroes for healthy bridges."""
    rule = _alert_rule("lo-bridge-last-success-stale")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_last_success_age_seconds" in expr
    assert "on(job, bridge)" in expr
    assert "== bool 1" in expr
    assert "> bool" in expr


def test_dashboard_bridge_state_panels_aggregate_by_job() -> None:
    """Bridge state panels must expose per-job state without an always-present 0 fallback."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    for title in ("UptimeRobot Bridge", "GitHub Workflow Bridge"):
        panel = next(p for p in panels if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert "max by (job)" in expr, f"{title} should aggregate by job"
        assert "+ on(job)" in expr, f"{title} should join enabled/success by job"
        assert "or on() vector(0)" in expr, f"{title} should only fallback when no bridge series exist"
        assert "or vector(0)" not in expr, f"{title} must not add an unlabeled zero series beside real data"
        assert panel["targets"][0]["legendFormat"] == "{{job}}", f"{title} should label per job"


# --------------------------------------------------------------------------- #
# Review follow-up assertions (2026-06-27)
# --------------------------------------------------------------------------- #


def test_dashboard_success_rate_panel_description_matches_http_requests() -> None:
    """Success Rate (%) must describe /smc_live HTTP request success, not compute cycles."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Success Rate (%)")
    expr = panel["targets"][0]["expr"]
    description = panel.get("description", "")
    assert "live_overlay_smc_live_success_total" in expr
    assert "live_overlay_smc_live_requests_total" in expr
    assert "HTTP" in description or "request" in description.lower()
    assert "compute cycle" not in description.lower()


def test_dashboard_has_no_restart_cause_panel_or_series() -> None:
    """The restart-cause dimension is gone (2026-07-28, B-sweep).

    LIVE_OVERLAY_RESTART_CAUSE was never set in any deploy surface, so the
    cause-labeled live_overlay_daemon_start_time_seconds gauge was the constant
    cause="unknown" — the "Restart Causes (24h)" panel was single-valued by
    construction (and a static env can never distinguish deploy from crash).
    Panel, gauge, and env are removed; restart COUNTING stays on the
    "Daemon Restarts (24h)" panel via changes() of the process start-time gauge.
    """
    dashboard_text = _DASHBOARD_JSON.read_text(encoding="utf-8")
    dashboard = json.loads(dashboard_text)
    panels = _dashboard_panels(dashboard)
    restart_cause_panels = [p for p in panels if "Restart Cause" in p.get("title", "")]
    assert not restart_cause_panels, [p.get("title") for p in restart_cause_panels]
    assert "live_overlay_daemon_start_time_seconds" not in dashboard_text
    # The count panel survives the removal.
    count_panels = [p for p in panels if p.get("title") == "Daemon Restarts (24h)"]
    assert len(count_panels) == 1
    expr = count_panels[0]["targets"][0]["expr"]
    assert "changes(live_overlay_process_start_time_seconds" in expr, expr


def test_dashboard_rows_are_either_expanded_or_contain_children() -> None:
    """Rows follow the new convention: top-level rows expanded, service-owner details collapsed.

    Detail rows keep their panels in the flat top-level list for compatibility
    with the v1 updater; collapsing the row header still reduces first-load noise.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    expanded = {"Overview", "Health", "Status", "Incident Overview", "Operational Drill-down"}
    collapsed = {
        "External Integrations",
        "Reliability Drill-down",
        "Provider Health",
        "Collector / Scrape Targets",
        "Railway Resources",
    }
    rows = [p for p in dashboard["panels"] if p.get("type") == "row"]
    titles = {r["title"] for r in rows}
    for title in expanded:
        if title in titles:
            row = next(r for r in rows if r["title"] == title)
            assert row.get("collapsed") is False, f"row {title} should be expanded"
    for title in collapsed:
        if title in titles:
            row = next(r for r in rows if r["title"] == title)
            assert row.get("collapsed") is True, f"row {title} should be collapsed"


def test_dashboard_has_process_resident_memory_panel() -> None:
    """Process resident memory must live in the Daemon Operations section and match the memory alerts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Process Resident Memory")
    assert _section_of(dashboard, "Process Resident Memory") == "Daemon Operations"
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_process_resident_memory_bytes" in expr, expr


def test_dashboard_bridge_metrics_present_counts_generic_contracts() -> None:
    """Bridge Metrics Present must count missing generic bridge contracts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Bridge Metrics Present")
    expr = panel["targets"][0]["expr"]
    families = (
        "enabled",
        "configured",
        "scrape_success",
        "error_info",
        "last_success_age_seconds",
        "last_scrape_duration_seconds",
    )
    # 2026-08-13: bridges and the expected-series count are derived from
    # metrics.py. Both were hand-written here, so a newly added bridge left the
    # panel counting the old number of series and this test still passed.
    bridges = live_overlay_bridge_names()
    assert expr.startswith(f"{len(bridges) * len(families)} - (")
    assert "group by (__name__, bridge)" in expr
    assert (
        'live_overlay_bridge_(enabled|configured|scrape_success|error_info|last_success_age_seconds|last_scrape_duration_seconds)'
        in expr
    )
    assert 'job=~"$job"' in expr
    selected = re.search(r'bridge=~"([^"]+)"', expr)
    assert selected, f"no bridge selector in {expr}"
    assert set(selected.group(1).split("|")) == set(bridges), (
        f"panel selects {selected.group(1)} but the daemon exports {bridges}"
    )
    for family in families:
        assert family in expr, f"missing family {family} in {expr}"
    assert "sum(absent(live_overlay_bridge_" not in expr
    assert " or vector(0)" not in expr
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    options: dict[str, dict[str, str]] = {}
    for mapping in mappings:
        options.update(mapping.get("options", {}))
    assert options["0"]["text"] == "PRESENT"
    assert options[str(len(bridges) * len(families))]["text"] == "ALL MISSING"
    assert "15" not in options


def test_railway_disk_panel_explains_optional_no_data_state() -> None:
    """Railway disk data can be absent even when the bridge is healthy."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Railway Disk Usage (GB)")

    description = panel.get("description", "")
    assert "DISK_USAGE_GB" in description
    assert "Railway Metrics Bridge is OK" in description
    assert "scraped as zero" in description
    assert panel["fieldConfig"]["defaults"].get("noValue") == "NO DISK DATA"


def test_dashboard_bridge_scrape_health_timeline_uses_generic_contract() -> None:
    """Bridge Scrape Health Timeline must use the generic bridge contract."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Bridge Scrape Health Timeline")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert 'bridge=~"uptimerobot|github_workflow"' in expr
    assert panel["targets"][0].get("legendFormat") == "{{bridge}}"


def test_dashboard_bridge_state_panels_use_generic_contract() -> None:
    """UptimeRobot/GitHub bridge stat panels must use the generic contract."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    for title, bridge in (
        ("UptimeRobot Bridge", "uptimerobot"),
        ("GitHub Workflow Bridge", "github_workflow"),
    ):
        panel = next(p for p in panels if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert "live_overlay_bridge_enabled" in expr
        assert "live_overlay_bridge_scrape_success" in expr
        assert f'bridge="{bridge}"' in expr
        assert "or on() vector(0)" in expr
        assert panel["targets"][0].get("legendFormat") == "{{job}}"


def test_dashboard_bridge_error_panels_use_generic_contract() -> None:
    """Bridge error panels must use the generic bridge_error_info metric."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    for title, bridge in (
        ("UptimeRobot Bridge Error", "uptimerobot"),
        ("GitHub Workflow Bridge Error", "github_workflow"),
        ("Railway Metrics Error", "railway_metrics"),
    ):
        panel = next(p for p in panels if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert "live_overlay_bridge_error_info" in expr
        assert f'bridge="{bridge}"' in expr
        assert 'error!="none"' in expr


def test_dashboard_grid_has_no_overlapping_panels() -> None:
    """All dashboard panels must occupy disjoint grid cells."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    rects = []
    for p in panels:
        gp = p.get("gridPos", {})
        rects.append((p.get("title", "?"), gp.get("x", 0), gp.get("y", 0), gp.get("w", 0), gp.get("h", 0)))
    overlaps = []
    for i, (t1, x1, y1, w1, h1) in enumerate(rects):
        for t2, x2, y2, w2, h2 in rects[i + 1 :]:
            if x1 < x2 + w2 and x1 + w1 > x2 and y1 < y2 + h2 and y1 + h1 > y2:
                overlaps.append((t1, t2))
    assert not overlaps, f"overlapping panels: {overlaps}"


def test_dashboard_active_alerts_panel_includes_infrastructure() -> None:
    """The top alert list must not filter to job=live_overlay only."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Active Alerts")
    options = panel.get("options", {})
    assert options.get("alertInstanceLabelFilter") is None, "alert list must not hide infrastructure alerts"
    assert options.get("maxItems") >= 20


def test_dashboard_market_sessions_closed_is_not_red() -> None:
    """CLOSED market sessions must not use a red color (closed market is not an incident)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Global Market Sessions")
    mappings = panel.get("fieldConfig", {}).get("defaults", {}).get("mappings", [])
    closed = None
    for mapping in mappings:
        opts = mapping.get("options", {})
        if "0" in opts:
            closed = opts["0"]
            break
    assert closed is not None
    assert closed.get("color") in {"gray", "blue", "purple"}, closed
    assert closed.get("text") == "CLOSED"


def test_dashboard_triage_guide_uses_user_impact_language() -> None:
    """The incident triage guide must speak in user-impact terms, not raw metric names."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Incident Triage Guide")
    content = panel.get("options", {}).get("content", "")
    assert "Active Alerts" in content
    assert "Runbook" in content or "README" in content
    assert "**Incident triage**" in content


def test_dashboard_job_variable_is_datasource_pinned() -> None:
    """The $job variable must use the grafanacloud-prom datasource explicitly."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    job_var = next(v for v in dashboard["templating"]["list"] if v.get("name") == "job")
    assert job_var.get("datasource") == {"type": "prometheus", "uid": "grafanacloud-prom"}


def test_dashboard_memory_threshold_matches_alert() -> None:
    """Process Resident Memory red threshold must track the critical RSS alert.

    Pinned against the rule itself rather than a literal, so the dashboard can
    never silently drift from the alert the way both did off the 1 GiB tier.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Process Resident Memory")
    steps = panel.get("fieldConfig", {}).get("defaults", {}).get("thresholds", {}).get("steps", [])
    red_step = next((s for s in steps if s.get("color") == "red"), None)
    assert red_step is not None
    critical_mib = _memory_threshold(_alert_rule("lo-memory-critical"))
    assert red_step.get("value") == critical_mib * 1024 * 1024


def test_dashboard_refresh_rate_reduced() -> None:
    """Refresh rate should be 5m to avoid query storms."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    assert dashboard.get("refresh") == "5m"


def test_dashboard_has_collector_service_metrics_row() -> None:
    """Collector service-metric panels must live in the Infrastructure section (expanded)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = next(
        p for p in dashboard["panels"]
        if p.get("type") == "row" and p.get("title") == "Infrastructure (Railway / Collector)"
    )
    assert row.get("collapsed") is False
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Service Metrics Present" in titles
    assert "Collector Resident Memory" in titles
    assert _section_of(dashboard, "Service Metrics Present") == "Infrastructure (Railway / Collector)"


def test_dashboard_latency_panel_uses_only_histogram_quantile() -> None:
    """Latency vs SLO must use histogram_quantile over exported buckets and not fall back to legacy gauges."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Request Latency Against 500 ms Target")
    exprs = {t.get("legendFormat"): t["expr"] for t in panel["targets"] if "expr" in t}

    assert "histogram_quantile(0.95" in exprs["p95"]
    assert "histogram_quantile(0.99" in exprs["p99"]
    assert "live_overlay_smc_live_latency_ms_bucket" in exprs["p95"]
    assert "live_overlay_smc_live_latency_ms_bucket" in exprs["p99"]
    assert all("live_overlay_smc_live_latency_p95_ms" not in e for e in exprs.values())
    assert all("live_overlay_smc_live_latency_p99_ms" not in e for e in exprs.values())


def test_dashboard_news_panels_split_by_unit() -> None:
    """News age and provider counts must be separate panels with correct units."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    age_panel = next(p for p in panels if p.get("title") == "News Snapshot Age")
    count_panel = next(p for p in panels if p.get("title") == "News Provider Counts")
    assert age_panel.get("fieldConfig", {}).get("defaults", {}).get("unit") == "s"
    assert count_panel.get("fieldConfig", {}).get("defaults", {}).get("unit") == "short"


def test_dashboard_collector_resident_memory_covers_prefixed_metrics() -> None:
    """Collector Resident Memory must cover alloy's bare metric plus prefixed live_overlay/signals_producer metrics."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Collector Resident Memory")
    expr = panel["targets"][0]["expr"]
    assert "process_resident_memory_bytes" in expr
    assert "live_overlay_process_resident_memory_bytes" in expr
    assert "signals_producer_process_resident_memory_bytes" in expr


def test_dashboard_ingest_queue_backpressure_separates_drop_rate_axis() -> None:
    """Ingest Queue Backpressure must show depth on the left axis and drop rate on the right."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Ingest Queue Backpressure")
    overrides = panel.get("fieldConfig", {}).get("overrides", [])
    dropped_overrides = [o for o in overrides if o.get("matcher", {}).get("options") == "dropped rate"]
    assert dropped_overrides, "missing override for dropped rate"
    prop_ids = {prop["id"] for prop in dropped_overrides[0].get("properties", [])}
    assert "custom.axisPlacement" in prop_ids, prop_ids
    assert "unit" in prop_ids, prop_ids


def test_dashboard_hotspots_timeframes_legend_uses_timeframe_label() -> None:
    """The Hotspots Timeframes panel query produces a 'timeframe' label, so the legend must use it."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Most Requested Timeframes")
    exprs = [t["expr"] for t in panel["targets"]]
    legends = [t.get("legendFormat") for t in panel["targets"]]
    assert any("label_replace" in e and '"timeframe"' in e for e in exprs), exprs
    assert all("{{timeframe}}" in legend for legend in legends), legends
    assert all("{{tf}}" not in legend for legend in legends), legends


def test_dashboard_has_no_horizontal_gaps_within_stat_rows() -> None:
    """Stat tiles packed on the same y must tile x=0 leftward with no gaps, so
    a section reads as a clean grid rather than scattered tiles."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = [p for p in _dashboard_panels(dashboard) if p.get("type") != "row"]
    by_y: dict[int, list[dict]] = {}
    for p in panels:
        by_y.setdefault(p["gridPos"]["y"], []).append(p)
    for y, row in by_y.items():
        row.sort(key=lambda p: p["gridPos"]["x"])
        cursor = 0
        for p in row:
            gp = p["gridPos"]
            assert gp["x"] == cursor, (
                f"gap/overlap at y={y}: {p.get('title')} starts at x={gp['x']}, expected {cursor}"
            )
            cursor += gp["w"]
        assert cursor <= 24, f"row at y={y} overflows 24 columns ({cursor})"


def test_latency_alert_uses_histogram_quantile_bucket() -> None:
    """p99 latency alert must query histogram buckets, not the legacy gauge."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    rule = next(r for g in rules_doc["groups"] for r in g["rules"] if r.get("uid") == "lo-latency-p99-high")
    expr = rule["data"][0]["model"]["expr"]
    assert "histogram_quantile(" in expr and "0.99" in expr
    assert "live_overlay_smc_live_latency_ms_bucket" in expr
    assert "sum by (le)" in expr
    assert "[5m]" in expr
    assert "live_overlay_smc_live_latency_p99_ms" not in expr
    assert "or vector(0)" in expr


def test_alert_rules_error_budget_burn_uses_two_windows() -> None:
    """Burn-rate alerts must evaluate both a short and a long window."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    expected_windows = {
        "lo-error-budget-burn-critical": ("[5m]", "[1h]"),
        "lo-error-budget-burn-warning": ("[30m]", "[6h]"),
    }
    for group in rules_doc["groups"]:
        for rule in group["rules"]:
            uid = rule.get("uid", "")
            if uid not in expected_windows:
                continue
            short, long = expected_windows[uid]
            expressions = [d["model"]["expr"] for d in rule["data"] if "expr" in d.get("model", {})]
            assert any(short in e for e in expressions), f"{uid} missing {short} window"
            assert any(long in e for e in expressions), f"{uid} missing {long} window"
            condition = next((d for d in rule["data"] if d.get("refId") == rule.get("condition")), {})
            condition_expr = condition.get("model", {}).get("expression", "")
            assert "$A" in condition_expr and "$B" in condition_expr, condition_expr


def test_latency_queries_guard_zero_observation_histogram() -> None:
    """Latency panels must not render NaN when no requests have been observed."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Request Latency Against 500 ms Target")
    for target in panel["targets"]:
        expr = target.get("expr", "")
        if "histogram_quantile" not in expr:
            continue
        assert "live_overlay_smc_live_latency_ms_count" in expr
        assert "or vector(0)" in expr


def test_age_alerts_use_arithmetic_not_or_between_bool_vectors() -> None:
    """Stale-age alerts must fire both when age is unknown and when it exceeds the threshold.

    ``or`` between bool-comparison vectors is dangerous because bool comparisons
    drop the metric name and ``or`` keeps the left side when both sides share the
    same label set.  The current alerts therefore use arithmetic 0/1 logic instead.
    """
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    groups = rules_doc["groups"]

    overlay = next(r for g in groups for r in g["rules"] if r.get("uid") == "lo-overlay-stale")
    overlay_expr = overlay["data"][0]["model"]["expr"]
    assert "(1 - live_overlay_overlay_age_known" in overlay_expr
    assert "* 3601" in overlay_expr
    assert " or " not in overlay_expr.replace("\n", " ")

    last_bar = next(r for g in groups for r in g["rules"] if r.get("uid") == "lo-last-bar-stale-open")
    last_bar_expr = last_bar["data"][0]["model"]["expr"]
    assert "(1 - live_overlay_last_bar_age_known" in last_bar_expr
    assert "> bool 300" in last_bar_expr
    assert " or " not in last_bar_expr.replace("\n", " ")


def test_burn_rate_panel_covers_warning_windows() -> None:
    """Error-budget burn-rate panel must visualise the warning windows 30m/6h."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Error Budget Burn Rate")
    exprs = [t.get("expr", "") for t in panel["targets"]]
    assert any("[30m]" in e for e in exprs)
    assert any("[6h]" in e for e in exprs)


def test_compute_cycle_errors_panel_has_vector_zero_guard() -> None:
    """Compute Cycle Errors panel must show 0 instead of NoData."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Compute Cycle Errors")
    for target in panel["targets"]:
        assert "or on() vector(0)" in target.get("expr", "")


def test_burn_rate_red_threshold_matches_alert() -> None:
    """Dashboard red threshold must match the critical alert threshold 14.4."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Error Budget Burn Rate")
    steps = panel.get("fieldConfig", {}).get("defaults", {}).get("thresholds", {}).get("steps", [])
    red_step = next((s for s in steps if s.get("color") == "red"), None)
    assert red_step is not None
    assert red_step.get("value") == 14.4


def test_alloy_targets_down_uses_absent_for_missing_series() -> None:
    """alloy-targets-down must fire when a target job disappears completely."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    rule = next(r for g in rules_doc["groups"] for r in g["rules"] if r.get("uid") == "alloy-targets-down")
    expr = rule["data"][0]["model"]["expr"]
    assert 'absent(up{job="signals_producer"})' in expr
    assert 'absent(up{job="live_overlay"})' in expr


def test_auth_denied_spike_has_non_zero_for() -> None:
    """Auth-denied spike alert should wait briefly to avoid single-flap paging."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    rule = next(r for g in rules_doc["groups"] for r in g["rules"] if r.get("uid") == "lo-auth-denied-spike")
    assert rule.get("for") == "2m"


# --------------------------------------------------------------------------- #
# Second UX-layout review follow-up assertions (2026-06-27)
# --------------------------------------------------------------------------- #

PROMOTED_SLO_TITLES = {
    "Success Rate (%)",
    "External Consumer Traffic",
    "Market Data Freshness",
    "Core Metrics Present",
    "Bridge Metrics Present",
    "Request Latency Against 500 ms Target",
    "Error Budget Burn Rate",
}

# --------------------------------------------------------------------------- #
# User-first section design (2026-07-07 product-owner redesign): one long
# always-expanded dashboard, sections ordered by who reads them first —
# at-a-glance status and trading evidence up top, service-owner drill-downs
# below. No collapsed rows (scrolling over clicking). These helpers assert the
# design by section membership + ordering rather than brittle exact positions.
# --------------------------------------------------------------------------- #
SECTION_ORDER = [
    "Status at a Glance",
    "Trading Evidence and Promotion Readiness",
    "Live Data Chain (Feed → Overlay → Pine)",
    "Overlay API Reliability",
    "Daemon Operations",
    "External Checks and Automation",
    "Providers (Feeds, News & Credentials)",
    "Infrastructure (Railway / Collector)",
    # #3599/#3603 follow-up: repo↔TradingView Pine-library version drift. Last
    # (bottom) because it is a low-frequency correctness signal, not a live-ops
    # feed — but it MUST be visible so a stale import pin (the ~4-month
    # micro_profiles /1-vs-/152 blind spot) surfaces instead of a silent CE10272.
    "Pine Library ↔ TradingView Versions",
    # Read-only dropdown-binding verification is the final, operator-focused
    # drill-down section and remains expanded like every other dashboard row.
    "TradingView Dropdown Bindings",
]


def _rows_in_order(dashboard: dict) -> list[dict]:
    return [
        p
        for p in sorted(dashboard["panels"], key=lambda p: p["gridPos"]["y"])
        if p.get("type") == "row"
    ]


def _section_of(dashboard: dict, title: str) -> str | None:
    """Return the section-row title whose y-band contains the given panel."""
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == title)
    py = panel["gridPos"]["y"]
    current = None
    for r in _rows_in_order(dashboard):
        if r["gridPos"]["y"] <= py:
            current = r["title"]
    return current


def test_dashboard_sections_are_user_first_and_all_expanded() -> None:
    """The 8 sections must appear in the approved user-first order, every one
    expanded (no collapsed rows — scrolling is preferred over clicking)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    rows = _rows_in_order(dashboard)
    assert rows, "dashboard exposes no section row — the checks below would pass vacuously"
    assert [r["title"] for r in rows] == SECTION_ORDER
    for r in rows:
        assert r.get("collapsed") is False, f"{r['title']} must be expanded"
        assert r.get("description"), f"{r['title']} needs a section description"


def test_dashboard_has_top_cross_link_banner() -> None:
    """A slim text banner at the very top permanently shows a described link to
    the paired Signals & Experiments dashboard (not just a hover tooltip)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    banner = next((p for p in _dashboard_panels(dashboard) if p.get("id") == 999), None)
    assert banner is not None, "top cross-link banner missing"
    assert banner["type"] == "text"
    assert banner["gridPos"]["y"] == 0
    content = banner["options"]["content"]
    assert "/d/smc-live-overlay-signals-v1" in content
    assert "Signals & Experiments" in content
    # It is the topmost panel — no section row sits above it.
    assert _rows_in_order(dashboard)[0]["gridPos"]["y"] >= banner["gridPos"]["h"]


def test_dashboard_databento_and_fmp_are_surfaced_as_providers() -> None:
    """Databento (market-data feed) and FMP credential health must be visible in
    the Providers section — a user should see the feeds they actually use."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    for title in ("Databento API Key", "Databento Delivery Age", "FMP API Key"):
        assert _section_of(dashboard, title) == "Providers (Feeds, News & Credentials)", title
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Databento Delivery Age")
    assert "databento_delivery_staleness_days" in panel["targets"][0]["expr"]


def test_dashboard_optional_provider_panels_have_explicit_not_configured_state() -> None:
    """Missing optional credential probes must not be presented as ambiguous NO DATA."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title, metric in (
        ("Databento Delivery Age", "databento_delivery_staleness_days"),
        ("Benzinga/Massive API Key", "benzinga_key_valid"),
    ):
        panel = panels[title]
        target = panel["targets"][0]
        assert metric in target["expr"]
        assert "or on() vector(-1)" in target["expr"]
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults["noValue"] == "NOT CONFIGURED"
        assert defaults["mappings"][0]["options"]["-1"]["text"] == "NOT CONFIGURED"


def test_dashboard_tradingview_credential_panels_surface_unloaded_state() -> None:
    """The TV credential panels must show NOT LOADED instead of dropping the series."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in ("TradingView Credential Status", "TradingView Credential Age"):
        panel = panels[title]
        expr = panel["targets"][0]["expr"]
        assert "or on(job,instance)" in expr
        assert "* 0 - 1" in expr
        defaults = panel["fieldConfig"]["defaults"]
        assert defaults["noValue"] == "NOT LOADED"
        assert defaults["mappings"][0]["options"]["-1"]["text"] == "NOT LOADED"


def test_dashboard_fmp_bandwidth_panels_present() -> None:
    """FMP data-VOLUME (bandwidth quota) panels must be in the Providers section
    so the FMP 90%-quota concern is visible/alertable from the dashboard."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    for title in ("Estimated FMP Quota Used (%)", "Estimated FMP Usage", "Provider Data Volume (this month)"):
        assert _section_of(dashboard, title) == "Providers (Feeds, News & Credentials)", title
    pct = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Estimated FMP Quota Used (%)")
    expr = pct["targets"][0]["expr"]
    assert "live_overlay_provider_usage_bytes" in expr
    assert "live_overlay_provider_bandwidth_limit_bytes" in expr
    assert "signals_producer_fmp_endpoint_response_bytes_total" in expr
    assert "signals_producer_fmp_response_bytes_total" not in expr


def test_dashboard_bridge_tiles_show_state_word_not_job_name() -> None:
    """The scrape-bridge tiles must show the state word only (textMode=value),
    not the meaningless Prometheus job label, and read the current instant."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    for title in ("GitHub Workflow Bridge", "UptimeRobot Bridge"):
        panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == title)
        assert panel["options"].get("textMode") == "value", title
        assert panel["targets"][0].get("instant") is True, title
        assert "scrap" in panel.get("description", "").lower(), title


def test_dashboard_traffic_wording_is_disambiguated() -> None:
    """'traffic' must never be bare: overlay-request panels must name the source
    (Pine/overlay /smc_live), so a user knows WHICH traffic is meant."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    by = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    sr = by["Success Rate (%)"]
    assert sr["fieldConfig"]["defaults"].get("noValue") != "NO TRAFFIC"
    assert "/smc_live" in sr.get("description", "")
    mth = by["External Consumer Traffic"].get("description", "").lower()
    assert "/smc_live" in mth and "external client" in mth, mth


def test_dashboard_user_impact_block_is_promoted_to_top() -> None:
    """Reliability and user-impact panels must sit in the Overlay API Reliability section,
    which is above the service-owner Daemon Operations drill-down."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    by_title = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in PROMOTED_SLO_TITLES:
        assert title in by_title, f"missing panel: {title}"
    for title in ("Success Rate (%)", "Request Latency Against 500 ms Target", "Error Budget Burn Rate"):
        assert _section_of(dashboard, title) == "Overlay API Reliability", title
    rows = {r["title"]: r["gridPos"]["y"] for r in _rows_in_order(dashboard)}
    assert rows["Overlay API Reliability"] < rows["Daemon Operations"]


def test_dashboard_title_uses_api_not_daemon() -> None:
    """Dashboard title should be approachable for stakeholders."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    assert dashboard.get("title") == "SMC Live Overlay API"


def test_dashboard_job_variable_hidden_but_effective() -> None:
    """$job should default to live_overlay and be hidden as an advanced control."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    job_var = next(v for v in dashboard["templating"]["list"] if v.get("name") == "job")
    assert job_var.get("hide") == 2
    assert job_var.get("label") == "Prometheus job (advanced)"
    assert job_var["current"]["value"] == "live_overlay"


def test_dashboard_idle_state_is_gray_not_orange() -> None:
    """Market-closed (IDLE) must not look like a warning."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    by_title = {p.get("title"): p for p in panels}
    for title in ("Overall Health", "Service Status"):
        p = by_title[title]
        mapping = p["fieldConfig"]["defaults"]["mappings"][0]["options"]["2"]
        assert mapping["color"] == "gray", f"{title} idle color is {mapping['color']}"
        threshold_step = next(s for s in p["fieldConfig"]["defaults"]["thresholds"]["steps"] if s.get("value") == 2)
        assert threshold_step["color"] == "gray", f"{title} idle threshold is {threshold_step['color']}"
    assert (
        by_title["Overall Health"]["fieldConfig"]["defaults"]["mappings"][0]["options"]["2"]["text"]
        == "IDLE (MARKET CLOSED)"
    )


def test_dashboard_incident_overview_row_renamed_and_compacted() -> None:
    """The first section row is the at-a-glance status section and holds the key
    tiles (a slim cross-link banner sits above it at the very top)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = _rows_in_order(dashboard)[0]  # lowest-y row
    assert row["title"] == "Status at a Glance"
    for title in ("Overall Health", "Active Alerts"):
        assert _section_of(dashboard, title) == "Status at a Glance", title


def test_dashboard_uptimerobot_monitor_states_moved_to_external_integrations() -> None:
    """UptimeRobot Monitor States must live inside the External Integrations section."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "UptimeRobot Monitor States")
    gp = panel["gridPos"]
    assert gp["y"] >= 80


def test_dashboard_jargon_reduced_in_top_panels() -> None:
    """Top panels must use stakeholder-friendly titles."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    titles = {p.get("title") for p in panels}
    assert "External Checks" in titles
    assert "Core Metrics Present" in titles
    assert "External Consumer Traffic" in titles
    assert "No-Data Guard (Core Metrics)" not in titles
    assert "Market-open Request Health" not in titles
    assert "Bridge Scrapes" not in titles


def test_dashboard_has_no_grid_overlaps() -> None:
    """No two visual panels may occupy the same grid cell."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = [p for p in dashboard["panels"] if p.get("type") != "row"]
    for i, a in enumerate(panels):
        ag = a["gridPos"]
        for b in panels[i + 1 :]:
            bg = b["gridPos"]
            overlap = (
                ag["x"] < bg["x"] + bg["w"]
                and bg["x"] < ag["x"] + ag["w"]
                and ag["y"] < bg["y"] + bg["h"]
                and bg["y"] < ag["y"] + ag["h"]
            )
            assert not overlap, f"{a.get('title')} overlaps {b.get('title')}"


def test_dashboard_external_details_are_not_in_incident_overview() -> None:
    """External-integration detail must live in its own section, not top status."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    assert _section_of(dashboard, "UptimeRobot Monitor States") == "External Checks and Automation"


def test_dashboard_operational_drill_down_row_exists() -> None:
    """A dedicated Daemon Operations section must hold the service-owner details."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in dashboard["panels"] if p.get("type") == "row"}
    assert "Daemon Operations" in titles


def test_dashboard_reliability_row_renamed() -> None:
    """The Daemon Operations section header must explain its restart/backpressure role."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = next(p for p in dashboard["panels"] if p.get("type") == "row" and p.get("title") == "Daemon Operations")
    assert "restart" in row.get("description", "").lower()
    assert "backpressure" in row.get("description", "").lower()


def test_dashboard_stakeholder_descriptions_put_impact_first() -> None:
    """Descriptions for top SLO panels must lead with user impact, not metric jargon."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in ("Core Metrics Present", "Market Data Freshness", "Overlay Fresh"):
        desc = panels[title].get("description", "")
        assert desc.startswith("Can") or desc.startswith("Are") or desc.startswith("Is"), (
            f"{title} description does not lead with user impact: {desc[:80]}"
        )


def test_dashboard_triage_guide_has_quick_links() -> None:
    """The triage guide must surface direct links to logs, deploys and runbooks."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    content = panels["Incident Triage Guide"].get("options", {}).get("content", "")
    assert "Railway logs" in content
    assert "Railway deployments" in content
    assert "Runbook" in content


# --------------------------------------------------------------------------- #
# Third UX-layout review follow-up assertions (2026-06-28)
# --------------------------------------------------------------------------- #


def test_dashboard_incident_rows_have_descriptions() -> None:
    """Row headers must explain their purpose for 3-a.m. triage."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    required = set(SECTION_ORDER)
    rows = {p["title"]: p for p in dashboard["panels"] if p.get("type") == "row"}
    for title in required:
        assert rows[title].get("description"), title


def test_dashboard_top_incident_path_is_above_drilldown() -> None:
    """All top-level incident signal panels must appear before Operational Drill-down."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    y = {p["title"]: p["gridPos"]["y"] for p in _dashboard_panels(dashboard) if "title" in p}

    rows = {r["title"]: r["gridPos"]["y"] for r in _rows_in_order(dashboard)}
    drilldown_start = rows["Daemon Operations"]
    for title in (
        "Overall Health",
        "Active Alerts",
        "Success Rate (%)",
        "External Consumer Traffic",
        "Market Data Freshness",
        "Core Metrics Present",
        "Request Latency Against 500 ms Target",
        "Error Budget Burn Rate",
        "External Consumer Watchdog",
    ):
        assert y[title] < drilldown_start, title


def test_dashboard_top_tiles_have_drilldown_links() -> None:
    """External Checks and Core Metrics Present must link to related detail rows."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in ("External Checks", "Core Metrics Present"):
        links = panels[title].get("links") or []
        assert links, f"{title} is missing drilldown links"
        assert all(link.get("targetBlank") for link in links), f"{title} drilldown should open in new tab"


# --------------------------------------------------------------------------- #
# Fourth UX-layout review follow-up assertions (2026-06-29)
# --------------------------------------------------------------------------- #


def test_dashboard_triage_guide_links_are_known() -> None:
    """Triage-guide links must point at existing repo docs or concrete consoles."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    content = panels["Incident Triage Guide"].get("options", {}).get("content", "")
    known_urls = {"https://github.com/skipp-dev/skipp-algo/actions"}
    links = list(re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", content))
    assert links, "the triage guide links nowhere — the URL checks below would pass vacuously"
    for m in links:
        url = m.group(2)
        assert "REPLACE_" not in url, f"placeholder Railway URL leaked into dashboard: {url}"
        if url.startswith("https://github.com/skipp-dev/skipp-algo/blob/main/"):
            rel = url.replace("https://github.com/skipp-dev/skipp-algo/blob/main/", "")
            assert (_REPO_ROOT / rel).exists(), f"missing repo file: {rel}"
        elif "railway.com/project/" in url:
            # Service-scoped Railway console links generated by the updater.
            assert "/service/" in url, f"Railway URL must be service-scoped: {url}"
            assert "environmentId=" in url, f"Railway URL must include environment: {url}"
        elif url in known_urls:
            pass
        else:
            pytest.fail(f"unexpected triage-guide URL: {url}")


def test_dashboard_drilldown_links_target_real_panels() -> None:
    """Any panel link that uses a viewPanel ID must point to an existing panel."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    assert panels, "dashboard exposes no panel — the link checks below would pass vacuously"
    valid_ids = {p.get("id") for p in panels if "id" in p}
    for panel in panels:
        for link in panel.get("links", []) + panel.get("fieldConfig", {}).get("defaults", {}).get("links", []):
            url = link.get("url", "")
            m = re.search(r"viewPanel=(\d+)", url)
            if m:
                assert int(m.group(1)) in valid_ids, f"{panel.get('title')} -> {url}"


def test_dashboard_detail_rows_are_marked_as_service_owner_details() -> None:
    """Detail rows must explicitly describe themselves as service-owner details."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    detail_rows = {
        "Overlay API Reliability", "Daemon Operations",
        "External Checks and Automation", "Providers (Feeds, News & Credentials)",
        "Infrastructure (Railway / Collector)",
    }
    rows = {p["title"]: p for p in dashboard["panels"] if p.get("type") == "row"}
    for title in detail_rows:
        desc = rows[title].get("description", "")
        assert "service-owner detail" in desc.lower(), f"{title}: {desc}"


# --------------------------------------------------------------------------- #
# Signals-producer readiness panels and alerts
# --------------------------------------------------------------------------- #


def test_dashboard_has_signal_pipeline_ready_panel() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Signal Pipeline Ready" in titles


def test_dashboard_signal_pipeline_ready_panel_uses_boolean_expression() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Signal Pipeline Ready")
    expr = panel["targets"][0]["expr"]
    assert "signals_producer_watchlist_symbols" in expr
    assert "signals_producer_open_prep_snapshot_loaded" in expr
    assert "signals_producer_last_poll_age_seconds" in expr
    assert "bool" in expr
    # Age==0 (before first poll) must not be treated as ready; missing series
    # must fall back via label-safe vector so the panel never goes blank.
    assert "clamp_min" not in expr
    assert " or on() vector(" in expr


def test_dashboard_signal_pipeline_ready_absent_series_render_unknown_not_not_ready() -> None:
    """An absent signals_producer target must read UNKNOWN, not NOT READY.

    The readiness verdict is a product of three ``signals_producer`` series. If
    the whole target disappears (scrape down, job-label mismatch, exporter not
    serving) the product is an empty vector and only the outer fallback renders.
    With ``vector(0)`` that fallback claimed a *functional* verdict — "the
    pipeline is not ready" — for what is a telemetry failure, blaming the
    producer for a collector outage and erasing the distinction operators need.

    ``vector(-1)`` + an explicit UNKNOWN mapping keeps the panel populated (no
    NO DATA blank) while attributing the gap honestly. Paging is unchanged:
    sp-scrape-down covers the absent target, and sp-watchlist-empty /
    sp-snapshot-missing / sp-poll-stale each carry ``or on() vector(1)``.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Signal Pipeline Ready")
    expr = panel["targets"][0]["expr"]
    assert expr.rstrip().endswith("or on() vector(-1)"), (
        f"absent-series fallback must be the sentinel -1, not a functional verdict; got {expr!r}"
    )
    assert " or on() vector(0)" not in expr

    mapped = {}
    for mapping in panel["fieldConfig"]["defaults"]["mappings"]:
        if mapping.get("type") == "value":
            mapped.update(mapping.get("options", {}))
    assert mapped["-1"]["text"] == "UNKNOWN", "the -1 sentinel must render as UNKNOWN, not as a bare number"
    assert mapped["-1"]["color"] != "green", "unknown telemetry must never render as a healthy colour"
    # The real verdicts must keep their meaning.
    assert mapped["0"]["text"] == "NOT READY"
    assert mapped["1"]["text"] == "READY"


def test_dashboard_open_prep_snapshot_panel_uses_label_safe_fallback() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Open-Prep Snapshot")
    expr = panel["targets"][0]["expr"]
    assert " or on() vector(0)" in expr


def test_dashboard_watchlist_symbols_panel_uses_label_safe_fallback() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Watchlist Symbols")
    expr = panel["targets"][0]["expr"]
    assert " or on() vector(0)" in expr


def test_dashboard_producer_poll_age_panel_uses_label_safe_fallback() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Producer Poll Age")
    expr = panel["targets"][0]["expr"]
    assert " or on() vector(999999)" in expr


def test_dashboard_has_open_prep_snapshot_panel() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Open-Prep Snapshot" in titles


def test_dashboard_has_watchlist_symbols_panel() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Watchlist Symbols" in titles


def test_dashboard_has_producer_poll_age_panel() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Producer Poll Age" in titles


def test_dashboard_signal_readiness_panels_are_grouped() -> None:
    """The four signal-readiness tiles must stay grouped together inside the
    Live Data Chain section (same row band), not scattered."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    names = ("Signal Pipeline Ready", "Open-Prep Snapshot", "Watchlist Symbols", "Producer Poll Age")
    readiness = [p for p in _dashboard_panels(dashboard) if p.get("title") in names]
    assert len(readiness) == 4
    for panel in readiness:
        assert _section_of(dashboard, panel["title"]) == "Live Data Chain (Feed → Overlay → Pine)"
    ys = {p["gridPos"]["y"] for p in readiness}
    assert max(ys) - min(ys) <= max(p["gridPos"]["h"] for p in readiness), (
        f"readiness tiles are not grouped on one band: y={sorted(ys)}"
    )


def test_main_dashboard_has_compact_linked_signal_summary() -> None:
    """The operations board mirrors only the three decision-critical facts.

    Full rankings and per-symbol details belong exclusively on the paired
    Signals & Experiments dashboard.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    names = ("Active Signals", "Strongest Signal", "Signal Snapshot Age")

    assert all(name in panels for name in names)
    assert all(
        _section_of(dashboard, name) == "Live Data Chain (Feed → Overlay → Pine)"
        for name in names
    )
    assert {panels[name]["gridPos"]["y"] for name in names} == {46}
    assert sorted(
        (panels[name]["gridPos"]["x"], panels[name]["gridPos"]["w"])
        for name in names
    ) == [(0, 8), (8, 8), (16, 8)]

    for name in names:
        links = panels[name].get("links", [])
        assert any("/d/smc-live-overlay-signals-v1" in link.get("url", "") for link in links)
        assert all(link.get("targetBlank") for link in links)

    active_expr = panels["Active Signals"]["targets"][0]["expr"]
    assert "live_overlay_trading_signals_active" in active_expr
    assert "live_overlay_trading_signals_snapshot_age_known" in active_expr

    strongest = panels["Strongest Signal"]
    assert strongest["targets"][0]["expr"].startswith(
        'topk(1, live_overlay_trading_signal_score{job=~"$job"})'
    )
    assert "{{symbol}}" in strongest["targets"][0]["legendFormat"]
    assert strongest["options"]["textMode"] == "value_and_name"

    age_expr = panels["Signal Snapshot Age"]["targets"][0]["expr"]
    assert "live_overlay_trading_signals_snapshot_age_seconds" in age_expr
    assert "live_overlay_trading_signals_snapshot_age_known" in age_expr
    assert panels["Signal Snapshot Age"]["fieldConfig"]["defaults"]["unit"] == "s"

    for detail_title in (
        "Signal Strength - Live Ranking (now)",
        "Top Trading Signals — Latest Detail",
        "Signal Score — Active Symbols",
    ):
        assert detail_title not in panels


def test_alert_rules_include_signals_producer_readiness_group() -> None:
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    group_names = [g.get("name") for g in rules_doc["groups"]]
    assert "signals-producer-readiness" in group_names


def test_alert_rules_watchlist_empty_uses_watchlist_symbols() -> None:
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "signals-producer-readiness")
    rule = next(r for r in group["rules"] if r.get("uid") == "sp-watchlist-empty")
    expr = rule["data"][0]["model"]["expr"]
    assert "signals_producer_watchlist_symbols" in expr
    assert "== bool 0" in expr, "alert must fire when the metric is missing or zero"
    assert "or on() vector(1)" in expr, "label-safe fallback required for missing series"
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_snapshot_missing_uses_snapshot_loaded() -> None:
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "signals-producer-readiness")
    rule = next(r for r in group["rules"] if r.get("uid") == "sp-snapshot-missing")
    expr = rule["data"][0]["model"]["expr"]
    assert "signals_producer_open_prep_snapshot_loaded" in expr
    assert "or on() vector(1)" in expr, "label-safe fallback required for missing series"
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_poll_stale_uses_last_poll_age() -> None:
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    group = next(g for g in rules_doc["groups"] if g.get("name") == "signals-producer-readiness")
    rule = next(r for r in group["rules"] if r.get("uid") == "sp-poll-stale")
    expr = rule["data"][0]["model"]["expr"]
    assert "signals_producer_last_poll_age_seconds" in expr
    assert "300" in expr
    assert "> bool 300" in expr, "alert must fire when the metric is missing or stale"
    assert "or on() vector(1)" in expr, "label-safe fallback required for missing series"
    assert rule["labels"]["severity"] == "warning"


# --------------------------------------------------------------------------- #
# Fifth UX-layout review follow-up assertions (2026-06-30)
# --------------------------------------------------------------------------- #


def test_dashboard_signal_pipeline_ready_links_to_concrete_detail_panels() -> None:
    """Signal Pipeline Ready drilldowns must target concrete signal-pipeline panels."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    by_title = {p.get("title"): p for p in panels}
    by_id = {str(p.get("id")): p for p in panels if p.get("id") is not None}

    panel = by_title.get("Signal Pipeline Ready")
    assert panel is not None, "Signal Pipeline Ready panel missing from dashboard"
    links = panel.get("links") or []
    assert links, "Signal Pipeline Ready needs at least one drilldown link"
    assert all(link.get("targetBlank") for link in links), "drilldown links should open in a new tab"
    urls = {link.get("url", "") for link in links}

    expected = {
        "2165782568": "signals_producer_open_prep_snapshot_loaded",
        "2165782569": "signals_producer_watchlist_symbols",
        "2165782570": "signals_producer_last_poll_age_seconds",
        "2133310723": "live_overlay_health_status_code|signals_producer_watchlist_symbols",
    }
    for panel_id, metric in expected.items():
        assert any(f"viewPanel={panel_id}" in url for url in urls), f"missing drilldown to panel {panel_id}"
        target_panel = by_id.get(panel_id)
        assert target_panel is not None, f"drilldown target panel {panel_id} missing"
        targets = target_panel.get("targets", [])
        exprs = " ".join(t.get("expr", "") for t in targets)
        assert metric in exprs, f"panel {panel_id} does not contain expected metric {metric!r}"

    assert not any("viewPanel=2133310722" in url for url in urls), "legacy row-header link still present"
    assert not any("viewPanel=1580287418" in url for url in urls), (
        "legacy live-overlay readiness timeline link still present"
    )
    assert any("/service/" in url for url in urls), "missing service-scoped Railway link"


def test_dashboard_triage_guide_includes_signal_pipeline_path() -> None:
    """The 3-a.m. guide must include the new signal-producer readiness action path."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    content = panels["Incident Triage Guide"].get("options", {}).get("content", "")
    assert "Signal Pipeline Ready" in content
    assert "Open-Prep Snapshot" in content
    assert "Producer Poll Age" in content


def test_dashboard_market_traffic_health_explains_us_market_context() -> None:
    """The description must spell out the US market open/closed context."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "External Consumer Traffic")
    expr = panel["targets"][0]["expr"]
    description = panel.get("description", "").lower()
    assert "live_overlay_market_us_open" in expr
    assert "us" in description or "u.s." in description, description
    assert "market" in description or "trading" in description, description
    assert "closed" in description or "session" in description or "hours" in description, description
    assert "europe" not in description, description


def test_dashboard_no_row_is_collapsed() -> None:
    """Redesign contract: every section is expanded so content is visible by
    scrolling — no click-to-expand tabs (2026-07-07 product-owner decision)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    rows = _rows_in_order(dashboard)
    assert rows, "dashboard exposes no section row — the checks below would pass vacuously"
    for row in rows:
        assert row.get("collapsed") is False, f"{row['title']} must not be collapsed"
        assert not row.get("panels"), (
            f"{row['title']} must not nest panels (expanded rows keep panels at top level)"
        )


def test_dashboard_external_integration_details_are_co_located() -> None:
    """External-integration detail panels must live inside the External Integrations section."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    for title in ("Bridge Scrape Health Timeline", "GitHub Workflows — Latest Run Detail"):
        assert _section_of(dashboard, title) == "External Checks and Automation", title


def test_dashboard_external_checks_ignores_unconfigured_bridges() -> None:
    """Unconfigured bridges must show NO CHECKS CONFIGURED, not SCRAPE ERROR."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "External Checks")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_scrape_success" in expr
    assert "live_overlay_bridge_enabled" in expr
    assert 'bridge=~"uptimerobot|github_workflow"' in expr
    assert "vector(-1)" in expr, expr
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    options_keys = {k for m in mappings for k in m.get("options", {})}
    assert "-1" in options_keys, options_keys
    labels = {v["text"] for m in mappings for v in (m.get("options") or {}).values()}
    assert "NO CHECKS CONFIGURED" in labels, labels


def test_dashboard_market_data_freshness_hides_when_market_closed() -> None:
    """Market Data Freshness: closed market renders MARKET CLOSED via the
    presence-gated -1 mapping; noValue is reserved for a dead exporter and
    must not claim the market is closed (audit: noValue double duty)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Market Data Freshness")
    expr = panel["targets"][0]["expr"]
    assert "unless on()" in expr, expr
    assert 'sum_over_time(live_overlay_market_us_open{job=~"$job"}[1h:]) == 0' in expr
    assert panel["fieldConfig"]["defaults"].get("noValue") == "NO DATA"


def test_dashboard_core_metrics_present_checks_critical_series() -> None:
    """Core Metrics Present must detect missing critical series, not just uptime."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Core Metrics Present")
    expr = panel["targets"][0]["expr"]
    assert "absent(live_overlay_uptime_seconds" in expr
    assert "absent(live_overlay_overlay_fresh" in expr
    assert "absent(live_overlay_feed_healthy" in expr
    assert "absent(live_overlay_workers_healthy" in expr
    assert "absent(live_overlay_market_us_open" in expr
    assert "absent(live_overlay_last_bar_age_known" in expr
    assert "absent(live_overlay_smc_live_requests_total" in expr
    assert "absent(live_overlay_smc_live_success_total" in expr
    assert "absent(live_overlay_smc_live_errors_total" in expr
    assert "absent(live_overlay_smc_live_latency_ms_count" in expr


def test_dashboard_traffic_alert_armed_tile_uses_expected_market_traffic() -> None:
    """External Consumer Watchdog shows rollout intent in the top incident row."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    panel = panels["External Consumer Watchdog"]
    assert _section_of(dashboard, "External Consumer Watchdog") == "Status at a Glance"
    expr = panel["targets"][0]["expr"]
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    labels = {v["text"]: v["color"] for m in mappings for v in (m.get("options") or {}).values()}

    assert expr == 'live_overlay_expected_market_traffic{job=~"$job"}'
    assert panel["targets"][0]["legendFormat"] == "expected_market_traffic"
    assert panel["targets"][0]["instant"] is True
    assert labels["NO CONSUMER EXPECTED"] == "gray"
    assert labels["CONSUMER EXPECTED"] == "dark-green"
    assert panel["fieldConfig"]["defaults"].get("noValue") == "NO SIGNAL"
    rows = {r["title"]: r["gridPos"]["y"] for r in _rows_in_order(dashboard)}
    assert panel["gridPos"]["y"] < rows["Daemon Operations"]


def test_dashboard_railway_bridge_shows_generic_contract() -> None:
    """Railway Metrics Bridge must use the generic bridge contract."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert 'bridge="railway_metrics"' in expr
    for legacy_metric in (
        "live_overlay_railway_metrics_configured",
        "live_overlay_railway_metrics_scrape_success",
        "live_overlay_railway_metrics_enabled",
    ):
        assert legacy_metric not in expr, expr
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    options_keys = {k for m in mappings for k in m.get("options", {})}
    assert {"0", "1", "2"}.issubset(options_keys), options_keys
    labels = {v["text"] for m in mappings for v in (m.get("options") or {}).values()}
    assert {"DISABLED", "SCRAPE ERROR", "OK"}.issubset(labels), labels


def test_vix_panel_gates_on_age_known_and_matches_alert_sentinel() -> None:
    """The VIX panel must render never-fetched as N/A, and the alert must pair
    a 5401 unknown-sentinel with its 5400 threshold.

    live_overlay_vix_level exports 0.0 while never-fetched (series stays
    present), so an ungated panel would chart a plausible-looking 0 instead of
    N/A. And a sentinel <= threshold would make lo-vix-unavailable blind to the
    never-fetched state — the exact F-2 gap this pair was added to close.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(
        p for p in _dashboard_panels(dashboard) if p.get("title") == "VIX Level (^VIX via FMP)"
    )
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_vix_level" in expr
    assert "live_overlay_vix_age_known" in expr, (
        f"VIX panel plots the level without gating on age_known — a never-fetched "
        f"level renders as a misleading 0. Got: {expr}"
    )
    assert panel["fieldConfig"]["defaults"].get("noValue"), (
        "VIX panel gates on age_known (unknown -> empty series) but sets no "
        "noValue text — it would render blank instead of N/A"
    )

    rule = _alert_rule("lo-vix-unavailable")
    rule_expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_vix_age_seconds" in rule_expr
    assert "live_overlay_vix_age_known" in rule_expr
    sentinel = int(re.search(r"\*\s*(\d+)\s*\)?\s*$", rule_expr.strip()).group(1))
    threshold_node = next(n for n in rule["data"] if n.get("refId") == rule["condition"])
    threshold = threshold_node["model"]["conditions"][0]["evaluator"]["params"][0]
    assert sentinel > threshold, (
        f"lo-vix-unavailable sentinel ({sentinel}) must exceed its threshold "
        f"({threshold}) or the never-fetched state can never fire"
    )


def test_vix_wire_gate_matches_the_alert_threshold() -> None:
    """``cache.VIX_MAX_AGE_SECS`` and lo-vix-unavailable must not drift apart.

    The gate decides when a stale level stops reaching the wire; the alert
    decides when a human is told. If they diverge, clients keep being served a
    frozen quote for the gap between the two.
    """
    from services.live_overlay_daemon import cache

    rule = _alert_rule("lo-vix-unavailable")
    threshold_node = next(n for n in rule["data"] if n.get("refId") == rule["condition"])
    threshold = threshold_node["model"]["conditions"][0]["evaluator"]["params"][0]

    assert threshold == cache.VIX_MAX_AGE_SECS, (
        f"wire gate ({cache.VIX_MAX_AGE_SECS}s) and lo-vix-unavailable "
        f"({threshold}s) disagree on when a VIX level is stale"
    )


def test_feed_down_critical_covers_silent_stall_via_bar_age_ladder() -> None:
    """The critical feed-down rule must fire on a silent stall, not only a loud one.

    `feed_healthy` (= feed.is_ready()) only drops on BentoError/circuit-break or
    the 3600s payload-staleness gate — a silent stall keeps _feed_ready set, so
    `1 - feed_healthy` alone left the critical blind for up to ~1h (truth-audit
    2026-07-22 F-1). The bar-age term must use the `> bool` form: a bare `>`
    filter would drop the series while fresh and empty the whole arithmetic
    sum, silencing the feed_healthy path too. The 600s gate is pinned as
    exactly 2x the lo-last-bar-stale-open high threshold so the escalation
    ladder (high -> critical) cannot silently collapse or drift apart.
    """
    critical = _alert_rule("lo-feed-down-market-open")
    critical_expr = critical["data"][0]["model"]["expr"]
    assert "live_overlay_market_us_open" in critical_expr
    assert "1 - live_overlay_feed_healthy" in critical_expr, (
        f"loud-failure path vanished from the critical feed-down rule: {critical_expr}"
    )
    assert "live_overlay_last_bar_age_known" in critical_expr, (
        f"bar-age term must gate on age_known so unknown-age 0.0 cannot read as "
        f"fresh: {critical_expr}"
    )
    critical_gate = re.search(
        r"live_overlay_last_bar_age_seconds\{[^}]*\}\s*>\s*bool\s*(\d+)", critical_expr
    )
    assert critical_gate, (
        f"critical feed-down rule lost its `> bool` bar-age gate (bare `>` would "
        f"filter the series away and silence the whole sum): {critical_expr}"
    )

    high = _alert_rule("lo-last-bar-stale-open")
    high_expr = high["data"][0]["model"]["expr"]
    high_gate = re.search(
        r"live_overlay_last_bar_age_seconds\{[^}]*\}\s*>\s*bool\s*(\d+)", high_expr
    )
    assert high_gate, f"high bar-age rule lost its `> bool` gate: {high_expr}"

    assert int(critical_gate.group(1)) == 2 * int(high_gate.group(1)), (
        f"escalation ladder broke: critical bar-age gate {critical_gate.group(1)}s "
        f"must stay exactly 2x the high rule's {high_gate.group(1)}s"
    )

    assert critical["labels"]["severity"] == "critical"
    assert high["labels"]["severity"] == "high"


def _panel_by_id(dashboard: dict, panel_id: int) -> dict:
    match = [p for p in _dashboard_panels(dashboard) if p.get("id") == panel_id]
    assert match, f"panel id {panel_id} not found"
    return match[0]


def test_external_consumer_traffic_distinguishes_dead_daemon_from_closed_market() -> None:
    """A dead daemon/exporter must not render as benign gray MARKET CLOSED:
    the vector(0) fallbacks made 'everything absent' numerically identical to
    a weekend night, even mid-session (audit finding C3). The expr must gate
    on exporter presence and map the absent case to a red NO DATA state."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = _panel_by_id(dashboard, 471930109)
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_uptime_seconds" in expr, "expr must gate on exporter presence"
    assert "vector(-1)" in expr, "absent exporter must resolve to the -1 sentinel"
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    flat: dict[str, dict] = {}
    for m in mappings:
        flat.update(m.get("options", {}))
    assert flat.get("-1", {}).get("text") == "NO DATA"
    assert flat.get("-1", {}).get("color") == "red"
    assert flat.get("0", {}).get("text") == "MARKET CLOSED"


def test_market_data_freshness_novalue_is_not_benign() -> None:
    """noValue did double duty for 'market closed' AND 'daemon dead' — the
    dead case must not read as a benign closed market. Genuine closed
    sessions get the presence-gated -1 mapping instead."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = _panel_by_id(dashboard, 1544709606)
    assert panel["fieldConfig"]["defaults"]["noValue"] == "NO DATA"
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_uptime_seconds" in expr, "expr must presence-gate the closed-market sentinel"
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    flat: dict[str, dict] = {}
    for m in mappings:
        flat.update(m.get("options", {}))
    assert flat.get("-1", {}).get("text") == "MARKET CLOSED"


def test_stat_panels_without_sparkline_use_instant_queries() -> None:
    """Stat panels reduce with lastNotNull; over a range query that renders
    the last pre-death sample as current for up to the whole dashboard window
    after the exporter dies (audit finding C6). Panels with no sparkline
    (graphMode none) have no use for range data — their queries must be
    instant so absent data becomes NO DATA immediately."""
    for path in (_DASHBOARD_JSON, _DASHBOARD_JSON.parent / "dashboard-signals-experiments.json"):
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        offenders = []
        for panel in _dashboard_panels(dashboard):
            if panel.get("type") != "stat":
                continue
            if panel.get("options", {}).get("graphMode", "area") != "none":
                continue
            for target in panel.get("targets", []):
                if "expr" in target and not target.get("instant"):
                    offenders.append(f"{path.name}: {panel.get('title')}")
        assert not offenders, (
            "sparkline-free stat panels with range queries (stale lastNotNull "
            f"renders dead exporters green): {sorted(set(offenders))}"
        )


def test_health_status_panels_map_degraded_code() -> None:
    """Both status stat panels must label code 4 as DEGRADED.

    metrics.py exports status code 4 for a sustained market-open failure past
    warmup (truth-audit F-3). Without the value mapping the stat renders a raw
    "4" — worse than the old perpetual STARTING it replaced. Descriptions must
    also name the state so operators can look it up.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    for title in ("Overall Health", "Service Status"):
        panel = panels[title]
        options = panel["fieldConfig"]["defaults"]["mappings"][0]["options"]
        assert "4" in options, f"{title!r} lacks a mapping for status code 4"
        assert options["4"]["text"] == "DEGRADED"
        assert "DEGRADED" in str(panel.get("description", "")), (
            f"{title!r} description no longer names the DEGRADED state"
        )


def test_dashboard_exposes_portfolio_shadow_evidence_without_auto_promotion() -> None:
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {panel.get("title"): panel for panel in _dashboard_panels(dashboard)}
    readiness = panels["Portfolio Shadow Readiness"]
    progress = panels["Portfolio Evidence Progress"]
    integrity = panels["Portfolio Audit Integrity"]

    readiness_expr = readiness["targets"][0]["expr"]
    assert "live_overlay_portfolio_shadow_ready_for_human_review" in readiness_expr
    assert "live_overlay_portfolio_shadow_evidence_known" in readiness_expr
    mappings = readiness["fieldConfig"]["defaults"]["mappings"][0]["options"]
    assert mappings["0"]["text"] == "OBSERVING"
    assert mappings["1"]["text"] == "REVIEW READY"
    assert "never enables enforcement automatically" in readiness["description"]

    progress_exprs = {target["expr"] for target in progress["targets"]}
    assert any("risk_relevant_sessions" in expr for expr in progress_exprs)
    assert any("min_sessions" in expr for expr in progress_exprs)
    assert any("missing_reconciliation_sessions" in expr for expr in progress_exprs)
    assert any("newest_risk_relevant_session_age_seconds" in expr for expr in progress_exprs)
    assert any("newest_risk_relevant_session_age_known" in expr for expr in progress_exprs)
    assert any("portfolio_snapshot_age_seconds" in expr for expr in progress_exprs)
    assert any('verdict="reject"' in expr for expr in progress_exprs)
    assert any('verdict="resize"' in expr for expr in progress_exprs)

    integrity_exprs = {target["expr"] for target in integrity["targets"]}
    assert any("without_prior_evaluation" in expr for expr in integrity_exprs)
    assert any("submission_attempts_total" in expr for expr in integrity_exprs)
    assert any("incomplete_decisions" in expr for expr in integrity_exprs)
    assert any("reconciliation_failures" in expr for expr in integrity_exprs)
    assert any("reconciliation_max_abs_quantity_delta" in expr for expr in integrity_exprs)
    assert any("reconciliation_reconciled" in expr for expr in integrity_exprs)


@pytest.mark.parametrize(
    ("uid", "metric", "severity"),
    [
        (
            "lo-portfolio-evidence-section-missing",
            "live_overlay_portfolio_shadow_evidence_known",
            "warning",
        ),
        (
            "lo-portfolio-submit-no-risk-eval",
            "live_overlay_portfolio_shadow_submission_attempts_without_prior_evaluation_total",
            "critical",
        ),
        (
            "lo-portfolio-snapshot-age-invalid",
            "live_overlay_portfolio_snapshot_age_seconds",
            "critical",
        ),
        (
            "lo-portfolio-risk-rejection",
            "live_overlay_portfolio_risk_decisions_total",
            "warning",
        ),
        (
            "lo-portfolio-reconcile-missing",
            "live_overlay_portfolio_shadow_missing_reconciliation_sessions",
            "warning",
        ),
        (
            "lo-portfolio-reconciliation-failed",
            "live_overlay_portfolio_reconciliation_max_abs_quantity_delta",
            "critical",
        ),
        (
            "lo-portfolio-decision-incomplete",
            "live_overlay_portfolio_shadow_incomplete_decisions_total",
            "warning",
        ),
    ],
)
def test_alert_rules_cover_portfolio_evidence_integrity(
    uid: str,
    metric: str,
    severity: str,
) -> None:
    rule = _alert_rule(uid)
    assert rule["labels"]["severity"] == severity
    assert metric in rule["data"][0]["model"]["expr"]
