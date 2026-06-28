#!/usr/bin/env python3
"""Idempotent Grafana dashboard UX hardening for the live-overlay daemon.

Applies a consistent, less saturated color palette and removes redundant
thresholds from state-timeline panels that already use value mappings.
"""
from __future__ import annotations

import argparse
import copy
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_DASHBOARD_PATH = Path("services/live_overlay_daemon/infra/grafana/dashboard.json")

logger = logging.getLogger(__name__)

# Concrete Railway console URLs for live-overlay on-call.
#
# Railway resource IDs are not secrets. Keep production IDs as defaults so the
# committed dashboard remains directly useful during incidents; env vars still
# allow staging/forked environments to generate their own links.
_DEFAULT_RAILWAY_PROJECT_ID = "0616a3b7-7b7f-41d1-8fac-a0b8922c94ca"
_DEFAULT_RAILWAY_ENVIRONMENT_ID = "470fbd0f-894d-46cd-8722-6b072d255d99"
_DEFAULT_RAILWAY_LIVE_OVERLAY_SERVICE_ID = "705582c5-ba8b-4c6e-848c-33bffe0a61b0"
_DEFAULT_RAILWAY_SIGNALS_PRODUCER_SERVICE_ID = "81f8c6b5-ffe2-4646-a978-e62143192a9a"

_RAILWAY_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", _DEFAULT_RAILWAY_PROJECT_ID)
_RAILWAY_ENVIRONMENT_ID = os.getenv(
    "RAILWAY_ENVIRONMENT_ID", _DEFAULT_RAILWAY_ENVIRONMENT_ID
)
_RAILWAY_LIVE_OVERLAY_SERVICE_ID = os.getenv(
    "RAILWAY_LIVE_OVERLAY_SERVICE_ID", _DEFAULT_RAILWAY_LIVE_OVERLAY_SERVICE_ID
)
_RAILWAY_SIGNALS_PRODUCER_SERVICE_ID = os.getenv(
    "RAILWAY_SIGNALS_PRODUCER_SERVICE_ID",
    _DEFAULT_RAILWAY_SIGNALS_PRODUCER_SERVICE_ID,
)

RAILWAY_LINKS: dict[str, str] = {
    "live_overlay_logs": (
        f"https://railway.com/project/{_RAILWAY_PROJECT_ID}/service/"
        f"{_RAILWAY_LIVE_OVERLAY_SERVICE_ID}/logs?environmentId={_RAILWAY_ENVIRONMENT_ID}"
    ),
    "live_overlay_deployments": (
        f"https://railway.com/project/{_RAILWAY_PROJECT_ID}/service/"
        f"{_RAILWAY_LIVE_OVERLAY_SERVICE_ID}/deployments?environmentId={_RAILWAY_ENVIRONMENT_ID}"
    ),
    "live_overlay_metrics": (
        f"https://railway.com/project/{_RAILWAY_PROJECT_ID}/service/"
        f"{_RAILWAY_LIVE_OVERLAY_SERVICE_ID}/metrics?environmentId={_RAILWAY_ENVIRONMENT_ID}"
    ),
    "signals_producer_logs": (
        f"https://railway.com/project/{_RAILWAY_PROJECT_ID}/service/"
        f"{_RAILWAY_SIGNALS_PRODUCER_SERVICE_ID}/logs?environmentId={_RAILWAY_ENVIRONMENT_ID}"
    ),
    "signals_producer_deployments": (
        f"https://railway.com/project/{_RAILWAY_PROJECT_ID}/service/"
        f"{_RAILWAY_SIGNALS_PRODUCER_SERVICE_ID}/deployments?environmentId={_RAILWAY_ENVIRONMENT_ID}"
    ),
}

# Generic Railway URLs that must never appear in the committed dashboard.
_GENERIC_RAILWAY_URLS = {
    "https://railway.app/project",
    "https://railway.app/project/deployments",
    "https://railway.app/project/metrics",
    "https://railway.com/project",
    "https://railway.com/project/deployments",
    "https://railway.com/project/metrics",
}

