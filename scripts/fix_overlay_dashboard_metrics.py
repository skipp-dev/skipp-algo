#!/usr/bin/env python3
"""Apply metric correctness fixes to the live-overlay Grafana dashboard.

Changes:
- Add explicit datasource to every panel and target.
- Make the $job variable multi-select with All option.
- Replace job="$job" with job=~"$job" everywhere.
- Rewrite dashboard annotations to use regex job matching.
- Rename the resets() uptime panel to use live_overlay_daemon_restarts_total.
- Fix restart-cause panels to preserve __name__ in aggregation.
- Fix GitHub workflow rate() queries to deriv() because counts are gauges.
- Replace signals_producer container row with Railway metrics.
- Generate stable panel ids.
- Set refresh to 1m and collapse rows by default.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

try:
    from scripts.smc_atomic_write import atomic_write_text
except ImportError:  # script-style invocation: `python scripts/X.py`
    from smc_atomic_write import atomic_write_text

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")
DATASOURCE = {"type": "prometheus", "uid": "grafanacloud-prom"}


def _stable_id(title: str, salt: str = "") -> int:
    h = hashlib.sha256(f"{salt}:{title}".encode()).hexdigest()
    return int(h[:12], 16) % (2**31 - 1)


def _ensure_datasource(target: dict) -> None:
    target["datasource"] = DATASOURCE


def _ensure_panel_datasource(panel: dict) -> None:
    panel["datasource"] = DATASOURCE
    for target in panel.get("targets", []):
        _ensure_datasource(target)


def _update_job_variable(dashboard: dict) -> None:
    for var in dashboard.get("templating", {}).get("list", []):
        if var.get("name") == "job":
            var["multi"] = True
            var["includeAll"] = True
            var["allValue"] = ".*"


def _rewrite_job_selector(expr: str) -> str:
    return expr.replace('job="$job"', 'job=~"$job"')


def _rewrite_all_job_selectors(panel: dict) -> None:
    for target in panel.get("targets", []):
        if "expr" in target:
            target["expr"] = _rewrite_job_selector(target["expr"])


def _fix_resets_panel(panel: dict) -> None:
    if panel.get("title") != "Uptime Resets (24h, est.)":
        return
    panel["title"] = "Daemon Restarts (24h)"
    panel["targets"] = [
        {
            "datasource": DATASOURCE,
            "expr": 'sum(increase(live_overlay_daemon_restarts_total{job=~"$job"}[24h])) or vector(0)',
            "refId": "A",
            "legendFormat": "restarts",
        }
    ]


def _fix_restart_causes_counted(panel: dict) -> None:
    if panel.get("title") != "Restart Causes (24h, counted)":
        return
    panel["targets"] = [
        {
            "datasource": DATASOURCE,
            "expr": 'sum by (__name__) (increase({__name__=~"live_overlay_daemon_restart_cause_.*_total",job=~"$job"}[24h]))',
            "refId": "A",
            "legendFormat": "{{__name__}}",
        }
    ]


def _fix_restart_causes_by_cause(panel: dict) -> None:
    if panel.get("title") != "Restart Causes (24h, by cause)":
        return
    panel["targets"] = [
        {
            "datasource": DATASOURCE,
            "expr": 'sum by (__name__) (increase({__name__=~"live_overlay_daemon_restart_cause_.*_total",job=~"$job"}[24h]))',
            "refId": "A",
            "legendFormat": "{{__name__}}",
        }
    ]


def _fix_github_workflow_runs(panel: dict) -> None:
    if panel.get("title") != "GitHub Workflow Runs":
        return
    for target in panel.get("targets", []):
        expr = target.get("expr", "")
        if "live_overlay_github_workflow_runs_" in expr and "_total" not in expr:
            expr = expr.replace("rate(", "deriv(")
            target["expr"] = _rewrite_job_selector(expr)


def _fix_ingest_queue_backpressure(panel: dict) -> None:
    if panel.get("title") != "Ingest Queue Backpressure":
        return
    for target in panel.get("targets", []):
        expr = target.get("expr", "")
        if "live_overlay_feed_ingest_queue_dropped_total" in expr and "rate(" not in expr:
            target["expr"] = 'rate(live_overlay_feed_ingest_queue_dropped_total{job=~"$job"}[$__rate_interval])'
            target["legendFormat"] = "dropped rate"


def _railway_panel(title: str, expr: str, unit: str, y: int, x: int, description: str) -> dict:
    return {
        "id": _stable_id(title),
        "title": title,
        "description": description,
        "type": "timeseries",
        "datasource": DATASOURCE,
        "gridPos": {"h": 7, "w": 8, "x": x, "y": y},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"drawStyle": "line", "lineInterpolation": "linear"},
            },
            "overrides": [],
        },
        "targets": [
            {
                "datasource": DATASOURCE,
                "expr": expr,
                "refId": "A",
                "legendFormat": "{{instance}}",
            }
        ],
        "options": {"legend": {"displayMode": "list", "placement": "bottom"}},
    }


_RAILWAY_DESCRIPTIONS = {
    "Railway CPU Utilization (%)": "Railway container CPU utilization as reported by the Railway API.",
    "Railway Memory Utilization (%)": "Railway container memory utilization as reported by the Railway API.",
    "Railway Disk Utilization (%)": "Railway container disk utilization as reported by the Railway API.",
    "Railway Network Receive (Bps)": "Railway container inbound network traffic rate.",
    "Railway Network Transmit (Bps)": "Railway container outbound network traffic rate.",
    "Railway Container Restarts": "Cumulative Railway container restart count.",
}


def _add_railway_descriptions(panels: list[dict]) -> None:
    for panel in panels:
        desc = _RAILWAY_DESCRIPTIONS.get(panel.get("title"))
        if desc:
            panel["description"] = desc


def _replace_signals_producer_row(panels: list[dict]) -> list[dict]:
    new_panels: list[dict] = []
    skip_mode = False
    found_sentinel = False
    for panel in panels:
        title = panel.get("title", "")
        if title in ("Container Resources", "Container Resources (Railway)"):
            skip_mode = True
            found_sentinel = False
            grid = panel.get("gridPos", {"h": 1, "w": 24, "x": 0, "y": 0})
            row_panel = {
                "id": _stable_id("Railway Resources", "row"),
                "title": "Railway Resources",
                "type": "row",
                "datasource": DATASOURCE,
                "collapsed": True,
                "gridPos": grid,
                "panels": [],
            }
            base_y = grid.get("y", 0)
            new_panels.append(row_panel)
            new_panels.extend(
                [
                    _railway_panel(
                        "Railway CPU Utilization (%)",
                        'live_overlay_railway_cpu_utilization_percent{job=~"$job"}',
                        "percent",
                        base_y + 1,
                        0,
                        "Railway container CPU utilization as reported by the Railway API.",
                    ),
                    _railway_panel(
                        "Railway Memory Utilization (%)",
                        'live_overlay_railway_memory_utilization_percent{job=~"$job"}',
                        "percent",
                        base_y + 1,
                        8,
                        "Railway container memory utilization as reported by the Railway API.",
                    ),
                    _railway_panel(
                        "Railway Disk Utilization (%)",
                        'live_overlay_railway_disk_utilization_percent{job=~"$job"}',
                        "percent",
                        base_y + 1,
                        16,
                        "Railway container disk utilization as reported by the Railway API.",
                    ),
                    _railway_panel(
                        "Railway Network Receive (Bps)",
                        'rate(live_overlay_railway_network_bytes_received_total{job=~"$job"}[$__rate_interval])',
                        "Bps",
                        base_y + 8,
                        0,
                        "Railway container inbound network traffic rate.",
                    ),
                    _railway_panel(
                        "Railway Network Transmit (Bps)",
                        'rate(live_overlay_railway_network_bytes_sent_total{job=~"$job"}[$__rate_interval])',
                        "Bps",
                        base_y + 8,
                        8,
                        "Railway container outbound network traffic rate.",
                    ),
                    _railway_panel(
                        "Railway Container Restarts",
                        'live_overlay_railway_container_restarts_total{job=~"$job"}',
                        "short",
                        base_y + 8,
                        16,
                        "Cumulative Railway container restart count.",
                    ),
                ]
            )
            continue
        if skip_mode:
            if panel.get("type") == "row":
                skip_mode = False
                found_sentinel = True
            else:
                continue
        new_panels.append(panel)
    if skip_mode and not found_sentinel:
        raise RuntimeError(
            "Container Resources row was found but no subsequent row panel; "
            "dashboard structure changed unexpectedly."
        )
    return new_panels


def _generate_ids(panels: list[dict]) -> None:
    seen: dict[str, int] = {}
    for panel in panels:
        title = panel.get("title", "")
        seen[title] = seen.get(title, 0) + 1
        panel["id"] = _stable_id(title, str(seen[title]))


def _rewrite_annotations(dashboard: dict) -> None:
    for annotation in dashboard.get("annotations", {}).get("list", []):
        if "expr" in annotation:
            annotation["expr"] = _rewrite_job_selector(annotation["expr"])
        expr = annotation.get("expr", "")
        if "resets(live_overlay_uptime_seconds" in expr:
            annotation["expr"] = (
                'changes(live_overlay_daemon_restarts_total{job=~"$job"}[10m]) > 0'
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fix live-overlay dashboard metrics.")
    parser.add_argument("--path", type=Path, default=DEFAULT_DASHBOARD_PATH)
    args = parser.parse_args(argv)

    dashboard_path: Path = args.path
    data: dict[str, Any] = json.loads(dashboard_path.read_text(encoding="utf-8"))

    _update_job_variable(data)
    _rewrite_annotations(data)

    panels = data.get("panels", [])
    for panel in panels:
        _ensure_panel_datasource(panel)
        _rewrite_all_job_selectors(panel)
        _fix_resets_panel(panel)
        _fix_restart_causes_counted(panel)
        _fix_restart_causes_by_cause(panel)
        _fix_github_workflow_runs(panel)
        _fix_ingest_queue_backpressure(panel)

    panels = _replace_signals_producer_row(panels)
    data["panels"] = panels

    _generate_ids(panels)
    _add_railway_descriptions(panels)

    for panel in panels:
        if panel.get("type") == "row":
            panel["collapsed"] = True

    data["refresh"] = "1m"
    data.setdefault("timepicker", {})
    data["timepicker"]["refresh_intervals"] = ["5s", "10s", "30s", "1m", "5m", "15m", "30m", "1h"]
    data["timepicker"]["hide"] = False

    data["version"] = int(data.get("version", 0) or 0) + 1

    atomic_write_text(dashboard_path, json.dumps(data, indent=2) + "\n")
    print(f"Updated {dashboard_path} (version={data['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
