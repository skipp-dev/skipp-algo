"""A9b.2a — Plan shards for matrix-sharded producer workflow.

Splits a contiguous trailing calendar window into ``num_shards`` near-equal
contiguous sub-ranges and emits a JSON array on stdout. The output is
designed to be consumed by a GitHub Actions matrix strategy:

    matrix={"include": <output of this script>}

Each element is::

    {
        "shard_id": 1-based int,
        "shard_of": int,
        "start_date": "YYYY-MM-DD",  # inclusive
        "end_date":   "YYYY-MM-DD",  # inclusive
    }

Sharding is done over CALENDAR days (not trading days). The producer
itself filters to actual trading days via ``list_recent_trading_days``,
so weekend/holiday gaps inside a shard's window are harmless.

Invariants enforced:
- ``num_shards >= 1``
- ``lookback_days >= num_shards`` (each shard gets at least one calendar day)
- Sub-ranges are contiguous, disjoint, and cover the full window exactly.

Usage::

    python scripts/databento_plan_shards.py --lookback-days 30 --num-shards 6
    python scripts/databento_plan_shards.py --lookback-days 10 --num-shards 2 \\
        --end-date 2026-05-08
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Sequence


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def plan_shards(
    *, lookback_days: int, num_shards: int, end_date: date
) -> list[dict[str, object]]:
    """Return the shard plan for the closed window [end - lookback + 1, end]."""
    if num_shards < 1:
        raise ValueError(f"--num-shards must be >= 1 (got {num_shards}).")
    if lookback_days < num_shards:
        raise ValueError(
            f"--lookback-days ({lookback_days}) must be >= --num-shards "
            f"({num_shards}); each shard needs at least one calendar day."
        )

    window_start = end_date - timedelta(days=lookback_days - 1)

    base = lookback_days // num_shards
    extra = lookback_days % num_shards

    shards: list[dict[str, object]] = []
    cursor = window_start
    for i in range(num_shards):
        # Distribute the remainder across the FIRST `extra` shards so the
        # split stays maximally even (e.g. lookback=10, N=3 -> 4,3,3).
        size = base + (1 if i < extra else 0)
        shard_end = cursor + timedelta(days=size - 1)
        shards.append(
            {
                "shard_id": i + 1,
                "shard_of": num_shards,
                "start_date": cursor.isoformat(),
                "end_date": shard_end.isoformat(),
            }
        )
        cursor = shard_end + timedelta(days=1)

    # Post-conditions are covered by tests/test_a9b_2a_plan_shards.py
    # (`_coverage_invariants` checks first start, last end, contiguity,
    # and total day-count). No `assert` here per
    # tests/test_os_system_input_assert_zero_surface.py discipline.
    return shards


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lookback-days", type=int, required=True)
    parser.add_argument("--num-shards", type=int, required=True)
    parser.add_argument(
        "--end-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Inclusive end of the window (YYYY-MM-DD). Defaults to today (UTC).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    end_date = args.end_date if args.end_date is not None else _today_utc()
    try:
        shards = plan_shards(
            lookback_days=int(args.lookback_days),
            num_shards=int(args.num_shards),
            end_date=end_date,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Emit via print/json.dumps rather than json.dump(stdout, ...) per
    # tests/test_no_direct_to_csv_in_production.py discipline (avoids the
    # need for an `# ATOMIC-WRITE-EXEMPT:` marker for a tiny CLI helper).
    print(json.dumps(shards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
