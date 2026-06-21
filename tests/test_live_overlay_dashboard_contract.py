"""Contract tests for the live-overlay Grafana dashboard JSON."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


_REPO_ROOT = Path(__file__).resolve().parents[1]
_DASHBOARD_JSON = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "dashboard.json"
_ALERT_RULES_YAML = _REPO_ROOT / "services" / "live_overlay_daemon" / "infra" / "grafana" / "alert-rules.yaml"


def test_active_alerts_panel_no_data_filter_disabled() -> None:
    """Grafana alert list should not include no_data to avoid unknown-state rows."""
    dashboard = json.loads(_DASHBOARD_JSON.read_text(encoding="utf-8"))
    panel = next(p for p in dashboard["panels"] if p.get("title") == "Active Alerts (live_overlay)")
    state_filter = panel["options"]["stateFilter"]
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
