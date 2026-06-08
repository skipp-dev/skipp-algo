"""Option (b) cadence — narrow the producer scan window incrementally.

The matrix-sharded producer (``databento_plan_shards.py``) re-scans the full
trailing ``lookback_days`` window on every run. When the cadence is raised
(running more often than 2x/day), re-scanning the entire window each time is
wasteful: almost every run only needs the handful of trading days that have
elapsed since the last successful bake.

This helper computes a *narrowed* window ``[start_date, end_date]`` given the
last successfully-baked trading day (a "watermark"). The window is then handed
to ``plan_shards`` instead of the fixed trailing lookback. The full lookback is
still used on a cold start (no watermark) and acts as an upper bound so an
incremental run can never accidentally widen the scan.

A small ``safety_overlap_days`` re-scans the most recent already-baked days so
late-arriving revisions (corrections, late prints) are still picked up. The
watermark idiom mirrors ``newsstack_fmp.pipeline._filter_new_by_watermark``
(inclusive bracket), applied here to trading-day windows.

This module is PURE date arithmetic — it performs no I/O and needs no Databento
access, so it is fully unit-testable in isolation. Wiring it into the producer
(reading the watermark from the base-snapshot manifest and feeding the result
into ``plan_shards``) is a separate, opt-in step gated behind ``--last-baked-day``
so production behaviour is unchanged until explicitly enabled.

Usage::

    python scripts/databento_incremental_window.py --full-lookback-days 30
    python scripts/databento_incremental_window.py --full-lookback-days 30 \\
        --last-baked-day 2026-06-05 --end-date 2026-06-08
    python scripts/databento_incremental_window.py --full-lookback-days 30 \\
        --last-baked-day 2026-06-05 --safety-overlap-days 2 --min-refresh-days 1
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Sequence

# Reason codes for the narrowing decision (stable strings — consumed by the
# producer's logs and by tests; do not rename without updating both).
REASON_COLD_START = "cold_start"
REASON_INCREMENTAL = "incremental"
REASON_WATERMARK_AHEAD = "watermark_ahead"


def _today_utc() -> date:
    return datetime.now(UTC).date()


@dataclass(frozen=True)
class WindowPlan:
    """A narrowed, inclusive scan window for the producer.

    ``effective_lookback_days`` is the inclusive day-count of
    ``[start_date, end_date]`` and is always within
    ``[min_refresh_days, full_lookback_days]``.
    """

    start_date: date
    end_date: date
    effective_lookback_days: int
    reason: str

    def to_json_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["start_date"] = self.start_date.isoformat()
        d["end_date"] = self.end_date.isoformat()
        return d


def narrow_scan_window(
    *,
    last_baked_day: date | None,
    today: date,
    full_lookback_days: int,
    min_refresh_days: int = 1,
    safety_overlap_days: int = 1,
) -> WindowPlan:
    """Compute the inclusive scan window ``[start_date, today]``.

    Parameters
    ----------
    last_baked_day:
        The last successfully-baked trading day (the watermark). ``None``
        triggers a cold start (full lookback).
    today:
        Inclusive end of the window (the producer's "as of" day).
    full_lookback_days:
        The configured trailing lookback; also the hard upper bound on the
        narrowed window so an incremental run can never widen the scan.
    min_refresh_days:
        The smallest window to scan, even when the watermark is current. This
        guarantees at least one day is always re-confirmed.
    safety_overlap_days:
        How many already-baked days to re-scan (inclusive) so late revisions
        are captured. ``0`` starts strictly after the watermark.

    Returns
    -------
    WindowPlan
        ``start_date`` is clamped so the effective lookback stays within
        ``[min_refresh_days, full_lookback_days]`` and ``start_date <= today``.
    """
    if full_lookback_days < 1:
        raise ValueError(
            f"--full-lookback-days must be >= 1 (got {full_lookback_days})."
        )
    if min_refresh_days < 1:
        raise ValueError(
            f"--min-refresh-days must be >= 1 (got {min_refresh_days})."
        )
    if min_refresh_days > full_lookback_days:
        raise ValueError(
            f"--min-refresh-days ({min_refresh_days}) must be <= "
            f"--full-lookback-days ({full_lookback_days})."
        )
    if safety_overlap_days < 0:
        raise ValueError(
            f"--safety-overlap-days must be >= 0 (got {safety_overlap_days})."
        )

    full_start = today - timedelta(days=full_lookback_days - 1)
    min_start = today - timedelta(days=min_refresh_days - 1)

    if last_baked_day is None:
        # Cold start: scan the full configured lookback.
        return WindowPlan(
            start_date=full_start,
            end_date=today,
            effective_lookback_days=full_lookback_days,
            reason=REASON_COLD_START,
        )

    if last_baked_day >= today:
        # Watermark already at/after today: nothing new elapsed, but still
        # re-confirm the minimum window so the bake never goes fully stale.
        return WindowPlan(
            start_date=min_start,
            end_date=today,
            effective_lookback_days=min_refresh_days,
            reason=REASON_WATERMARK_AHEAD,
        )

    # Steady-state incremental: start just after the watermark, minus the
    # safety overlap so late revisions to recent days are re-scanned.
    candidate_start = last_baked_day - timedelta(days=safety_overlap_days) + timedelta(days=1)

    # Clamp into [full_start, min_start] so the window never exceeds the full
    # lookback (upper bound) nor shrinks below the minimum refresh (lower bound).
    start = candidate_start
    if start < full_start:
        start = full_start
    if start > min_start:
        start = min_start

    effective = (today - start).days + 1
    return WindowPlan(
        start_date=start,
        end_date=today,
        effective_lookback_days=effective,
        reason=REASON_INCREMENTAL,
    )


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--full-lookback-days", type=int, required=True)
    parser.add_argument(
        "--last-baked-day",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Last successfully-baked trading day (YYYY-MM-DD). Omit for a "
        "cold start (full lookback).",
    )
    parser.add_argument("--min-refresh-days", type=int, default=1)
    parser.add_argument("--safety-overlap-days", type=int, default=1)
    parser.add_argument(
        "--end-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Inclusive end of the window (YYYY-MM-DD). Defaults to today (UTC).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    today = args.end_date if args.end_date is not None else _today_utc()
    try:
        plan = narrow_scan_window(
            last_baked_day=args.last_baked_day,
            today=today,
            full_lookback_days=int(args.full_lookback_days),
            min_refresh_days=int(args.min_refresh_days),
            safety_overlap_days=int(args.safety_overlap_days),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    # Emit via print/json.dumps rather than json.dump(stdout, ...) per
    # tests/test_no_direct_to_csv_in_production.py discipline.
    print(json.dumps(plan.to_json_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
