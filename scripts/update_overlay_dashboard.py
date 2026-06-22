#!/usr/bin/env python3
"""Idempotent Grafana dashboard UX hardening for the live-overlay daemon.

Applies a consistent, less saturated color palette and removes redundant
thresholds from state-timeline panels that already use value mappings.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")

# Semantic, desaturated Grafana named colors used across the dashboard.
COLOR_OK = "dark-green"
COLOR_ERROR = "dark-red"
COLOR_WARN = "dark-yellow"
COLOR_DEGRADED = "dark-orange"
COLOR_NEUTRAL = "gray"
COLOR_STARTING = "dark-yellow"

# Canonical classic (v1) definition of the per-monitor UptimeRobot state-timeline
# panel. The updater self-heals this panel if it is ever removed from the
# hand-maintained v1 dashboard, so the deployed dashboard never silently loses
# UptimeRobot visibility.
UPTIMEROBOT_PANEL: dict[str, Any] = {
    "title": "UptimeRobot Monitor States",
    "type": "state-timeline",
    "description": (
        "Per-monitor UptimeRobot state over time. paused = monitor intentionally "
        "paused; unknown = unrecognized status code."
    ),
    "gridPos": {"h": 6, "w": 12, "x": 0, "y": 61},
    "targets": [
        {
            "expr": '{__name__=~"live_overlay_uptimerobot_monitor_.*_status_code",job="$job"}',
            "legendFormat": "{{__name__}}",
        }
    ],
    "options": {
        "tooltip": {"mode": "multi", "sort": "none"},
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
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


def _load_dashboard(dashboard_path: Path) -> dict[str, Any]:
    if not dashboard_path.exists():
        raise SystemExit(f"Dashboard not found: {dashboard_path}")
    data = json.loads(dashboard_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit("Dashboard JSON must be a JSON object")
    if data.get("kind") == "Dashboard" and isinstance(data.get("spec"), dict):
        return data
    if isinstance(data.get("panels"), list):
        # Classic Grafana v1 dashboard (top-level "panels" list). This is the
        # format actually deployed via grafana_dashboard_upsert.py, so it is
        # fully supported here.
        return data
    raise SystemExit(
        "Unsupported dashboard JSON shape: expected either a Grafana v2/Kubernetes "
        "dashboard (kind='Dashboard' + spec) or a classic v1 dashboard (top-level 'panels')."
    )


def _save_dashboard(dashboard_path: Path, data: dict[str, Any]) -> None:
    payload = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    dashboard_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{dashboard_path.name}.",
        suffix=".tmp",
        dir=str(dashboard_path.parent),
        text=True,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(payload)
        os.replace(tmp_path, dashboard_path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def _is_v2(data: dict[str, Any]) -> bool:
    return data.get("kind") == "Dashboard" and isinstance(data.get("spec"), dict)


def _iter_v1_panels(data: dict[str, Any]):
    """Yield every classic-format panel, including panels nested inside rows."""
    for panel in data.get("panels", []) or []:
        if not isinstance(panel, dict):
            continue
        yield panel
        for child in panel.get("panels", []) or []:
            if isinstance(child, dict):
                yield child


def _ensure_uptimerobot_panel(data: dict[str, Any]) -> bool:
    """Self-heal the classic UptimeRobot state-timeline panel.

    Returns True when the panel was (re)added so the caller can bump the
    dashboard version; returns False (no-op) when it is already present.
    """
    for panel in _iter_v1_panels(data):
        if panel.get("title") == "UptimeRobot Monitor States":
            return False
    data.setdefault("panels", []).append(copy.deepcopy(UPTIMEROBOT_PANEL))
    return True


def _elements(data: dict[str, Any]) -> dict[str, Any]:
    return data.setdefault("spec", {}).setdefault("elements", {})


def _panel_by_title(data: dict[str, Any], title: str) -> dict[str, Any] | None:
    for element in _elements(data).values():
        if element.get("kind") == "Panel" and element.get("spec", {}).get("title") == title:
            return element["spec"]
    return None


def _field_config(panel: dict[str, Any]) -> dict[str, Any]:
    return panel.setdefault("vizConfig", {}).setdefault("spec", {}).setdefault("fieldConfig", {})


def _defaults(panel: dict[str, Any]) -> dict[str, Any]:
    return _field_config(panel).setdefault("defaults", {})


def _set_mappings(panel: dict[str, Any], mappings: list[dict[str, Any]]) -> None:
    _defaults(panel)["mappings"] = mappings


def _remove_thresholds(panel: dict[str, Any]) -> None:
    _defaults(panel).pop("thresholds", None)
    _defaults(panel).pop("color", None)


def _value_mapping(value: int | str, text: str, color: str) -> dict[str, Any]:
    return {"type": "value", "options": {str(value): {"text": text, "color": color}}}


def _map_color(color: str) -> str:
    """Translate saturated Grafana named colors to their desaturated variants."""
    mapping = {
        "green": "dark-green",
        "red": "dark-red",
        "yellow": "dark-yellow",
        "orange": "dark-orange",
        "semi-dark-orange": "dark-orange",
        "semi-dark-red": "dark-red",
        "semi-dark-green": "dark-green",
        "semi-dark-yellow": "dark-yellow",
        "blue": "dark-blue",
        "purple": "dark-purple",
    }
    return mapping.get(color, color)


def _desaturate_thresholds(panel: dict[str, Any]) -> None:
    defaults = _defaults(panel)
    thresholds = defaults.get("thresholds")
    if not thresholds:
        return
    for step in thresholds.get("steps", []):
        if "color" in step:
            step["color"] = _map_color(step["color"])


def _desaturate_mappings(panel: dict[str, Any]) -> None:
    defaults = _defaults(panel)
    mappings = defaults.get("mappings")
    if not mappings:
        return
    for mapping in mappings:
        options = mapping.get("options", {})
        for key in options:
            opt = options[key]
            if isinstance(opt, dict) and "color" in opt:
                opt["color"] = _map_color(opt["color"])


def _apply_state_timeline_consistency(panel: dict[str, Any], mappings: list[dict[str, Any]]) -> None:
    """State-timeline panels should rely on value mappings only; thresholds add
    redundant legend/tooltip entries next to the explicit state labels."""
    _set_mappings(panel, mappings)
    _remove_thresholds(panel)
    _desaturate_mappings(panel)


def _apply_stat_consistency(panel: dict[str, Any]) -> None:
    """Stat panels keep thresholds for numeric ranges but use desaturated colors."""
    _desaturate_mappings(panel)
    _desaturate_thresholds(panel)


def main(argv: list[str] | None = None) -> int:
    dashboard_path = _resolve_dashboard_path(argv)
    data = _load_dashboard(dashboard_path)

    if not _is_v2(data):
        # Classic v1 dashboards are hand-maintained and authoritative. The v2
        # color/mapping transforms below assume the v2 element/vizConfig shape
        # and would corrupt v1 panels, so for v1 we only self-heal the
        # UptimeRobot panel and write back idempotently (version bumps only when
        # something actually changed).
        changed = _ensure_uptimerobot_panel(data)
        if changed:
            data["version"] = int(data.get("version", 0) or 0) + 1
        _save_dashboard(dashboard_path, data)
        print(f"Updated {dashboard_path} (v1, version={data.get('version')})")
        return 0

    # Top-level status panels: consistent semantic colors.
    service_status = _panel_by_title(data, "Service Status")
    if service_status:
        _set_mappings(
            service_status,
            [
                _value_mapping(0, "STARTING", COLOR_STARTING),
                _value_mapping(1, "IDLE (MARKET CLOSED)", COLOR_NEUTRAL),
                _value_mapping(2, "OK", COLOR_OK),
            ],
        )
        _apply_stat_consistency(service_status)

    market_banner = _panel_by_title(data, "Market Session Banner")
    if market_banner:
        _set_mappings(
            market_banner,
            [
                _value_mapping(0, "SERVICE DOWN", COLOR_ERROR),
                _value_mapping(1, "MARKET CLOSED", COLOR_NEUTRAL),
                _value_mapping(2, "OPEN / TELEMETRY MISSING", COLOR_DEGRADED),
                _value_mapping(3, "MARKET OPEN", COLOR_OK),
            ],
        )
        _apply_stat_consistency(market_banner)

    workers_healthy = _panel_by_title(data, "Workers Healthy")
    if workers_healthy:
        _set_mappings(
            workers_healthy,
            [
                _value_mapping(0, "DEGRADED", COLOR_ERROR),
                _value_mapping(1, "OK", COLOR_OK),
            ],
        )
        _apply_stat_consistency(workers_healthy)

    for title in ("UptimeRobot Bridge", "GitHub Workflow Bridge"):
        bridge = _panel_by_title(data, title)
        if bridge:
            _set_mappings(
                bridge,
                [
                    _value_mapping(0, "DISABLED", COLOR_NEUTRAL),
                    _value_mapping(1, "SCRAPE ERROR", COLOR_ERROR),
                    _value_mapping(2, "OK", COLOR_OK),
                ],
            )
            _apply_stat_consistency(bridge)

    market_req = _panel_by_title(data, "Market-open Request Health")
    if market_req:
        _set_mappings(
            market_req,
            [
                _value_mapping(0, "MARKET_CLOSED", COLOR_NEUTRAL),
                _value_mapping(1, "OPEN_NO_TRAFFIC", COLOR_WARN),
                _value_mapping(2, "TRAFFIC_OK", COLOR_OK),
            ],
        )
        _apply_stat_consistency(market_req)

    overlay_symbols = _panel_by_title(data, "Overlay Symbols")
    if overlay_symbols:
        _set_mappings(overlay_symbols, [_value_mapping(0, "EMPTY", COLOR_ERROR)])
        _apply_stat_consistency(overlay_symbols)

    bar_symbols = _panel_by_title(data, "Bar Symbols")
    if bar_symbols:
        _set_mappings(bar_symbols, [_value_mapping(0, "EMPTY", COLOR_ERROR)])
        _apply_stat_consistency(bar_symbols)

    # State-timeline panels: remove redundant thresholds, rely on mappings.
    worker_liveness = _panel_by_title(data, "Worker Liveness")
    if worker_liveness:
        _apply_state_timeline_consistency(
            worker_liveness,
            [
                _value_mapping(0, "DEAD", COLOR_ERROR),
                _value_mapping(1, "ALIVE", COLOR_OK),
            ],
        )

    readiness = _panel_by_title(data, "Readiness Components Timeline")
    if readiness:
        _apply_state_timeline_consistency(
            readiness,
            [
                _value_mapping(0, "NO", COLOR_ERROR),
                _value_mapping(1, "YES", COLOR_OK),
            ],
        )

    global_sessions = _panel_by_title(data, "Global Market Sessions")
    if global_sessions:
        _apply_state_timeline_consistency(
            global_sessions,
            [
                _value_mapping(0, "CLOSED", COLOR_NEUTRAL),
                _value_mapping(1, "OPEN", COLOR_OK),
            ],
        )

    bridge_timeline = _panel_by_title(data, "Bridge Scrape Health Timeline")
    if bridge_timeline:
        _apply_state_timeline_consistency(
            bridge_timeline,
            [
                _value_mapping(0, "ERROR", COLOR_ERROR),
                _value_mapping(1, "OK", COLOR_OK),
            ],
        )

    news_state = _panel_by_title(data, "News Provider Health State")
    if news_state:
        _apply_state_timeline_consistency(
            news_state,
            [
                _value_mapping(0, "OFF", COLOR_NEUTRAL),
                _value_mapping(1, "ON", COLOR_OK),
            ],
        )

    # Numeric threshold panels: desaturate remaining red/yellow/green steps.
    for title in (
        "Feed Circuit Breakers (Total)",
        "Feed Partial Restarts (Total)",
        "Restarts (24h)",
        "Success Rate (%)",
        "Freshness SLO (Market Open, 1h)",
        "Error Budget Burn Rate (5m / 1h)",
        "Overlay & Bar Age",
        "Stale Responses (served)",
        "smc_live Latency Avg (ms)",
        "Latency p95/p99 (ms)",
        "Ingest Queue Lag (ms)",
        "UptimeRobot Snapshot Age",
        "GitHub Workflow Snapshot Age",
        "Compute Cycle Errors",
    ):
        panel = _panel_by_title(data, title)
        if panel:
            _apply_stat_consistency(panel)

    # News provider state-code panel uses thresholds for discrete codes.
    news_state_code = _panel_by_title(data, "News Providers — State Code")
    if news_state_code:
        defaults = _defaults(news_state_code)
        defaults["mappings"] = [
            _value_mapping(0, "UNKNOWN", COLOR_NEUTRAL),
            _value_mapping(1, "DEGRADED", COLOR_DEGRADED),
            _value_mapping(2, "OK", COLOR_OK),
        ]
        defaults["thresholds"] = {
            "mode": "absolute",
            "steps": [
                {"value": None, "color": COLOR_NEUTRAL},
                {"value": 1, "color": COLOR_DEGRADED},
                {"value": 2, "color": COLOR_OK},
            ],
        }

    # Bump dashboard version so the change is visible after import.
    data["spec"] = data.get("spec", {})
    data["spec"]["version"] = data["spec"].get("version", 0) + 1

    _save_dashboard(dashboard_path, data)
    print(f"Updated {dashboard_path} (version={data['spec']['version']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
