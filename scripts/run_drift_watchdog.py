"""Drift watchdog CLI (Sprint C9 / T3).

Reads recent live outcomes from ``artifacts/open_prep/outcomes/`` and
compares per-metric distributions against a backtest baseline using the
helpers in :mod:`scripts.drift_alert`. Emits a JSON report to
``artifacts/drift/drift_report_<run_date>.json``.

Originally run from a weekly cron (Sprint C9 / T5) with
GitHub-issue-on-red automation (Sprint C9 / T4) in
``.github/workflows/drift-watchdog.yml``. That workflow was retired
2026-06-12 (#2726): its WFO baseline
(``artifacts/wfo/walk_forward_latest.json``) was never produced by any
pipeline, so the cron had been a guaranteed no-op (and, since #2725, a
guaranteed rc=4) every week. The CLI remains available for manual runs
against an explicitly supplied baseline.

.. note::
    The default p-value bands and PSI thresholds in this script are
    *interim* values from C9/T7. They must be re-locked once ≥ 90
    days of live data are available — see
    ``docs/c9_threshold_tuning.md`` and the tracking issue
    https://github.com/skippALGO/skipp-algo/issues/298.
    The CI anchor test
    ``tests/test_c9_threshold_finalisation_anchor.py`` fires the
    moment the live sample is sufficient and the literals are still
    unchanged.

Usage
-----

::

    python scripts/run_drift_watchdog.py \\
        --baseline-json /path/to/your_wfo_baseline.json \\
        --live-window-days 30 \\
        --output-dir artifacts/drift

The baseline JSON is expected to contain a ``per_setup`` mapping where
each entry has at least ``oos_pnl_returns`` (a list of per-trade
returns). The exact schema is defined in
``docs/SPRINT_PLAN_C9_DRIFT_ALERT_2026-04-26.md`` (T1).
"""

from __future__ import annotations

# F-V5-A1-2 / F-CI-O1 (2026-05-01): bootstrap root logging so the
# logger.info(...) progress messages this entry point emits actually
# surface in CI logs (default WARNING-only handler would drop them).
try:
    from scripts._logging_init import init_cli_logging
except ImportError:  # script-style invocation: `python scripts/X.py`
    import sys as _v5a12_sys
    from pathlib import Path as _v5a12_Path

    _v5a12_sys.path.insert(0, str(_v5a12_Path(__file__).resolve().parents[1]))
    from scripts._logging_init import init_cli_logging  # type: ignore[no-redef]


import argparse
import contextlib
import json
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.drift_alert import compute_drift_report

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
    """Load outcomes JSONs covering the most recent ``window_days``.

    Missing date files are silently skipped (weekends, holidays, ingestion
    gaps). Use :func:`load_live_outcomes_with_coverage` if you need to
    distinguish a complete window from a backfilled-with-gaps one.
    """

    out, _ = load_live_outcomes_with_coverage(
        outcomes_dir, window_days=window_days, today=today
    )
    return out


