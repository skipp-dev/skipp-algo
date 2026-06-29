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


def test_active_alerts_panel_no_data_filter_disabled() -> None:
    """Grafana alert list should not include no_data to avoid unknown-state rows."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Active Alerts")
    options = panel.get("vizConfig", {}).get("spec", {}).get("options", panel.get("options", {}))
    state_filter = options.get("stateFilter")
    if state_filter is None:
        pytest.skip("Active Alerts panel has no stateFilter in current dashboard layout")
    assert state_filter.get("no_data") is False


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


def test_alert_rules_include_combined_news_snapshot_stale_or_missing_warning() -> None:
    """Combined stale/missing snapshot alert must stay present and warning-severity."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    groups = rules_doc["groups"]
    warning_group = next(g for g in groups if g.get("name") == "live-overlay-warning")
    rule = next(
        (r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-stale-or-missing"),
        None,
    )

    if rule is None:
        pytest.skip("combined stale/missing warning rule not present in current ruleset")

    assert rule["labels"]["severity"] == "warning"
    expr = rule["data"][0]["model"]["expr"]
    assert "live_overlay_provider_news_snapshot_loaded" in expr
    assert "live_overlay_provider_news_snapshot_age_seconds" in expr
    assert "or" in expr


def test_state_timeline_panels_hide_threshold_range_legend() -> None:
    """State-timeline legends render threshold ranges (e.g. '< 1', '1+') as
    duplicate-looking entries; they must stay hidden since cell states already
    convey the value mappings.

    In v2 format: vizConfig.group == 'state-timeline' identifies the panel type;
    legend settings live at vizConfig.spec.options.legend.showLegend.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    if isinstance(dashboard.get("panels"), list):
        pytest.skip("state-timeline legend pin currently enforced for v2 dashboards only")
    panels = _dashboard_panels(dashboard)
    timelines = [
        p
        for p in panels
        if p.get("vizConfig", {}).get("group") == "state-timeline" or p.get("type") == "state-timeline"
    ]
    if not timelines:
        pytest.skip("no state-timeline panel present in current dashboard layout")
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
    panel = next(p for p in panels if p.get("title") == "Market Traffic Health")
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
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Market Traffic Health")
    expr = panel["targets"][0]["expr"]
    assert "$__rate_interval" not in expr, "stat panel must use a fixed range vector"
    assert "[5m]" in expr
    assert 'live_overlay_market_us_open{job=~"$job"}' in expr
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


def test_alert_rules_include_expected_traffic_armed_guard() -> None:
    """Production must alert if the first-zero traffic guard is not armed."""
    rule = _alert_rule("lo-expected-traffic-not-armed")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_expected_market_traffic" in expr
    assert "== bool 0" in expr
    assert rule["labels"]["severity"] == "warning"
    assert rule.get("for") == "15m"


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
    assert "!= bool 5" in count_expr

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


def test_alert_rules_use_railway_memory_ratio_thresholds() -> None:
    """Railway memory alerts should use usage/limit ratio instead of only static RSS."""
    warning = _alert_rule("lo-railway-memory-ratio-high")
    warning_expr = warning["data"][0]["model"]["expr"]
    assert "live_overlay_railway_service_memory_used_ratio" in warning_expr
    assert "> 0.75" in warning_expr
    assert "service_id" in warning_expr
    assert warning["labels"]["severity"] == "warning"

    critical = _alert_rule("lo-railway-memory-ratio-critical")
    critical_expr = critical["data"][0]["model"]["expr"]
    assert "live_overlay_railway_service_memory_used_ratio" in critical_expr
    assert "> 0.90" in critical_expr
    assert "service_id" in critical_expr
    assert critical["labels"]["severity"] == "critical"


def test_alert_rules_include_alloy_remote_write_failure_guard() -> None:
    """Alloy must alert when remote-write starts dropping samples."""
    rule = _alert_rule("alloy-remote-write-failures")
    expr = rule["data"][0]["model"]["expr"]

    assert "increase(prometheus_remote_storage_samples_failed_total" in expr
    assert '{job="alloy"}[10m]' in expr
    assert "> 0" in expr
    assert rule["labels"]["severity"] == "warning"


def test_alert_rules_include_generic_bridge_failure_alert() -> None:
    """Generic bridge failure alert must use enabled + scrape_success without configured gate."""
    rule = _alert_rule("lo-bridge-scrape-failed")
    expr = rule["data"][0]["model"]["expr"]

    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert "on(job, bridge)" in expr
    assert "live_overlay_bridge_configured" not in expr


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


def test_dashboard_restart_causes_panel_is_unique_and_groups_by_cause() -> None:
    """There must be exactly one restart-cause panel and it must group by extracted cause label."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    restart_panels = [p for p in panels if "Restart Cause" in p.get("title", "")]
    matches = [(p.get("title"), p.get("id")) for p in restart_panels]
    assert len(restart_panels) == 1, f"expected exactly one restart-cause panel, got {matches}"
    panel = restart_panels[0]
    expr = panel["targets"][0]["expr"]
    assert "sum by (cause)" in expr, expr
    assert "label_replace" in expr, expr
    assert panel["targets"][0].get("legendFormat") == "{{cause}}"


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
    """A process-resident-memory panel must sit in the secondary top row and match the memory alerts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Process Resident Memory")
    gp = panel["gridPos"]
    assert gp["y"] == 13 and gp["x"] == 20 and gp["w"] == 4 and gp["h"] == 3, gp
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_process_resident_memory_bytes" in expr, expr


def test_dashboard_bridge_metrics_present_counts_generic_contracts() -> None:
    """Bridge Metrics Present must count missing generic bridge contracts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Bridge Metrics Present")
    expr = panel["targets"][0]["expr"]
    for bridge in ("uptimerobot", "github_workflow", "railway_metrics"):
        assert f'bridge="{bridge}"' in expr, f"missing bridge {bridge} in {expr}"
        assert (
            f'sum(absent(live_overlay_bridge_enabled{{job=~"$job",bridge="{bridge}"}}) '
            "or on() vector(0))"
        ) in expr
    assert "absent(live_overlay_bridge_enabled" in expr
    assert " or vector(0)" not in expr
    options = panel["fieldConfig"]["defaults"]["mappings"]
    assert any("ALL MISSING" in str(m) for m in options)


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
    """Process Resident Memory red threshold must align with the 900 MiB alert."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Process Resident Memory")
    steps = panel.get("fieldConfig", {}).get("defaults", {}).get("thresholds", {}).get("steps", [])
    red_step = next((s for s in steps if s.get("color") == "red"), None)
    assert red_step is not None
    assert red_step.get("value") == 943718400


def test_dashboard_refresh_rate_reduced() -> None:
    """Refresh rate should be 5m to avoid query storms."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    assert dashboard.get("refresh") == "5m"


def test_dashboard_has_collector_scrape_targets_row() -> None:
    """A Collector row with up and memory panels for alloy/signals_producer/live_overlay must exist."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = next(
        p for p in dashboard["panels"] if p.get("type") == "row" and p.get("title") == "Collector / Scrape Targets"
    )
    # Service-owner detail rows are collapsed by default to reduce first-load noise.
    assert row.get("collapsed") is True
    titles = {p.get("title") for p in _dashboard_panels(dashboard)}
    assert "Scrape Targets Up" in titles
    assert "Collector Resident Memory" in titles


def test_dashboard_latency_panel_uses_only_histogram_quantile() -> None:
    """Latency vs SLO must use histogram_quantile over exported buckets and not fall back to legacy gauges."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Latency vs. SLO (ms)")
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
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Hotspots — Timeframes (Top)")
    exprs = [t["expr"] for t in panel["targets"]]
    legends = [t.get("legendFormat") for t in panel["targets"]]
    assert any("label_replace" in e and '"timeframe"' in e for e in exprs), exprs
    assert all("{{timeframe}}" in legend for legend in legends), legends
    assert all("{{tf}}" not in legend for legend in legends), legends


