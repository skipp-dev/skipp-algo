from __future__ import annotations

import pandas as pd

from scripts.explicit_structure_from_bars import (
    build_explicit_structure_from_bars,
    build_full_structure_from_bars,
    resample_bars_to_timeframe,
)


def _bars(symbol: str = "AAPL") -> pd.DataFrame:
    timestamps = pd.date_range("2024-01-01", periods=18, freq="D", tz="UTC")
    rows: list[dict[str, float | str | pd.Timestamp]] = []
    for index, ts in enumerate(timestamps):
        base = 100.0 + index * 0.2
        rows.append(
            {
                "symbol": symbol,
                "timestamp": ts,
                "open": base,
                "high": base + 0.8,
                "low": base - 0.8,
                "close": base + 0.2,
                "volume": 1000.0 + index,
            }
        )
    return pd.DataFrame(rows)


def test_resample_bars_to_timeframe_keeps_required_columns() -> None:
    bars = _bars()
    out = resample_bars_to_timeframe(bars, "1D")

    assert not out.empty
    assert list(out.columns) == ["symbol", "timestamp", "open", "high", "low", "close", "volume"]


def test_build_full_structure_from_bars_returns_expected_shape() -> None:
    bars = _bars()
    structure = build_full_structure_from_bars(bars, symbol="AAPL", timeframe="1D")

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure["bos"], list)
    assert isinstance(structure["orderblocks"], list)
    assert isinstance(structure["fvg"], list)
    assert isinstance(structure["liquidity_sweeps"], list)


def test_explicit_structure_contains_auxiliary_but_full_stays_canonical() -> None:
    bars = _bars()
    explicit = build_explicit_structure_from_bars(bars, symbol="AAPL", timeframe="1D", structure_profile="hybrid_default")
    full = build_full_structure_from_bars(bars, symbol="AAPL", timeframe="1D", structure_profile="hybrid_default")

    assert "auxiliary" in explicit
    assert "diagnostics" in explicit
    assert "producer_debug" in explicit
    assert set(full.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}


def _minutes(start: str, n: int, *, symbol: str = "AAPL", skip: tuple[int, ...] = ()) -> pd.DataFrame:
    """``n`` one-minute bars stamped at their START, as the vendor frame is.

    Minute ``i`` opens at ``100 + i`` and closes at ``100 + i + 0.5``; its high
    and low straddle that, so every aggregate is recognisable by its minutes.
    """
    first = pd.Timestamp(start, tz="UTC")
    rows = []
    for i in range(n):
        if i in skip:
            continue
        rows.append(
            {
                "symbol": symbol,
                "timestamp": first + pd.Timedelta(minutes=i),
                "open": 100.0 + i,
                "high": 100.0 + i + 0.8,
                "low": 100.0 + i - 0.3,
                "close": 100.0 + i + 0.5,
                "volume": 10.0,
            }
        )
    return pd.DataFrame(rows)


def test_resample_excludes_incomplete_last_bucket() -> None:
    """Minutes 09:30–09:32 are three fifths of the bar [09:30, 09:35): it is
    still forming and must not be served as a confirmed bar."""
    out = resample_bars_to_timeframe(_minutes("2024-01-02T09:30:00Z", 3), "5m")
    assert out.empty

    # Positive control: with the minutes 09:33 and 09:34 the bar is complete.
    out = resample_bars_to_timeframe(_minutes("2024-01-02T09:30:00Z", 5), "5m")
    assert [str(t) for t in pd.to_datetime(out["timestamp"], utc=True)] == ["2024-01-02 09:35:00+00:00"]


# ── start-stamped source bars (ADR-0031, Nachtrag 2026-10-02 III) ──


def test_a_minute_belongs_to_the_bar_that_starts_with_it() -> None:
    """The minute stamped 13:30 covers 13:30:00–13:31:00 and is the FIRST
    minute of the bar [13:30, 13:45), which is labelled by its end, 13:45.

    Until 2026-10-02 it was booked as the LAST minute of the bar ending 13:30,
    which put the opening minute of the regular session into the last
    pre-market bar and shifted every intraday bar by one minute."""
    bars = _minutes("2024-01-02T13:30:00Z", 30)  # 13:30 … 13:59
    out = resample_bars_to_timeframe(bars, "15m")

    labels = [str(t)[11:16] for t in pd.to_datetime(out["timestamp"], utc=True)]
    assert labels == ["13:45", "14:00"]
    first = out.iloc[0]
    assert first["open"] == 100.0  # open of the minute 13:30
    assert first["close"] == 114.5  # close of the minute 13:44
    assert first["high"] == 114.8 and first["low"] == 99.7
    assert first["volume"] == 150.0
    second = out.iloc[1]
    assert second["open"] == 115.0 and second["close"] == 129.5  # minutes 13:45 … 13:59


def test_the_trailing_bar_needs_its_last_minute() -> None:
    """Minutes 13:30 … 13:58: the second bar lacks 13:59 and is dropped."""
    out = resample_bars_to_timeframe(_minutes("2024-01-02T13:30:00Z", 29), "15m")
    assert [str(t)[11:16] for t in pd.to_datetime(out["timestamp"], utc=True)] == ["13:45"]


