from __future__ import annotations

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