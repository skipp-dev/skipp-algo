#!/usr/bin/env python3
"""Idempotent Grafana dashboard UX improvements for SMC Live Overlay Daemon.

Transforms services/live_overlay_daemon/infra/grafana/dashboard.json in place:
- Adds a single-pane Overall Health ampel + an On-Call row for mobile triage.
- Adds deploy/restart annotations on time-series panels.
- Adds a UptimeRobot monitor state-timeline panel so ``paused`` no longer
  appears as an ``unknown`` numeric line.
- Replaces confusing state-timeline min/max with explicit value mappings and
  human-readable labels (NO/YES, CLOSED/OPEN, DEAD/ALIVE, OFF/ON).
- Maps News Provider State Code values to UNKNOWN/DEGRADED/OK labels.
- Adds a News Provider legend text panel so state codes are visible without
  scrolling.
- Converts "GitHub Workflow Runs" from raw counters to rates with a labelled
  y-axis.
- Renames redundant "Overlay Freshness Budget" panel to clarify it shows
  stale-budget consumption, not another overlay_fresh view.
- Adds panel descriptions to key panels.
- Removes duplicate fallback queries from state-timeline panels that cause
  contradictory rows on newer Grafana versions.

Run after editing dashboard.json sources by hand, then run this script to
re-apply UX transforms:

    python scripts/update_overlay_dashboard.py [path/to/dashboard.json]
"""

from __future__ import annotations

import argparse
import json
import re
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


def _move_panels_down(panels: list[dict], threshold_y: int, delta: int, skip_title: str | None = None) -> None:
    for panel in panels:
        y = panel.get("gridPos", {}).get("y", 0)
        if y >= threshold_y and panel.get("title") != skip_title:
            panel["gridPos"]["y"] += delta


def _health_ampel_panel() -> dict:
    return {
        "title": "Overall Health",
        "type": "stat",
        "description": (
            "Single-pane triage signal. HEALTHY = feed, workers and overlay fresh; "
            "DEGRADED = bridge stale/scrape error or workers not healthy; "
            "CRITICAL = feed down while market open or overlay stale."
        ),
        "gridPos": {"h": 4, "w": 8, "x": 0, "y": 0},
        "targets": [
            {
                "expr": (
                    '(live_overlay_health_status_ok{job=~"$job"} * 2) + '
                    '(live_overlay_health_status_idle_market_closed{job=~"$job"} * 1)'
                ),
                "legendFormat": "health_code",
            }
        ],
        "options": {
            "colorMode": "background_solid",
            "graphMode": "none",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
        "fieldConfig": {
            "defaults": {
                "mappings": [
                    {
                        "type": "value",
                        "options": {
                            "0": {"text": "CRITICAL", "color": "red"},
                            "1": {"text": "IDLE", "color": "yellow"},
                            "2": {"text": "HEALTHY", "color": "green"},
                        },
                    }
                ],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "red", "value": None},
                        {"color": "yellow", "value": 1},
                        {"color": "green", "value": 2},
                    ],
                },
            }
        },
    }


def _triage_text_panel(y: int) -> dict:
    return {
        "title": "Incident Triage Guide",
        "type": "text",
        "description": "Suggested first checks when Overall Health is not HEALTHY.",
        "gridPos": {"h": 4, "w": 16, "x": 0, "y": y},
        "options": {
            "mode": "markdown",
            "content": (
                "**Incident triage quick-checks**\n\n"
                "- `feed_healthy == 0` -> check `DATABENTO_API_KEY`, Railway logs, circuit breaker.\n"
                "- `workers_healthy == 0` -> check thread liveness in Worker Liveness panel; restart via Railway.\n"
                "- `overlay_fresh == 0` -> check compute cycle errors, full/flow compute logs.\n"
                "- `market_open == 1` but no traffic -> check TradingView token rollout / auth denied rate.\n"
                "- bridge scrape error -> verify UptimeRobot / GitHub API token and quota.\n"
                "- vertical grey lines on time-series = recent deploy/restart.\n\n"
                "Full runbook: [README](https://github.com/skippALGO/skipp-algo/blob/main/services/live_overlay_daemon/README.md)"
            ),
        },
    }


