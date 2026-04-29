"""Summarize the F2 contextual-promotion history into a single digest.

Reads:
  * The rollback-history ring at
    ``artifacts/ci/f2/rollback_history.json`` (treatment − control
    ``calibrated_brier`` deltas, one per daily run).
  * Optionally a directory of per-day promotion-gate JSON reports
    (``artifacts/reports/f2_promotion_gate_*.json``) to extract
    decision counts and the most recent SPRT terminal block.

Produces a small operator-facing JSON digest:

  {
    "schema_version": 1,
    "history": {
      "len": 14,
      "last": -0.003,
      "trend_30d": -0.0021,
      "consecutive_worse": 0,
      "consecutive_better": 5
    },
    "decisions": {
      "promote": 1, "hold": 12, "rollback": 0, "insufficient_data": 1
    },
    "latest_report": {
      "path": "artifacts/reports/f2_promotion_gate_2026-04-21.json",
      "decision": "hold",
      "date": "2026-04-21"
    },
    "latest_sprt": { ...passed through verbatim... }
  }

Pure-Python, deterministic, no network. Useful as input for a future
Pine HUD row or a weekly Slack digest.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

SUMMARY_SCHEMA_VERSION = 1
DEFAULT_TREND_WINDOW = 30
REPORT_NAME_RE = re.compile(r"f2_promotion_gate_(\d{4}-\d{2}-\d{2})\.json$")


# ---------------------------------------------------------------------------
# History helpers
# ---------------------------------------------------------------------------


def _load_history(path: Path) -> list[float]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"history file {path} must contain a JSON list, got {type(raw).__name__}"
        )
    return [float(x) for x in raw]


def _trailing_mean(values: list[float], window: int) -> float | None:
    if not values or window < 1:
        return None
    tail = values[-window:]
    return sum(tail) / len(tail)


def _consecutive_worse(values: list[float]) -> int:
    """Count trailing values strictly > 0 (treatment WORSE on calibrated_brier)."""
    n = 0
    for v in reversed(values):
        if v > 0:
            n += 1
        else:
            break
    return n


def _consecutive_better(values: list[float]) -> int:
    """Count trailing values strictly < 0 (treatment BETTER on calibrated_brier)."""
    n = 0
    for v in reversed(values):
        if v < 0:
            n += 1
        else:
            break
    return n


def summarize_history(values: list[float], *, trend_window: int = DEFAULT_TREND_WINDOW) -> dict[str, Any]:
    return {
        "len": len(values),
        "last": (values[-1] if values else None),
        "trend_window": trend_window,
        "trend_mean": _trailing_mean(values, trend_window),
        "consecutive_worse": _consecutive_worse(values),
        "consecutive_better": _consecutive_better(values),
    }


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------


def _iter_reports(reports_dir: Path) -> Iterable[tuple[str, Path]]:
    """Yield (date, path) tuples sorted ascending by date string."""
    if not reports_dir.exists():
        return
    matches: list[tuple[str, Path]] = []
    for p in reports_dir.iterdir():
        m = REPORT_NAME_RE.search(p.name)
        if m and p.is_file():
            matches.append((m.group(1), p))
    matches.sort(key=lambda x: x[0])
    yield from matches


def summarize_reports(reports_dir: Path) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    latest_path: Path | None = None
    latest_date: str | None = None
    latest_decision: str | None = None
    latest_sprt: dict[str, Any] | None = None
    seen = 0

    for date, path in _iter_reports(reports_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        decision = str(payload.get("decision") or "unknown")
        decisions[decision] = decisions.get(decision, 0) + 1
        seen += 1
        latest_path = path
        latest_date = date
        latest_decision = decision
        sprt = payload.get("sprt")
        if isinstance(sprt, dict):
            latest_sprt = sprt

    return {
        "reports_seen": seen,
        "decisions": decisions,
        "latest_report": (
            None if latest_path is None
            else {
                "path": str(latest_path),
                "date": latest_date,
                "decision": latest_decision,
            }
        ),
        "latest_sprt": latest_sprt,
    }


# ---------------------------------------------------------------------------
# Top-level summarizer
# ---------------------------------------------------------------------------


def build_summary(
    *,
    history_path: Path,
    reports_dir: Path | None,
    trend_window: int = DEFAULT_TREND_WINDOW,
) -> dict[str, Any]:
    values = _load_history(history_path)
    summary: dict[str, Any] = {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "history_path": str(history_path),
        "history": summarize_history(values, trend_window=trend_window),
    }
    if reports_dir is not None:
        summary["reports_dir"] = str(reports_dir)
        summary.update(summarize_reports(reports_dir))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Summarize the F2 rollback-history ring and recent promotion-gate reports."
    )
    parser.add_argument("--history", type=Path, required=True,
                        help="Path to the rollback-history JSON list.")
    parser.add_argument("--reports-dir", type=Path, default=None,
                        help="Optional directory of f2_promotion_gate_*.json reports.")
    parser.add_argument("--trend-window", type=int, default=DEFAULT_TREND_WINDOW,
                        help=f"Window for the trailing-mean trend (default: {DEFAULT_TREND_WINDOW}).")
    parser.add_argument("--output", type=Path, default=None,
                        help="Optional path to write the digest JSON to (defaults to stdout).")
    args = parser.parse_args(argv)

    if args.trend_window < 1:
        print(f"ERROR: --trend-window must be >= 1, got {args.trend_window}", file=sys.stderr)
        return 1

    try:
        summary = build_summary(
            history_path=args.history,
            reports_dir=args.reports_dir,
            trend_window=args.trend_window,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    text = json.dumps(summary, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(text, args.output)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
