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
so weekend/holiday gaps inside a shard's window are harmless -- as long as
the shard also spans at least one weekday. A shard whose window is
*entirely* weekend resolves to zero trading days and the producer exits 1
("No trading days available"), failing the shard job. Pass
``--drop-weekend-only-shards`` to omit such shards from the matrix.

Invariants enforced:
- ``num_shards >= 1``
- ``lookback_days >= num_shards`` (each shard gets at least one calendar day)
- Sub-ranges are contiguous, disjoint, and cover the full window exactly.

Usage::

    python scripts/databento_plan_shards.py --lookback-days 30 --num-shards 6
    python scripts/databento_plan_shards.py --lookback-days 10 --num-shards 2 \\
        --end-date 2026-05-08

Incremental mode (opt-in): pass ``--last-baked-date`` (the watermark, i.e. the
last successfully-baked trading day) to narrow the window to only the elapsed
days since that date. Default behaviour (flag omitted) is unchanged. When the
narrowed window is smaller than ``--num-shards``, the shard count is clamped
down so each shard still spans at least one calendar day::

    python scripts/databento_plan_shards.py --lookback-days 30 --num-shards 6 \\
        --last-baked-date 2026-05-27

Current-day deferral (opt-in): pass ``--defer-current-day-until-intraday-window``
to cap the window end at the last day the producer can actually rank. Before the
intraday window opens (09:20 ET) the current day has no Databento data yet and
the FMP bridge returns empty by contract, so a shard covering *only* that day
raises ``No ranked results``. Relevant once the watermark is current: the
narrowed window is then only a few days wide, so the shard split isolates the
current day instead of burying it in a multi-day shard.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

# Regular US equity market open (ET). Mirrors the constant the producer's FMP
# bridge derives its window from; there is no exported SSOT for it (see
# databento_session.compute_market_relative_window, which hardcodes the same
# time(9, 30)).
_MARKET_OPEN_ET = time(9, 30)


def _today_utc() -> date:
    return datetime.now(UTC).date()


def _ensure_repo_root_on_path() -> None:
    """Put REPO_ROOT on ``sys.path`` so first-party imports resolve.

    Needed so the lazy loaders below work both under script-style invocation
    (``python scripts/databento_plan_shards.py``) and via importlib in tests.
    Single bootstrap site on purpose — ``tests/test_sys_path_mutation_ledger.py``
    pins this file at exactly one sys.path mutation.
    """
    repo_root = str(Path(__file__).resolve().parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)


def _load_narrow_scan_window():
    """Lazily import the sibling incremental-window helper.

    The import is deferred so the default, non-incremental code path never
    depends on the helper module being importable.
    """
    _ensure_repo_root_on_path()
    from scripts.databento_incremental_window import narrow_scan_window

    return narrow_scan_window


def _load_intraday_window_defaults():
    """Return the dependency-free ET timezone and pinned pre-open default."""
    from zoneinfo import ZoneInfo

    return ZoneInfo("America/New_York"), 10


def _now_et() -> datetime:
    """Current time in US/Eastern. Split out so tests can pin it."""
    tz, _ = _load_intraday_window_defaults()
    return datetime.now(tz)


def _intraday_window_start_et(pre_open_minutes: int) -> time:
    """The ET time from which a day becomes measurable.

    Mirrors the producer's FMP-bridge derivation verbatim, including the
    ``max(0, ...)`` clamp:
    ``databento_production_export._run_fmp_intraday_bridge``::

        _market_open_et = time(9, 30)
        _pre_open_minutes = 10  # mirrors _DEFAULT_INTRADAY_PRE_OPEN_MINUTES
        ws = time(_market_open_et.hour, max(0, _market_open_et.minute - _pre_open_minutes))

    Kept in lockstep by ``test_planner_window_start_matches_producer_bridge``.
    """
    return time(
        _MARKET_OPEN_ET.hour,
        max(0, _MARKET_OPEN_ET.minute - pre_open_minutes),
    )