def _oncall_stat(
    title: str, expr: str, mapping: tuple[tuple[str, str], tuple[str, str]], description: str, x: int, y: int
) -> dict:
    (low_text, low_color), (high_text, high_color) = mapping
    return {
        "title": title,
        "type": "stat",
        "description": description,
        "gridPos": {"h": 3, "w": 4, "x": x, "y": y},
        "targets": [{"expr": expr, "legendFormat": title.lower().replace(" ", "_")}],
        "options": {
            "colorMode": "background_solid",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
        },
        "fieldConfig": {
            "defaults": {
                "mappings": [
                    {
                        "type": "value",
                        "options": {
                            "0": {"text": low_text, "color": low_color},
                            "1": {"text": high_text, "color": high_color},
                        },
                    }
                ],
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": low_color, "value": None},
                        {"color": high_color, "value": 1},
                    ],
                },
            }
        },
    }


def _oncall_row_panels(y: int) -> list[dict]:
    return [
        _oncall_stat(
            "Feed Healthy",
            'live_overlay_feed_healthy{job=~"$job"}',
            (("UNHEALTHY", "red"), ("HEALTHY", "green")),
            "Live feed connection health (0 = unhealthy, 1 = healthy).",
            0,
            y,
        ),
        _oncall_stat(
            "Overlay Fresh",
            'live_overlay_overlay_fresh{job=~"$job"} or vector(0)',
            (("STALE", "red"), ("FRESH", "green")),
            "Overlay data freshness (1 = fresh, 0 = stale).",
            4,
            y,
        ),
        _oncall_stat(
            "Workers Healthy",
            'live_overlay_workers_healthy{job=~"$job"}',
            (("DEGRADED", "red"), ("HEALTHY", "green")),
            "Background thread liveness (1 = all alive, 0 = at least one dead).",
            8,
            y,
        ),
        _oncall_stat(
            "Bridge Scrapes",
            'min(live_overlay_uptimerobot_scrape_success{job=~"$job"} or live_overlay_github_workflow_scrape_success{job=~"$job"})',
            (("ERROR", "red"), ("OK", "green")),
            "External bridge scrape health (UptimeRobot + GitHub Workflows).",
            12,
            y,
        ),
        _oncall_stat(
            "Market Status",
            'live_overlay_market_open{job=~"$job"}',
            (("CLOSED", "gray"), ("OPEN", "green")),
            "US regular trading session state (1 = open, 0 = closed).",
            16,
            y,
        ),
        {
            "title": "Last Bar Age",
            "type": "stat",
            "description": "Age of the newest bar received from Databento.",
            "gridPos": {"h": 3, "w": 4, "x": 20, "y": y},
            "targets": [{"expr": 'live_overlay_last_bar_age_seconds{job=~"$job"} or vector(0)', "legendFormat": "age"}],
            "options": {
                "colorMode": "background_solid",
                "graphMode": "area",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            },
            "fieldConfig": {
                "defaults": {
                    "unit": "s",
                    "thresholds": {
                        "mode": "absolute",
                        "steps": [
                            {"color": "green", "value": None},
                            {"color": "yellow", "value": 300},
                            {"color": "red", "value": 600},
                        ],
                    },
                }
            },
        },
    ]


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
                "expr": '{__name__=~"live_overlay_uptimerobot_monitor_.*_status_code",job=~"$job"}',
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
                            "1": {"text": "NOT CHECKED", "color": "purple"},
                            "2": {"text": "UP", "color": "green"},
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
                        {"color": "purple", "value": 1},
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


def _split_top_level_or(expr: str) -> list[str]:
    """Split `or` only at the top PromQL level (outside parens/braces/strings)."""
    parts: list[str] = []
    current: list[str] = []
    depth_paren = 0
    depth_brace = 0
    in_string: str | None = None
    i = 0
    n = len(expr)
    while i < n:
        ch = expr[i]
        if in_string:
            current.append(ch)
            if ch == "\\" and i + 1 < n:
                i += 1
                current.append(expr[i])
            elif ch == in_string:
                in_string = None
        elif ch in ('"', "'", "`"):
            in_string = ch
            current.append(ch)
        elif ch == "(":
            depth_paren += 1
            current.append(ch)
        elif ch == ")":
            depth_paren -= 1
            current.append(ch)
        elif ch == "{":
            depth_brace += 1
            current.append(ch)
        elif ch == "}":
            depth_brace -= 1
            current.append(ch)
        elif depth_paren == 0 and depth_brace == 0 and expr.startswith(" or ", i):
            parts.append("".join(current).strip())
            current = []
            i += 3
            continue
        else:
            current.append(ch)
        i += 1
    parts.append("".join(current).strip())
    return parts


