"""Drift watchdog CLI (Sprint C9 / T3).

Reads recent live outcomes from ``artifacts/open_prep/outcomes/`` and
compares per-metric distributions against a backtest baseline using the
helpers in :mod:`scripts.drift_alert`. Emits a JSON report to
``artifacts/drift/drift_report_<run_date>.json``.

Designed to be run from a weekly cron (Sprint C9 / T5) and to feed the
GitHub-issue-on-red automation (Sprint C9 / T4) defined in
``.github/workflows/drift-watchdog.yml``.

Usage
-----

::

    python scripts/run_drift_watchdog.py \\
        --baseline-json artifacts/wfo/walk_forward_latest.json \\
        --live-window-days 30 \\
        --output-dir artifacts/drift

The baseline JSON is expected to contain a ``per_setup`` mapping where
each entry has at least ``oos_pnl_returns`` (a list of per-trade
returns). The exact schema is defined in
``docs/SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md`` (T1).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow direct script invocation.
_REPO_ROOT_FOR_BOOTSTRAP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT_FOR_BOOTSTRAP not in sys.path:
    sys.path.insert(0, _REPO_ROOT_FOR_BOOTSTRAP)

from scripts.drift_alert import compute_drift_report  # noqa: E402

DEFAULT_OUTCOMES_DIR = Path("artifacts/open_prep/outcomes")
DEFAULT_OUTPUT_DIR = Path("artifacts/drift")
INSUFFICIENT_LIVE_TRADES = 30


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_live_outcomes(
    outcomes_dir: Path,
    *,
    window_days: int,
    today: date,
) -> list[dict[str, Any]]:
    """Load outcomes JSONs covering the most recent ``window_days``."""

    if not outcomes_dir.exists():
        return []
    cutoff = today - timedelta(days=window_days)
    out: list[dict[str, Any]] = []
    for path in sorted(outcomes_dir.glob("outcomes_*.json")):
        # Filename pattern: outcomes_YYYY-MM-DD.json
        try:
            file_date = date.fromisoformat(path.stem.replace("outcomes_", ""))
        except ValueError:
            continue
        if file_date < cutoff or file_date > today:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            out.extend(data)
    return out


def load_baseline(baseline_json: Path) -> dict[str, Any]:
    """Load the backtest baseline JSON. Returns ``{}`` if missing."""

    if not baseline_json.exists():
        return {}
    try:
        return json.loads(baseline_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


# ---------------------------------------------------------------------------
# Per-setup metric extraction
# ---------------------------------------------------------------------------


def extract_metric_pairs(
    *,
    live_outcomes: list[dict[str, Any]],
    baseline: dict[str, Any],
    pnl_field: str = "pnl_30m_pct",
) -> dict[str, tuple[list[float], list[float]]]:
    """Build a metric → (baseline_samples, live_samples) mapping.

    Currently emits one metric: per-trade PnL. The structure is
    intentionally extensible — additional metrics (Sharpe per fold,
    win-rate per setup, etc.) can be added without changing the
    consumer in :func:`compute_drift_report`.
    """

    live_pnl = [
        float(o[pnl_field])
        for o in live_outcomes
        if pnl_field in o and o[pnl_field] is not None
    ]

    baseline_per_setup = baseline.get("per_setup", {})
    baseline_pnl: list[float] = []
    if isinstance(baseline_per_setup, dict):
        for setup_block in baseline_per_setup.values():
            if not isinstance(setup_block, dict):
                continue
            for r in setup_block.get("oos_pnl_returns", []) or []:
                try:
                    baseline_pnl.append(float(r))
                except (TypeError, ValueError):
                    continue

    return {"pnl_per_trade": (baseline_pnl, live_pnl)}


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def build_report(
    *,
    outcomes_dir: Path,
    baseline_json: Path,
    window_days: int,
    today: date,
    pnl_field: str = "pnl_30m_pct",
) -> dict[str, Any]:
    live = load_live_outcomes(outcomes_dir, window_days=window_days, today=today)
    baseline = load_baseline(baseline_json)
    pairs = extract_metric_pairs(
        live_outcomes=live, baseline=baseline, pnl_field=pnl_field
    )

    n_live_trades = len(pairs.get("pnl_per_trade", ([], []))[1])
    if n_live_trades < INSUFFICIENT_LIVE_TRADES:
        return {
            "run_date": today.isoformat(),
            "aggregate_severity": "yellow",
            "reason": "insufficient_n",
            "n_live_trades": n_live_trades,
            "min_required": INSUFFICIENT_LIVE_TRADES,
            "n_metrics": 0,
            "findings": [],
        }

    report = compute_drift_report(pairs)
    report["run_date"] = today.isoformat()
    report["window_days"] = window_days
    report["n_live_trades"] = n_live_trades
    return report


def write_report(report: dict[str, Any], *, output_dir: Path, run_date: date) -> Path:
    """Atomic write of ``drift_report_<run_date>.json``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"drift_report_{run_date.isoformat()}.json"
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    return target


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outcomes-dir", type=Path, default=DEFAULT_OUTCOMES_DIR)
    parser.add_argument(
        "--baseline-json",
        type=Path,
        required=True,
        help="JSON with backtest baseline samples (see C9 sprint plan T1).",
    )
    parser.add_argument("--live-window-days", type=int, default=30)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--today",
        type=date.fromisoformat,
        default=None,
        help="Override today's date (ISO YYYY-MM-DD); defaults to UTC now.",
    )
    parser.add_argument(
        "--exit-nonzero-on-red",
        action="store_true",
        help="Exit with status 2 when aggregate_severity == 'red' "
        "(used by the cron to escalate via GitHub-issue-auto-open).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    today = args.today or datetime.now(tz=timezone.utc).date()
    report = build_report(
        outcomes_dir=args.outcomes_dir,
        baseline_json=args.baseline_json,
        window_days=args.live_window_days,
        today=today,
    )
    path = write_report(report, output_dir=args.output_dir, run_date=today)
    print(f"drift report written: {path}")
    print(f"aggregate_severity: {report['aggregate_severity']}")
    if args.exit_nonzero_on_red and report.get("aggregate_severity") == "red":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
