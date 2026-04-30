"""F2 rollback-history append helper (plan §2.4 G2 / §2.3 F2).

Maintains ``artifacts/ci/f2/rollback_history.json`` as a chronologically-
ordered JSON list of ``treatment - control`` ``calibrated_brier`` deltas,
one per daily promotion-gate run. Bounded to a configurable ring length
(default 30) so the file never grows unbounded.

Reads the digest produced by :mod:`scripts.f2_run_promotion_gate` (which
embeds ``kpi_metrics`` from
:func:`scripts.run_ab_comparison.compare`) and appends the matching
metric's delta. Idempotent on accidental re-runs of the same day's
report — duplicate values at the tail are NOT deduplicated; the caller
controls cadence (one CI invocation per day), so dedup is intentionally
omitted to keep the helper composable.

The output file is the input to ``--rollback-history`` for the next
day's promotion-gate run, closing the loop:

  Day N: f2_run_promotion_gate -> report_N.json
         f2_append_rollback_history --report report_N.json
                                    --history history.json
  Day N+1: f2_run_promotion_gate --rollback-history history.json
                                 -> reads trailing K deltas
                                 -> rollback gate fires if all worse

Atomic write via tempfile + os.replace so a Ctrl-C mid-run cannot
truncate the history.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any
import contextlib

DEFAULT_MAX_LEN = 30
DEFAULT_METRIC = "calibrated_brier"


def _load_history(path: Path) -> list[float]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"history file {path} must contain a JSON list, got {type(raw).__name__}"
        )
    return [float(x) for x in raw]


def _atomic_write(path: Path, data: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(tmp, str(path))
    except BaseException:
        if fd >= 0:
            os.close(fd)
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _delta_from_report(report: dict[str, Any], metric: str) -> float:
    metrics = report.get("kpi_metrics") or []
    for row in metrics:
        if row.get("metric") == metric:
            return float(row.get("delta") or 0.0)
    raise ValueError(
        f"report does not contain a kpi_metrics row for metric={metric!r}"
    )


def append_history(
    *,
    report: dict[str, Any],
    history_path: Path,
    metric: str = DEFAULT_METRIC,
    max_len: int = DEFAULT_MAX_LEN,
) -> list[float]:
    """Append the metric delta from *report* to *history_path*.

    Returns the new bounded history list (also persisted to disk).
    """
    if max_len < 1:
        raise ValueError(f"max_len must be >= 1, got {max_len}")
    delta = _delta_from_report(report, metric)
    history = _load_history(history_path)
    history.append(delta)
    if len(history) > max_len:
        history = history[-max_len:]
    _atomic_write(history_path, history)
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Append today's F2 calibrated_brier delta to the rollback history."
    )
    parser.add_argument("--report", type=Path, required=True,
                        help="Path to today's promotion-gate JSON report.")
    parser.add_argument("--history", type=Path, required=True,
                        help="Path to the rollback-history JSON list (created if missing).")
    parser.add_argument("--metric", type=str, default=DEFAULT_METRIC,
                        help=f"KPI metric to track (default: {DEFAULT_METRIC}).")
    parser.add_argument("--max-len", type=int, default=DEFAULT_MAX_LEN,
                        help=f"Maximum history length (default: {DEFAULT_MAX_LEN}).")
    args = parser.parse_args(argv)

    if not args.report.exists():
        print(f"ERROR: report does not exist: {args.report}", file=sys.stderr)
        return 1
    try:
        report = json.loads(args.report.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: failed to parse {args.report}: {exc}", file=sys.stderr)
        return 1
    try:
        new_history = append_history(
            report=report,
            history_path=args.history,
            metric=args.metric,
            max_len=args.max_len,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "history_path": str(args.history),
        "metric": args.metric,
        "history_len": len(new_history),
        "tail": new_history[-min(5, len(new_history)):],
    }, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
