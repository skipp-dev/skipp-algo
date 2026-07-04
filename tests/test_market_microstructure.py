"""Smoke + unit coverage for open_prep.market_microstructure.

Exercises the pure, network-free building blocks of the Phase-1 (2026-07-04)
market-microstructure module: fund filtering, Kaufman efficiency ratio,
percentile ranking, sampling, and the fail-soft snapshot contract. The live
``compute_microstructure_snapshot`` path needs an FMP client and is covered by
the open-prep integration flow, not here.
"""
from __future__ import annotations

import math

import pytest

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


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_percentile_rank_rejects_non_finite_value(bad: float) -> None:
    assert mm._percentile_rank([1.0, 2.0, 3.0], bad) is None


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_weather_summary_line_renders_nonfinite_as_na(bad: float) -> None:
    line = mm.weather_summary_line(
        "GREEN",
        er_intraday=bad,
        dispersion=bad,
        correlation=bad,
    )
    assert "inf" not in line
    assert "nan" not in line.casefold()
    assert "ER n/a" in line
    assert "Disp n/a" in line
    assert "Korr n/a" in line


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


# ---------------------------------------------------------------------------
# Bug-hunt round 3: non-finite closes from FMP must be dropped at ingestion
# ---------------------------------------------------------------------------


class _NonFiniteClient:
    """Fake FMP client that mixes NaN/inf into otherwise valid payloads."""

    def get_historical_price_eod_full(self, symbol, date_from=None, date_to=None):
        return [
            {"date": "2026-07-01", "close": float("nan")},
            {"date": "2026-07-02", "close": float("inf")},
            {"date": "2026-07-03", "close": "-inf"},
            {"date": "2026-07-06", "close": 100.0},
        ]

    def get_intraday_chart(self, symbol, interval="1hour"):
        return [{"close": float("nan")} for _ in range(mm.ER_INTRADAY_BARS + 5)]


def test_fetch_eod_closes_drops_non_finite() -> None:
    from datetime import date

    out = mm._fetch_eod_closes(
        _NonFiniteClient(), "AAPL", date(2026, 6, 1), date(2026, 7, 6)
    )
    assert out == {"2026-07-06": 100.0}


def test_fetch_intraday_er_ignores_non_finite() -> None:
    # All closes non-finite -> too few points -> fail-soft None, no crash.
    assert mm._fetch_intraday_er(_NonFiniteClient(), "AAPL") is None


class _NanLacedClient:
    """Fake FMP client: full EOD histories with NaN/inf sprinkled in."""

    def __init__(self, n_days: int = 130) -> None:
        from datetime import date, timedelta

        start = date(2026, 1, 1)
        self.dates = [str(start + timedelta(days=i)) for i in range(n_days)]

    def get_historical_price_eod_full(self, symbol, date_from=None, date_to=None):
        seed = sum(ord(ch) for ch in symbol)
        rows = []
        for i, d in enumerate(self.dates):
            close: float = 100.0 + ((seed + i * 7) % 13) * 0.5
            if i % 11 == (seed % 11):
                close = float("nan")
            elif i % 17 == (seed % 17):
                close = float("inf")
            rows.append({"date": d, "close": close})
        return rows

    def get_intraday_chart(self, symbol, interval="1hour"):
        seed = sum(ord(ch) for ch in symbol)
        rows = []
        for i in range(mm.ER_INTRADAY_BARS + 10):
            close: float = 50.0 + ((seed + i * 3) % 7) * 0.25
            if i % 9 == (seed % 9):
                close = float("nan")
            rows.append({"close": close})
        return rows


def test_snapshot_survives_nan_and_inf_closes() -> None:
    """Report repro: NaN/inf from FMP must not crash the snapshot."""
    symbols = [f"SY{i:02d}" for i in range(45)]
    snap = mm.compute_microstructure_snapshot(
        client=_NanLacedClient(), symbols=symbols, max_workers=2
    )
    assert snap.market_weather in (
        mm.WEATHER_GREEN, mm.WEATHER_YELLOW, mm.WEATHER_RED, mm.WEATHER_UNKNOWN
    )
    for value in (
        snap.market_efficiency_ratio,
        snap.intraday_efficiency_ratio,
        snap.cs_dispersion,
        snap.avg_pair_correlation,
    ):
        assert value is None or math.isfinite(value)


def test_sample_symbols_limit_zero_returns_empty() -> None:
    # Bug-hunt round 4: limit=0 previously returned one element because the
    # break check ran only after the first append.
    assert mm._sample_symbols(["AAPL", "MCD"], limit=0) == []
    assert mm._sample_symbols(["AAPL"], limit=-3) == []
