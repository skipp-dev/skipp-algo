"""Property tests for ``smc_core.htf_context`` pure helpers.

Pins the math contract of the HTF (higher-timeframe) bias context
primitives feeding the FVG bias counter, the IPDA-range quartiles, and
the calendar-boundary detectors used by every HTF overlay:

  * :func:`smc_core.htf_context.compute_fvg_bias_counter`
  * :func:`smc_core.htf_context.select_ipda_htf`
  * :func:`smc_core.htf_context.build_ipda_range`
  * :func:`smc_core.htf_context.compute_calendar_boundaries`
  * :func:`smc_core.htf_context.build_htf_bias_context`

Continues the PQ Re-Audit Tier-1 spillover series
(PRs #2350, #2363, #2366, #2370, #2371, #2372, #2373, #2374).

Pure stdlib + pandas (already a hard dep of ``htf_context``); ≤ 2s.
"""

from __future__ import annotations

import random
from typing import Any

import pandas as pd
import pytest

from smc_core.htf_context import (
    build_htf_bias_context,
    build_ipda_range,
    compute_calendar_boundaries,
    compute_fvg_bias_counter,
    select_ipda_htf,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bars(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])


def _make_bar(ts: int, o: float, h: float, lo: float, c: float, v: float = 1.0) -> dict:
    return {"timestamp": ts, "open": o, "high": h, "low": lo, "close": c, "volume": v}


# ---------------------------------------------------------------------------
# compute_fvg_bias_counter
# ---------------------------------------------------------------------------


def test_fvg_bias_counter_single_bar_returns_empty() -> None:
    """Counter iterates i in [1, len) → a single bar produces no entries."""
    df = _bars([_make_bar(1, 100, 101, 99, 100)])
    assert compute_fvg_bias_counter(df) == []


def test_fvg_bias_counter_continuous_bullish_breakouts_increment() -> None:
    """Each `close[i] > high[i-1]` increments the counter by 1."""
    df = _bars([
        _make_bar(1, 100, 105, 95, 100),
        _make_bar(2, 100, 110, 100, 106),   # close 106 > prev high 105 → +1
        _make_bar(3, 106, 115, 105, 111),   # close 111 > prev high 110 → +1
        _make_bar(4, 111, 120, 110, 116),   # close 116 > prev high 115 → +1
    ])
    out = compute_fvg_bias_counter(df)
    assert [row["counter"] for row in out] == [1, 2, 3]
    assert all(row["direction"] == "BULLISH" for row in out)


def test_fvg_bias_counter_continuous_bearish_breakouts_decrement() -> None:
    df = _bars([
        _make_bar(1, 100, 105, 95, 100),
        _make_bar(2, 100, 100, 90, 94),     # close 94 < prev low 95 → -1
        _make_bar(3, 94, 95, 85, 89),       # close 89 < prev low 90 → -1
    ])
    out = compute_fvg_bias_counter(df)
    assert [row["counter"] for row in out] == [-1, -2]
    assert all(row["direction"] == "BEARISH" for row in out)


def test_fvg_bias_counter_flip_resets_then_steps() -> None:
    """Sign flip resets to 0 first, then applies the new step (BULL → -1, BEAR → +1)."""
    df = _bars([
        _make_bar(1, 100, 105, 95, 100),
        _make_bar(2, 100, 110, 100, 106),   # bullish → +1
        _make_bar(3, 106, 115, 105, 111),   # bullish → +2
        _make_bar(4, 111, 112, 100, 104),   # bearish (close 104 < prev low 105) → reset to 0 then -1
        _make_bar(5, 104, 105, 95, 99),     # bearish (close 99 < prev low 100) → -2
        _make_bar(6, 99, 115, 99, 110),     # bullish (close 110 > prev high 105) → reset to 0 then +1
    ])
    out = compute_fvg_bias_counter(df)
    assert [row["counter"] for row in out] == [1, 2, -1, -2, 1]