def _metric_name(expr: str) -> str:
    """Return the leading metric name, ignoring surrounding parens."""
    expr = expr.strip()
    while expr.startswith("(") and expr.endswith(")"):
        expr = expr[1:-1].strip()
    return expr.split("{")[0].strip()


def _strip_fallback_queries(expr: str) -> str:
    """Remove legacy fallback `A or A_without_labels or vector(0)` chains.

    In newer Grafana versions each branch of an `or` is rendered as a separate
    series.  That causes duplicate/w contradictory rows in state-timeline
    panels.  We keep only the labelled metric expression, but we preserve
    genuine `or` joins between different metrics (e.g. bridge min()).
    """
    expr = expr.strip()
    parts = _split_top_level_or(expr)
    if len(parts) <= 1:
        return expr
    first_metric = _metric_name(parts[0])
    for part in parts[1:]:
        bare = part.strip()
        if bare in {"vector(0)", "vector(1)"}:
            continue
        if _metric_name(bare) != first_metric:
            # This is a real union of different metrics, not a label fallback.
            return expr
    return parts[0]


def _deduplicate_state_timeline(panel: dict) -> None:
    """Remove duplicate fallback queries that cause contradictory entries."""
    cleaned: list[dict] = []
    seen: set[str] = set()
    for target in panel.get("targets", []):
        expr = _strip_fallback_queries(target.get("expr", ""))
        if not expr:
            continue
        if expr in seen:
            continue
        seen.add(expr)
        target["expr"] = expr
        cleaned.append(target)
    panel["targets"] = cleaned


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
    _deduplicate_state_timeline(panel)


def _ensure_worker_liveness_panel(panel: dict) -> None:
    """Ensure Worker Liveness covers all daemon worker threads."""
    expected = {
        "live_feed": 'live_overlay_worker_live_feed_alive{job=~"$job"}',
        "overlay_refresh": 'live_overlay_worker_overlay_refresh_alive{job=~"$job"}',
        "flow_refresh": 'live_overlay_worker_flow_refresh_alive{job=~"$job"}',
        "ingest_processor": 'live_overlay_worker_ingest_processor_alive{job=~"$job"}',
    }
    existing_exprs = {t.get("expr", "").strip() for t in panel.get("targets", [])}
    for legend, expr in expected.items():
        if expr not in existing_exprs:
            panel["targets"].append({"expr": expr, "legendFormat": legend})


def _strip_fallback_queries_from_all_panels(panels: list[dict]) -> None:
    """Clean legacy fallback chains from every panel, not just state timelines."""
    for panel in panels:
        for target in panel.get("targets", []):
            target["expr"] = _strip_fallback_queries(target.get("expr", ""))


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


def _apply_news_state_code_mapping(panel: dict) -> None:
    """Map News Provider State Code values to human-readable labels."""
    panel["description"] = "Per-provider news state code: 0=unknown, 1=degraded, 2=ok."
    defaults = panel.setdefault("fieldConfig", {}).setdefault("defaults", {})
    defaults.pop("min", None)
    defaults.pop("max", None)
    defaults["mappings"] = [
        {
            "type": "value",
            "options": {
                "0": {"text": "UNKNOWN", "color": "gray"},
                "1": {"text": "DEGRADED", "color": "orange"},
                "2": {"text": "OK", "color": "green"},
            },
        }
    ]
    defaults["color"] = {"mode": "thresholds"}
    defaults["thresholds"] = {
        "mode": "absolute",
        "steps": [
            {"color": "gray", "value": None},
            {"color": "orange", "value": 1},
            {"color": "green", "value": 2},
        ],
    }
    _deduplicate_state_timeline(panel)


def _add_annotations(data: dict) -> None:
    """Add deploy/restart annotations derived from uptime resets and restart counters."""
    annotations = data.setdefault("annotations", {"list": []})
    existing = {a.get("name") for a in annotations["list"]}
    if "Deploys / Restarts" in existing:
        return
    annotations["list"].append(
        {
            "name": "Deploys / Restarts",
            "datasource": "grafanacloud-prom",
            "expr": (
                'resets(live_overlay_uptime_seconds{job=~"$job"}[1m]) > 0 or '
                'sum by (__name__) (increase({__name__=~"live_overlay_daemon_restart_cause_.*_total",job=~"$job"}[1m])) > 0'
            ),
            "tagKeys": "",
            "textFormat": "restart/deploy",
            "iconColor": "yellow",
            "enable": True,
            "hide": False,
        }
    )


