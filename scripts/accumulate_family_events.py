"""ADR-0023 Option B — rolling accumulation of FamilyEvent records.

Merges ``FamilyEvent`` JSON files produced by successive daily runs of the
``smc-measurement-benchmark-rolling`` workflow into a single accumulated
snapshot.  This implements the **Score-Persistenz + Akkumulationsfenster**
fix for Issue #2706: a single daily benchmark run yields only ~9 % of events
with score + triggered return (all clustering in ~3 anchor days), which is
below the MIN_OOS_SAMPLES=40 threshold the purged walk-forward calibration
needs.  By accumulating up to ``--max-age-days`` days of daily runs the
event pool grows large enough for the walk-forward to assemble sufficient
out-of-sample folds.

Deduplication rule (Score-Persistenz):
    Events are keyed by ``(family, anchor_ts)``.  When the same event appears
    in multiple daily snapshots (re-detected as *open* structure), the version
    with the *longest* ``forward_closes`` list is kept: each successive day
    the benchmark appends one more day of realized bars, so the newest version
    carries the most complete outcome window, which is the one to use for
    return calculation.  This is NOT lookahead: the forward bars were already
    generated at event-formation time in each separate daily run; we merely
    keep the most informative copy.

Age filter:
    Events whose ``anchor_ts`` is older than ``--max-age-days`` calendar days
    before today UTC are dropped from the accumulated output.  This prevents
    unbounded growth and keeps the accumulated pool representative of recent
    market behaviour.

Usage::

    python scripts/accumulate_family_events.py \\
        --current  artifacts/ci/measurement_benchmark_rolling/2026-06-16/scored_family_events.json \\
        --previous artifacts/ci/accumulated_family_events_prev.json \\
        --output   artifacts/ci/accumulated_family_events.json \\
        --max-age-days 30

    # Or use --input-files for an arbitrary list:
    python scripts/accumulate_family_events.py \\
        --input-files day1.json day2.json day3.json \\
        --output merged.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json


def _load_events(path: Path) -> list[dict[str, Any]]:
    """Load a JSON list of FamilyEvent dicts; return [] on any read error."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"::warning ::accumulate_family_events: cannot read {path}: {exc}",
              file=sys.stderr)
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"::warning ::accumulate_family_events: cannot parse {path}: {exc}",
              file=sys.stderr)
        return []
    if not isinstance(data, list):
        print(f"::warning ::accumulate_family_events: {path} is not a JSON list, "
              "skipping", file=sys.stderr)
        return []
    return [e for e in data if isinstance(e, dict)]


def _forward_len(event: dict[str, Any]) -> int:
    """Length of the forward_closes list; 0 when absent."""
    return len(event.get("forward_closes") or [])


def _cutoff_ts(max_age_days: int) -> float:
    """Epoch-seconds cutoff: events older than this are dropped."""
    now = datetime.now(UTC)
    seconds_per_day = 86_400
    return now.timestamp() - max_age_days * seconds_per_day


def accumulate(
    input_files: list[Path],
    *,
    max_age_days: int,
) -> list[dict[str, Any]]:
    """Merge *input_files* into a single deduplicated event list.

    Deduplication key: ``(family, anchor_ts)``.
    Tie-break: keep the event with the longest ``forward_closes`` list.
    Age filter: drop events older than ``max_age_days`` calendar days.
    """
    by_key: dict[tuple[str, float], dict[str, Any]] = {}
    cutoff = _cutoff_ts(max_age_days)

    for path in input_files:
        if not path.exists():
            continue
        for event in _load_events(path):
            family = str(event.get("family", ""))
            anchor_ts_raw = event.get("anchor_ts")
            if not family or anchor_ts_raw is None:
                continue
            try:
                anchor_ts = float(anchor_ts_raw)
            except (TypeError, ValueError):
                continue
            if anchor_ts < cutoff:
                continue  # too old — skip

            key = (family, anchor_ts)
            existing = by_key.get(key)
            if existing is None or _forward_len(event) > _forward_len(existing):
                by_key[key] = event

    # Sort by anchor_ts ascending so consumers get a deterministic order.
    return sorted(by_key.values(), key=lambda e: float(e.get("anchor_ts", 0)))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument(
        "--input-files",
        nargs="+",
        metavar="PATH",
        help="One or more JSON event files to merge (alternative to --current / --previous).",
    )
    source_group.add_argument(
        "--current",
        metavar="PATH",
        help="Today's scored_family_events.json from the rolling benchmark.",
    )
    parser.add_argument(
        "--previous",
        metavar="PATH",
        default=None,
        help=(
            "Previously accumulated JSON (output of an earlier run of this script). "
            "May be absent on the first run."
        ),
    )
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Write merged+deduplicated events to this path (JSON list).",
    )
    parser.add_argument(
        "--max-age-days",
        type=int,
        default=30,
        metavar="N",
        help="Drop events older than N calendar days before today UTC (default: 30).",
    )
    args = parser.parse_args(argv)

    if args.max_age_days <= 0:
        print("error: --max-age-days must be a positive integer", file=sys.stderr)
        return 1

    if args.input_files is not None:
        input_files = [Path(p) for p in args.input_files]
    else:
        input_files = [Path(args.current)]
        if args.previous is not None:
            input_files.append(Path(args.previous))

    merged = accumulate(input_files, max_age_days=args.max_age_days)

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(merged, output_path, indent=2, sort_keys=True)

    family_counts: dict[str, int] = {}
    for event in merged:
        family_counts[str(event.get("family", "?"))] = (
            family_counts.get(str(event.get("family", "?")), 0) + 1
        )
    count_str = " | ".join(f"{f}:{n}" for f, n in sorted(family_counts.items()))
    print(
        f"accumulate_family_events: {len(merged)} events after merge "
        f"(max_age_days={args.max_age_days})"
        + (f" — {count_str}" if count_str else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
