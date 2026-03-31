"""Tests for smc_core.vol_regime — volatility regime MVP."""

from __future__ import annotations

import pandas as pd
import pytest

from smc_core.vol_regime import VolRegimeResult, compute_vol_regime


def _make_bars(n: int = 60, base_range: float = 1.0) -> pd.DataFrame:
    """Generate synthetic OHLC bars with controlled volatility."""
    rows = []
    close = 100.0
    for i in range(n):
        o = close
        h = o + base_range
        l = o - base_range * 0.5
        c = o + base_range * 0.3
        rows.append({"high": h, "low": l, "close": c, "open": o, "timestamp": 1700000000 + i * 900})
        close = c
    return pd.DataFrame(rows)


def _make_extreme_bars(n: int = 60) -> pd.DataFrame:
    """Bars with a sudden volatility spike at the end."""
    rows = []
    close = 100.0
    for i in range(n):
        factor = 1.0 if i < n - 5 else 5.0  # last 5 bars spike
        o = close
        h = o + factor * 2
        l = o - factor * 1
        c = o + factor * 0.5
        rows.append({"high": h, "low": l, "close": c, "open": o, "timestamp": 1700000000 + i * 900})
        close = c
    return pd.DataFrame(rows)


class TestComputeVolRegime:
    def test_normal_regime(self) -> None:
        result = compute_vol_regime(_make_bars(60))
        assert result.label == "NORMAL"
        assert 0.5 < result.raw_atr_ratio < 1.5
        assert result.confidence > 0

    def test_empty_bars_graceful(self) -> None:
        result = compute_vol_regime(pd.DataFrame(columns=["high", "low", "close"]))
        assert result.label == "NORMAL"
        assert result.confidence == 0.0

    def test_insufficient_bars_graceful(self) -> None:
        result = compute_vol_regime(_make_bars(5))
        assert result.label == "NORMAL"
        assert result.confidence == 0.0

    def test_extreme_regime(self) -> None:
        result = compute_vol_regime(_make_extreme_bars(60))
        assert result.label in ("HIGH_VOL", "EXTREME")
        assert result.raw_atr_ratio > 1.5

    def test_deterministic(self) -> None:
        bars = _make_bars(60)
        results = {compute_vol_regime(bars).label for _ in range(20)}
        assert len(results) == 1

    def test_result_fields(self) -> None:
        result = compute_vol_regime(_make_bars(60))
        assert isinstance(result, VolRegimeResult)
        assert 0.0 <= result.confidence <= 1.0
        assert result.bars_used > 0

    def test_custom_atr_period(self) -> None:
        result = compute_vol_regime(_make_bars(60), atr_period=7)
        assert result.label in ("LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME")
