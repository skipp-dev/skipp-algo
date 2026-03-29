"""Tests for smc_session_structure (AP3 v5.3).

14 fields, covering:
  - defaults / neutral outputs
  - session high/low tracking
  - opening range detection & break
  - intra-session BOS/CHoCH
  - PDH/PDL sweep detection
  - impulse direction/strength
  - composite score
  - overrides & symbol filter
  - return contract
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_session_structure import DEFAULTS, build_session_structure


# ── Test data helpers ────────────────────────────────────────────────

def _session_bars_bull() -> pd.DataFrame:
    """Intra-session bars trending up, breaking OR high.

    OR (first 5 bars): high=102, low=99
    Close at bar 9 = 108, well above OR high → ABOVE break.
    """
    return pd.DataFrame({
        "open":  [100, 101, 100, 101, 102, 103, 104, 105, 106, 107],
        "high":  [101, 102, 101, 102, 102, 104, 105, 106, 107, 108],
        "low":   [99,  100, 99,  100, 101, 102, 103, 104, 105, 106],
        "close": [101, 101, 100, 102, 102, 103, 104, 106, 107, 108],
    })


def _session_bars_bear() -> pd.DataFrame:
    """Intra-session bars trending down, breaking OR low.

    OR (first 5 bars): high=101, low=96
    Close at bar 9 = 91, below OR low → BELOW break.
    """
    return pd.DataFrame({
        "open":  [100, 99, 100, 99, 98, 97, 96, 95, 94, 93],
        "high":  [101, 100, 101, 100, 99, 98, 97, 96, 95, 94],
        "low":   [99,  98,  99,  97,  96, 95, 94, 93, 92, 91],
        "close": [99,  99,  99,  97,  97, 96, 95, 94, 93, 91],
    })


def _session_bars_with_swings() -> pd.DataFrame:
    """10 bars with clear swing highs/lows for BOS detection.

    Wave-up pattern producing swing highs and lows.
    """
    return pd.DataFrame({
        "open":  [100, 103, 101, 104, 102, 105, 103, 107, 105, 109],
        "high":  [102, 104, 103, 106, 104, 107, 105, 108, 107, 110],
        "low":   [99,  101, 100, 102, 101, 103, 102, 105, 104, 108],
        "close": [101, 103, 101, 104, 102, 106, 103, 107, 105, 109],
    })


def _session_bars_with_choch() -> pd.DataFrame:
    """Bars with uptrend then reversal → CHoCH.

    Bars 0-5: up-trending with swing highs/lows
    Bars 6-9: reversal, close breaks below last swing low.
    """
    return pd.DataFrame({
        "open":  [100, 103, 101, 105, 103, 108, 105, 102, 99, 96],
        "high":  [102, 105, 103, 107, 104, 109, 106, 103, 100, 97],
        "low":   [99,  101,  99, 103, 101, 106, 103, 100, 97, 94],
        "close": [101, 104, 101, 106, 103, 108, 104, 101, 98, 95],
    })


def _flat_bars() -> pd.DataFrame:
    """Flat bars — no movement."""
    return pd.DataFrame({
        "open":  [100, 100, 100, 100, 100, 100],
        "high":  [101, 101, 101, 101, 101, 101],
        "low":   [99,  99,  99,  99,  99,  99],
        "close": [100, 100, 100, 100, 100, 100],
    })


def _prev_day() -> pd.DataFrame:
    """Previous day summary: high=105, low=95."""
    return pd.DataFrame({"high": [105], "low": [95]})


# ── Tests ────────────────────────────────────────────────────────────

class TestDefaults:
    def test_field_count(self):
        assert len(DEFAULTS) == 14

    def test_all_neutral(self):
        result = build_session_structure()
        assert result == DEFAULTS


class TestNoneInputs:
    def test_none_snapshot(self):
        result = build_session_structure(snapshot=None)
        assert result == DEFAULTS

    def test_empty_df(self):
        result = build_session_structure(snapshot=pd.DataFrame())
        assert result == DEFAULTS


class TestSessionHighLow:
    def test_bull_session(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        assert result["SESS_HIGH"] == 108
        assert result["SESS_LOW"] == 99

    def test_bear_session(self):
        result = build_session_structure(snapshot=_session_bars_bear())
        assert result["SESS_HIGH"] == 101
        assert result["SESS_LOW"] == 91


class TestOpeningRange:
    def test_or_from_first_bars(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        assert result["SESS_OPEN_RANGE_HIGH"] == 102
        assert result["SESS_OPEN_RANGE_LOW"] == 99

    def test_or_break_above(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        assert result["SESS_OPEN_RANGE_BREAK"] == "ABOVE"

    def test_or_break_below(self):
        result = build_session_structure(snapshot=_session_bars_bear())
        assert result["SESS_OPEN_RANGE_BREAK"] == "BELOW"

    def test_no_break_flat(self):
        result = build_session_structure(snapshot=_flat_bars())
        assert result["SESS_OPEN_RANGE_BREAK"] == "NONE"


class TestIntraBOS:
    def test_bos_detected(self):
        result = build_session_structure(snapshot=_session_bars_with_swings())
        assert result["SESS_INTRA_BOS_COUNT"] > 0

    def test_no_bos_flat(self):
        result = build_session_structure(snapshot=_flat_bars())
        assert result["SESS_INTRA_BOS_COUNT"] == 0


class TestIntraCHOCH:
    def test_choch_detected(self):
        result = build_session_structure(snapshot=_session_bars_with_choch())
        assert result["SESS_INTRA_CHOCH"] is True

    def test_no_choch_flat(self):
        result = build_session_structure(snapshot=_flat_bars())
        assert result["SESS_INTRA_CHOCH"] is False


class TestPDH_PDL:
    def test_pdh_pdl_populated(self):
        result = build_session_structure(
            snapshot=_session_bars_bull(),
            prev_day_snapshot=_prev_day(),
        )
        assert result["SESS_PDH"] == 105
        assert result["SESS_PDL"] == 95

    def test_pdh_swept(self):
        """Session high 108 > PDH 105 → swept."""
        result = build_session_structure(
            snapshot=_session_bars_bull(),
            prev_day_snapshot=_prev_day(),
        )
        assert result["SESS_PDH_SWEPT"] is True

    def test_pdl_swept(self):
        """Session low 91 < PDL 95 → swept."""
        result = build_session_structure(
            snapshot=_session_bars_bear(),
            prev_day_snapshot=_prev_day(),
        )
        assert result["SESS_PDL_SWEPT"] is True

    def test_no_sweep_when_within_range(self):
        """Session stays within PDH/PDL range → no sweep."""
        result = build_session_structure(
            snapshot=_flat_bars(),
            prev_day_snapshot=_prev_day(),
        )
        assert result["SESS_PDH_SWEPT"] is False
        assert result["SESS_PDL_SWEPT"] is False


class TestImpulse:
    def test_bull_impulse(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        assert result["SESS_IMPULSE_DIR"] == "BULL"
        assert result["SESS_IMPULSE_STRENGTH"] > 0

    def test_bear_impulse(self):
        result = build_session_structure(snapshot=_session_bars_bear())
        assert result["SESS_IMPULSE_DIR"] == "BEAR"
        assert result["SESS_IMPULSE_STRENGTH"] > 0

    def test_no_impulse_flat(self):
        result = build_session_structure(snapshot=_flat_bars())
        assert result["SESS_IMPULSE_DIR"] == "NONE"
        assert result["SESS_IMPULSE_STRENGTH"] == 0


class TestCompositeScore:
    def test_high_score_bull(self):
        result = build_session_structure(
            snapshot=_session_bars_bull(),
            prev_day_snapshot=_prev_day(),
        )
        # OR break + impulse + PDH swept = at least 3
        assert result["SESS_STRUCT_SCORE"] >= 3

    def test_zero_score_flat(self):
        result = build_session_structure(snapshot=_flat_bars())
        assert result["SESS_STRUCT_SCORE"] == 0


class TestOverrides:
    def test_override_applied(self):
        result = build_session_structure(
            snapshot=_flat_bars(),
            overrides={"SESS_IMPULSE_DIR": "BULL"},
        )
        assert result["SESS_IMPULSE_DIR"] == "BULL"

    def test_unknown_override_ignored(self):
        result = build_session_structure(overrides={"UNKNOWN": 999})
        assert "UNKNOWN" not in result


class TestSymbolFilter:
    def test_matching_symbol(self):
        df = _session_bars_bull().copy()
        df["symbol"] = "AAPL"
        result = build_session_structure(snapshot=df, symbol="AAPL")
        assert result["SESS_HIGH"] == 108

    def test_non_matching_symbol(self):
        df = _session_bars_bull().copy()
        df["symbol"] = "AAPL"
        result = build_session_structure(snapshot=df, symbol="MSFT")
        assert result == DEFAULTS


class TestReturnContract:
    def test_all_keys_present(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        for key in DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_no_extra_keys(self):
        result = build_session_structure(snapshot=_session_bars_bull())
        for key in result:
            assert key in DEFAULTS, f"Extra key: {key}"

    def test_returns_dict(self):
        result = build_session_structure()
        assert isinstance(result, dict)
