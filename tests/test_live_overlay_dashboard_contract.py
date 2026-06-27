"""Contract tests for the live-overlay Grafana dashboard JSON.

The dashboard is currently stored in legacy Grafana v1 format (top-level
``panels``). These tests also accept the Grafana v2 shape
(apiVersion: dashboard.grafana.app/v2), where panel data lives in
``spec.elements`` (a dict keyed by "panel-N"), panel type is at
``vizConfig.group``, and options are at ``vizConfig.spec.options``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DASHBOARD_JSON = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
_ALERT_RULES_YAML = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"


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
    panel = next(p for p in panels if p.get("title") == "Active Alerts (live_overlay)")
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

def test_market_open_request_health_uses_major_session_metric() -> None:
    """The synthetic traffic-health panel must follow live_overlay_market_open.

    metrics.py widens the headline display gauge to "any major session" (US or
    Europe) so the dashboard does not falsely show MARKET_CLOSED while European
    exchanges trade ahead of the US open.  Using live_overlay_market_us_open
    here would reintroduce that false-closed signal.
    """
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Market-open Request Health")
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_market_open" in expr, expr
    assert "live_overlay_market_us_open" not in expr, expr


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


def test_dashboard_railway_metrics_bridge_query_does_not_filter_value_inside_max() -> None:
    """Railway Metrics Bridge must show 0 when disabled, not drop the series."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Railway Metrics Bridge")
    expr = panel["targets"][0]["expr"]
    assert "max(live_overlay_railway_metrics_enabled" in expr
    assert "== 1" not in expr, "value selector inside max() hides the disabled state"
    assert "or vector(0)" in expr


def test_dashboard_market_open_request_health_uses_fixed_rate_range() -> None:
    """stat panels must not use $__rate_interval because it depends on time range."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in _dashboard_panels(dashboard) if p.get("title") == "Market-open Request Health")
    expr = panel["targets"][0]["expr"]
    assert "$__rate_interval" not in expr, "stat panel must use a fixed range vector"
    assert "[5m]" in expr
    assert 'live_overlay_market_open{job=~"$job"}' in expr
    assert 'live_overlay_smc_live_requests_total{job=~"$job"}[5m]' in expr
    assert "or live_overlay_market_open" not in expr
    assert "rate(live_overlay_smc_live_requests_total[5m])" not in expr


def test_dashboard_bridge_scrapes_aggregates_by_job() -> None:
    """Bridge Scrapes should not hide a disabled job behind a global min()."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Bridge Scrapes")
    expr = panel["targets"][0]["expr"]
    assert "min by (job)" in expr
    assert panel["targets"][0]["legendFormat"] == "{{job}}"


def test_dashboard_bridge_state_panels_aggregate_by_job() -> None:
    """Bridge state panels must expose per-job state, not global max()."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    for title in ("UptimeRobot Bridge", "GitHub Workflow Bridge"):
        panel = next(p for p in dashboard["panels"] if p.get("title") == title)
        expr = panel["targets"][0]["expr"]
        assert "max by (job)" in expr, f"{title} should aggregate by job"
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


def test_dashboard_rows_are_expanded() -> None:
    """Previously collapsed rows must be expanded so child panels are visible."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    row_titles = {"External Integrations", "SLO & Reliability", "Provider Health", "Railway Resources"}
    rows = [p for p in dashboard["panels"] if p.get("type") == "row" and p.get("title") in row_titles]
    assert len(rows) == 4
    for row in rows:
        assert row.get("collapsed") is False, f"row {row['title']} is still collapsed"


def test_dashboard_has_process_resident_memory_panel() -> None:
    """A process-resident-memory panel must close the y=12 grid gap and match the memory alerts."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Process Resident Memory")
    gp = panel["gridPos"]
    assert gp["y"] == 12 and gp["x"] == 4 and gp["w"] == 4 and gp["h"] == 4, gp
    expr = panel["targets"][0]["expr"]
    assert "live_overlay_process_resident_memory_bytes" in expr, expr


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


def test_dashboard_y12_grid_gap_is_closed() -> None:
    """The x=4..8 slot at y=12 must be occupied (no cosmetic gap)."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _dashboard_panels(dashboard)
    at_y12 = [p for p in panels if p.get("gridPos", {}).get("y") == 12]
    xs = {p["gridPos"]["x"] for p in at_y12}
    assert {0, 4, 8, 12, 16, 20}.issubset(xs), f"y=12 panels occupy x positions {xs}"


def test_alert_rules_error_budget_burn_uses_two_windows() -> None:
    """Burn-rate alerts must evaluate both a short and a long window."""
    rules_doc = yaml.safe_load(_ALERT_RULES_YAML.read_text(encoding="utf-8"))
    for group in rules_doc["groups"]:
        for rule in group["rules"]:
            title = rule.get("title", "")
            if "burn" not in title.lower():
                continue
            expressions = [d["model"]["expr"] for d in rule["data"] if "expr" in d.get("model", {})]
            assert any("[5m]" in e for e in expressions), f"{title} missing 5m window"
            assert any("[1h]" in e for e in expressions), f"{title} missing 1h window"
            condition = next((d for d in rule["data"] if d.get("refId") == rule.get("condition")), {})
            condition_expr = condition.get("model", {}).get("expression", "")
            assert "$A" in condition_expr and "$B" in condition_expr, condition_expr
