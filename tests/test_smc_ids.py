"""Tests for smc_core.ids – ticksize-aware price quantization and session-aware time anchoring."""

from __future__ import annotations

import pytest

from smc_core.ids import (
    DEFAULT_SESSION_TZ,
    SYMBOL_TICKSIZE,
    bos_id,
    fvg_id,
    ob_id,
    quantize_price,
    quantize_time_to_tf,
    sweep_id,
)


# --- quantize_price: backward-compatible decimals mode ---


def test_quantize_price_decimals_default() -> None:
    assert quantize_price(185.256) == 185.26
    assert quantize_price(185.254) == 185.25


def test_quantize_price_zero_decimals() -> None:
    assert quantize_price(185.5, 0) == 186.0


def test_quantize_price_negative_decimals_raises() -> None:
    with pytest.raises(ValueError, match="decimals must be >= 0"):
        quantize_price(1.0, -1)


# --- quantize_price: ticksize mode ---


def test_quantize_price_ticksize_quarter() -> None:
    assert quantize_price(185.12, ticksize=0.25) == 185.0   # 0.12 from 185.0, 0.13 from 185.25
    assert quantize_price(185.13, ticksize=0.25) == 185.25  # 0.13 from 185.0, 0.12 from 185.25
    assert quantize_price(185.00, ticksize=0.25) == 185.00
    assert quantize_price(185.125, ticksize=0.25) == 185.25  # half-up


def test_quantize_price_ticksize_one_dollar() -> None:
    assert quantize_price(42345.6, ticksize=1.0) == 42346.0
    assert quantize_price(42345.4, ticksize=1.0) == 42345.0


def test_quantize_price_ticksize_ten_cents() -> None:
    assert quantize_price(1950.04, ticksize=0.10) == 1950.0
    assert quantize_price(1950.06, ticksize=0.10) == 1950.1


def test_quantize_price_ticksize_invalid() -> None:
    with pytest.raises(ValueError, match="ticksize must be > 0"):
        quantize_price(100.0, ticksize=0.0)
    with pytest.raises(ValueError, match="ticksize must be > 0"):
        quantize_price(100.0, ticksize=-0.01)


# --- quantize_price: symbol lookup mode ---


def test_quantize_price_symbol_lookup() -> None:
    assert quantize_price(4505.12, symbol="ES") == 4505.0   # nearest 0.25
    assert quantize_price(4505.13, symbol="ES") == 4505.25  # nearest 0.25
    assert quantize_price(42345.6, symbol="BTC") == 42346.0


def test_quantize_price_unknown_symbol_falls_through() -> None:
    # Unknown symbol falls back to decimals parameter
    assert quantize_price(185.256, symbol="UNKNOWN_XYZ") == 185.26


# --- quantize_price: priority (ticksize > symbol > decimals) ---


def test_quantize_price_ticksize_overrides_symbol() -> None:
    # ES would normally use 0.25, but explicit ticksize=0.01 wins
    assert quantize_price(4505.123, ticksize=0.01, symbol="ES") == 4505.12


# --- quantize_price: determinism ---


def test_quantize_price_deterministic() -> None:
    for _ in range(100):
        assert quantize_price(123.456789, ticksize=0.25) == 123.50
        assert quantize_price(123.456789, decimals=4) == 123.4568


# --- quantize_time_to_tf: sub-daily (unchanged behavior) ---


def test_quantize_time_15m() -> None:
    # 2024-03-01 10:07:00 UTC → floor to 10:00:00
    ts = 1709287620.0  # some random intra-15m timestamp
    result = quantize_time_to_tf(ts, "15m")
    assert result == float(int(ts) - int(ts) % 900)


def test_quantize_time_5m() -> None:
    ts = 1709287620.0
    result = quantize_time_to_tf(ts, "5m")
    assert result == float(int(ts) - int(ts) % 300)


# --- quantize_time_to_tf: 1D session-aware ---


def test_quantize_time_1d_default_ny() -> None:
    """1D should anchor to midnight ET by default."""
    # 2024-03-01 15:30:00 UTC  →  10:30 AM ET  →  anchor = 2024-03-01 00:00 ET = 05:00 UTC
    ts = 1709305800.0
    result = quantize_time_to_tf(ts, "1D")
    # midnight ET on 2024-03-01 is 05:00 UTC (EST = UTC-5)
    assert result == quantize_time_to_tf(ts, "1D", session_tz="America/New_York")


def test_quantize_time_1d_explicit_utc() -> None:
    """When session_tz=UTC, 1D anchoring matches pure UTC midnight."""
    ts = 1709305800.0  # 2024-03-01 15:30:00 UTC
    result = quantize_time_to_tf(ts, "1D", session_tz="UTC")
    # midnight UTC on 2024-03-01 = 1709251200
    assert result == 1709251200.0


def test_quantize_time_1d_session_boundary() -> None:
    """Timestamps just before and after local midnight should land in different day anchors."""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    # 2024-03-01 23:59:59 ET
    dt_before = datetime(2024, 3, 1, 23, 59, 59, tzinfo=tz)
    # 2024-03-02 00:00:01 ET
    dt_after = datetime(2024, 3, 2, 0, 0, 1, tzinfo=tz)

    ts_before = dt_before.timestamp()
    ts_after = dt_after.timestamp()

    anchor_before = quantize_time_to_tf(ts_before, "1D")
    anchor_after = quantize_time_to_tf(ts_after, "1D")
    assert anchor_before != anchor_after


# --- quantize_time_to_tf: determinism ---


def test_quantize_time_deterministic() -> None:
    ts = 1709305800.0
    results = {quantize_time_to_tf(ts, "1D") for _ in range(50)}
    assert len(results) == 1


# --- ID builders: same inputs => same IDs ---


def test_bos_id_deterministic() -> None:
    id1 = bos_id("AAPL", "15m", 1709250000.0, "BOS", "UP", 185.25)
    id2 = bos_id("AAPL", "15m", 1709250000.0, "BOS", "UP", 185.25)
    assert id1 == id2


def test_ob_id_deterministic() -> None:
    id1 = ob_id("AAPL", "15m", 1709250000.0, "BULL", 184.50, 185.10)
    id2 = ob_id("AAPL", "15m", 1709250000.0, "BULL", 184.50, 185.10)
    assert id1 == id2


def test_fvg_id_deterministic() -> None:
    id1 = fvg_id("AAPL", "15m", 1709250000.0, "BULL", 184.50, 185.10)
    id2 = fvg_id("AAPL", "15m", 1709250000.0, "BULL", 184.50, 185.10)
    assert id1 == id2


def test_sweep_id_deterministic() -> None:
    id1 = sweep_id("AAPL", "5m", 1709349600.0, "SELL_SIDE", 189.80)
    id2 = sweep_id("AAPL", "5m", 1709349600.0, "SELL_SIDE", 189.80)
    assert id1 == id2


def test_unsupported_timeframe_raises() -> None:
    with pytest.raises(ValueError, match="unsupported timeframe"):
        quantize_time_to_tf(1709250000, "3m")
