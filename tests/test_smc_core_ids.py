from __future__ import annotations

import pytest

from smc_core.ids import bos_id, fvg_id, ob_id, quantize_price, quantize_time_to_tf, sweep_id


def test_ob_id_deterministic() -> None:
    id1 = ob_id("aapl", "15m", 1709250123.4, "BULL", 184.501, 185.099)
    id2 = ob_id("AAPL ", "15m", 1709250199.9, "BULL", 184.499, 185.101)
    assert id1 == id2


def test_quantize_time_to_tf_alignment() -> None:
    t = 1709250123
    for tf, minutes in [("5m", 5), ("15m", 15), ("1H", 60), ("4H", 240), ("1D", 1440)]:
        anchor = quantize_time_to_tf(t, tf)
        block = minutes * 60
        assert int(anchor) % block == 0


def test_quantize_price_stable() -> None:
    assert quantize_price(185.249) == 185.25
    assert quantize_price(185.251) == 185.25


def test_id_prefixes() -> None:
    assert bos_id("AAPL", "15m", 1709250000, "BOS", "UP", 185.25).startswith("bos:")
    assert ob_id("AAPL", "15m", 1709250000, "BULL", 184.5, 185.1).startswith("ob:")
    assert fvg_id("AAPL", "15m", 1709250000, "BULL", 186.0, 186.5).startswith("fvg:")
    assert sweep_id("AAPL", "5m", 1709349600, "SELL_SIDE", 189.8).startswith("sweep:")


def test_bos_id_normalizes_symbol_and_bar_anchor() -> None:
    got = bos_id(" aapl ", "15m", 1709250123.4, "CHOCH", "DOWN", 185.249)
    assert got == "bos:AAPL:15m:1709249400:CHOCH:DOWN:185.25"


# ── Teil B: edge-case hardening ──────────────────────────────────────


def test_quantize_price_half_up_edge() -> None:
    """0.005 rounds UP to 0.01 (banker's rounding would give 0.00)."""
    assert quantize_price(0.005, 2) == 0.01
    assert quantize_price(0.015, 2) == 0.02
    assert quantize_price(185.255, 2) == 185.26


def test_quantize_price_zero_decimals() -> None:
    assert quantize_price(1234.5, 0) == 1235.0
    assert quantize_price(1234.4, 0) == 1234.0


def test_quantize_price_zero_and_negative_inputs() -> None:
    assert quantize_price(0.0, 2) == 0.0
    assert quantize_price(-185.255, 2) == -185.26
    assert quantize_price(-0.005, 2) == -0.01


def test_quantize_price_negative_decimals_raises() -> None:
    with pytest.raises(ValueError, match="decimals must be >= 0"):
        quantize_price(1.0, -1)


def test_unsupported_timeframe_raises() -> None:
    with pytest.raises(ValueError, match="unsupported timeframe"):
        quantize_time_to_tf(1709250000, "1W")


def test_fvg_id_normalizes_symbol() -> None:
    a = fvg_id(" msft ", "15m", 1709250000, "BULL", 186.0, 186.5)
    b = fvg_id("MSFT", "15m", 1709250000, "BULL", 186.0, 186.5)
    assert a == b
    assert ":MSFT:" in a


def test_sweep_id_normalizes_symbol() -> None:
    a = sweep_id("  eth  ", "5m", 1709349600, "BUY_SIDE", 3450.0)
    b = sweep_id("ETH", "5m", 1709349600, "BUY_SIDE", 3450.0)
    assert a == b
    assert ":ETH:" in a


def test_all_id_types_deterministic_same_inputs() -> None:
    """Calling each ID generator twice with identical inputs yields same result."""
    for _ in range(3):
        assert bos_id("AAPL", "15m", 1709250123, "BOS", "UP", 185.25) == \
               bos_id("AAPL", "15m", 1709250123, "BOS", "UP", 185.25)
        assert ob_id("AAPL", "15m", 1709250123, "BULL", 184.5, 185.1) == \
               ob_id("AAPL", "15m", 1709250123, "BULL", 184.5, 185.1)
        assert fvg_id("AAPL", "15m", 1709250123, "BULL", 186.0, 186.5) == \
               fvg_id("AAPL", "15m", 1709250123, "BULL", 186.0, 186.5)
        assert sweep_id("AAPL", "5m", 1709349600, "SELL_SIDE", 189.8) == \
               sweep_id("AAPL", "5m", 1709349600, "SELL_SIDE", 189.8)