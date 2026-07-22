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
    with the *longest* ``forward_closes`` list wins: each successive day
    the benchmark appends one more day of realized bars, so the newest version
    carries the most complete outcome window, which is the one to use for
    return calculation.  This is NOT lookahead: the forward bars were already
    generated at event-formation time in each separate daily run; we merely
    keep the most informative copy.

    Anchor-time fields missing from the winner are backfilled from the loser
    (the actual Score-Persistenz half of the fix).  ``score``, ``regime``,
    ``relative_volume`` etc. are computed from the trailing bars at anchor
    time; a later re-detection sees the anchor drifted toward the start of
    the sliding bar window, the trailing ATR window (14 bars) no longer
    fits, and the re-detected copy carries NO score.  Keeping only the
    longest-forward copy therefore silently discarded every score after
    ~3 days — the pool converged to "long forward windows, no scores"
    and the magnitude walk-forward saw 0 usable samples (observed
    2026-06-12..07-03: every daily run ended all_thin, the shadow ledger
    never grew past its 2026-06-11 seed).  Backfilling anchor-time fields
    from the older copy is not lookahead either: they were measured when
    the event formed, strictly from bars at or before the anchor.

Age filter:
    Events whose ``anchor_ts`` is older than a rolling N × 86 400-second
    window (approximately ``--max-age-days`` days) before the current UTC time
    are dropped from the accumulated output.  This prevents unbounded growth
    and keeps the accumulated pool representative of recent market behaviour.

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


# Fields computed strictly from bars at or before the anchor. They are
# immutable per (family, anchor_ts) but disappear from later re-detections
# once the anchor drifts below the trailing-window requirement (ATR period,
# regime/relative-volume lookbacks) in the sliding benchmark bar window.
_ANCHOR_TIME_FIELDS: tuple[str, ...] = (
    "score",
    "regime",
    "relative_volume",
    "vrvp_va_pos",
    "vrvp_vpoc_dist",
    "entry_price",
    "entry_mode",
    "zone_low",
    "zone_high",
)


def _merge_event(
    winner: dict[str, Any], loser: dict[str, Any]
) -> dict[str, Any]:
    """Winner's copy, with anchor-time fields backfilled from the loser.

    The winner (longest forward window) keeps every field it has; only
    anchor-time fields it *lacks* are carried over from the loser, so a
    scored day-0 detection survives being superseded by an unscored
    day-k re-detection.
    """
    merged = dict(winner)
    for field in _ANCHOR_TIME_FIELDS:
        if merged.get(field) is None and loser.get(field) is not None:
            merged[field] = loser[field]
    return merged


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
    Tie-break: the event with the longest ``forward_closes`` list wins;
    anchor-time fields the winner lacks are backfilled from the loser
    (Score-Persistenz — see module docstring).
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
            if existing is None:
                by_key[key] = event
            elif _forward_len(event) > _forward_len(existing):
                by_key[key] = _merge_event(event, existing)
            else:
                by_key[key] = _merge_event(existing, event)

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
    parser.add_argument(
        "--max-shrink-fraction",
        type=float,
        default=None,
        metavar="F",
        help=(
            "Pool-continuity guard (issue #3872 post-mortem): refuse to write "
            "when the merged pool keeps fewer than (1-F) of --previous's "
            "events, and always refuse an EMPTY merge when a non-empty "
            "--previous existed. On 2026-07-13 an empty-list pool slipped "
            "through the workflow's file-size check (a JSON '[]' is a "
            "non-empty FILE) and the accumulated lineage was wiped and "
            "rebuilt from single-day snapshots. rc=4 on refusal; the "
            "workflow maps any non-zero rc to publishable=false, preserving "
            "the last-good artifact. Default: guard off (previous behaviour)."
        ),
    )
    args = parser.parse_args(argv)

    if args.max_age_days <= 0:
        print("error: --max-age-days must be a positive integer", file=sys.stderr)
        return 1
    if args.max_shrink_fraction is not None and not (0.0 < args.max_shrink_fraction < 1.0):
        print("error: --max-shrink-fraction must be in (0, 1)", file=sys.stderr)
        return 1

    if args.input_files is not None:
        input_files = [Path(p) for p in args.input_files]
    else:
        input_files = [Path(args.current)]
        if args.previous is not None:
            input_files.append(Path(args.previous))

    merged = accumulate(input_files, max_age_days=args.max_age_days)

    if args.max_shrink_fraction is not None and args.previous is not None:
        prev_count = len(_load_events(Path(args.previous)))
        floor_count = int(prev_count * (1.0 - args.max_shrink_fraction))
        if prev_count > 0 and (not merged or len(merged) < floor_count):
            print(
                "error: pool-continuity guard refused the merge: "
                f"previous pool had {prev_count} events, merged result has "
                f"{len(merged)} (floor: {floor_count}). A legitimate age-out "
                "never shrinks this fast; this looks like a wiped or "
                "truncated input. Not writing output — the last-good "
                "artifact stays canonical. Rebuild deliberately via the "
                "reseed dispatch if the shrink is intentional.",
                file=sys.stderr,
            )
            return 4

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(merged, output_path, indent=2, sort_keys=True)

    family_counts: dict[str, int] = {}
    scored_counts: dict[str, int] = {}
    for event in merged:
        family = str(event.get("family", "?"))
        family_counts[family] = family_counts.get(family, 0) + 1
        if event.get("score") is not None:
            scored_counts[family] = scored_counts.get(family, 0) + 1
    # Scored counts make Score-Persistenz observable in the rolling-bench
    # log: without them weeks of silent score loss looked identical to a
    # healthy pool (the 2026-06/07 all_thin incident).
    count_str = " | ".join(
        f"{f}:{n} (scored {scored_counts.get(f, 0)})"
        for f, n in sorted(family_counts.items())
    )
    print(
        f"accumulate_family_events: {len(merged)} events after merge "
        f"(max_age_days={args.max_age_days})"
        + (f" — {count_str}" if count_str else ""),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
