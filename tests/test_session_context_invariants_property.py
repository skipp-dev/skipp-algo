"""Property tests for ``smc_core.session_context`` pure helpers.

Pins the math contract of the session liquidity context primitives
(killzones, session pivots, DWM levels, opening levels):

  * :func:`smc_core.session_context._parse_hhmm`
  * :func:`smc_core.session_context._in_session`
  * :func:`smc_core.session_context._session_date_for_row`
  * :func:`smc_core.session_context.build_killzones`
  * :func:`smc_core.session_context.build_session_pivots`
  * :func:`smc_core.session_context.build_dwm_levels`
  * :func:`smc_core.session_context.build_opening_levels`
  * :func:`smc_core.session_context.build_session_liquidity_context`

Continues the PQ Re-Audit Tier-1 spillover series
(PRs #2350, #2363, #2366, #2370, #2371, #2372, #2373, #2374, #2375).
Pure stdlib + pandas (already a hard dep of ``session_context``); ≤ 2s.
"""

from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from smc_core.session_context import (
    DEFAULT_KILLZONES,
    DEFAULT_OPENING_LEVELS,
    DEFAULT_TZ,
    _in_session,
    _parse_hhmm,
    _session_date_for_row,
    build_dwm_levels,
    build_killzones,
    build_opening_levels,
    build_session_liquidity_context,
    build_session_pivots,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


ET = ZoneInfo(DEFAULT_TZ)


def _et_ts(y: int, mo: int, d: int, hh: int, mm: int) -> int:
    """Epoch seconds for a local-ET wall clock instant."""
    return int(pd.Timestamp(datetime(y, mo, d, hh, mm), tz=ET).timestamp())


def _bar(ts: int, o: float, h: float, lo: float, c: float, v: float = 1.0) -> dict:
    return {"timestamp": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}


def _bars(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# _parse_hhmm
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    (
        ("00:00", time(0, 0)),
        ("09:30", time(9, 30)),
        ("13:45", time(13, 45)),
        ("23:59", time(23, 59)),
    ),
)
def test_parse_hhmm_basic(raw: str, expected: time) -> None:
    assert _parse_hhmm(raw) == expected


def test_parse_hhmm_default_killzones_parseable() -> None:
    for _, start_hm, end_hm in DEFAULT_KILLZONES:
        _parse_hhmm(start_hm)
        _parse_hhmm(end_hm)


def test_parse_hhmm_default_opening_levels_parseable() -> None:
    for hm in DEFAULT_OPENING_LEVELS:
        _parse_hhmm(hm)


# ---------------------------------------------------------------------------
# _in_session
# ---------------------------------------------------------------------------


def _et_dt(hh: int, mm: int) -> datetime:
    return datetime(2025, 1, 15, hh, mm, tzinfo=ET)


# NY AM 09:30 → 11:00 (non-wrap)


@pytest.mark.parametrize(
    "hh,mm,expected",
    (
        (9, 30, True),   # start inclusive
        (10, 0, True),
        (10, 59, True),
        (11, 0, False),  # end exclusive
        (9, 29, False),
    ),
)
def test_in_session_non_wrap_half_open_interval(hh: int, mm: int, expected: bool) -> None:
    assert _in_session(_et_dt(hh, mm), time(9, 30), time(11, 0)) is expected


# Asia 20:00 → 00:00 (wrap, end == midnight)


@pytest.mark.parametrize(
    "hh,mm,expected",
    (
        (20, 0, True),   # start inclusive
        (22, 30, True),
        (23, 59, True),
        (0, 0, False),   # end-exclusive midnight: local_t < 00:00 never matches
        (19, 59, False),
        (12, 0, False),
    ),
)
def test_in_session_wrap_to_midnight(hh: int, mm: int, expected: bool) -> None:
    assert _in_session(_et_dt(hh, mm), time(20, 0), time(0, 0)) is expected


# Generic wrap 22:00 → 02:00


@pytest.mark.parametrize(
    "hh,mm,expected",
    (
        (22, 0, True),
        (23, 30, True),
        (0, 30, True),
        (1, 59, True),
        (2, 0, False),   # end exclusive
        (21, 59, False),
        (12, 0, False),
    ),
)
def test_in_session_wrap_overnight(hh: int, mm: int, expected: bool) -> None:
    assert _in_session(_et_dt(hh, mm), time(22, 0), time(2, 0)) is expected


# ---------------------------------------------------------------------------
# _session_date_for_row
# ---------------------------------------------------------------------------


def test_session_date_non_wrap_uses_calendar_date() -> None:
    dt = _et_dt(10, 0)
    assert _session_date_for_row(dt, time(9, 30), time(11, 0)) == dt.date()


def test_session_date_wrap_evening_part_uses_starting_date() -> None:
    """Evening side of an overnight session is keyed by the starting date."""
    dt = _et_dt(22, 30)  # 2025-01-15 22:30
    assert _session_date_for_row(dt, time(22, 0), time(2, 0)) == dt.date()


def test_session_date_wrap_morning_part_uses_previous_date() -> None:
    """Morning side of an overnight session is keyed by the previous day."""
    dt = _et_dt(1, 30)   # 2025-01-15 01:30 ET, session started 2025-01-14 22:00
    assert _session_date_for_row(dt, time(22, 0), time(2, 0)) == datetime(2025, 1, 14).date()


# ---------------------------------------------------------------------------
# build_killzones
# ---------------------------------------------------------------------------


def test_build_killzones_empty_returns_empty() -> None:
    df = _bars([_bar(_et_ts(2025, 1, 15, 7, 0), 100, 101, 99, 100)])  # 07:00 ET — outside every zone
    assert build_killzones(df) == []


def test_build_killzones_ny_am_aggregates_high_low() -> None:
    """NY AM (09:30–11:00 ET) high/low/mid/range come from the bars in-window."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 105, 95, 102),
        _bar(_et_ts(2025, 1, 15, 10, 0), 102, 110, 100, 108),
        _bar(_et_ts(2025, 1, 15, 10, 30), 108, 112, 104, 110),
        _bar(_et_ts(2025, 1, 15, 11, 0), 110, 115, 109, 114),   # exactly at end — excluded
    ])
    out = build_killzones(df)
    assert len(out) == 1
    zone = out[0]
    assert zone["name"] == "NY AM"
    assert zone["date"] == "2025-01-15"
    assert zone["high"] == 112.0
    assert zone["low"] == 95.0
    assert zone["mid"] == pytest.approx((112.0 + 95.0) / 2.0)
    assert zone["range"] == pytest.approx(112.0 - 95.0)
    assert zone["start_ts"] == _et_ts(2025, 1, 15, 9, 30)
    assert zone["end_ts"] == _et_ts(2025, 1, 15, 10, 30)


def test_build_killzones_asia_overnight_keyed_by_starting_date() -> None:
    """Asia (20:00–00:00 ET) on 2025-01-15 22:00 keys the session under 2025-01-15."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 21, 0), 100, 105, 95, 102),
        _bar(_et_ts(2025, 1, 15, 23, 30), 102, 108, 99, 106),
    ])
    out = build_killzones(df)
    assert len(out) == 1
    assert out[0]["name"] == "Asia"
    assert out[0]["date"] == "2025-01-15"