def test_fvg_bias_counter_inside_bar_holds_counter() -> None:
    """Bars that are neither bullish nor bearish breakouts leave the counter unchanged."""
    df = _bars([
        _make_bar(1, 100, 110, 90, 100),
        _make_bar(2, 100, 115, 95, 112),    # bullish breakout → +1
        _make_bar(3, 112, 113, 105, 108),   # inside (close 108 < prev high 115, close 108 > prev low 95) → 1
        _make_bar(4, 108, 112, 100, 110),   # inside → 1
    ])
    out = compute_fvg_bias_counter(df)
    assert [row["counter"] for row in out] == [1, 1, 1]
    assert [row["direction"] for row in out] == ["BULLISH", "BULLISH", "BULLISH"]


def test_fvg_bias_counter_neutral_when_counter_zero() -> None:
    """Bar that is neither bullish nor bearish before any breakout → counter stays 0 → NEUTRAL."""
    df = _bars([
        _make_bar(1, 100, 110, 90, 100),
        _make_bar(2, 100, 108, 92, 100),    # inside, counter stays 0
    ])
    out = compute_fvg_bias_counter(df)
    assert out == [{"time": 2, "counter": 0, "direction": "NEUTRAL"}]


@pytest.mark.parametrize("seed", (0, 1, 7, 13, 42))
def test_fvg_bias_counter_direction_matches_sign(seed: int) -> None:
    """Invariant: ``direction == sign(counter)`` for every output row."""
    rng = random.Random(seed)
    rows = [_make_bar(0, 100.0, 102.0, 98.0, 100.0)]
    for i in range(1, 40):
        prev = rows[-1]
        mid = (prev["high"] + prev["low"]) / 2
        # random close above/below/inside prev
        close = mid + rng.uniform(-5.0, 5.0)
        h = max(prev["high"], close) + 1.0
        lo = min(prev["low"], close) - 1.0
        rows.append(_make_bar(i, prev["close"], h, lo, close))
    out = compute_fvg_bias_counter(_bars(rows))
    for row in out:
        c = row["counter"]
        if c > 0:
            assert row["direction"] == "BULLISH"
        elif c < 0:
            assert row["direction"] == "BEARISH"
        else:
            assert row["direction"] == "NEUTRAL"


# ---------------------------------------------------------------------------
# select_ipda_htf
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chart_tf,expected",
    (
        ("1m", "D"),
        ("5m", "D"),
        ("10m", "D"),
        ("15m", "D"),
        ("30m", "D"),
        ("1H", "D"),
        ("2H", "D"),
        ("3H", "W"),
        ("4H", "W"),
        ("6H", "W"),
        ("8H", "W"),
        ("12H", "W"),
        ("D", "M"),
        ("W", "6M"),
    ),
)
def test_select_ipda_htf_known_timeframes(chart_tf: str, expected: str) -> None:
    assert select_ipda_htf(chart_tf) == expected


@pytest.mark.parametrize("unknown", ("M", "6M", "Y", "tick", "", "  "))
def test_select_ipda_htf_unknown_returns_daily_fallback(unknown: str) -> None:
    assert select_ipda_htf(unknown) == "D"


@pytest.mark.parametrize("chart_tf", ("  1m  ", "\t5m\n", " 1H "))
def test_select_ipda_htf_strips_whitespace(chart_tf: str) -> None:
    assert select_ipda_htf(chart_tf) == "D"


# ---------------------------------------------------------------------------
# build_ipda_range
# ---------------------------------------------------------------------------


def test_build_ipda_range_quartiles_are_linear_interpolation() -> None:
    out = build_ipda_range(
        {"high": 110.0, "low": 100.0}, {"high": 105.0, "low": 95.0},
    )
    assert out["range_high"] == 110.0
    assert out["range_low"] == 95.0
    assert out["width"] == pytest.approx(15.0)
    assert out["q25"] == pytest.approx(95.0 + 0.25 * 15.0)
    assert out["mid"] == pytest.approx(95.0 + 0.50 * 15.0)
    assert out["q75"] == pytest.approx(95.0 + 0.75 * 15.0)