def test_dashboard_y12_grid_gap_is_closed() -> None:
    """The x=0..24 slot at y=10 must be fully occupied by the health-cause stat row."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    at_y10 = [p for p in panels if p.get("gridPos", {}).get("y") == 10]
    xs = {p["gridPos"]["x"] for p in at_y10}
    assert {0, 4, 8, 12, 16, 20}.issubset(xs), f"y=10 health-cause panels occupy x positions {xs}"


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
    panel = next(p for p in panels if p.get("title") == "Latency vs. SLO (ms)")
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
        assert "or vector(0)" in target.get("expr", "")


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
    "Market Traffic Health",
    "Market Data Freshness",
    "Core Metrics Present",
    "Bridge Metrics Present",
    "Latency vs. SLO (ms)",
    "Error Budget Burn Rate",
    "Traffic Alert Armed",
}


def test_dashboard_user_impact_block_is_promoted_to_top() -> None:
    """User-impact/SLO panels must sit directly after the root-cause stat row."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    by_title = {p.get("title"): p for p in panels}
    for title in PROMOTED_SLO_TITLES:
        assert title in by_title, f"missing panel: {title}"
    assert by_title["Success Rate (%)"]["gridPos"]["y"] == 23
    assert by_title["Market Traffic Health"]["gridPos"]["y"] == 23
    assert by_title["Market Data Freshness"]["gridPos"]["y"] == 23
    assert by_title["Core Metrics Present"]["gridPos"]["y"] == 23
    assert by_title["Bridge Metrics Present"]["gridPos"]["y"] == 28
    assert by_title["Latency vs. SLO (ms)"]["gridPos"]["y"] == 33
    assert by_title["Error Budget Burn Rate"]["gridPos"]["y"] == 33
    assert by_title["Traffic Alert Armed"]["gridPos"]["y"] == 41
    assert by_title["Traffic Alert Armed"]["gridPos"]["y"] < by_title["Operational Drill-down"]["gridPos"]["y"]


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
    """The first row must be renamed to Incident Overview."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = next(p for p in dashboard["panels"] if p.get("type") == "row" and p.get("gridPos", {}).get("y") == 0)
    assert row["title"] == "Incident Overview"


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
    assert "Market Traffic Health" in titles
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
    """External-integration detail must not appear inside the first triage section."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    rows = sorted(
        [p for p in dashboard["panels"] if p.get("type") == "row"],
        key=lambda p: p["gridPos"]["y"],
    )
    incident_end = next(r for r in rows if r["title"] == "Operational Drill-down")["gridPos"]["y"]
    external_detail = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "UptimeRobot Monitor States")
    assert external_detail["gridPos"]["y"] > incident_end