def test_a_gap_inside_a_bar_does_not_move_minutes_between_bars() -> None:
    """Sparse pre-market: only 08:14 and 08:15 print. They belong to two bars
    — [08:00, 08:15) and [08:15, 08:30). The source ends at 08:15, so the
    second bar is still forming; under the old rule BOTH minutes were booked
    into one bar ending 08:15."""
    bars = _minutes("2024-01-02T08:00:00Z", 16, skip=tuple(range(14)))  # 08:14, 08:15
    out = resample_bars_to_timeframe(bars, "15m")
    assert [str(t)[11:16] for t in pd.to_datetime(out["timestamp"], utc=True)] == ["08:15"]
    assert out.iloc[0]["open"] == 114.0 and out.iloc[0]["close"] == 114.5  # the minute 08:14 alone


def test_bars_already_at_the_target_timeframe_pass_through_unchanged() -> None:
    """A provider's 15m candles (the TV bridge) are not re-labelled: there is
    nothing to aggregate, and their stamps stay the caller's."""
    first = pd.Timestamp("2024-01-02T13:30:00Z")
    bars = pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": first + pd.Timedelta(minutes=15 * i), "open": 100.0 + i, "high": 101.0 + i, "low": 99.0 + i, "close": 100.5 + i, "volume": 5.0}
            for i in range(4)
        ]
    )
    out = resample_bars_to_timeframe(bars, "15m")
    assert [str(t)[11:16] for t in pd.to_datetime(out["timestamp"], utc=True)] == ["13:30", "13:45", "14:00", "14:15"]
    assert out["close"].tolist() == bars["close"].tolist()


def test_end_stamped_output_can_be_aggregated_further() -> None:
    """1m → 5m → 15m equals 1m → 15m when the second stage is told that its
    input is end-stamped (this function's own output)."""
    minutes = _minutes("2024-01-02T13:30:00Z", 45)
    direct = resample_bars_to_timeframe(minutes, "15m")
    five = resample_bars_to_timeframe(minutes, "5m")
    staged = resample_bars_to_timeframe(five, "15m", source_stamp="end")
    assert len(direct) == 3
    for column in ("timestamp", "open", "high", "low", "close", "volume"):
        assert staged[column].tolist() == direct[column].tolist(), column

    # Told nothing, the second stage would read the 5m END stamps as starts
    # and shift every bar by five minutes — that is why the argument exists.
    shifted = resample_bars_to_timeframe(five, "15m")
    assert shifted["open"].tolist() != direct["open"].tolist()


def test_an_unknown_source_stamp_is_refused() -> None:
    import pytest

    with pytest.raises(ValueError, match="source_stamp"):
        resample_bars_to_timeframe(_minutes("2024-01-02T13:30:00Z", 15), "15m", source_stamp="middle")  # type: ignore[arg-type]


# ── 1D identity vs aggregation (silent-fallback audit 2026-06-10) ──


def test_resample_1d_keeps_identity_for_true_daily_bars() -> None:
    """Genuinely daily input (≤1 row per symbol/day) stays untouched,
    regardless of intraday stamp time."""
    bars = _bars()
    # restamp at 09:30 — daily bars stamped at session open must survive
    bars["timestamp"] = pd.to_datetime(bars["timestamp"]) + pd.Timedelta(hours=9, minutes=30)

    out = resample_bars_to_timeframe(bars, "1D")
    assert len(out) == len(bars)
    assert out["close"].tolist() == bars["close"].tolist()


def test_resample_1d_aggregates_intraday_bars(caplog) -> None:
    """Intraday bars requested as 1D must be aggregated to calendar
    days, not silently served as-is (mirror of the #2666 aliasing)."""
    rows = []
    for day in ("2024-01-02", "2024-01-03"):
        for index, hour in enumerate((10, 12, 14)):
            base = 100.0 + index
            rows.append(
                {
                    "symbol": "AAPL",
                    "timestamp": f"{day}T{hour:02d}:00:00Z",
                    "open": base,
                    "high": base + 1.0,
                    "low": base - 1.0,
                    "close": base + 0.5,
                    "volume": 10.0,
                }
            )
    bars = pd.DataFrame(rows)

    import logging

    with caplog.at_level(logging.WARNING, logger="scripts.explicit_structure_from_bars"):
        out = resample_bars_to_timeframe(bars, "1D")

    # 2 calendar days × 3 intraday bars → the generic path buckets to
    # day-end and trims the trailing partial bucket (> max source ts).
    assert len(out) < len(bars)
    assert any("finer than 1D" in record.message for record in caplog.records)
    # aggregation semantics: day high == max of intraday highs
    first_day = out.iloc[0]
    assert first_day["high"] == 103.0
    assert first_day["low"] == 99.0
    assert first_day["volume"] == 30.0


def test_explicit_structure_keeps_daily_fvg_confirmation_anchor() -> None:
    timestamps = pd.date_range("2024-03-01", periods=5, freq="D", tz="UTC")
    bars = pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": timestamps[0], "open": 97.0, "high": 100.0, "low": 95.0, "close": 99.0},
            {"symbol": "AAPL", "timestamp": timestamps[1], "open": 100.0, "high": 101.0, "low": 98.0, "close": 100.5},
            {"symbol": "AAPL", "timestamp": timestamps[2], "open": 104.0, "high": 108.0, "low": 103.0, "close": 107.0},
            {"symbol": "AAPL", "timestamp": timestamps[3], "open": 106.0, "high": 107.0, "low": 104.0, "close": 105.0},
            {"symbol": "AAPL", "timestamp": timestamps[4], "open": 96.0, "high": 99.0, "low": 94.0, "close": 95.0},
        ]
    )

    structure = build_explicit_structure_from_bars(bars, symbol="AAPL", timeframe="1D")
    bullish = next(item for item in structure["fvg"] if item["dir"] == "BULL")

    assert bullish["anchor_ts"] == int(pd.Timestamp(timestamps[2]).timestamp())