def test_build_ipda_range_zero_width_when_identical_extremes() -> None:
    out = build_ipda_range({"high": 100.0, "low": 100.0}, {"high": 100.0, "low": 100.0})
    assert out["width"] == 0.0
    assert out["range_high"] == out["range_low"] == 100.0
    assert out["q25"] == out["mid"] == out["q75"] == 100.0


def test_build_ipda_range_symmetric_in_argument_order() -> None:
    """``build_ipda_range(a, b) == build_ipda_range(b, a)`` (max/min are commutative)."""
    a = {"high": 120.0, "low": 100.0}
    b = {"high": 110.0, "low": 90.0}
    assert build_ipda_range(a, b) == build_ipda_range(b, a)


@pytest.mark.parametrize("seed", (0, 1, 7, 13))
def test_build_ipda_range_quartile_ordering_invariant(seed: int) -> None:
    """For any inputs: low ≤ q25 ≤ mid ≤ q75 ≤ high and width ≥ 0."""
    rng = random.Random(seed)
    for _ in range(25):
        h1 = rng.uniform(0.0, 1000.0)
        l1 = h1 - rng.uniform(0.0, 50.0)
        h2 = rng.uniform(0.0, 1000.0)
        l2 = h2 - rng.uniform(0.0, 50.0)
        out = build_ipda_range({"high": h1, "low": l1}, {"high": h2, "low": l2})
        assert out["width"] >= 0.0
        assert out["range_low"] <= out["q25"] <= out["mid"] <= out["q75"] <= out["range_high"]


# ---------------------------------------------------------------------------
# compute_calendar_boundaries
# ---------------------------------------------------------------------------


def _day_seconds(day: int) -> int:
    return day * 86400


def test_compute_calendar_boundaries_first_bar_is_always_boundary() -> None:
    """``Series.shift()`` puts NaN at index 0 → first row is always a boundary."""
    df = _bars([_make_bar(_day_seconds(1), 100, 101, 99, 100)])
    out = compute_calendar_boundaries(df)
    first_ts = _day_seconds(1)
    assert out["day_boundaries"] == [first_ts]
    assert out["week_boundaries"] == [first_ts]
    assert out["month_boundaries"] == [first_ts]


def test_compute_calendar_boundaries_same_day_no_extra_boundary() -> None:
    """Multiple bars within one UTC day → only the first counts."""
    df = _bars([
        _make_bar(_day_seconds(1) + 0, 100, 101, 99, 100),
        _make_bar(_day_seconds(1) + 3600, 100, 101, 99, 100),
        _make_bar(_day_seconds(1) + 7200, 100, 101, 99, 100),
    ])
    out = compute_calendar_boundaries(df)
    assert out["day_boundaries"] == [_day_seconds(1)]


def test_compute_calendar_boundaries_day_crossing_adds_boundary() -> None:
    df = _bars([
        _make_bar(_day_seconds(1), 100, 101, 99, 100),
        _make_bar(_day_seconds(2), 100, 101, 99, 100),
        _make_bar(_day_seconds(3), 100, 101, 99, 100),
    ])
    out = compute_calendar_boundaries(df)
    assert out["day_boundaries"] == [_day_seconds(1), _day_seconds(2), _day_seconds(3)]


def test_compute_calendar_boundaries_iso_week_vs_calendar_month_diverge() -> None:
    """Quantum-sweep L3 invariant: ISO week (%G-W%V) and calendar month (%Y-%m)
    diverge at year boundaries. 2024-12-30 is in ISO week 2025-W01 but month
    2024-12; 2025-01-06 is in ISO week 2025-W02 and month 2025-01.
    """
    ts_2024_12_30 = int(pd.Timestamp("2024-12-30", tz="UTC").timestamp())
    ts_2025_01_06 = int(pd.Timestamp("2025-01-06", tz="UTC").timestamp())
    df = _bars([
        _make_bar(ts_2024_12_30, 100, 101, 99, 100),
        _make_bar(ts_2025_01_06, 100, 101, 99, 100),
    ])
    out = compute_calendar_boundaries(df)
    # Both rows are boundaries for week + month + day.
    assert out["day_boundaries"] == [ts_2024_12_30, ts_2025_01_06]
    assert out["week_boundaries"] == [ts_2024_12_30, ts_2025_01_06]
    assert out["month_boundaries"] == [ts_2024_12_30, ts_2025_01_06]


