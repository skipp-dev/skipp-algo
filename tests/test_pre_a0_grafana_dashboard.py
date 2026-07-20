"""Production contract for the PRE-A0 Grafana dashboard."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.build_pre_a0_dashboard import _render

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATH = (
    REPO_ROOT
    / "services"
    / "live_overlay_daemon"
    / "infra"
    / "grafana"
    / "dashboard-pre-a0.json"
)


def _dashboard() -> dict:
    return json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))


def test_committed_dashboard_matches_deterministic_builder() -> None:
    assert DASHBOARD_PATH.read_text(encoding="utf-8") == _render()


def test_dashboard_identity_and_operator_defaults() -> None:
    dashboard = _dashboard()
    assert dashboard["uid"] == "pre-a0-shadow-v1"
    assert dashboard["title"] == "PRE-A0 Shadow Operations"
    assert dashboard["editable"] is False
    assert dashboard["refresh"] == "30s"
    assert dashboard["timezone"] == "utc"
    assert dashboard["time"] == {"from": "now-6h", "to": "now"}
    assert {"pre-a0", "a0-fast", "shadow", "skipp-algo"} <= set(
        dashboard["tags"]
    )


def test_dashboard_has_complete_operational_sections() -> None:
    dashboard = _dashboard()
    panels = dashboard["panels"]
    titles = {panel.get("title") for panel in panels}
    required = {
        "Status at a Glance",
        "Overall Shadow Readiness",
        "Active Grafana Alerts",
        "Loaded Model Identity",
        "Last Disconnect Reason",
        "Live Data Path",
        "Input and Processing Throughput",
        "Inference, Quality, and Shadow Outputs",
        "Score Buckets by Horizon",
        "Observed Outcomes",
        "Runtime Resilience",
        "Process CPU Usage",
        "Promotion Guardrails",
        "How to Read Promotion Readiness",
    }
    assert required <= titles
    assert len(panels) >= 40


def test_every_visible_panel_has_description_and_unique_identity() -> None:
    panels = _dashboard()["panels"]
    ids = [panel["id"] for panel in panels]
    titles = [panel["title"] for panel in panels]
    assert len(ids) == len(set(ids))
    assert len(titles) == len(set(titles))
    assert all(panel.get("description") for panel in panels)


def test_dashboard_grid_has_no_overlaps() -> None:
    panels = _dashboard()["panels"]
    occupied: dict[tuple[int, int], str] = {}
    for panel in panels:
        grid = panel["gridPos"]
        for x in range(grid["x"], grid["x"] + grid["w"]):
            for y in range(grid["y"], grid["y"] + grid["h"]):
                point = (x, y)
                assert point not in occupied, (
                    f"{panel['title']!r} overlaps {occupied[point]!r} at {point}"
                )
                occupied[point] = panel["title"]


def test_prometheus_queries_are_scoped_to_a0_fast_job() -> None:
    panels = _dashboard()["panels"]
    expressions = [
        target["expr"]
        for panel in panels
        for target in panel.get("targets", [])
        if isinstance(target.get("expr"), str)
    ]
    assert expressions
    assert all('job=~"$job"' in expression for expression in expressions)
    assert all(
        target.get("datasource", {}).get("uid") == "grafanacloud-prom"
        for panel in panels
        for target in panel.get("targets", [])
    )


def test_dashboard_covers_runtime_and_dynamic_shadow_metrics() -> None:
    expressions = "\n".join(
        target["expr"]
        for panel in _dashboard()["panels"]
        for target in panel.get("targets", [])
        if isinstance(target.get("expr"), str)
    )
    required_metrics = {
        "a0_fast_stream_connected",
        "a0_fast_records_received_total",
        "a0_fast_records_processed_total",
        "a0_fast_queue_dropped_total",
        "a0_fast_historical_bars_total",
        "a0_fast_process_cpu_seconds_total",
        "pre_a0_model_info",
        "pre_a0_inference_duration_ms_count",
        "pre_a0_feature_missing_total",
        "pre_a0_snapshots_recorded_total",
        "pre_a0_estimates_total",
        "pre_a0_scores_total",
        "pre_a0_alerts_total",
        "pre_a0_outcomes_total",
    }
    missing = sorted(metric for metric in required_metrics if metric not in expressions)
    assert not missing, f"dashboard does not consume operational metrics: {missing}"
    assert 'a0_fast_(forced_)?resync_required_symbols' in expressions


def test_shadow_safety_language_is_explicit() -> None:
    dashboard = _dashboard()
    text = "\n".join(
        str(panel.get("options", {}).get("content", ""))
        for panel in dashboard["panels"]
        if panel.get("type") == "text"
    ).lower()
    assert "unconfirmed early-warning shadow" in text
    assert "does not approve promotion" in text
    assert "fail-closed" in text