def test_build_killzones_sorted_by_date_then_name() -> None:
    """Output rows sort by (date, name)."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 110, 90, 100),    # NY AM 2025-01-15
        _bar(_et_ts(2025, 1, 15, 13, 30), 100, 110, 90, 100),   # NY PM 2025-01-15
        _bar(_et_ts(2025, 1, 16, 9, 30), 100, 110, 90, 100),    # NY AM 2025-01-16
    ])
    out = build_killzones(df)
    keys = [(z["date"], z["name"]) for z in out]
    assert keys == sorted(keys)


def test_build_session_pivots_alias_of_killzones() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 110, 90, 100),
        _bar(_et_ts(2025, 1, 15, 10, 0), 100, 110, 90, 100),
    ])
    assert build_session_pivots(df) == build_killzones(df)


# ---------------------------------------------------------------------------
# build_dwm_levels
# ---------------------------------------------------------------------------


def test_build_dwm_levels_single_day_returns_empty_dict() -> None:
    """Less than 2 daily buckets → no day/week/month levels emitted."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 110, 90, 100),
        _bar(_et_ts(2025, 1, 15, 10, 0), 100, 110, 90, 100),
    ])
    assert build_dwm_levels(df) == {}


def test_build_dwm_levels_prev_day_from_local_tz_not_utc() -> None:
    """Bucketing happens in local tz (ET), not UTC.

    A 2025-01-14 21:00 ET bar (= 2025-01-15 02:00 UTC) belongs to **2025-01-14**
    in ET but would land on **2025-01-15** in UTC. If bucketing used UTC, both
    bars would share one daily bucket and ``prev_day_*`` would not be emitted.
    """
    df = _bars([
        _bar(_et_ts(2025, 1, 14, 21, 0), 100, 120, 80, 110),   # ET 2025-01-14
        _bar(_et_ts(2025, 1, 15, 14, 0), 110, 115, 105, 112),  # ET 2025-01-15
    ])
    result = build_dwm_levels(df)
    assert result["prev_day_high"] == 120.0
    assert result["prev_day_low"] == 80.0
    assert result["day_open"] == 110.0  # first 'open' of latest ET day


