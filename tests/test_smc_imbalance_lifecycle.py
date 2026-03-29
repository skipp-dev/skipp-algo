"""Tests for smc_imbalance_lifecycle (AP2 v5.3).

23 fields, covering:
  - defaults / neutral outputs
  - bullish FVG detection & mitigation
  - bearish FVG detection & mitigation
  - partial & full mitigation lifecycle
  - BPR overlap detection
  - liquidity void detection
  - overrides & symbol filter
  - return contract
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_imbalance_lifecycle import DEFAULTS, build_imbalance_lifecycle


# ── Test data helpers ────────────────────────────────────────────────

def _bars_with_bull_fvg() -> pd.DataFrame:
    """3 bars producing a bullish FVG: bar[2].low > bar[0].high.

    FVG: top=bar[2].low=102, bottom=bar[0].high=101, gap=1.
    Gap pct ~0.96% < 2% → no liq void.
    """
    return pd.DataFrame({
        "open":  [100, 102, 104],
        "high":  [101, 103, 106],
        "low":   [99,  100, 102],  # bar[2].low=102 > bar[0].high=101 → bull FVG
        "close": [100, 102, 105],
    })


def _bars_with_bear_fvg() -> pd.DataFrame:
    """3 bars producing a bearish FVG: bar[2].high < bar[0].low.

    FVG: top=bar[0].low=108, bottom=bar[2].high=107, gap=1.
    Gap pct ~0.94% < 2% → no liq void.
    """
    return pd.DataFrame({
        "open":  [110, 108, 106],
        "high":  [111, 109, 107],  # bar[2].high=107 < bar[0].low=108 → bear FVG
        "low":   [108, 106, 105],
        "close": [109, 107, 106],
    })


def _bars_bull_fvg_partial_mit() -> pd.DataFrame:
    """Bull FVG then price retraces into gap (partial mitigation).

    FVG: top=bar[2].low=102, bottom=bar[0].high=101.  Gap=1.
    Last bar low=101.5 → fill_depth = 102-101.5 = 0.5 → mit_pct = 0.5 → partial.
    """
    return pd.DataFrame({
        "open":  [100, 102, 104, 103],
        "high":  [101, 103, 106, 105],
        "low":   [99,  100, 102, 101.5],
        "close": [100, 102, 105, 103],
    })


def _bars_bull_fvg_full_mit() -> pd.DataFrame:
    """Bull FVG then price completely fills gap (full mitigation).

    FVG: top=bar[2].low=102, bottom=bar[0].high=101.  Gap=1.
    Last bar low=99 → fill_depth = 102-99 = 3 → capped 1.0 → full.
    """
    return pd.DataFrame({
        "open":  [100, 102, 104, 100],
        "high":  [101, 103, 106, 103],
        "low":   [99,  100, 102, 99],
        "close": [100, 102, 105, 100],
    })


def _bars_bear_fvg_partial_mit() -> pd.DataFrame:
    """Bear FVG then price retraces into gap (partial mitigation).

    FVG: top=bar[0].low=108, bottom=bar[2].high=107.  Gap=1.
    Last bar high=107.5 → fill_depth = 107.5-107 = 0.5 → mit_pct = 0.5 → partial.
    """
    return pd.DataFrame({
        "open":  [110, 108, 106, 107],
        "high":  [111, 109, 107, 107.5],
        "low":   [108, 106, 105, 106],
        "close": [109, 107, 106, 107],
    })


def _bars_bear_fvg_full_mit() -> pd.DataFrame:
    """Bear FVG then price completely fills gap (full mitigation).

    FVG: top=bar[0].low=108, bottom=bar[2].high=107.  Gap=1.
    Last bar high=110 → fill_depth = 110-107 = 3, capped 1.0 → full.
    """
    return pd.DataFrame({
        "open":  [110, 108, 106, 109],
        "high":  [111, 109, 107, 110],
        "low":   [108, 106, 105, 107],
        "close": [109, 107, 106, 108],
    })


def _bars_with_bpr() -> pd.DataFrame:
    """Bars where both a bull and bear FVG overlap (balanced price range).

    bars 0-2: bull FVG  → top=bar[2].low=106, bottom=bar[0].high=101
    bars 3-5: bear FVG  → top=bar[3].low=107, bottom=bar[5].high=105
    overlap zone: max(101,105)=105 – min(106,107)=106 → (105,106)
    Last bar: low=103, high=105 → bull FVG mit 75%<100% (active), bear FVG mit 0% (active).
    """
    return pd.DataFrame({
        "open":  [100, 102, 108, 110, 108, 104],
        "high":  [101, 103, 112, 111, 109, 105],
        "low":   [99,  100, 106, 107, 106, 103],
        "close": [100, 102, 110, 108, 107, 104],
    })


def _bars_with_liq_void() -> pd.DataFrame:
    """Bars producing a liquidity void (very large FVG > 2% of price).

    Price ~100, so a gap of ~3 would be 3% → qualifies as liquidity void.
    """
    return pd.DataFrame({
        "open":  [100, 104, 110],
        "high":  [101, 107, 115],
        "low":   [99,  102, 106],  # bar[2].low=106 > bar[0].high=101 → bull FVG, gap=5, ~5% of ~105
        "close": [100, 106, 112],
    })


def _flat_bars() -> pd.DataFrame:
    """Flat bars with no FVGs."""
    return pd.DataFrame({
        "open":  [100, 100, 100, 100, 100],
        "high":  [101, 101, 101, 101, 101],
        "low":   [99,  99,  99,  99,  99],
        "close": [100, 100, 100, 100, 100],
    })


# ── Tests ────────────────────────────────────────────────────────────

class TestDefaults:
    def test_field_count(self):
        assert len(DEFAULTS) == 23

    def test_all_neutral(self):
        result = build_imbalance_lifecycle()
        assert result == DEFAULTS


class TestNoneInputs:
    def test_none_snapshot(self):
        result = build_imbalance_lifecycle(snapshot=None)
        assert result == DEFAULTS

    def test_empty_df(self):
        result = build_imbalance_lifecycle(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_too_few_bars(self):
        df = pd.DataFrame({"open": [1, 2], "high": [2, 3], "low": [0, 1], "close": [1, 2]})
        result = build_imbalance_lifecycle(snapshot=df)
        assert result == DEFAULTS


class TestBullFVG:
    def test_active(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bull_fvg())
        assert result["BULL_FVG_ACTIVE"] is True
        assert result["BULL_FVG_TOP"] == 102
        assert result["BULL_FVG_BOTTOM"] == 101
        assert result["BULL_FVG_COUNT"] >= 1
        assert result["IMBALANCE_STATE"] == "FVG_BULL"

    def test_no_bear_when_only_bull(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bull_fvg())
        assert result["BEAR_FVG_ACTIVE"] is False


class TestBearFVG:
    def test_active(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bear_fvg())
        assert result["BEAR_FVG_ACTIVE"] is True
        assert result["BEAR_FVG_TOP"] == 108
        assert result["BEAR_FVG_BOTTOM"] == 107
        assert result["BEAR_FVG_COUNT"] >= 1
        assert result["IMBALANCE_STATE"] == "FVG_BEAR"

    def test_no_bull_when_only_bear(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bear_fvg())
        assert result["BULL_FVG_ACTIVE"] is False


class TestPartialMitigation:
    def test_bull_partial(self):
        result = build_imbalance_lifecycle(snapshot=_bars_bull_fvg_partial_mit())
        assert result["BULL_FVG_ACTIVE"] is True
        assert result["BULL_FVG_PARTIAL_MITIGATION"] is True
        assert result["BULL_FVG_FULL_MITIGATION"] is False
        assert 0 < result["BULL_FVG_MITIGATION_PCT"] < 1.0

    def test_bear_partial(self):
        result = build_imbalance_lifecycle(snapshot=_bars_bear_fvg_partial_mit())
        assert result["BEAR_FVG_ACTIVE"] is True
        assert result["BEAR_FVG_PARTIAL_MITIGATION"] is True
        assert result["BEAR_FVG_FULL_MITIGATION"] is False
        assert 0 < result["BEAR_FVG_MITIGATION_PCT"] < 1.0


class TestFullMitigation:
    def test_bull_full(self):
        result = build_imbalance_lifecycle(snapshot=_bars_bull_fvg_full_mit())
        # Fully mitigated → no longer active
        assert result["BULL_FVG_ACTIVE"] is False
        assert result["BULL_FVG_FULL_MITIGATION"] is True
        assert result["BULL_FVG_MITIGATION_PCT"] == 1.0

    def test_bear_full(self):
        result = build_imbalance_lifecycle(snapshot=_bars_bear_fvg_full_mit())
        assert result["BEAR_FVG_ACTIVE"] is False
        assert result["BEAR_FVG_FULL_MITIGATION"] is True
        assert result["BEAR_FVG_MITIGATION_PCT"] == 1.0


class TestBPR:
    def test_bpr_detected(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bpr())
        assert result["BPR_ACTIVE"] is True
        assert result["BPR_DIRECTION"] in ("BULL", "BEAR")
        assert result["BPR_TOP"] > 0
        assert result["BPR_BOTTOM"] > 0
        assert result["BPR_TOP"] > result["BPR_BOTTOM"]
        assert result["IMBALANCE_STATE"] == "BPR"


class TestLiquidityVoid:
    def test_liq_void_detected(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_liq_void())
        assert result["LIQ_VOID_BULL_ACTIVE"] is True
        assert result["LIQ_VOID_TOP"] > 0
        assert result["LIQ_VOID_BOTTOM"] > 0
        assert result["IMBALANCE_STATE"] == "LIQ_VOID"


class TestFlatBars:
    def test_no_fvg(self):
        result = build_imbalance_lifecycle(snapshot=_flat_bars())
        assert result["BULL_FVG_ACTIVE"] is False
        assert result["BEAR_FVG_ACTIVE"] is False
        assert result["BPR_ACTIVE"] is False
        assert result["IMBALANCE_STATE"] == "NONE"


class TestOverrides:
    def test_override_active(self):
        result = build_imbalance_lifecycle(
            snapshot=_flat_bars(),
            overrides={"BULL_FVG_ACTIVE": True},
        )
        assert result["BULL_FVG_ACTIVE"] is True

    def test_unknown_override_ignored(self):
        result = build_imbalance_lifecycle(
            overrides={"UNKNOWN_KEY": 999},
        )
        assert "UNKNOWN_KEY" not in result

    def test_override_replaces_derived(self):
        result = build_imbalance_lifecycle(
            snapshot=_bars_with_bull_fvg(),
            overrides={"IMBALANCE_STATE": "MANUAL"},
        )
        assert result["IMBALANCE_STATE"] == "MANUAL"


class TestSymbolFilter:
    def test_matching_symbol(self):
        df = _bars_with_bull_fvg().copy()
        df["symbol"] = "AAPL"
        result = build_imbalance_lifecycle(snapshot=df, symbol="AAPL")
        assert result["BULL_FVG_ACTIVE"] is True

    def test_non_matching_symbol(self):
        df = _bars_with_bull_fvg().copy()
        df["symbol"] = "AAPL"
        result = build_imbalance_lifecycle(snapshot=df, symbol="MSFT")
        assert result == DEFAULTS


class TestReturnContract:
    def test_all_keys_present(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bull_fvg())
        for key in DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_no_extra_keys(self):
        result = build_imbalance_lifecycle(snapshot=_bars_with_bull_fvg())
        for key in result:
            assert key in DEFAULTS, f"Extra key: {key}"

    def test_returns_dict(self):
        result = build_imbalance_lifecycle()
        assert isinstance(result, dict)