# Semantic, desaturated Grafana named colors used across the dashboard.
COLOR_OK = "dark-green"
COLOR_ERROR = "dark-red"
COLOR_WARN = "dark-yellow"
COLOR_DEGRADED = "dark-orange"
COLOR_NEUTRAL = "gray"
COLOR_STARTING = "dark-yellow"
# Canonical phase-code colors for the GitHub Workflow Status timeline.
_GITHUB_WORKFLOW_PHASE_COLORS: dict[int, tuple[str, str]] = {
    0: ("Unknown", COLOR_NEUTRAL),
    1: ("Queued", COLOR_WARN),
    2: ("In progress", "dark-blue"),
    3: ("Success", COLOR_OK),
    4: ("Failure", COLOR_ERROR),
    5: ("Cancelled", COLOR_DEGRADED),
    6: ("Skipped", "dark-purple"),
    7: ("Neutral", "dark-blue"),
    8: ("Timed out", COLOR_ERROR),
    9: ("Action required", COLOR_DEGRADED),
    10: ("Startup failure", COLOR_ERROR),
    11: ("Stale", COLOR_WARN),
}

_GITHUB_WORKFLOW_TIMELINE_TITLE = "GitHub Workflow Status — Timeline"
_GITHUB_WORKFLOW_TIMELINE_HEIGHT = 25
_GITHUB_WORKFLOW_TIMELINE_DESCRIPTION = (
    "Colour-coded latest status of each GitHub Actions workflow over time. Every row "
    "is one named workflow ({{workflow}} legend); the cell colour encodes the run "
    "conclusion — green=success, red=failure/timed-out/startup-failure, "
    "orange=cancelled/action-required, blue=in-progress/neutral, "
    "yellow=queued/stale, gray=unknown, purple=skipped. Series come from "
    "live_overlay_github_workflow_phase_code{workflow,event,workflow_id}, sampled "
    "at the daemon's GitHub workflow bridge interval (so runs shorter than one "
    "scrape interval may not appear)."
)


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


def _v1_panel_by_title(data: dict[str, Any], title: str) -> dict[str, Any] | None:
    for panel in _iter_v1_panels(data):
        if panel.get("title") == title:
            return panel
    return None


def _fix_github_workflow_timeline_panel(data: dict[str, Any]) -> bool:
    """Make the GitHub Workflow Status timeline readable and colourful.

    The panel grows from 8 to 25 grid units so ~35 workflow rows can be read
    without scrolling. Value labels are shown automatically, state mappings and
    thresholds are kept in sync so successes are green, failures red, etc.
    """
    panels = data.get("panels", [])
    panel: dict[str, Any] | None = None
    for candidate in panels:
        if candidate.get("title") == _GITHUB_WORKFLOW_TIMELINE_TITLE:
            panel = candidate
            break
    if panel is None:
        return False

    grid_pos = panel.setdefault("gridPos", {})
    old_h = grid_pos.get("h")
    old_y = grid_pos.get("y", 0)
    old_bottom_y = old_y + (old_h if isinstance(old_h, int) else 8)

    mappings = [
        {"type": "value", "options": {str(code): {"text": text, "color": color}}}
        for code, (text, color) in _GITHUB_WORKFLOW_PHASE_COLORS.items()
    ]
    thresholds = {
        "mode": "absolute",
        "steps": [
            {"value": None, "color": COLOR_NEUTRAL},
            *[
                {"value": code, "color": color}
                for code, (_text, color) in _GITHUB_WORKFLOW_PHASE_COLORS.items()
            ],
        ],
    }
    desired_options = {
        "showValue": "auto",
        "rowHeight": 0.92,
        "mergeValues": True,
        "alignValue": "left",
        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": False},
        "tooltip": {"mode": "single", "sort": "none"},
    }
    desired_field_config = {
        "defaults": {
            "custom": {"fillOpacity": 80, "lineWidth": 0},
            "mappings": mappings,
            "color": {"mode": "thresholds"},
            "thresholds": thresholds,
        },
        "overrides": [],
    }

    changed = False
    if grid_pos.get("h") != _GITHUB_WORKFLOW_TIMELINE_HEIGHT:
        grid_pos["h"] = _GITHUB_WORKFLOW_TIMELINE_HEIGHT
        changed = True
    if panel.get("options") != desired_options:
        panel["options"] = desired_options
        changed = True
    if panel.get("fieldConfig") != desired_field_config:
        panel["fieldConfig"] = desired_field_config
        changed = True
    if panel.get("description") != _GITHUB_WORKFLOW_TIMELINE_DESCRIPTION:
        panel["description"] = _GITHUB_WORKFLOW_TIMELINE_DESCRIPTION
        changed = True

    new_bottom_y = old_y + _GITHUB_WORKFLOW_TIMELINE_HEIGHT
    delta = new_bottom_y - old_bottom_y
    if delta > 0:
        for candidate in panels:
            candidate_grid = candidate.get("gridPos", {})
            if candidate_grid.get("y", 0) > old_y:
                candidate_grid["y"] = candidate_grid["y"] + delta
        changed = True

    return changed

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