def test_build_dwm_levels_iso_week_year_boundary_uses_iso_year() -> None:
    """``%G-W%V`` puts 2024-12-30 into ISO week ``2025-W01``; the following
    ISO week ``2025-W02`` starts 2025-01-06. Both rows therefore live in
    separate weekly buckets, so ``prev_week_*`` is emitted from the first.
    """
    df = _bars([
        _bar(_et_ts(2024, 12, 30, 10, 0), 100, 130, 70, 110),   # ISO week 2025-W01
        _bar(_et_ts(2025, 1, 6, 10, 0), 110, 115, 105, 112),    # ISO week 2025-W02
    ])
    result = build_dwm_levels(df)
    assert result["prev_week_high"] == 130.0
    assert result["prev_week_low"] == 70.0
    # ...and month-bucketing remains calendar-based: 2024-12 vs 2025-01.
    assert result["prev_month_high"] == 130.0
    assert result["prev_month_low"] == 70.0


def test_build_dwm_levels_two_months_two_days_yields_all_levels() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 31, 10, 0), 100, 120, 80, 110),
        _bar(_et_ts(2025, 2, 3, 10, 0), 110, 115, 105, 112),
    ])
    result = build_dwm_levels(df)
    for key in (
        "day_open", "prev_day_high", "prev_day_low",
        "week_open", "prev_week_high", "prev_week_low",
        "month_open", "prev_month_high", "prev_month_low",
    ):
        assert key in result


# ---------------------------------------------------------------------------
# build_opening_levels
# ---------------------------------------------------------------------------


def test_build_opening_levels_picks_matching_local_time() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 6, 0), 101, 102, 100, 101),
        _bar(_et_ts(2025, 1, 15, 10, 0), 110, 111, 109, 110),
        _bar(_et_ts(2025, 1, 15, 14, 0), 120, 121, 119, 120),
    ])
    out = build_opening_levels(df)
    by_name = {row["name"]: row for row in out}
    assert by_name["06:00"]["price"] == 101.0
    assert by_name["10:00"]["price"] == 110.0
    assert by_name["14:00"]["price"] == 120.0


def test_build_opening_levels_missing_exact_match_falls_back_to_next_bar() -> None:
    """No exact 10:00 bar → first bar at or after 10:00 ET is picked."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 10, 5), 110, 111, 109, 110),
    ])
    out = build_opening_levels(df)
    names = [row["name"] for row in out]
    assert "10:00" in names
    picked = next(row for row in out if row["name"] == "10:00")
    assert picked["price"] == 110.0


def test_build_opening_levels_no_eligible_bar_excludes_entry() -> None:
    """Bars only at 11:00 → no 14:00 entry can be produced for that day."""
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 11, 0), 110, 111, 109, 110),
    ])
    out = build_opening_levels(df)
    names = {row["name"] for row in out}
    assert "14:00" not in names


def test_build_opening_levels_sorted_by_date_then_ts_then_name() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 6, 0), 101, 102, 100, 101),
        _bar(_et_ts(2025, 1, 15, 10, 0), 110, 111, 109, 110),
        _bar(_et_ts(2025, 1, 16, 6, 0), 201, 202, 200, 201),
    ])
    out = build_opening_levels(df)
    keys = [(r["date"], r["timestamp"], r["name"]) for r in out]
    assert keys == sorted(keys)


# ---------------------------------------------------------------------------
# build_session_liquidity_context — orchestration
# ---------------------------------------------------------------------------


def test_build_session_liquidity_context_keys_complete() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 110, 90, 100),
        _bar(_et_ts(2025, 1, 16, 9, 30), 100, 110, 90, 100),
    ])
    ctx = build_session_liquidity_context(df)
    assert set(ctx.keys()) == {"killzones", "session_pivots", "dwm_levels", "opening_levels"}


def test_build_session_liquidity_context_components_match_individual_builders() -> None:
    df = _bars([
        _bar(_et_ts(2025, 1, 15, 9, 30), 100, 110, 90, 100),
        _bar(_et_ts(2025, 1, 16, 9, 30), 100, 110, 90, 100),
    ])
    ctx = build_session_liquidity_context(df)
    assert ctx["killzones"] == build_killzones(df)
    assert ctx["session_pivots"] == build_session_pivots(df)
    assert ctx["dwm_levels"] == build_dwm_levels(df)
    assert ctx["opening_levels"] == build_opening_levels(df)
