#!/usr/bin/env python3
"""Build the production PRE-A0 Grafana dashboard deterministically."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The import below depends on REPO_ROOT being on sys.path so the script works
# both as ``python -m scripts.build_pre_a0_dashboard`` and as
# ``python scripts/build_pre_a0_dashboard.py`` (the form used by
# live-overlay-dashboard-publish.yml and this script's own --check hint).
from scripts.smc_atomic_write import atomic_write_text

DEFAULT_OUTPUT = Path(
    "services/live_overlay_daemon/infra/grafana/dashboard-pre-a0.json"
)
PROMETHEUS = {"type": "prometheus", "uid": "grafanacloud-prom"}

_PROJECT_ID = "0616a3b7-7b7f-41d1-8fac-a0b8922c94ca"
_ENVIRONMENT_ID = "470fbd0f-894d-46cd-8722-6b072d255d99"
_A0_FAST_SERVICE_ID = "743407dc-0926-4a94-a98d-87b5ade67f37"
_RAILWAY_BASE = (
    f"https://railway.com/project/{_PROJECT_ID}/service/{_A0_FAST_SERVICE_ID}"
)


def _target(
    expr: str,
    legend: str,
    ref_id: str = "A",
    *,
    instant: bool = False,
) -> dict[str, Any]:
    target: dict[str, Any] = {
        "datasource": PROMETHEUS,
        "expr": expr,
        "legendFormat": legend,
        "refId": ref_id,
    }
    if instant:
        target["instant"] = True
    return target


def _row(panel_id: int, title: str, y: int, description: str) -> dict[str, Any]:
    return {
        "id": panel_id,
        "title": title,
        "type": "row",
        "description": description,
        "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "collapsed": False,
        "panels": [],
    }


def _text(
    panel_id: int,
    title: str,
    content: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    description: str,
) -> dict[str, Any]:
    return {
        "id": panel_id,
        "title": title,
        "type": "text",
        "description": description,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {"mode": "markdown", "content": content},
    }


def _stat(
    panel_id: int,
    title: str,
    description: str,
    expr: str,
    legend: str,
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    unit: str = "short",
    no_value: str = "NO DATA",
    mappings: dict[str, tuple[str, str]] | None = None,
    thresholds: list[tuple[float | None, str]] | None = None,
    text_mode: str = "auto",
) -> dict[str, Any]:
    field_defaults: dict[str, Any] = {
        "unit": unit,
        "noValue": no_value,
        "color": {"mode": "thresholds"},
        "thresholds": {
            "mode": "absolute",
            "steps": [
                {"value": value, "color": color}
                for value, color in (
                    thresholds
                    or [
                        (None, "dark-green"),
                    ]
                )
            ],
        },
    }
    if mappings:
        field_defaults["mappings"] = [
            {
                "type": "value",
                "options": {
                    value: {"text": text, "color": color}
                    for value, (text, color) in mappings.items()
                },
            }
        ]
    return {
        "id": panel_id,
        "title": title,
        "type": "stat",
        "description": description,
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [_target(expr, legend, instant=True)],
        "fieldConfig": {"defaults": field_defaults, "overrides": []},
        "options": {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "textMode": text_mode,
            "reduceOptions": {
                "calcs": ["lastNotNull"],
                "fields": "",
                "values": False,
            },
        },
    }


def _timeseries(
    panel_id: int,
    title: str,
    description: str,
    targets: list[dict[str, Any]],
    *,
    x: int,
    y: int,
    w: int,
    h: int,
    unit: str = "short",
    min_value: float | None = 0,
) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "unit": unit,
        "custom": {
            "drawStyle": "line",
            "lineInterpolation": "linear",
            "lineWidth": 2,
            "fillOpacity": 8,
            "showPoints": "never",
            "spanNulls": False,
        },
    }
    if min_value is not None:
        defaults["min"] = min_value
    return {
        "id": panel_id,
        "title": title,
        "type": "timeseries",
        "description": description,
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom",
                "calcs": ["lastNotNull", "max"],
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def _alert_list(panel_id: int, *, x: int, y: int, w: int, h: int) -> dict[str, Any]:
    return {
        "id": panel_id,
        "title": "Active Grafana Alerts",
        "type": "alertlist",
        "description": (
            "Firing, pending, recovering, and error-state Grafana-managed alerts "
            "from the PRE-A0 folder only."
        ),
        "datasource": PROMETHEUS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "options": {
            "alertInstanceLabelFilter": "",
            "alertName": "",
            "dashboardAlerts": False,
            "datasource": "grafana",
            "folder": {"uid": "bfshrlee72tc0d", "title": "PRE-A0"},
            "groupBy": [],
            "showLabels": True,
            "showInstances": True,
            "showInactiveAlerts": False,
            "sortOrder": 1,
            "groupMode": "default",
            "maxItems": 20,
            "stateFilter": {
                "error": True,
                "firing": True,
                "noData": False,
                "normal": False,
                "pending": True,
                "recovering": True,
            },
            "viewMode": "list",
        },
    }


def build_dashboard() -> dict[str, Any]:
    healthy = (
        'min(pre_a0_enabled{job=~"$job"}) '
        '* min(pre_a0_model_ready{job=~"$job"}) '
        '* min(pre_a0_calibration_valid{job=~"$job"}) '
        '* min(a0_fast_stream_connected{job=~"$job"})'
    )
    panels: list[dict[str, Any]] = [
        _text(
            1,
            "PRE-A0 Shadow Operations",
            (
                "**Unconfirmed early-warning shadow.** This dashboard is operational "
                "evidence only; PRE-A0 is not a confirmed A0 signal and must remain "
                "fail-closed. Start with readiness and active alerts, then follow the "
                "data path into inference quality and persistence.\n\n"
                f"**Quick links:** [Railway logs]({_RAILWAY_BASE}/logs?environmentId={_ENVIRONMENT_ID})"
                f" · [Railway deployments]({_RAILWAY_BASE}/deployments?environmentId={_ENVIRONMENT_ID})"
                " · [PRE-A0 alerts](/alerting/list?search=PRE-A0)"
                " · [Runbook](https://github.com/skipp-dev/skipp-algo/blob/main/docs/pre_a0_rollout_runbook.md)"
            ),
            x=0,
            y=0,
            w=24,
            h=2,
            description="Scope, safety boundary, and direct operational links.",
        ),
        _row(
            10,
            "Status at a Glance",
            2,
            "Immediate readiness of telemetry, model, calibration, and the A0-Fast stream.",
        ),
        _stat(
            11,
            "Control Plane Readiness",
            (
                "CONTROL READY requires PRE-A0 enabled, model ready, calibration valid, "
                "and the A0-Fast stream connected. It does not claim that records are "
                "being processed or that inference and persistence are active; verify "
                "the Live Data Path separately."
            ),
            healthy,
            "readiness",
            x=0,
            y=3,
            w=5,
            h=5,
            mappings={
                "0": ("CONTROL NOT READY", "dark-red"),
                "1": ("CONTROL READY", "dark-green"),
            },
            thresholds=[(None, "dark-red"), (1, "dark-green")],
            no_value="NO TELEMETRY",
        ),
        _alert_list(12, x=5, y=3, w=7, h=5),
        _stat(
            13,
            "PRE-A0 Mode",
            "Whether PRE-A0 shadow scoring is enabled in the isolated A0-Fast worker.",
            'min(pre_a0_enabled{job=~"$job"})',
            "enabled",
            x=12,
            y=3,
            w=3,
            h=5,
            mappings={"0": ("OFF", "gray"), "1": ("SHADOW ON", "dark-green")},
            thresholds=[(None, "gray"), (1, "dark-green")],
        ),
        _stat(
            14,
            "Model",
            "Fail-closed model contract status after artifact identity and validity checks.",
            'min(pre_a0_model_ready{job=~"$job"})',
            "model",
            x=15,
            y=3,
            w=3,
            h=5,
            mappings={"0": ("UNAVAILABLE", "dark-red"), "1": ("READY", "dark-green")},
            thresholds=[(None, "dark-red"), (1, "dark-green")],
        ),
        _stat(
            15,
            "Calibration",
            "Whether the loaded model exposes a compatible calibration contract.",
            'min(pre_a0_calibration_valid{job=~"$job"})',
            "calibration",
            x=18,
            y=3,
            w=3,
            h=5,
            mappings={"0": ("INVALID", "dark-red"), "1": ("VALID", "dark-green")},
            thresholds=[(None, "dark-red"), (1, "dark-green")],
        ),
        _stat(
            16,
            "A0-Fast Stream",
            "Databento stream connection used by the isolated shadow worker.",
            'min(a0_fast_stream_connected{job=~"$job"})',
            "stream",
            x=21,
            y=3,
            w=3,
            h=5,
            mappings={"0": ("DISCONNECTED", "dark-red"), "1": ("CONNECTED", "dark-green")},
            thresholds=[(None, "dark-red"), (1, "dark-green")],
        ),
        _stat(
            17,
            "Loaded Model Identity",
            (
                "Live model status, artifact ID, and calibration version from "
                "pre_a0_model_info. The panel name is the evidence; the numeric value is always 1."
            ),
            'pre_a0_model_info{job=~"$job"}',
            "{{status}} · artifact={{artifact_id}} · calibration={{calibration_version}}",
            x=0,
            y=8,
            w=18,
            h=5,
            unit="none",
            text_mode="name",
            no_value="NO MODEL INFO",
        ),
        _stat(
            18,
            "Last Disconnect Reason",
            "Most recently recorded A0-Fast stream disconnect reason; none means no disconnect in this process lifetime.",
            'a0_fast_last_disconnect_info{job=~"$job"}',
            "{{reason}}",
            x=18,
            y=8,
            w=6,
            h=5,
            unit="none",
            text_mode="name",
            no_value="NO DISCONNECT INFO",
        ),
        _row(
            20,
            "Live Data Path",
            13,
            "Input freshness, queue pressure, processing throughput, and shadow persistence.",
        ),
        _stat(
            21,
            "Last Record Age",
            "Seconds since the worker received its most recent Databento record; red above 8 seconds.",
            'max(a0_fast_last_record_age_seconds{job=~"$job"})',
            "age",
            x=0,
            y=14,
            w=4,
            h=4,
            unit="s",
            thresholds=[(None, "dark-green"), (5, "dark-yellow"), (8, "dark-red")],
        ),
        _stat(
            22,
            "Queue Utilization",
            "Current bounded-queue depth divided by capacity; warning at 50%, red at 80%.",
            (
                'max(a0_fast_queue_depth{job=~"$job"}) '
                '/ clamp_min(max(a0_fast_queue_capacity{job=~"$job"}), 1)'
            ),
            "queue",
            x=4,
            y=14,
            w=4,
            h=4,
            unit="percentunit",
            thresholds=[(None, "dark-green"), (0.5, "dark-yellow"), (0.8, "dark-red")],
        ),
        _stat(
            23,
            "Records Received",
            "Databento records received per second over the last five minutes.",
            'sum(rate(a0_fast_records_received_total{job=~"$job"}[5m]))',
            "received/s",
            x=8,
            y=14,
            w=4,
            h=4,
            unit="ops",
        ),
        _stat(
            24,
            "Records Processed",
            "Records consumed by the A0-Fast decision path per second over five minutes.",
            'sum(rate(a0_fast_records_processed_total{job=~"$job"}[5m]))',
            "processed/s",
            x=12,
            y=14,
            w=4,
            h=4,
            unit="ops",
        ),
        _stat(
            25,
            "Shadow Snapshots",
            "PRE-A0 snapshots recorded per second over five minutes; zero is expected before scoring starts.",
            'sum(rate(pre_a0_snapshots_recorded_total{job=~"$job"}[5m]))',
            "snapshots/s",
            x=16,
            y=14,
            w=4,
            h=4,
            unit="ops",
        ),
        _stat(
            26,
            "A0-Fast Decisions",
            "Confirmed core-only A0-Fast shadow decisions per hour; separate from PRE-A0 estimates.",
            'sum(increase(a0_fast_decisions_total{job=~"$job"}[1h]))',
            "decisions/h",
            x=20,
            y=14,
            w=4,
            h=4,
        ),
        _timeseries(
            27,
            "Input and Processing Throughput",
            (
                "Five-minute rates for records received, processed, and rejected by "
                "reason. A sustained gap now identifies whether input is rejected or "
                "the decision path is not consuming it."
            ),
            [
                _target(
                    'sum(rate(a0_fast_records_received_total{job=~"$job"}[5m]))',
                    "received/s",
                    "A",
                ),
                _target(
                    'sum(rate(a0_fast_records_processed_total{job=~"$job"}[5m]))',
                    "processed/s",
                    "B",
                ),
                _target(
                    'sum by (reason) (rate(a0_fast_records_rejected_total{job=~"$job"}[5m]))',
                    "rejected · {{reason}}/s",
                    "C",
                ),
            ],
            x=0,
            y=18,
            w=12,
            h=8,
            unit="ops",
        ),
        _timeseries(
            28,
            "Queue Depth and High-Water Mark",
            "Current queue depth, configured capacity, and the process-lifetime high-water mark.",
            [
                _target('a0_fast_queue_depth{job=~"$job"}', "depth", "A"),
                _target('a0_fast_queue_high_watermark{job=~"$job"}', "high water", "B"),
                _target('a0_fast_queue_capacity{job=~"$job"}', "capacity", "C"),
            ],
            x=12,
            y=18,
            w=12,
            h=8,
        ),
        _row(
            30,
            "Inference, Quality, and Shadow Outputs",
            26,
            "Model execution, feature-contract violations, early-warning states, scores, alerts, and outcomes.",
        ),
        _stat(
            31,
            "Inference Throughput",
            "PRE-A0 model inferences per second over five minutes.",
            'sum(rate(pre_a0_inference_duration_ms_count{job=~"$job"}[5m]))',
            "inferences/s",
            x=0,
            y=27,
            w=6,
            h=5,
            unit="ops",
        ),
        _stat(
            32,
            "Mean Inference Latency",
            "Five-minute mean model inference time; empty until at least one inference occurs.",
            (
                'sum(rate(pre_a0_inference_duration_ms_sum{job=~"$job"}[5m])) '
                '/ sum(rate(pre_a0_inference_duration_ms_count{job=~"$job"}[5m]))'
            ),
            "latency",
            x=6,
            y=27,
            w=6,
            h=5,
            unit="ms",
        ),
        _stat(
            33,
            "Input Contract Violations",
            "Missing plus out-of-range features during the last 15 minutes; red above the alert threshold of 10.",
            (
                'sum(increase(pre_a0_feature_missing_total{job=~"$job"}[15m])) '
                '+ sum(increase(pre_a0_feature_out_of_range_total{job=~"$job"}[15m]))'
            ),
            "violations/15m",
            x=12,
            y=27,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-yellow"), (11, "dark-red")],
        ),
        _stat(
            34,
            "Runtime Integrity Errors",
            "Inference, duplicate-decision, and persistence errors during the last five minutes.",
            (
                'sum(increase(pre_a0_inference_errors_total{job=~"$job"}[5m])) '
                '+ sum(increase(pre_a0_duplicate_decision_ids_total{job=~"$job"}[5m])) '
                '+ sum(increase(pre_a0_persistence_errors_total{job=~"$job"}[5m]))'
            ),
            "errors/5m",
            x=18,
            y=27,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _timeseries(
            35,
            "Feature Contract Violations",
            "Five-minute rates of missing and out-of-range model inputs.",
            [
                _target(
                    'sum(rate(pre_a0_feature_missing_total{job=~"$job"}[5m]))',
                    "missing/s",
                    "A",
                ),
                _target(
                    'sum(rate(pre_a0_feature_out_of_range_total{job=~"$job"}[5m]))',
                    "out of range/s",
                    "B",
                ),
            ],
            x=0,
            y=32,
            w=12,
            h=8,
            unit="ops",
        ),
        _timeseries(
            36,
            "Inference and Persistence Activity",
            "Five-minute rates for inference execution, snapshots recorded, and snapshot rows flushed.",
            [
                _target(
                    'sum(rate(pre_a0_inference_duration_ms_count{job=~"$job"}[5m]))',
                    "inferences/s",
                    "A",
                ),
                _target(
                    'sum(rate(pre_a0_snapshots_recorded_total{job=~"$job"}[5m]))',
                    "snapshots/s",
                    "B",
                ),
                _target(
                    'sum(rate(pre_a0_snapshot_rows_flushed_total{job=~"$job"}[5m]))',
                    "rows flushed/s",
                    "C",
                ),
            ],
            x=12,
            y=32,
            w=12,
            h=8,
            unit="ops",
        ),
        _timeseries(
            37,
            "PRE-A0 Estimates by State",
            "Estimate rate by shadow state. This panel becomes populated when live PRE-A0 estimates are recorded.",
            [
                _target(
                    'sum by (state) (rate(pre_a0_estimates_total{job=~"$job"}[5m]))',
                    "{{state}}",
                )
            ],
            x=0,
            y=40,
            w=6,
            h=8,
            unit="ops",
        ),
        _timeseries(
            38,
            "Score Buckets by Horizon",
            "Scored probabilities by configured horizon and decile bucket; unavailable scores use their own bucket.",
            [
                _target(
                    'sum by (horizon, bucket) (rate(pre_a0_scores_total{job=~"$job"}[5m]))',
                    "{{horizon}}s · {{bucket}}",
                )
            ],
            x=6,
            y=40,
            w=6,
            h=8,
            unit="ops",
        ),
        _timeseries(
            39,
            "PRE-A0 Alerts by Direction",
            "Operator-visible PRE-A0 alert events by horizon and direction; empty in pure shadow mode is valid.",
            [
                _target(
                    'sum by (horizon, direction) (rate(pre_a0_alerts_total{job=~"$job"}[5m]))',
                    "{{horizon}}s · {{direction}}",
                )
            ],
            x=12,
            y=40,
            w=6,
            h=8,
            unit="ops",
        ),
        _timeseries(
            40,
            "Observed Outcomes",
            "Recorded PRE-A0 outcomes by horizon and outcome label, used for shadow calibration evidence.",
            [
                _target(
                    'sum by (horizon, outcome) (rate(pre_a0_outcomes_total{job=~"$job"}[5m]))',
                    "{{horizon}}s · {{outcome}}",
                )
            ],
            x=18,
            y=40,
            w=6,
            h=8,
            unit="ops",
        ),
        _row(
            50,
            "Runtime Resilience",
            48,
            "Queue safety, recovery state, process resources, and transport throughput.",
        ),
        _stat(
            51,
            "Queue Drops (15m)",
            "Bars dropped by the bounded queue; any drop forces fail-closed reconstruction.",
            'sum(increase(a0_fast_queue_dropped_total{job=~"$job"}[15m]))',
            "drops",
            x=0,
            y=49,
            w=4,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _stat(
            52,
            "Disconnects (1h)",
            "Stream disconnects during the last hour; each disconnect invalidates symbol state until recovery.",
            'sum(increase(a0_fast_disconnects_total{job=~"$job"}[1h]))',
            "disconnects",
            x=4,
            y=49,
            w=4,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-yellow")],
        ),
        _stat(
            53,
            "Resync Required",
            "Symbols blocked until a complete historical reconstruction proves continuity.",
            (
                'max({__name__=~"a0_fast_(forced_)?resync_required_symbols",'
                'job=~"$job"})'
            ),
            "symbols",
            x=8,
            y=49,
            w=4,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _stat(
            54,
            "Peak RSS",
            "Process peak resident memory reported by the A0-Fast worker.",
            'max(a0_fast_process_peak_rss_bytes{job=~"$job"})',
            "peak RSS",
            x=12,
            y=49,
            w=4,
            h=5,
            unit="bytes",
        ),
        _stat(
            55,
            "Wire Throughput",
            "Estimated Databento wire bytes received per second over five minutes.",
            'sum(rate(a0_fast_wire_bytes_total{job=~"$job"}[5m]))',
            "bytes/s",
            x=16,
            y=49,
            w=4,
            h=5,
            unit="Bps",
        ),
        _stat(
            56,
            "Worker Uptime",
            "Seconds since the A0-Fast worker process started.",
            'max(a0_fast_uptime_seconds{job=~"$job"})',
            "uptime",
            x=20,
            y=49,
            w=4,
            h=5,
            unit="s",
        ),
        _timeseries(
            57,
            "Stream Freshness",
            "Age of the newest received Databento record; warning and alert budgets are 5 and 8 seconds.",
            [_target('a0_fast_last_record_age_seconds{job=~"$job"}', "record age")],
            x=0,
            y=54,
            w=8,
            h=8,
            unit="s",
        ),
        _timeseries(
            58,
            "Disconnect, Drop, and Recovery Events",
            "Five-minute event rates for disconnects, queue drops, and reconstruction outcomes.",
            [
                _target(
                    'sum(rate(a0_fast_disconnects_total{job=~"$job"}[5m]))',
                    "disconnects/s",
                    "A",
                ),
                _target(
                    'sum(rate(a0_fast_queue_dropped_total{job=~"$job"}[5m]))',
                    "drops/s",
                    "B",
                ),
                _target(
                    'sum by (status) (rate(a0_fast_recoveries_total{job=~"$job"}[5m]))',
                    "recovery · {{status}}",
                    "C",
                ),
                _target(
                    'sum(rate(a0_fast_historical_bars_total{job=~"$job"}[5m]))',
                    "historical bars/s",
                    "D",
                ),
            ],
            x=8,
            y=54,
            w=8,
            h=8,
            unit="ops",
        ),
        _timeseries(
            59,
            "Process CPU Usage",
            "Five-minute rate of process CPU seconds; 1.0 corresponds to one fully used CPU core.",
            [
                _target(
                    'sum(rate(a0_fast_process_cpu_seconds_total{job=~"$job"}[5m]))',
                    "CPU cores",
                )
            ],
            x=16,
            y=54,
            w=8,
            h=8,
            unit="percentunit",
        ),
        _row(
            60,
            "Promotion Guardrails",
            62,
            "Evidence and integrity counters. Green is necessary for review but never sufficient for promotion.",
        ),
        _stat(
            61,
            "Inference Errors (24h)",
            "Model inference errors during the last 24 hours.",
            'sum(increase(pre_a0_inference_errors_total{job=~"$job"}[24h]))',
            "errors",
            x=0,
            y=63,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _stat(
            62,
            "Input Violations (24h)",
            "Missing and out-of-range feature observations during the last 24 hours.",
            (
                'sum(increase(pre_a0_feature_missing_total{job=~"$job"}[24h])) '
                '+ sum(increase(pre_a0_feature_out_of_range_total{job=~"$job"}[24h]))'
            ),
            "violations",
            x=6,
            y=63,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-yellow"), (11, "dark-red")],
        ),
        _stat(
            63,
            "Persistence Integrity (24h)",
            "Persistence failures plus duplicate decision IDs during the last 24 hours.",
            (
                'sum(increase(pre_a0_persistence_errors_total{job=~"$job"}[24h])) '
                '+ sum(increase(pre_a0_duplicate_decision_ids_total{job=~"$job"}[24h]))'
            ),
            "errors",
            x=12,
            y=63,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _stat(
            64,
            "Alert Budget Breaches (24h)",
            "PRE-A0 hourly alert-budget breaches during the last 24 hours.",
            'sum(increase(pre_a0_alert_budget_exceeded_total{job=~"$job"}[24h]))',
            "breaches",
            x=18,
            y=63,
            w=6,
            h=5,
            thresholds=[(None, "dark-green"), (1, "dark-red")],
        ),
        _text(
            65,
            "How to Read Promotion Readiness",
            (
                "**This dashboard does not approve promotion.** Before any move beyond "
                "shadow, require non-zero shadow snapshots and outcomes, stable calibration, "
                "zero critical integrity errors, acceptable missingness, bounded alert volume, "
                "and the explicit promotion checklist in the runbook. If telemetry disappears "
                "or any integrity tile turns red, keep PRE-A0 fail-closed and investigate."
            ),
            x=0,
            y=68,
            w=24,
            h=5,
            description="Human interpretation and the non-automatic promotion boundary.",
        ),
    ]

    return {
        "uid": "pre-a0-shadow-v1",
        "title": "PRE-A0 Shadow Operations",
        "description": (
            "Operational dashboard for PRE-A0 shadow scoring and the isolated A0-Fast "
            "worker: readiness, live input, inference quality, persistence, outputs, and guardrails."
        ),
        "tags": ["pre-a0", "a0-fast", "shadow", "skipp-algo"],
        "timezone": "utc",
        "schemaVersion": 39,
        "version": 1,
        "editable": False,
        "graphTooltip": 1,
        "refresh": "30s",
        "liveNow": True,
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {
            "refresh_intervals": ["10s", "30s", "1m", "5m", "15m", "30m", "1h"]
        },
        "templating": {
            "list": [
                {
                    "name": "job",
                    "label": "Prometheus job (advanced)",
                    "type": "query",
                    "hide": 2,
                    "datasource": PROMETHEUS,
                    "query": "label_values(pre_a0_enabled, job)",
                    "definition": "label_values(pre_a0_enabled, job)",
                    "current": {"selected": False, "text": "a0_fast", "value": "a0_fast"},
                    "includeAll": True,
                    "allValue": ".*",
                    "multi": True,
                    "options": [],
                    "refresh": 1,
                    "sort": 1,
                    "skipUrlSync": False,
                    "description": "Prometheus job label for the isolated A0-Fast worker.",
                }
            ]
        },
        "annotations": {
            "list": [
                {
                    "name": "Worker restarts",
                    "datasource": PROMETHEUS,
                    "expr": 'resets(a0_fast_uptime_seconds{job=~"$job"}[10m]) > 0',
                    "tagKeys": "",
                    "textFormat": "A0-Fast restart",
                    "iconColor": "yellow",
                    "enable": True,
                    "hide": False,
                }
            ]
        },
        "links": [
            {
                "title": "PRE-A0 alert rules",
                "type": "link",
                "url": "/alerting/list?search=PRE-A0",
                "icon": "external link",
                "includeVars": False,
                "keepTime": True,
                "targetBlank": False,
            }
        ],
        "panels": panels,
    }


def _render() -> str:
    return json.dumps(build_dashboard(), indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail when the committed dashboard differs from the generated output.",
    )
    args = parser.parse_args(argv)
    rendered = _render()
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != rendered:
            raise SystemExit(
                f"{args.output} is stale; run: python {Path(__file__)} {args.output}"
            )
        print(f"{args.output} is up to date")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(rendered, args.output)  # atomic tempfile+os.replace; see tests/test_no_direct_to_csv_in_production.py
    print(f"Wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