def test_compute_calendar_boundaries_subset_relationships() -> None:
    """Month boundaries ⊆ day boundaries AND week boundaries ⊆ day boundaries
    (a new month or new ISO week always implies a new day; month and week
    are independent — a new month does not imply a new ISO week and vice
    versa)."""
    # 5 bars across a month + week + day transition.
    ts = [
        int(pd.Timestamp("2025-03-30", tz="UTC").timestamp()),  # Sun, ISO week 13, month 03
        int(pd.Timestamp("2025-03-31", tz="UTC").timestamp()),  # Mon, ISO week 14 (new week, same month)
        int(pd.Timestamp("2025-04-01", tz="UTC").timestamp()),  # Tue, ISO week 14, month 04 (new month, same week)
        int(pd.Timestamp("2025-04-02", tz="UTC").timestamp()),  # Wed, ISO week 14
        int(pd.Timestamp("2025-04-07", tz="UTC").timestamp()),  # Mon, ISO week 15 (new week)
    ]
    df = _bars([_make_bar(t, 100, 101, 99, 100) for t in ts])
    out = compute_calendar_boundaries(df)
    days = set(out["day_boundaries"])
    weeks = set(out["week_boundaries"])
    months = set(out["month_boundaries"])
    assert months <= days
    assert weeks <= days


# ---------------------------------------------------------------------------
# build_htf_bias_context
# ---------------------------------------------------------------------------


def test_build_htf_bias_context_without_htf_frames_yields_none_ipda() -> None:
    df = _bars([
        _make_bar(_day_seconds(1), 100, 105, 95, 100),
        _make_bar(_day_seconds(2), 100, 110, 100, 106),
    ])
    out = build_htf_bias_context(df, "1H")
    assert out["selected_ipda_htf"] == "D"
    assert out["ipda_range"] is None
    assert out["fvg_bias_counter"] == compute_fvg_bias_counter(df)
    assert out["calendar_boundaries"] == compute_calendar_boundaries(df)


def test_build_htf_bias_context_with_short_htf_frame_yields_none_ipda() -> None:
    """HTF frame with < 2 rows → ipda_range falls back to None."""
    df = _bars([
        _make_bar(_day_seconds(1), 100, 105, 95, 100),
        _make_bar(_day_seconds(2), 100, 110, 100, 106),
    ])
    htf = {"D": _bars([_make_bar(_day_seconds(1), 100, 110, 90, 105)])}
    out = build_htf_bias_context(df, "1H", htf_frames=htf)
    assert out["ipda_range"] is None


def test_build_htf_bias_context_with_sufficient_htf_frame_builds_range() -> None:
    df = _bars([
        _make_bar(_day_seconds(1), 100, 105, 95, 100),
        _make_bar(_day_seconds(2), 100, 110, 100, 106),
    ])
    htf = {"D": _bars([
        _make_bar(_day_seconds(1), 100, 110, 90, 105),
        _make_bar(_day_seconds(2), 105, 120, 100, 115),
    ])}
    out = build_htf_bias_context(df, "1H", htf_frames=htf)
    assert out["ipda_range"] is not None
    # last two HTF bars: highs {110, 120} → 120; lows {90, 100} → 90
    assert out["ipda_range"]["range_high"] == 120.0
    assert out["ipda_range"]["range_low"] == 90.0


def test_build_htf_bias_context_picks_correct_htf_key() -> None:
    """Frame keyed under the wrong HTF is ignored → ipda_range stays None."""
    df = _bars([
        _make_bar(_day_seconds(1), 100, 105, 95, 100),
        _make_bar(_day_seconds(2), 100, 110, 100, 106),
    ])
    htf = {"W": _bars([
        _make_bar(_day_seconds(1), 100, 110, 90, 105),
        _make_bar(_day_seconds(2), 105, 120, 100, 115),
    ])}
    out = build_htf_bias_context(df, "1H", htf_frames=htf)  # 1H → D, not W
    assert out["ipda_range"] is None
