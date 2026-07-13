from __future__ import annotations

import pandas as pd

from scripts.smc_liquidity_engine import detect_liquidity_levels, detect_liquidity_sweeps
from scripts.smc_price_action_engine import normalize_bars


def make_bars(rows: list[dict]) -> pd.DataFrame:
    return normalize_bars(pd.DataFrame(rows))


def test_detect_pivot_liquidity_levels() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 13, "low": 9.5, "close": 12, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 11.5, "low": 9, "close": 10.2, "volume": 100},
            {"timestamp": 4, "open": 10.3, "high": 11.0, "low": 8.2, "close": 9.0, "volume": 100},
            {"timestamp": 5, "open": 9.0, "high": 10.8, "low": 8.9, "close": 10.0, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    assert any(x["side"] == "BUY_SIDE" for x in levels)
    assert any(x["side"] == "SELL_SIDE" for x in levels)


def test_detect_buy_side_sweep_against_pivot_high() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100},
            {"timestamp": 2, "open": 10, "high": 13, "low": 9.5, "close": 12, "volume": 100},
            {"timestamp": 3, "open": 12, "high": 11.5, "low": 9, "close": 10.0, "volume": 100},
            {"timestamp": 4, "open": 10, "high": 13.5, "low": 9.8, "close": 12.5, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    sweeps = detect_liquidity_sweeps(df, levels, "AAPL", "15m")
    assert any(x["side"] == "BUY_SIDE" for x in sweeps)


def test_detect_sell_side_sweep_against_pivot_low() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10, "high": 10.5, "low": 9.5, "close": 10.2, "volume": 100},
            {"timestamp": 2, "open": 10.1, "high": 10.2, "low": 8.0, "close": 8.4, "volume": 100},
            {"timestamp": 3, "open": 8.5, "high": 9.6, "low": 8.8, "close": 9.3, "volume": 100},
            {"timestamp": 4, "open": 9.2, "high": 9.5, "low": 7.6, "close": 8.3, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "AAPL", "15m")
    sweeps = detect_liquidity_sweeps(df, levels, "AAPL", "15m")
    assert any(x["side"] == "SELL_SIDE" for x in sweeps)


def test_detect_liquidity_levels_use_ticksize_aware_ids() -> None:
    df = make_bars(
        [
            {"timestamp": 1, "open": 10.0, "high": 11.0, "low": 9.2, "close": 10.0, "volume": 100},
            {"timestamp": 2, "open": 10.0, "high": 13.13, "low": 9.51, "close": 12.0, "volume": 100},
            {"timestamp": 3, "open": 12.0, "high": 11.5, "low": 9.01, "close": 10.2, "volume": 100},
            {"timestamp": 4, "open": 10.3, "high": 11.0, "low": 8.12, "close": 9.0, "volume": 100},
            {"timestamp": 5, "open": 9.0, "high": 10.8, "low": 8.91, "close": 10.0, "volume": 100},
        ]
    )
    levels = detect_liquidity_levels(df, "ES", "15m")

    ids = {str(item["id"]) for item in levels}
    assert "liq:ES:15m:2:BUY_SIDE:13.25" in ids
    assert "liq:ES:15m:4:SELL_SIDE:8.00" in ids


class TestSweepBarCloseReclaimInvariant:
    """Producer invariant behind the sweep_trap docstrings: every emitted sweep's
    OWN bar already closed back through the level (bull/SELL_SIDE: low pierces,
    close > level; bear/BUY_SIDE mirrored). The trap classifier only sees the
    bars AFTER it, so its 'reclaim' fields measure re-confirmation/persistence —
    if this invariant ever loosens, those docstrings (and the shadow-study
    reading) are wrong."""

    def _bars(self) -> pd.DataFrame:
        rows = []
        for i, (hi, lo, cl) in enumerate([
            (101.0, 100.0, 100.5),   # pre-level context
            (100.8, 97.9, 100.6),    # pierces 98-level low? no: this is generic
            (102.5, 99.5, 102.0),
            (103.0, 97.5, 100.4),    # sweeps a 98/100 low, closes back above 100
            (101.0, 100.2, 100.8),
        ]):
            rows.append({"timestamp": 1_700_000_000 + i * 900, "open": cl,
                         "high": hi, "low": lo, "close": cl, "volume": 1.0})
        return pd.DataFrame(rows)

    def test_sell_side_sweep_bar_closes_back_above_the_level(self) -> None:
        bars = self._bars()
        levels = [{"time": 1_700_000_000, "price": 100.0, "side": "SELL_SIDE"}]
        sweeps = detect_liquidity_sweeps(bars, levels, "TEST", "15m")
        assert sweeps, "fixture must produce at least one sweep"
        by_ts = {int(r["timestamp"]): r for _, r in bars.iterrows()}
        for sw in sweeps:
            bar = by_ts[int(sw["time"])]
            assert float(bar["low"]) < 100.0 < float(bar["close"])  # close-reclaim ON the sweep bar

    def test_no_sweep_without_a_close_reclaim_on_the_bar(self) -> None:
        # A pierce that does NOT close back through the level is not a sweep.
        rows = [
            {"timestamp": 1_700_000_000, "open": 100.5, "high": 101.0, "low": 100.0, "close": 100.5, "volume": 1.0},
            {"timestamp": 1_700_000_900, "open": 99.0, "high": 100.2, "low": 97.5, "close": 99.0, "volume": 1.0},
        ]
        sweeps = detect_liquidity_sweeps(
            pd.DataFrame(rows), [{"time": 1_700_000_000, "price": 100.0, "side": "SELL_SIDE"}], "TEST", "15m"
        )
        assert sweeps == []