def _fix_bridge_scrapes_panel(data: dict[str, Any]) -> bool:
    """Make the global external-checks stat ignore unconfigured bridges.

    The previous query used `or vector(0)` inside `min()`, so a bridge that
    was not enabled on any instance forced the panel to 0 (ERROR). By moving
    the fallback outside `min()`, only actually configured bridges vote.
    """
    changed = False
    for panel in _iter_v1_panels(data):
        if panel.get("title") != "External Checks":
            continue
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if "live_overlay_uptimerobot_scrape_success" not in expr:
                continue
            new_expr = (
                "min by (job) (\n"
                '  live_overlay_uptimerobot_scrape_success{job=~"$job"} or\n'
                '  live_overlay_github_workflow_scrape_success{job=~"$job"}\n'
                ")\n"
                'or on (job) label_replace(vector(0), "job", "live_overlay", "", "")'
            )
            if expr != new_expr:
                target["expr"] = new_expr
                changed = True
            if target.get("legendFormat") != "{{job}}":
                target["legendFormat"] = "{{job}}"
                changed = True
    return changed


def _ensure_v1_incident_drilldown_links(data: dict[str, Any]) -> bool:
    """Keep first-screen incident stat links pointed at real detail rows."""
    changed = False
    link_specs = {
        "External Checks": ("External Integrations", "External Integrations"),
        "Core Metrics Present": ("Collector / Scrape Targets", "Collector / Scrape Targets"),
    }
    for panel_title, (link_title, target_title) in link_specs.items():
        panel = _v1_panel_by_title(data, panel_title)
        target = _v1_panel_by_title(data, target_title)
        if not panel or not target or target.get("id") is None:
            continue
        desired_links = [
            {
                "title": link_title,
                "type": "link",
                "url": f"/d/smc-live-overlay-v1?orgId=1&viewPanel={target['id']}",
                "targetBlank": True,
            }
        ]
        if panel.get("links") != desired_links:
            panel["links"] = desired_links
            changed = True
    return changed


def _ensure_v1_service_owner_row_descriptions(data: dict[str, Any]) -> bool:
    """Label collapsed detail rows with their intended service-owner audience."""
    desired_descriptions = {
        "Provider Health": (
            "Service-owner detail: live news provider health and provider-level "
            "degradation context."
        ),
        "Collector / Scrape Targets": (
            "Service-owner detail: telemetry pipeline health, scrape target "
            "liveness, and collector memory."
        ),
        "Railway Resources": (
            "Service-owner detail: Railway container capacity and bridge health "
            "for production operations."
        ),
    }
    changed = False
    for title, description in desired_descriptions.items():
        panel = _v1_panel_by_title(data, title)
        if not panel or panel.get("type") != "row":
            continue
        if panel.get("description") != description:
            panel["description"] = description
            changed = True
    return changed


def _fix_bridge_error_panels(data: dict[str, Any]) -> bool:
    """Ensure bridge error panels only count real error codes.

    Healthy scrapes no longer emit an `error_code` label at all.  The
    filter is kept defensively so any stale or mislabelled healthy series
    (e.g. `error_code="none"`) cannot be counted as an error.
    """
    changed = False
    title_to_metric = {
        "UptimeRobot Bridge Error": "live_overlay_uptimerobot_scrape_error_info",
        "GitHub Workflow Bridge Error": "live_overlay_github_workflow_scrape_error_info",
    }
    for panel in _iter_v1_panels(data):
        metric = title_to_metric.get(panel.get("title", ""))
        if not metric:
            continue
        for target in panel.get("targets", []):
            expr = target.get("expr", "")
            if metric not in expr or 'error_code!="none"' in expr:
                continue
            target["expr"] = f'max({metric}{{job=~"$job",error_code!="none"}} or vector(0))'
            changed = True
    return changed