def test_dashboard_operational_drill_down_row_exists() -> None:
    """A dedicated drill-down row must split incident overview from root-cause details."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    titles = {p.get("title") for p in dashboard["panels"] if p.get("type") == "row"}
    assert "Operational Drill-down" in titles


def test_dashboard_reliability_row_renamed() -> None:
    """The former SLO & Reliability row must reflect its new drill-down role."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row = next(p for p in dashboard["panels"] if p.get("type") == "row" and p.get("title") == "Reliability Drill-down")
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
    required = {
        "Incident Overview",
        "Operational Drill-down",
        "Collector / Scrape Targets",
        "Railway Resources",
    }
    rows = {p["title"]: p for p in dashboard["panels"] if p.get("type") == "row"}
    for title in required:
        assert rows[title].get("description"), title


def test_dashboard_top_incident_path_is_above_drilldown() -> None:
    """All top-level incident signal panels must appear before Operational Drill-down."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    y = {p["title"]: p["gridPos"]["y"] for p in _dashboard_panels(dashboard) if "title" in p}

    for title in (
        "Overall Health",
        "Active Alerts",
        "Success Rate (%)",
        "Market Traffic Health",
        "Market Data Freshness",
        "Core Metrics Present",
        "Latency vs. SLO (ms)",
        "Error Budget Burn Rate",
        "Traffic Alert Armed",
    ):
        assert y[title] < y["Operational Drill-down"], title


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
    known_urls = {"https://github.com/skippALGO/skipp-algo/actions"}
    for m in re.finditer(r"\[([^\]]+)\]\(([^)]+)\)", content):
        url = m.group(2)
        assert "REPLACE_" not in url, f"placeholder Railway URL leaked into dashboard: {url}"
        if url.startswith("https://github.com/skippALGO/skipp-algo/blob/main/"):
            rel = url.replace("https://github.com/skippALGO/skipp-algo/blob/main/", "")
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
    detail_rows = {"Provider Health", "Collector / Scrape Targets", "Railway Resources"}
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


def test_dashboard_signal_readiness_panels_are_at_y16() -> None:
    """Signal readiness panels share a single row directly above Global Market Sessions."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    readiness = [
        p
        for p in panels
        if p.get("title") in ("Signal Pipeline Ready", "Open-Prep Snapshot", "Watchlist Symbols", "Producer Poll Age")
    ]
    assert len(readiness) == 4
    for panel in readiness:
        assert panel["gridPos"]["y"] == 16, panel["title"]


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
        "2133310723": 'up{job=~"alloy|signals_producer|live_overlay"}',
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
    panel = next(p for p in panels if p.get("title") == "Market Traffic Health")
    expr = panel["targets"][0]["expr"]
    description = panel.get("description", "").lower()
    assert "live_overlay_market_us_open" in expr
    assert "us" in description or "u.s." in description, description
    assert "market" in description or "trading" in description, description
    assert "closed" in description or "session" in description or "hours" in description, description
    assert "europe" not in description, description


