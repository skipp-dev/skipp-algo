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


def test_resample_excludes_incomplete_last_bucket() -> None:
    bars = pd.DataFrame(
        [
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:30:00Z", "open": 100.0, "high": 101.0, "low": 99.5, "close": 100.5, "volume": 10},
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:31:00Z", "open": 100.5, "high": 101.2, "low": 100.2, "close": 101.0, "volume": 12},
            {"symbol": "AAPL", "timestamp": "2024-01-01T09:32:00Z", "open": 101.0, "high": 101.3, "low": 100.8, "close": 101.1, "volume": 8},
        ]
    )

    out = resample_bars_to_timeframe(bars, "5m")
    assert not out.empty
    max_source = pd.to_datetime(bars["timestamp"], utc=True).max()
    assert pd.to_datetime(out["timestamp"], utc=True).max() <= max_source


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
