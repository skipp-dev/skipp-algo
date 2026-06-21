#!/usr/bin/env python3
"""Idempotent Grafana dashboard UX improvements for SMC Live Overlay Daemon.

Transforms services/live_overlay_daemon/infra/grafana/dashboard.json in place:
- Adds a UptimeRobot monitor state-timeline panel so ``paused`` no longer
  appears as an ``unknown`` numeric line.
- Replaces confusing state-timeline min/max with explicit value mappings and
  human-readable labels (NO/YES, CLOSED/OPEN, DEAD/ALIVE, OFF/ON).
- Adds a News Provider legend text panel so state codes are visible without
  scrolling.
- Converts "GitHub Workflow Runs" from raw counters to rates with a labelled
  y-axis.
- Renames redundant "Overlay Freshness Budget" panel to clarify it shows
  stale-budget consumption, not another overlay_fresh view.
- Adds panel descriptions to state timelines.

Run after editing dashboard.json sources by hand, then run this script to
re-apply UX transforms:

    python scripts/update_overlay_dashboard.py [path/to/dashboard.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")


def _resolve_dashboard_path(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description="Update Grafana dashboard UX.")
    parser.add_argument(
        "dashboard_path",
        nargs="?",
        type=Path,
        default=DEFAULT_DASHBOARD_PATH,
        help="Path to dashboard.json",
    )
    args = parser.parse_args(argv)
    return args.dashboard_path


def _load_dashboard(dashboard_path: Path) -> dict:
    if not dashboard_path.exists():
        raise SystemExit(f"Dashboard not found: {dashboard_path}")
    return json.loads(dashboard_path.read_text(encoding="utf-8"))


def _save_dashboard(dashboard_path: Path, data: dict) -> None:
    dashboard_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _find_panel_by_title(panels: list[dict], title: str) -> dict | None:
    for panel in panels:
        if panel.get("title") == title:
            return panel
    return None


def _uptimerobot_state_timeline() -> dict:
    return {
        "title": "UptimeRobot Monitor States",
        "type": "state-timeline",
        "description": (
            "Per-monitor UptimeRobot state over time. "
            "paused = monitor intentionally paused; unknown = unrecognized status code."
        ),
        "gridPos": {"h": 6, "w": 12, "x": 0, "y": 61},
        "targets": [
            {
                "expr": "live_overlay_uptimerobot_monitor_status_code{job=~\"$job\"} or vector(0)",
                "legendFormat": "{{__name__}}",
            }
        ],
        "options": {
            "tooltip": {"mode": "multi", "sort": "none"},
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            "rowHeight": 0.9,
        },
        "fieldConfig": {
            "defaults": {
                "mappings": [
                    {
                        "type": "value",
                        "options": {
                            "0": {"text": "PAUSED", "color": "gray"},
                            "1": {"text": "UNKNOWN", "color": "purple"},
                            "2": {"text": "NOT CHECKED", "color": "blue"},
                            "8": {"text": "DOWN", "color": "red"},
                            "9": {"text": "DOWN", "color": "red"},
                        },
                    }
                ],
                "color": {"mode": "thresholds"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "gray", "value": None},
                        {"color": "blue", "value": 1},
                        {"color": "green", "value": 2},
                        {"color": "red", "value": 8},
                    ],
                },
            }
        },
    }


def _news_provider_legend_text() -> dict:
    return {
        "title": "News Provider State Codes",
        "type": "text",
        "description": "Legend for News Provider panels directly below.",
        "gridPos": {"h": 2, "w": 24, "x": 0, "y": 129},
        "options": {
            "mode": "markdown",
            "content": (
                "**News provider state codes:** `0` = unknown / no data, "
                "`1` = degraded, `2` = ok. "
                "Drill-down panel shows per-provider ok/degraded flags; "
                "state-code panel maps the same provider to a single numeric state."
            ),
        },
    }


def _apply_state_timeline_defaults(panel: dict, labels: tuple[str, str], description: str) -> None:
    panel["description"] = description
    defaults = panel.setdefault("fieldConfig", {}).setdefault("defaults", {})
    defaults.pop("min", None)
    defaults.pop("max", None)
    low, high = labels
    low_color = "red" if low in ("DEAD", "NO", "CLOSED", "OFF", "ERROR") else "gray"
    defaults["mappings"] = [
        {
            "type": "value",
            "options": {
                "0": {"text": low, "color": low_color},
                "1": {"text": high, "color": "green"},
            },
        }
    ]
    defaults["color"] = {"mode": "thresholds"}
    defaults["thresholds"] = {
        "mode": "absolute",
        "steps": [
            {"color": low_color, "value": None},
            {"color": "green", "value": 1},
        ],
    }


def _convert_github_workflow_runs_to_rate(panel: dict) -> None:
    panel["description"] = "Rate of GitHub workflow runs by phase (runs per second)."
    defaults = panel.setdefault("fieldConfig", {}).setdefault("defaults", {})
    defaults["unit"] = "cps"
    defaults.setdefault("custom", {})["axisLabel"] = "runs / sec"
    for target in panel.get("targets", []):
        expr = target.get("expr", "")
        if "rate(" not in expr and "_total" in expr:
            metric = expr.split(" or ")[0].strip()
            target["expr"] = f"rate({metric}[$__rate_interval]) or vector(0)"


def main(argv: list[str] | None = None) -> int:
    dashboard_path = _resolve_dashboard_path(argv)
    data = _load_dashboard(dashboard_path)
    panels = data.get("panels", [])

    # 1. Add UptimeRobot state timeline.
    existing = _find_panel_by_title(panels, "UptimeRobot Monitor States")
    if existing is None:
        panels.append(_uptimerobot_state_timeline())
        for panel in panels:
            y = panel.get("gridPos", {}).get("y", 0)
            if y >= 67 and panel.get("title") != "UptimeRobot Monitor States":
                panel["gridPos"]["y"] += 6
    else:
        existing.update(_uptimerobot_state_timeline())

    # 2. Add News Provider legend text panel.
    legend_panel = _find_panel_by_title(panels, "News Provider State Codes")
    if legend_panel is None:
        panels.append(_news_provider_legend_text())
        for panel in panels:
            y = panel.get("gridPos", {}).get("y", 0)
            if y >= 131 and panel.get("title") != "News Provider State Codes":
                panel["gridPos"]["y"] += 2
    else:
        legend_panel.update(_news_provider_legend_text())

    # 3. Fix state timeline panels.
    state_fixes = {
        "Worker Liveness": (
            ("DEAD", "ALIVE"),
            "Per-worker thread liveness: live_feed, overlay_refresh, flow_refresh, ingest_processor.",
        ),
        "Readiness Components Timeline": (
            ("NO", "YES"),
            "Readiness components over time: feed healthy, workers healthy, overlay fresh, market open.",
        ),
        "Global Market Sessions": (
            ("CLOSED", "OPEN"),
            "Regular trading session state for US, Europe, and Asia markets.",
        ),
        "Bridge Scrape Health Timeline": (
            ("ERROR", "OK"),
            "External bridge scrape success over time (UptimeRobot + GitHub Workflows).",
        ),
        "News Provider Health State": (
            ("OFF", "ON"),
            "Aggregate news provider health flags (ok / degraded / unknown).",
        ),
    }
    for title, (labels, description) in state_fixes.items():
        panel = _find_panel_by_title(panels, title)
        if panel is not None:
            _apply_state_timeline_defaults(panel, labels, description)

    # 4. Fix GitHub Workflow Runs panel.
    gh_runs = _find_panel_by_title(panels, "GitHub Workflow Runs")
    if gh_runs is not None:
        _convert_github_workflow_runs_to_rate(gh_runs)

    # 5. Clarify stale-budget panel.
    fresh_budget = _find_panel_by_title(panels, "Overlay Freshness Budget (%)")
    if fresh_budget is not None:
        fresh_budget["title"] = "Stale Budget Consumed (%)"
        fresh_budget["description"] = (
            "How much of the configured max_stale budget is currently consumed. "
            "100 % means the overlay is at the stale threshold. "
            "This is derived from overlay_age_seconds / max_stale_seconds."
        )

    panels.sort(key=lambda p: (p.get("gridPos", {}).get("y", 0), p.get("gridPos", {}).get("x", 0)))

    data["panels"] = panels
    data["version"] = data.get("version", 0) + 1
    _save_dashboard(dashboard_path, data)
    print(f"Updated {dashboard_path} (version={data['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
