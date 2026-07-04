"""Smoke + unit coverage for open_prep.market_microstructure.

Exercises the pure, network-free building blocks of the Phase-1 (2026-07-04)
market-microstructure module: fund filtering, Kaufman efficiency ratio,
percentile ranking, sampling, and the fail-soft snapshot contract. The live
``compute_microstructure_snapshot`` path needs an FMP client and is covered by
the open-prep integration flow, not here.
"""
from __future__ import annotations

import math

from open_prep import market_microstructure as mm


def test_is_fundish_flags_mutual_funds_and_etfs() -> None:
    assert mm._is_fundish("VFIAX")   # 5-letter, ends in X
    assert mm._is_fundish("spy")     # ETF set, case-insensitive
    assert mm._is_fundish("QQQ")
    assert not mm._is_fundish("AAPL")
    assert not mm._is_fundish("MCD")


def test_kaufman_er_bounds_and_known_values() -> None:
    # Straight-line move: net == path -> ER == 1.0
    straight = [10.0, 11.0, 12.0, 13.0, 14.0]
    assert mm._kaufman_er(straight, window=4) == 1.0

    # Round trip back to start: net == 0 -> ER == 0.0
    round_trip = [10.0, 12.0, 10.0, 12.0, 10.0]
    er = mm._kaufman_er(round_trip, window=4)
    assert er == 0.0

    # Too few points for the window -> None
    assert mm._kaufman_er([1.0, 2.0], window=4) is None
    # Flat series (zero path) -> None, not a divide-by-zero
    assert mm._kaufman_er([5.0, 5.0, 5.0], window=2) is None


def test_percentile_rank() -> None:
    hist = [1.0, 2.0, 3.0, 4.0]
    assert mm._percentile_rank(hist, 2.5) == 50.0
    assert mm._percentile_rank(hist, 0.0) == 0.0
    assert mm._percentile_rank(hist, 5.0) == 100.0
    assert mm._percentile_rank([], 1.0) is None


def test_sample_symbols_dedups_and_drops_fundish_and_brka() -> None:
    got = mm._sample_symbols(["AAPL", "aapl", "SPY", "BRK-A", "MCD", ""], limit=10)
    assert got == ["AAPL", "MCD"]
    # Respects the limit.
    assert mm._sample_symbols(["A", "B", "C", "D"], limit=2) == ["A", "B"]


def test_unknown_snapshot_is_failsoft_and_serializable() -> None:
    snap = mm._unknown_snapshot("no client")
    assert snap.market_weather == mm.WEATHER_UNKNOWN
    assert snap.reasons == ["no client"]
    assert snap.market_efficiency_ratio is None

    d = snap.to_dict()
    for key in (
        "market_efficiency_ratio",
        "intraday_efficiency_ratio",
        "cs_dispersion",
        "avg_pair_correlation",
        "market_weather",
    ):
        assert key in d
    # Log line renders None as "n/a" without raising.
    assert "weather=UNKNOWN" in snap.to_log_line()
    assert "n/a" in snap.to_log_line()


def test_snapshot_to_log_line_formats_floats() -> None:
    snap = mm.MicrostructureSnapshot(
        market_efficiency_ratio=0.25,
        intraday_efficiency_ratio=0.23,
        cs_dispersion=3.5,
        avg_pair_correlation=0.11,
        market_weather=mm.WEATHER_GREEN,
        sample_size=97,
    )
    line = snap.to_log_line()
    assert "weather=GREEN" in line
    assert "er_daily=0.250" in line
    assert "n=97" in line
    # to_dict round-trips the numeric fields unchanged.
    assert math.isclose(snap.to_dict()["cs_dispersion"], 3.5)
