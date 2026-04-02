from __future__ import annotations

from datetime import datetime, timezone

import pytest
from zoneinfo import ZoneInfo

from smc_core.ids import DEFAULT_SESSION_TZ, bos_id, fvg_id, ob_id, quantize_price, quantize_time_to_tf, sweep_id, SYMBOL_TICKSIZE


def test_ob_id_deterministic() -> None:
    id1 = ob_id("aapl", "15m", 1709250123.4, "BULL", 184.501, 185.099)
    id2 = ob_id("AAPL ", "15m", 1709250199.9, "BULL", 184.499, 185.101)
    assert id1 == id2


def test_quantize_time_to_tf_alignment() -> None:
    t = 1709250123
    for tf, minutes in [("5m", 5), ("15m", 15), ("1H", 60), ("4H", 240)]:
        anchor = quantize_time_to_tf(t, tf)
        block = minutes * 60
        assert int(anchor) % block == 0

    daily_anchor = quantize_time_to_tf(t, "1D")
    session_dt = datetime.fromtimestamp(daily_anchor, tz=timezone.utc).astimezone(ZoneInfo(DEFAULT_SESSION_TZ))
    assert (session_dt.hour, session_dt.minute, session_dt.second) == (0, 0, 0)


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


# ── Teil C: ticksize-/symbol-aware ID quantization ───────────────────


class TestTicksizeAwareIDs:
    """Test that event-ID functions use symbol-aware tick quantization."""

    def test_equity_defaults_two_decimals(self) -> None:
        """AAPL (equity, no special ticksize) → 2-decimal default."""
        eid = bos_id("AAPL", "15m", 1709250000, "BOS", "UP", 185.123)
        assert eid.endswith(":185.12")

    def test_futures_es_quarter_tick(self) -> None:
        """ES (futures, ticksize=0.25) → snaps to nearest 0.25."""
        eid = bos_id("ES", "15m", 1709250000, "BOS", "UP", 5123.13)
        assert eid.endswith(":5123.25")  # 5123.13 rounds to 5123.25

    def test_futures_gc_dime_tick(self) -> None:
        """GC (gold, ticksize=0.10) → snaps to nearest 0.10."""
        eid = ob_id("GC", "1H", 1709250000, "BULL", 2044.03, 2044.97)
        assert ":2044.0:" in eid
        assert eid.endswith(":2045.0")

    def test_crypto_btc_whole_dollar(self) -> None:
        """BTC (crypto, ticksize=1.0) → snaps to whole dollars."""
        eid = fvg_id("BTC", "15m", 1709250000, "BULL", 67234.4, 67289.6)
        assert ":67234:" in eid
        assert eid.endswith(":67290")

    def test_crypto_eth_cent_tick(self) -> None:
        """ETH (crypto, ticksize=0.01) → 2 decimals."""
        eid = sweep_id("ETH", "5m", 1709349600, "SELL_SIDE", 3456.789)
        assert eid.endswith(":3456.79")

    def test_explicit_ticksize_overrides_symbol(self) -> None:
        """Explicit ticksize parameter takes priority over symbol lookup."""
        eid = bos_id("ES", "15m", 1709250000, "BOS", "UP", 5123.13, ticksize=0.50)
        assert eid.endswith(":5123.0")  # 5123.13 → nearest 0.50 = 5123.0

    def test_unknown_symbol_uses_default_decimals(self) -> None:
        """Unknown symbols fall back to 2-decimal default."""
        eid = ob_id("XYZUNKNOWN", "15m", 1709250000, "BEAR", 99.999, 100.111)
        assert ":100.00:" in eid
        assert eid.endswith(":100.11")

    def test_deterministic_across_calls(self) -> None:
        """Same inputs always produce the same ID, even with ticksize."""
        for _ in range(5):
            a = bos_id("ES", "15m", 1709250000, "BOS", "UP", 5123.13)
            b = bos_id("ES", "15m", 1709250000, "BOS", "UP", 5123.13)
            assert a == b

    def test_all_id_types_with_es(self) -> None:
        """All four ID types work with ES tick quantization."""
        b = bos_id("ES", "15m", 1709250000, "BOS", "UP", 5100.37)
        o = ob_id("ES", "15m", 1709250000, "BULL", 5100.37, 5101.13)
        f = fvg_id("ES", "15m", 1709250000, "BULL", 5100.37, 5101.13)
        s = sweep_id("ES", "5m", 1709349600, "SELL_SIDE", 5100.37)
        # 5100.37 → nearest 0.25 = 5100.25
        assert b.endswith(":5100.25")
        assert ":5100.25:" in o
        assert ":5100.25:" in f
        assert s.endswith(":5100.25")