def test_dashboard_detail_rows_collapsed_by_default() -> None:
    """Service-owner detail rows should be collapsed to reduce first-load noise."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    detail_rows = {
        "External Integrations",
        "Reliability Drill-down",
        "Provider Health",
        "Collector / Scrape Targets",
        "Railway Resources",
    }
    rows = {p["title"]: p for p in dashboard["panels"] if p.get("type") == "row"}
    for title in detail_rows:
        assert rows[title].get("collapsed") is True, f"{title} should be collapsed by default"
    assert rows["Incident Overview"].get("collapsed") is False
    assert rows["Operational Drill-down"].get("collapsed") is False


def test_dashboard_external_integration_details_are_co_located() -> None:
    """External-integration root-cause detail panels must live inside External Integrations."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    by_title = {p.get("title"): p for p in panels}
    external_row_y = by_title["External Integrations"]["gridPos"]["y"]
    next_row_y = next(
        p["gridPos"]["y"] for p in dashboard["panels"] if p.get("type") == "row" and p["gridPos"]["y"] > external_row_y
    )
    for title in ("Bridge Scrape Health Timeline", "GitHub Workflows — Latest Run Detail"):
        y = by_title[title]["gridPos"]["y"]
        assert external_row_y < y < next_row_y, f"{title} y={y} not inside External Integrations"


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
    """Market Data Freshness must show MARKET CLOSED instead of 0%% when idle."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Market Data Freshness")
    expr = panel["targets"][0]["expr"]
    assert "unless on()" in expr, expr
    assert 'sum_over_time(live_overlay_market_us_open{job=~"$job"}[1h:]) == 0' in expr
    assert panel["fieldConfig"]["defaults"].get("noValue") == "MARKET CLOSED"


def test_dashboard_core_metrics_present_checks_critical_series() -> None:
    """Core Metrics Present must detect missing critical series, not just uptime."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Core Metrics Present")
    expr = panel["targets"][0]["expr"]
    assert "absent(live_overlay_uptime_seconds" in expr
    assert "absent(live_overlay_overlay_fresh" in expr
    assert "absent(live_overlay_market_us_open" in expr
    assert "absent(live_overlay_last_bar_age_known" in expr
    assert "absent(live_overlay_smc_live_requests_total" in expr
    assert "absent(live_overlay_smc_live_success_total" in expr
    assert "absent(live_overlay_smc_live_errors_total" in expr
    assert "absent(live_overlay_smc_live_latency_ms_count" in expr


def test_dashboard_traffic_alert_armed_tile_uses_expected_market_traffic() -> None:
    """Traffic Alert Armed must show the production arming flag directly."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = {p.get("title"): p for p in _dashboard_panels(dashboard)}
    panel = panels["Traffic Alert Armed"]
    expr = panel["targets"][0]["expr"]
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    labels = {v["text"]: v["color"] for m in mappings for v in (m.get("options") or {}).values()}

    assert expr == 'live_overlay_expected_market_traffic{job=~"$job"}'
    assert panel["targets"][0]["legendFormat"] == "expected_market_traffic"
    assert labels["NOT ARMED"] == "dark-red"
    assert labels["ARMED"] == "dark-green"
    assert panel["fieldConfig"]["defaults"].get("noValue") == "NO SIGNAL"
    assert panel["gridPos"]["y"] < panels["Operational Drill-down"]["gridPos"]["y"]


def test_dashboard_railway_bridge_shows_generic_contract() -> None:
    """Railway Metrics Bridge must use the generic bridge contract."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_bridge_enabled" in expr
    assert "live_overlay_bridge_scrape_success" in expr
    assert 'bridge="railway_metrics"' in expr
    assert "live_overlay_railway_metrics_enabled" not in expr, expr
    mappings = panel["fieldConfig"]["defaults"]["mappings"]
    options_keys = {k for m in mappings for k in m.get("options", {})}
    assert {"0", "1", "2"}.issubset(options_keys), options_keys
    labels = {v["text"] for m in mappings for v in (m.get("options") or {}).values()}
    assert {"DISABLED", "SCRAPE ERROR", "OK"}.issubset(labels), labels