def load_live_outcomes_with_coverage(
    outcomes_dir: Path,
    *,
    window_days: int,
    today: date,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Like :func:`load_live_outcomes` but also returns window coverage info.

    The coverage dict has keys::

        days_present: int       # number of date files actually loaded
        days_expected: int      # window_days (calendar days, not biz)
        missing_dates: list[str]  # ISO dates with no outcomes_<DATE>.json
        window_complete: bool   # True iff missing_dates is empty
    """

    expected = [
        (today - timedelta(days=offset)).isoformat()
        for offset in range(window_days)
    ]
    expected_set = set(expected)
    if not outcomes_dir.exists():
        return [], {
            "days_present": 0,
            "days_expected": window_days,
            "missing_dates": expected,
            "window_complete": False,
        }
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(outcomes_dir.glob("outcomes_*.json")):
        # Filename pattern: outcomes_YYYY-MM-DD.json
        try:
            file_date = date.fromisoformat(path.stem.replace("outcomes_", ""))
        except ValueError:
            continue
        # Only load dates that fall inside the expected window. Using
        # an explicit set membership avoids an off-by-one between the
        # cutoff filter and the expected-dates window (Copilot review
        # PR #304: `cutoff = today - timedelta(days=window_days)` plus
        # `file_date < cutoff` would have admitted one extra older
        # date, inflating `days_present` past `days_expected`).
        if file_date.isoformat() not in expected_set:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(data, list):
            out.extend(data)
            seen.add(file_date.isoformat())
    missing = sorted(d for d in expected if d not in seen)
    coverage = {
        "days_present": len(seen),
        "days_expected": window_days,
        "missing_dates": missing,
        "window_complete": not missing,
    }
    return out, coverage


class BaselineUnavailableError(RuntimeError):
    """Raised when the baseline JSON is missing or unreadable.

    Audit D-1 (2026-06-12): the previous fail-open behaviour (return
    ``{}``) made the weekly watchdog structurally blind — with an empty
    baseline no metric pair can ever turn red, so the
    GitHub-issue-on-red escalation was dead while the cron stayed green.
    A missing/corrupt baseline is a configuration error, not a drift
    observation, and must surface as a loud failure (exit code 4).
    """


def load_baseline(baseline_json: Path) -> dict[str, Any]:
    """Load the backtest baseline JSON.

    Raises:
        BaselineUnavailableError: when the file is missing, unreadable
            or not valid JSON (audit D-1 — never fail open to ``{}``).
    """

    if not baseline_json.exists():
        raise BaselineUnavailableError(
            f"baseline JSON not found: {baseline_json} — the watchdog "
            "cannot detect drift without a baseline (audit D-1)."
        )
    try:
        return json.loads(baseline_json.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise BaselineUnavailableError(
            f"baseline JSON unreadable/invalid: {baseline_json}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# Per-setup metric extraction
# ---------------------------------------------------------------------------


def extract_metric_pairs(
    *,
    live_outcomes: list[dict[str, Any]],
    baseline: dict[str, Any],
    pnl_field: str = "pnl_30m_pct",
    setup_field: str = "setup_type",
) -> dict[str, tuple[list[float], list[float]]]:
    """Build a metric → (baseline_samples, live_samples) mapping.

    Always emits the pooled ``pnl_per_trade`` metric. Stat-review F10
    (2026-06-10): pooling heterogeneous setups against a pooled baseline
    can mask per-setup drift (a Simpson's-paradox-style failure). When
    live outcome records carry a ``setup_field`` attribution AND the
    baseline has a matching ``per_setup`` block, additional
    ``pnl_per_trade[setup=<name>]`` metrics are emitted so the detector
    consensus runs per setup as well. Live records without attribution
    (the current open_prep outcome schema has none) keep the pooled
    metric only — :func:`build_report` discloses that limitation
    explicitly instead of implying per-setup coverage.
    """

    live_pnl = [
        float(o[pnl_field])
        for o in live_outcomes
        if pnl_field in o and o[pnl_field] is not None
    ]

    baseline_per_setup = baseline.get("per_setup", {})
    baseline_pnl: list[float] = []
    baseline_by_setup: dict[str, list[float]] = {}
    if isinstance(baseline_per_setup, dict):
        for setup_name, setup_block in baseline_per_setup.items():
            if not isinstance(setup_block, dict):
                continue
            for r in setup_block.get("oos_pnl_returns", []) or []:
                try:
                    val = float(r)
                except (TypeError, ValueError):
                    continue
                baseline_pnl.append(val)
                baseline_by_setup.setdefault(str(setup_name), []).append(val)

    pairs: dict[str, tuple[list[float], list[float]]] = {
        "pnl_per_trade": (baseline_pnl, live_pnl)
    }

    # Per-setup split — only when live records carry the attribution.
    live_by_setup: dict[str, list[float]] = {}
    for o in live_outcomes:
        setup = o.get(setup_field)
        if not isinstance(setup, str) or pnl_field not in o or o[pnl_field] is None:
            continue
        live_by_setup.setdefault(setup, []).append(float(o[pnl_field]))
    for setup, live_samples in sorted(live_by_setup.items()):
        base_samples = baseline_by_setup.get(setup, [])
        if base_samples and live_samples:
            pairs[f"pnl_per_trade[setup={setup}]"] = (base_samples, live_samples)

    return pairs


# ---------------------------------------------------------------------------
# Top-level orchestration
# ---------------------------------------------------------------------------


def _assert_baseline_disjoint(
    *,
    baseline: dict[str, Any],
    window_days: int,
    today: date,
) -> None:
    """Raise if the live window overlaps the baseline OOS period.

    W9-5 (SMR wave 9): when the live window and the backtest OOS period
    overlap, the watchdog compares a distribution against itself and will
    always pass — a vacuous green that masks real drift.  Guard against
    this by checking whether the baseline's ``backtest_end_date`` falls
    inside the live window.  The threshold is >=5% overlap (i.e. at least
    one day out of a 20-day window, or more than 1 day in a 30-day window)
    rather than any overlap, to tolerate off-by-one date conventions.

    If the baseline carries no ``backtest_end_date`` the check is skipped
    with a warning — callers should add the field to new baselines.
    """
    baseline_end_str = baseline.get("backtest_end_date")
    if baseline_end_str is None:
        # Can't check without the field; tolerate missing for backward-compat
        # but log so operators know to add it to new baselines.
        import warnings
        warnings.warn(
            "baseline JSON is missing 'backtest_end_date' — temporal "
            "disjointness check skipped (W9-5).  Add backtest_end_date to "
            "the baseline to enable the overlap guard.",
            stacklevel=3,
        )
        return
    try:
        baseline_end = date.fromisoformat(str(baseline_end_str))
    except ValueError:
        import warnings
        warnings.warn(
            f"baseline 'backtest_end_date' is not a valid ISO date: "
            f"{baseline_end_str!r} — disjointness check skipped (W9-5).",
            stacklevel=3,
        )
        return

    live_dates = {
        (today - timedelta(days=offset)).isoformat()
        for offset in range(window_days)
    }
    overlap = {d for d in live_dates if date.fromisoformat(d) <= baseline_end}
    overlap_fraction = len(overlap) / max(len(live_dates), 1)
    if overlap_fraction >= 0.05:
        raise ValueError(
            f"Live window overlaps backtest baseline by {len(overlap)} date(s) "
            f"({overlap_fraction:.0%} of {len(live_dates)}-day window; "
            f"baseline ends {baseline_end}).  This would compare the "
            "distribution against itself — self-comparison detected (W9-5)."
        )


def build_report(
    *,
    outcomes_dir: Path,
    baseline_json: Path,
    window_days: int,
    today: date,
    pnl_field: str = "pnl_30m_pct",
) -> dict[str, Any]:
    live, coverage = load_live_outcomes_with_coverage(
        outcomes_dir, window_days=window_days, today=today
    )
    baseline = load_baseline(baseline_json)
    # W9-5 (SMR wave 9): guard against self-comparison before running detectors.
    _assert_baseline_disjoint(
        baseline=baseline, window_days=window_days, today=today
    )
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
            "window_days": window_days,
            "window_complete": coverage["window_complete"],
            "window_coverage": coverage,
        }

    # W3-1 (stat-review wave 3): an empty/corrupt baseline silences every
    # detector (KS/PSI/Welch-t/Brown-Forsythe all return None when the
    # baseline sample is empty) → vacuous green.  Gate to yellow instead.
    n_baseline_trades = len(pairs.get("pnl_per_trade", ([], []))[0])
    if n_baseline_trades == 0:
        return {
            "run_date": today.isoformat(),
            "aggregate_severity": "yellow",
            "reason": "missing_baseline",
            "n_live_trades": n_live_trades,
            "n_baseline_trades": 0,
            "n_metrics": 0,
            "findings": [],
            "window_days": window_days,
            "window_complete": coverage["window_complete"],
            "window_coverage": coverage,
        }

    report = compute_drift_report(pairs)
    report["run_date"] = today.isoformat()
    report["window_days"] = window_days
    report["n_live_trades"] = n_live_trades
    # Additive (non-breaking): consumers that ignore unknown keys are
    # unaffected; new consumers can yellow-flag incomplete windows.
    report["window_complete"] = coverage["window_complete"]
    report["window_coverage"] = coverage
    # Stat-review F10 (2026-06-10): disclose whether the comparison was
    # per-setup or pooled-only. Pooled-only comparisons can mask
    # per-setup drift behind an aggregate that still looks calm.
    per_setup_metrics = [m for m in pairs if m.startswith("pnl_per_trade[setup=")]
    report["per_setup_metrics"] = per_setup_metrics
    report["per_setup_live_attribution"] = bool(per_setup_metrics)
    if not per_setup_metrics:
        report["pooling_note"] = (
            "live outcomes carry no setup attribution; pnl_per_trade pools "
            "all setups against the pooled baseline — per-setup drift may "
            "be masked (stat-review F10)"
        )
    if not coverage["window_complete"] and report.get("aggregate_severity") == "green":
        # Don't escalate red→green on incomplete data; only soften green.
        report["aggregate_severity"] = "yellow"
        report["reason"] = "incomplete_window"
    # W8-1 (stat-review wave 8): when the baseline carries per-setup blocks
    # (a per-setup comparison was INTENDED) but live outcomes lacked setup
    # attribution so no pnl_per_trade[setup=…] pair could be formed, a green
    # verdict silently hides the fact that per-setup drift was never checked.
    # Mirror the incomplete_window pattern above: soften green→yellow as an
    # operator signal. Like incomplete_window this does not block the phase
    # gate (which passes on severity != "red"), but it surfaces the gap
    # instead of a clean green that masks an un-run per-setup comparison.
    if (
        bool(baseline.get("per_setup"))
        and not per_setup_metrics
        and report.get("aggregate_severity") == "green"
    ):
        report["aggregate_severity"] = "yellow"
        report.setdefault("reason", "per_setup_unattributable")
    return report


def write_report(report: dict[str, Any], *, output_dir: Path, run_date: date) -> Path:
    """Atomic write of ``drift_report_<run_date>.json``."""

    output_dir.mkdir(parents=True, exist_ok=True)
    target = output_dir / f"drift_report_{run_date.isoformat()}.json"
    fd, tmp_path = tempfile.mkstemp(dir=output_dir, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # ATOMIC-WRITE-EXEMPT: hand-rolled mkstemp+fsync+os.replace pattern above.
            json.dump(report, fh, indent=2, default=str, allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp_path)
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
    init_cli_logging()  # F-V5-A1-2 (2026-05-01)
    args = _parse_args(argv)
    today = args.today or datetime.now(tz=UTC).date()
    try:
        report = build_report(
            outcomes_dir=args.outcomes_dir,
            baseline_json=args.baseline_json,
            window_days=args.live_window_days,
            today=today,
        )
    except BaselineUnavailableError as exc:
        # Audit D-1: distinct exit code (4) so the workflow's
        # "Fail job if watchdog crashed unexpectedly" step (rc not in
        # {0, 2}) turns the run red instead of green-with-no-teeth.
        print(f"::error::drift watchdog baseline unavailable: {exc}")
        return 4
    path = write_report(report, output_dir=args.output_dir, run_date=today)
    print(f"drift report written: {path}")
    print(f"aggregate_severity: {report['aggregate_severity']}")
    if args.exit_nonzero_on_red and report.get("aggregate_severity") == "red":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