def _last_measurable_day(*, now_et: datetime, pre_open_minutes: int) -> date:
    """Return the most recent day the producer can actually rank.

    Before the intraday window opens, the producer has nothing for the current
    day: Databento has not finalised it (that happens ~20:00 UTC) and the FMP
    bridge deliberately returns an empty frame while ``we <= ws``. A shard whose
    window is *only* that day therefore ranks zero rows and raises
    ``RuntimeError("No ranked results were returned ...")``.

    Note the boundary is **strict**: the producer bails on ``we <= ws``, so at
    exactly ``ws`` the current day is still NOT measurable.
    """
    ws = _intraday_window_start_et(pre_open_minutes)
    if now_et.time() > ws:
        return now_et.date()
    return now_et.date() - timedelta(days=1)


def _shard_has_weekday(start: date, end: date) -> bool:
    """Return True if [start, end] inclusive contains at least one Mon-Fri."""
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            return True
        cur = cur + timedelta(days=1)
    return False


def _drop_weekend_only_shards(
    shards: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Return ``shards`` minus weekend-only entries, renumbered 1..M.

    Renumbering is mandatory, not cosmetic: the reduce step calls
    ``merge_manifests`` with ``--expected-shard-count`` set to ``len(shards)``
    and rejects any ``shard_id > expected_shard_count``. Dropping shard 2 of 5
    without renumbering would leave ids [1, 4, 5] against an expected count of
    3 and raise ``ManifestMergeError``.

    Dropping loses no coverage: a weekend-only window contains no trading days
    by construction, so the shard could only ever have contributed an empty
    slice to ``trade_dates_covered``.
    """
    kept = [
        s
        for s in shards
        if _shard_has_weekday(
            date.fromisoformat(str(s["start_date"])),
            date.fromisoformat(str(s["end_date"])),
        )
    ]
    return [
        {**s, "shard_id": i + 1, "shard_of": len(kept)} for i, s in enumerate(kept)
    ]


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
    parser.add_argument(
        "--require-weekday-coverage",
        action="store_true",
        help="Fail (rc=2) if any shard's calendar window maps to weekend-only days; "
             "otherwise emit a stderr warning. Diagnostic only -- it reports the "
             "condition, it does not make the matrix runnable. Takes precedence over "
             "--drop-weekend-only-shards when both are passed.",
    )
    parser.add_argument(
        "--drop-weekend-only-shards",
        action="store_true",
        help="Omit weekend-only shards from the emitted matrix and renumber the "
             "survivors 1..M (shard_of=M). Use in cron-driven matrices: such a shard "
             "resolves to zero trading days and the producer exits 1, which fails the "
             "shard job and (on schedule events) the whole run. Dropping loses no "
             "coverage. If every shard is weekend-only the output is an empty matrix, "
             "which the workflow's shard_count!='0' guard skips cleanly.",
    )
    parser.add_argument(
        "--defer-current-day-until-intraday-window",
        action="store_true",
        help="Cap the window's end date at the last day the producer can actually "
             "rank. Before the intraday window opens (09:20 ET = market open minus "
             "DEFAULT_INTRADAY_PRE_OPEN_MINUTES) the current day has no Databento "
             "data yet and the FMP bridge returns empty by contract, so a shard "
             "covering only that day raises 'No ranked results'. The cap only ever "
             "moves the end date BACKWARDS and never past an explicit historical "
             "--end-date. Use in cron-driven matrices whose early ticks fire "
             "pre-market.",
    )
    parser.add_argument(
        "--last-baked-date",
        type=lambda s: date.fromisoformat(s),
        default=None,
        help="Watermark: last successfully-baked trading day (YYYY-MM-DD). When set, "
             "the window is narrowed to only the elapsed days since this date "
             "(opt-in incremental mode). Omit for the default full-lookback behaviour.",
    )
    parser.add_argument(
        "--safety-overlap-days",
        type=int,
        default=1,
        help="Incremental mode only: re-scan this many already-baked days (inclusive) "
             "so late revisions are captured. Default 1.",
    )
    parser.add_argument(
        "--min-refresh-days",
        type=int,
        default=1,
        help="Incremental mode only: smallest window to scan even when the watermark "
             "is already current. Default 1.",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    end_date = args.end_date if args.end_date is not None else _today_utc()
    lookback_days = int(args.lookback_days)
    num_shards = int(args.num_shards)

    if getattr(args, "defer_current_day_until_intraday_window", False):
        # Cap BEFORE narrowing so the incremental window and the shard split
        # both see the same, actually-rankable end day.
        _tz, pre_open_minutes = _load_intraday_window_defaults()
        last_measurable = _last_measurable_day(
            now_et=_now_et(), pre_open_minutes=pre_open_minutes
        )
        if end_date > last_measurable:
            print(
                f"info: intraday window not open yet "
                f"(>{_intraday_window_start_et(pre_open_minutes).isoformat()} ET "
                f"required); capping end date {end_date.isoformat()} -> "
                f"{last_measurable.isoformat()} so no shard covers an unrankable day.",
                file=sys.stderr,
            )
            end_date = last_measurable

    if args.last_baked_date is not None:
        # Opt-in incremental narrowing: shard only the window that has elapsed
        # since the watermark instead of the full trailing lookback. The default
        # path (flag omitted) is byte-for-byte unchanged.
        try:
            narrow_scan_window = _load_narrow_scan_window()
            plan = narrow_scan_window(
                last_baked_day=args.last_baked_date,
                today=end_date,
                full_lookback_days=lookback_days,
                min_refresh_days=int(args.min_refresh_days),
                safety_overlap_days=int(args.safety_overlap_days),
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        # The narrowed window may be smaller than the requested shard count;
        # clamp so plan_shards' `lookback_days >= num_shards` invariant holds.
        effective_shards = min(num_shards, plan.effective_lookback_days)
        print(
            f"incremental: reason={plan.reason} "
            f"window={plan.start_date.isoformat()}..{plan.end_date.isoformat()} "
            f"effective_lookback_days={plan.effective_lookback_days} "
            f"(full={lookback_days}) shards={effective_shards} "
            f"(requested={num_shards})",
            file=sys.stderr,
        )
        lookback_days = plan.effective_lookback_days
        num_shards = effective_shards

    try:
        shards = plan_shards(
            lookback_days=lookback_days,
            num_shards=num_shards,
            end_date=end_date,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    weekend_only = [
        s for s in shards
        if not _shard_has_weekday(
            date.fromisoformat(str(s["start_date"])),
            date.fromisoformat(str(s["end_date"])),
        )
    ]
    if weekend_only:
        ids = [s["shard_id"] for s in weekend_only]
        msg = (
            f"weekend-only shards detected (shard_ids={ids}); list_recent_trading_days "
            "resolves zero trading days for such a shard, so the producer exits 1 "
            "('No trading days available') and FAILS the shard job -- it does not emit "
            "an empty manifest. Pass --drop-weekend-only-shards to omit them, or use "
            "--lookback-days >= 7 * num_shards so every shard spans a weekday."
        )
        if getattr(args, "require_weekday_coverage", False):
            print(f"error: {msg}", file=sys.stderr)
            return 2
        print(f"warning: {msg}", file=sys.stderr)
        if getattr(args, "drop_weekend_only_shards", False):
            shards = _drop_weekend_only_shards(shards)
            print(
                f"info: dropped weekend-only shard(s) {ids}; renumbered survivors to "
                f"{len(shards)} shard(s).",
                file=sys.stderr,
            )
    # Emit via print/json.dumps rather than json.dump(stdout, ...) per
    # tests/test_no_direct_to_csv_in_production.py discipline (avoids the
    # need for an `# ATOMIC-WRITE-EXEMPT:` marker for a tiny CLI helper).
    print(json.dumps(shards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