def main(argv: list[str] | None = None) -> int:
    dashboard_path = _resolve_dashboard_path(argv)
    data = _load_dashboard(dashboard_path)
    original_text = dashboard_path.read_text(encoding="utf-8")
    panels = data.get("panels", [])

    # Add deploy/restart annotations.
    _add_annotations(data)

    # Insert Overall Health + On-Call row at the top.
    # Overall Health sits at y=0 (h=4). Triage text at y=4 (h=4) ends at y=8.
    # On-Call row at y=9 (h=3) ends at y=12; shift all existing panels down by 12.
    oncall_y = 9
    existing_health = _find_panel_by_title(panels, "Overall Health")
    if existing_health is None:
        _move_panels_down(panels, 0, oncall_y + 3)
        panels.append(_health_ampel_panel())
        panels.append(_triage_text_panel(4))
        for panel in _oncall_row_panels(oncall_y):
            panels.append(panel)
    else:
        existing_health.update(_health_ampel_panel())

    # 1. Add UptimeRobot state timeline.
    existing = _find_panel_by_title(panels, "UptimeRobot Monitor States")
    if existing is None:
        panels.append(_uptimerobot_state_timeline())
        _move_panels_down(panels, 67, 6, skip_title="UptimeRobot Monitor States")
    else:
        existing.update(_uptimerobot_state_timeline())

    # 2. Add News Provider legend text panel.
    legend_panel = _find_panel_by_title(panels, "News Provider State Codes")
    if legend_panel is None:
        panels.append(_news_provider_legend_text())
        _move_panels_down(panels, 131, 2, skip_title="News Provider State Codes")
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
            if title == "Worker Liveness":
                _ensure_worker_liveness_panel(panel)

    # 4. Strip fallback queries from all panels.
    _strip_fallback_queries_from_all_panels(panels)

    # 5. Consolidate latency panels: remove Avg / Buckets, strengthen p95/p99 vs SLO.
    latency_panels_to_remove = {"smc_live Latency Avg (ms)", "smc_live Latency Buckets (req/s)"}
    panels = [panel for panel in panels if panel.get("title") not in latency_panels_to_remove]
    latency_slo = _find_panel_by_title(panels, "Latency p95/p99 (ms)")
    if latency_slo is not None:
        latency_slo["title"] = "Latency vs. SLO (ms)"
        latency_slo["description"] = "p95 and p99 latency with a fixed 500 ms SLO threshold."
        defs = latency_slo.setdefault("fieldConfig", {}).setdefault("defaults", {})
        steps = defs.setdefault("thresholds", {}).setdefault("steps", [])
        if not any(s.get("value") == 500 for s in steps):
            steps.append({"color": "red", "value": 500})
        has_slo_target = any("vector(500)" in (t.get("expr", "") or "") for t in latency_slo.get("targets", []))
        if not has_slo_target:
            latency_slo["targets"].append(
                {
                    "expr": "vector(500)",
                    "legendFormat": "SLO = 500ms",
                    "refId": "SLO",
                }
            )

    # 6. Fix GitHub Workflow Runs panel.
    gh_runs = _find_panel_by_title(panels, "GitHub Workflow Runs")
    if gh_runs is not None:
        _convert_github_workflow_runs_to_rate(gh_runs)

    # 7. Clarify stale-budget panel.
    fresh_budget = _find_panel_by_title(panels, "Overlay Freshness Budget (%)")
    if fresh_budget is not None:
        fresh_budget["title"] = "Stale Budget Consumed (%)"
        fresh_budget["description"] = (
            "How much of the configured max_stale budget is currently consumed. "
            "100 % means the overlay is at the stale threshold. "
            "This is derived from overlay_age_seconds / max_stale_seconds."
        )

    # 8. Map News Provider State Code panel.
    news_state = _find_panel_by_title(panels, "News Providers — State Code")
    if news_state is not None:
        _apply_news_state_code_mapping(news_state)

    panels.sort(key=lambda p: (p.get("gridPos", {}).get("y", 0), p.get("gridPos", {}).get("x", 0)))

    data["panels"] = panels
    new_text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if new_text == original_text:
        print(f"No changes needed for {dashboard_path}")
        return 0
    data["version"] = data.get("version", 0) + 1
    _save_dashboard(dashboard_path, data)
    print(f"Updated {dashboard_path} (version={data['version']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
