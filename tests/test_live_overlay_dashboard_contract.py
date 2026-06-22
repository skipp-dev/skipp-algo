"""Contract tests for the live-overlay Grafana dashboard JSON.

The dashboard is stored in Grafana API v2 format (apiVersion: dashboard.grafana.app/v2).
Panel data lives in spec.elements (a dict keyed by "panel-N"), panel type is at
vizConfig.group, and options are at vizConfig.spec.options.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DASHBOARD_JSON = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
_ALERT_RULES_YAML = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"


def _v2_panels(dashboard: dict) -> list[dict]:
    """Return a flat list of panel spec dicts from a v2-format dashboard."""
    elements = dashboard.get("spec", {}).get("elements", {})
    return [v["spec"] for v in elements.values() if v.get("kind") == "Panel"]


def test_active_alerts_panel_no_data_filter_disabled() -> None:
    """Grafana alert list should not include no_data to avoid unknown-state rows."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panels = _v2_panels(dashboard)
    panel = next(p for p in panels if p.get("title") == "Active Alerts (live_overlay)")
    state_filter = panel["vizConfig"]["spec"]["options"]["stateFilter"]
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
    rule = next(r for r in warning_group["rules"] if r.get("uid") == "lo-news-snapshot-stale-or-missing")

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
    panels = _v2_panels(dashboard)
    timelines = [p for p in panels if p.get("vizConfig", {}).get("group") == "state-timeline"]
    assert timelines, "expected at least one state-timeline panel"
    for panel in timelines:
        legend = panel["vizConfig"]["spec"]["options"]["legend"]
        assert legend.get("showLegend") is False, panel.get("title")