def _fix_bridge_state_panel_legends(data: dict[str, Any]) -> bool:
    """Keep per-job bridge state series distinguishable when $job is All."""
    changed = False
    for title in ("UptimeRobot Bridge", "GitHub Workflow Bridge"):
        panels = (
            [_panel_by_title(data, title)]
            if _is_v2(data)
            else [panel for panel in _iter_v1_panels(data) if panel.get("title") == title]
        )
        for panel in (panel for panel in panels if panel):
            for target in panel.get("targets", []):
                expr = target.get("expr", "")
                if "max by (job)" not in expr:
                    continue
                if target.get("legendFormat") != "{{job}}":
                    target["legendFormat"] = "{{job}}"
                    changed = True
    return changed


def _ensure_railway_status_panels(data: dict[str, Any]) -> bool:
    """Add status/age/error panels to the Railway row so operators can tell
    whether Railway metrics are enabled/reachable before interpreting "No data".

    Existing Railway resource panels are shifted down by one row (h=3) to make
    room for the new status strip.
    """
    panels = data.get("panels", [])
    titles = {p.get("title") for p in _iter_v1_panels(data)}
    if "Railway Metrics Bridge" in titles:
        return False

    row_index: int | None = None
    for i, panel in enumerate(panels):
        if panel.get("title") == "Railway Resources" and panel.get("type") == "row":
            row_index = i
            break
    if row_index is None:
        return False

    row_y = panels[row_index].get("gridPos", {}).get("y", 257)
    status_y = row_y + 1

    # Shift every panel at or below the Railway row down by 3 units.
    for panel in panels:
        grid_pos = panel.get("gridPos", {})
        if grid_pos.get("y", 0) >= status_y:
            grid_pos["y"] = grid_pos["y"] + 3

    datasource = {"type": "prometheus", "uid": "grafanacloud-prom"}
    status_panels = [
        {
            "title": "Railway Metrics Bridge",
            "type": "stat",
            "description": "Whether the Railway metrics bridge is enabled and its last poll succeeded.",
            "gridPos": {"h": 3, "w": 4, "x": 0, "y": status_y},
            "targets": [
                {
                    "expr": 'max(live_overlay_railway_metrics_enabled{job=~"$job"} == 1) or vector(0)',
                    "legendFormat": "enabled",
                    "instant": True,
                    "datasource": datasource,
                }
            ],
            "options": {
                "colorMode": "background_solid",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            },
            "fieldConfig": {
                "defaults": {
                    "mappings": [
                        {"type": "value", "options": {"0": {"text": "DISABLED", "color": "gray"}, "1": {"text": "OK", "color": "green"}}}
                    ],
                    "thresholds": {"mode": "absolute", "steps": [{"color": "gray", "value": None}, {"color": "green", "value": 1}]},
                }
            },
            "datasource": datasource,
            "id": 1230367684,
        },
        {
            "title": "Railway Metrics Snapshot Age",
            "type": "stat",
            "description": "Seconds since the last successful Railway metrics poll.",
            "gridPos": {"h": 3, "w": 4, "x": 4, "y": status_y},
            "targets": [
                {
                    "expr": 'live_overlay_railway_metrics_age_seconds{job=~"$job"} and on(job) (live_overlay_railway_metrics_enabled{job=~"$job"} == 1)',
                    "legendFormat": "age",
                    "instant": True,
                    "datasource": datasource,
                }
            ],
            "options": {
                "colorMode": "background_solid",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            },
            "fieldConfig": {"defaults": {"unit": "s"}},
            "datasource": datasource,
            "id": 1230367685,
        },
        {
            "title": "Railway Metrics Error",
            "type": "stat",
            "description": "Latest Railway metrics bridge error class. OK when healthy.",
            "gridPos": {"h": 3, "w": 4, "x": 8, "y": status_y},
            "targets": [
                {
                    "expr": 'max(live_overlay_railway_metrics_error_info{job=~"$job",error!="none"} or vector(0))',
                    "legendFormat": "{{error}}",
                    "instant": True,
                    "datasource": datasource,
                }
            ],
            "options": {
                "colorMode": "background_solid",
                "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            },
            "fieldConfig": {
                "defaults": {
                    "mappings": [
                        {"type": "value", "options": {"0": {"text": "OK", "color": "green"}, "1": {"text": "ERROR", "color": "red"}}}
                    ],
                    "thresholds": {"mode": "absolute", "steps": [{"color": "green", "value": None}, {"color": "red", "value": 1}]},
                    "noValue": "none",
                }
            },
            "datasource": datasource,
            "id": 1230367686,
        },
    ]

    # Insert the new status strip right after the row header.
    for insert_panel in reversed(status_panels):
        panels.insert(row_index + 1, insert_panel)
    return True


def _railway_link(title: str, key: str) -> dict[str, Any]:
    """Return a Grafana v1 dashboard link object for a concrete Railway URL."""
    return {
        "title": title,
        "type": "link",
        "url": RAILWAY_LINKS[key],
        "targetBlank": True,
    }


def _fix_triage_guide_railway_links(data: dict[str, Any]) -> bool:
    """Replace generic Railway links in the Incident Triage Guide with concrete URLs."""
    changed = False
    for panel in _iter_v1_panels(data):
        if panel.get("title") != "Incident Triage Guide":
            continue
        options = panel.setdefault("options", {})
        content = options.get("content", "")
        if not content:
            continue

        new_content = content
        placeholder_logs_url = (
            "https://railway.com/project/REPLACE_PROJECT_ID/service/"
            "REPLACE_LIVE_OVERLAY_SERVICE_ID/logs?environmentId=REPLACE_ENVIRONMENT_ID"
        )
        placeholder_deployments_url = (
            "https://railway.com/project/REPLACE_PROJECT_ID/service/"
            "REPLACE_LIVE_OVERLAY_SERVICE_ID/deployments?environmentId=REPLACE_ENVIRONMENT_ID"
        )
        placeholder_metrics_url = (
            "https://railway.com/project/REPLACE_PROJECT_ID/service/"
            "REPLACE_LIVE_OVERLAY_SERVICE_ID/metrics?environmentId=REPLACE_ENVIRONMENT_ID"
        )

        # Replace known generic and placeholder Railway console URLs anywhere
        # they appear inside the guide (markdown links or bare references).
        url_replacements = [
            ("https://railway.app/project/metrics", RAILWAY_LINKS["live_overlay_metrics"]),
            ("https://railway.app/project/deployments", RAILWAY_LINKS["live_overlay_deployments"]),
            ("https://railway.app/project", RAILWAY_LINKS["live_overlay_logs"]),
            (placeholder_metrics_url, RAILWAY_LINKS["live_overlay_metrics"]),
            (placeholder_deployments_url, RAILWAY_LINKS["live_overlay_deployments"]),
            (placeholder_logs_url, RAILWAY_LINKS["live_overlay_logs"]),
        ]
        for old_url, new_url in url_replacements:
            if old_url in new_content:
                new_content = new_content.replace(old_url, new_url)
        if new_content != content:
            options["content"] = new_content
            changed = True

        runbook_line = "Runbook: [README](https://github.com/skippALGO/skipp-algo/blob/main/services/live_overlay_daemon/README.md)"
        quick_links_header = "\n\n---\n**Quick links** "
        quick_links_line = (
            quick_links_header
            + f"\u00b7 [Railway logs]({RAILWAY_LINKS['live_overlay_logs']}) "
            + f"\u00b7 [Railway deployments]({RAILWAY_LINKS['live_overlay_deployments']}) "
            + "\u00b7 [GitHub Actions](https://github.com/skippALGO/skipp-algo/actions) "
            + "\u00b7 [Runbook: live-overlay on-call](https://github.com/skippALGO/skipp-algo/blob/main/services/live_overlay_daemon/OPS.md)"
        )
        if quick_links_header not in new_content and runbook_line in new_content:
            options["content"] = new_content.replace(runbook_line, runbook_line + quick_links_line)
            changed = True

    return changed


def _ensure_railway_resource_links(data: dict[str, Any]) -> bool:
    """Ensure the dashboard has concrete Railway resource links.

    Rewrites dashboard-level ``data["links"]``, per-panel ``panel["links"]``,
    ``fieldConfig.defaults.links`` and ``fieldConfig.overrides`` link entries.
    Stale generic entries are removed and replaced with concrete
    service-scoped URLs.
    """
    changed = False

    def _clean_links(links: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal changed
        kept: list[dict[str, Any]] = []
        for link in links:
            url = link.get("url", "")
            if url in _GENERIC_RAILWAY_URLS:
                changed = True
                continue
            kept.append(link)
        return kept

    def _rewrite_links_in_obj(obj: Any) -> Any:
        nonlocal changed
        if isinstance(obj, list):
            new_list: list[Any] = []
            for item in obj:
                if isinstance(item, dict) and "url" in item:
                    url = item.get("url", "")
                    title = item.get("title", "")
                    title_to_key = {
                        "Railway logs": "live_overlay_logs",
                        "Railway deployments": "live_overlay_deployments",
                        "Railway metrics": "live_overlay_metrics",
                    }
                    # Replace stale generic URLs and update concrete Railway URLs
                    # when environment variables (and therefore the URL) change.
                    if url in _GENERIC_RAILWAY_URLS or (
                        title in title_to_key and url.startswith("https://railway.com/")
                    ):
                        if title in title_to_key:
                            new_link = _railway_link(title, title_to_key[title])
                            new_list.append(new_link)
                            if new_link != item:
                                changed = True
                        else:
                            changed = True
                        continue
                new_list.append(_rewrite_links_in_obj(item))
            return new_list
        if isinstance(obj, dict):
            return {k: _rewrite_links_in_obj(v) for k, v in obj.items()}
        return obj

    data["links"] = _clean_links(data.get("links", []))

    desired_titles = {
        "Railway logs": "live_overlay_logs",
        "Railway deployments": "live_overlay_deployments",
        "Railway metrics": "live_overlay_metrics",
    }
    existing_titles = {link.get("title") for link in data["links"]}
    for title, key in desired_titles.items():
        if title in existing_titles:
            continue
        data["links"].append(_railway_link(title, key))
        changed = True

    # Recursively rewrite any generic link object anywhere in v1 panels.
    for panel in _iter_v1_panels(data):
        rewritten = _rewrite_links_in_obj(panel)
        if rewritten != panel:
            panel.clear()
            panel.update(rewritten)
            changed = True

    return changed




def _ensure_signal_pipeline_links(data: dict[str, Any]) -> bool:
    """Add drilldown links to the top-level Signal Pipeline Ready panel.

    Links point to the concrete signal-producer detail panels (Open-Prep
    Snapshot, Watchlist Symbols, Producer Poll Age) plus the Alloy scrape
    targets panel and the signals-producer Railway logs. Legacy links to the
    collapsed row header (2133310722) and the live-overlay readiness timeline
    (1580287418) are removed so the 3 a.m. on-call click lands on the actual
    signal-pipeline cause, not on live-overlay readiness.
    """
    changed = False
    panel = _v1_panel_by_title(data, "Signal Pipeline Ready")
    if not panel:
        return changed

    legacy_urls = {
        "/d/smc-live-overlay-v1?orgId=1&viewPanel=2133310722",
        "/d/smc-live-overlay-v1?orgId=1&viewPanel=1580287418",
    }
    links = [link for link in panel.get("links", []) if link.get("url") not in legacy_urls]
    if len(links) != len(panel.get("links", [])):
        changed = True

    existing_urls = {link.get("url", "") for link in links}
    wanted = [
        {
            "title": "Open-Prep snapshot",
            "type": "link",
            "url": "/d/smc-live-overlay-v1?orgId=1&viewPanel=2165782568",
            "targetBlank": True,
        },
        {
            "title": "Watchlist symbols",
            "type": "link",
            "url": "/d/smc-live-overlay-v1?orgId=1&viewPanel=2165782569",
            "targetBlank": True,
        },
        {
            "title": "Producer poll age",
            "type": "link",
            "url": "/d/smc-live-overlay-v1?orgId=1&viewPanel=2165782570",
            "targetBlank": True,
        },
        {
            "title": "Collector scrape targets",
            "type": "link",
            "url": "/d/smc-live-overlay-v1?orgId=1&viewPanel=2133310723",
            "targetBlank": True,
        },
        _railway_link("signals-producer Railway logs", "signals_producer_logs"),
    ]
    for link in wanted:
        if link["url"] not in existing_urls:
            links.append(link)
            changed = True
    if changed:
        panel["links"] = links
    return changed


def _fix_triage_guide_signal_path(data: dict[str, Any]) -> bool:
    """Ensure the triage guide mentions the signals-producer readiness path."""
    changed = False
    for panel in _iter_v1_panels(data):
        if panel.get("title") != "Incident Triage Guide":
            continue
        options = panel.setdefault("options", {})
        content = options.get("content", "")
        if not content:
            continue
        step = (
            "7. If **Signal Pipeline Ready** is red: check **Open-Prep Snapshot**, "
            "**Watchlist Symbols**, **Producer Poll Age**, then Collector / Scrape Targets "
            "and signals-producer Railway logs."
        )
        if step in content:
            continue
        # Insert before the Quick links separator.
        marker = "\n\n---\n**Quick links**"
        if marker in content:
            content = content.replace(marker, "\n" + step + marker)
        else:
            content = content + "\n" + step
        options["content"] = content
        changed = True
    return changed


def _fix_market_traffic_health_description(data: dict[str, Any]) -> bool:
    """Make the Market Traffic Health description match its US-only query."""
    changed = False
    panel = _v1_panel_by_title(data, "Market Traffic Health")
    if not panel:
        return changed
    wanted = (
        "Synthetic signal that amplifies request health while the US regular "
        "trading session is open and suppresses it when closed."
    )
    if panel.get("description") != wanted:
        panel["description"] = wanted
        changed = True
    return changed


def _collapse_service_owner_rows(data: dict[str, Any]) -> bool:
    """Collapse detail rows that are secondary during first-minute triage."""
    changed = False
    detail_rows = {
        "External Integrations",
        "Reliability Drill-down",
        "Provider Health",
        "Collector / Scrape Targets",
        "Railway Resources",
    }
    for panel in data.get("panels", []):
        if panel.get("type") == "row" and panel.get("title") in detail_rows:
            if panel.get("collapsed") is not True:
                panel["collapsed"] = True
                changed = True
    return changed


def _co_locate_external_integration_details(data: dict[str, Any]) -> bool:
    """Move external-integration detail panels to follow the External Integrations row.

    The dashboard keeps a flat top-level panel list so existing v1 tooling can
    continue to iterate panels directly; only the order and collapsed flag change.
    """
    changed = False
    panels = data.get("panels", [])
    titles_to_move = {
        "Bridge Scrape Health Timeline",
        "GitHub Workflows — Latest Run Detail",
    }
    move_indices = [
        i for i, p in enumerate(panels)
        if p.get("title") in titles_to_move
    ]
    if not move_indices:
        return changed
    external_idx = next(
        (i for i, p in enumerate(panels) if p.get("type") == "row" and p.get("title") == "External Integrations"),
        None,
    )
    if external_idx is None:
        return changed
    # If the desired panels already sit directly after the row header, do nothing.
    expected_order = ["Bridge Scrape Health Timeline", "GitHub Workflows — Latest Run Detail"]
    slice_after = panels[external_idx + 1 : external_idx + 1 + len(expected_order)]
    if [p.get("title") for p in slice_after] == expected_order:
        return False
    # Pop in reverse order so indices remain stable.
    moved = []
    for i in reversed(move_indices):
        moved.append(panels.pop(i))
    for mp in reversed(moved):
        panels.insert(external_idx + 1, mp)
    return True


def _fail_if_generic_railway_links_remain(data: dict[str, Any]) -> None:
    """Guard: the committed dashboard must never contain generic Railway URLs.

    Rejects:
    - legacy ``railway.app`` project URLs
    - ``railway.com/project`` URLs without a concrete ``/service/<id>`` scope
    - any remaining ``REPLACE_*`` placeholders
    """
    raw = json.dumps(data)
    hits: list[str] = []

    def _collect(prefix: str) -> None:
        start_idx = 0
        while True:
            idx = raw.find(prefix, start_idx)
            if idx == -1:
                break
            end_idx = raw.find(chr(34), idx)
            url = raw[idx:end_idx] if end_idx != -1 else raw[idx:]
            if url not in hits:
                hits.append(url)
            start_idx = idx + 1

    # Old railway.app domain is never acceptable.
    _collect("https://railway.app/project")
    _collect("https://railway.com/project/REPLACE_")
    _collect("REPLACE_PROJECT_ID")
    _collect("REPLACE_ENVIRONMENT_ID")
    _collect("REPLACE_LIVE_OVERLAY_SERVICE_ID")
    _collect("REPLACE_SIGNALS_PRODUCER_SERVICE_ID")

    # railway.com/project without a concrete /service/<id> path is too generic.
    start_idx = 0
    while True:
        idx = raw.find("https://railway.com/project", start_idx)
        if idx == -1:
            break
        end_idx = raw.find(chr(34), idx)
        url = raw[idx:end_idx] if end_idx != -1 else raw[idx:]
        if "/service/" not in url and url not in hits:
            hits.append(url)
        start_idx = idx + 1

    if hits:
        raise SystemExit(
            f"Generic or placeholder Railway URLs still present in dashboard: {hits[:5]}. "
            "Use concrete production Railway IDs or set RAILWAY_PROJECT_ID, "
            "RAILWAY_ENVIRONMENT_ID, RAILWAY_LIVE_OVERLAY_SERVICE_ID, and "
            "RAILWAY_SIGNALS_PRODUCER_SERVICE_ID, then re-run the updater."
        )


def main(argv: list[str] | None = None) -> int:
    dashboard_path = _resolve_dashboard_path(argv)
    data = _load_dashboard(dashboard_path)

    if not _is_v2(data):
        # Classic v1 dashboards are hand-maintained and authoritative. The v2
        # color/mapping transforms below assume the v2 element/vizConfig shape
        # and would corrupt v1 panels, so for v1 we only self-heal the
        # UptimeRobot panel and write back idempotently (version bumps only when
        # something actually changed).
        changed = _ensure_railway_resource_links(data)
        changed = _fix_triage_guide_railway_links(data) or changed
        changed = _ensure_uptimerobot_panel(data) or changed
        changed = _fix_bridge_scrapes_panel(data) or changed
        changed = _fix_bridge_error_panels(data) or changed
        changed = _fix_bridge_state_panel_legends(data) or changed
        changed = _ensure_railway_status_panels(data) or changed
        changed = _fix_github_workflow_timeline_panel(data) or changed
        changed = _ensure_v1_incident_drilldown_links(data) or changed
        changed = _ensure_v1_service_owner_row_descriptions(data) or changed
        changed = _ensure_signal_pipeline_links(data) or changed
        changed = _fix_triage_guide_signal_path(data) or changed
        changed = _fix_market_traffic_health_description(data) or changed
        changed = _collapse_service_owner_rows(data) or changed
        changed = _co_locate_external_integration_details(data) or changed
        if changed:
            data["version"] = int(data.get("version", 0) or 0) + 1
        _save_dashboard(dashboard_path, data)
        _fail_if_generic_railway_links_remain(data)
        print(f"Updated {dashboard_path} (v1, version={data.get('version')})")
        return 0

    # Top-level status panels: consistent semantic colors.
    _fix_bridge_state_panel_legends(data)

    service_status = _panel_by_title(data, "Service Status")
    if service_status:
        _set_mappings(
            service_status,
            [
                _value_mapping(0, "UNKNOWN", COLOR_ERROR),
                _value_mapping(1, "STARTING", COLOR_STARTING),
                _value_mapping(2, "IDLE (MARKET CLOSED)", COLOR_NEUTRAL),
                _value_mapping(3, "OK", COLOR_OK),
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
