"""Tests for smc_profile_context — profile context layer (v5.2).

Covers:
- neutral/default mode
- VWAP position classification
- spread regime classification
- PM/AH quality
- session bias
- ticker grade
- context score
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_profile_context import DEFAULTS, build_profile_context


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "profile_volume_node": "",
        "profile_vwap_distance_pct": 0.0,
        "avg_spread_bps_rth_20d": 2.5,
        "rth_active_minutes_share_20d": 0.90,
        "pm_dollar_share_20d": 0.10,
        "ah_dollar_share_20d": 0.08,
        "midday_efficiency_20d": 0.80,
        "setup_decay_half_life_bars_20d": 25.0,
        "consistency_score_20d": 0.85,
        "wickiness_20d": 0.10,
        "clean_intraday_score_20d": 0.80,
        "reclaim_respect_rate_20d": 0.75,
        "stop_hunt_rate_20d": 0.08,
        "open_30m_dollar_share_20d": 0.20,
        "close_60m_dollar_share_20d": 0.22,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_profile_context()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_profile_context(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_profile_context(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_profile_context()
        assert set(result.keys()) == set(DEFAULTS.keys())

    def test_field_count(self):
        assert len(DEFAULTS) == 18


class TestVWAPPosition:
    def test_above(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_vwap_distance_pct=0.5)
        )
        assert result["PROFILE_VWAP_POSITION"] == "ABOVE"

    def test_below(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_vwap_distance_pct=-0.5)
        )
        assert result["PROFILE_VWAP_POSITION"] == "BELOW"

    def test_at(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_vwap_distance_pct=0.05)
        )
        assert result["PROFILE_VWAP_POSITION"] == "AT"


class TestSpreadRegime:
    def test_tight(self):
        result = build_profile_context(
            snapshot=_make_snapshot(avg_spread_bps_rth_20d=1.0)
        )
        assert result["PROFILE_SPREAD_REGIME"] == "TIGHT"

    def test_wide(self):
        result = build_profile_context(
            snapshot=_make_snapshot(avg_spread_bps_rth_20d=6.0)
        )
        assert result["PROFILE_SPREAD_REGIME"] == "WIDE"

    def test_normal(self):
        result = build_profile_context(
            snapshot=_make_snapshot(avg_spread_bps_rth_20d=3.0)
        )
        assert result["PROFILE_SPREAD_REGIME"] == "NORMAL"


class TestPMQuality:
    def test_strong(self):
        result = build_profile_context(
            snapshot=_make_snapshot(pm_dollar_share_20d=0.25)
        )
        assert result["PROFILE_PM_QUALITY"] == "STRONG"

    def test_weak(self):
        result = build_profile_context(
            snapshot=_make_snapshot(pm_dollar_share_20d=0.03)
        )
        assert result["PROFILE_PM_QUALITY"] == "WEAK"

    def test_normal(self):
        result = build_profile_context(
            snapshot=_make_snapshot(pm_dollar_share_20d=0.10)
        )
        assert result["PROFILE_PM_QUALITY"] == "NORMAL"


class TestAHQuality:
    def test_strong(self):
        result = build_profile_context(
            snapshot=_make_snapshot(ah_dollar_share_20d=0.20)
        )
        assert result["PROFILE_AH_QUALITY"] == "STRONG"

    def test_weak(self):
        result = build_profile_context(
            snapshot=_make_snapshot(ah_dollar_share_20d=0.02)
        )
        assert result["PROFILE_AH_QUALITY"] == "WEAK"


class TestSessionBias:
    def test_bullish(self):
        result = build_profile_context(
            snapshot=_make_snapshot(
                open_30m_dollar_share_20d=0.30,
                close_60m_dollar_share_20d=0.20,
            )
        )
        assert result["PROFILE_SESSION_BIAS"] == "BULLISH"

    def test_bearish(self):
        result = build_profile_context(
            snapshot=_make_snapshot(
                open_30m_dollar_share_20d=0.15,
                close_60m_dollar_share_20d=0.25,
            )
        )
        assert result["PROFILE_SESSION_BIAS"] == "BEARISH"

    def test_neutral(self):
        result = build_profile_context(
            snapshot=_make_snapshot(
                open_30m_dollar_share_20d=0.20,
                close_60m_dollar_share_20d=0.22,
            )
        )
        assert result["PROFILE_SESSION_BIAS"] == "NEUTRAL"


class TestTickerGrade:
    def test_grade_a(self):
        result = build_profile_context(
            snapshot=_make_snapshot(clean_intraday_score_20d=0.95)
        )
        assert result["PROFILE_TICKER_GRADE"] == "A"

    def test_grade_b(self):
        result = build_profile_context(
            snapshot=_make_snapshot(clean_intraday_score_20d=0.80)
        )
        assert result["PROFILE_TICKER_GRADE"] == "B"

    def test_grade_c(self):
        result = build_profile_context(
            snapshot=_make_snapshot(clean_intraday_score_20d=0.60)
        )
        assert result["PROFILE_TICKER_GRADE"] == "C"

    def test_grade_d(self):
        result = build_profile_context(
            snapshot=_make_snapshot(clean_intraday_score_20d=0.40)
        )
        assert result["PROFILE_TICKER_GRADE"] == "D"


class TestContextScore:
    def test_zero_defaults(self):
        result = build_profile_context()
        assert result["PROFILE_CONTEXT_SCORE"] == 0

    def test_high_quality_ticker(self):
        result = build_profile_context(
            snapshot=_make_snapshot(
                clean_intraday_score_20d=0.95,
                avg_spread_bps_rth_20d=1.0,
                consistency_score_20d=0.90,
                reclaim_respect_rate_20d=0.85,
                pm_dollar_share_20d=0.25,
            )
        )
        assert result["PROFILE_CONTEXT_SCORE"] == 5


class TestVolumeNode:
    def test_hvn(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_volume_node="HVN")
        )
        assert result["PROFILE_VOLUME_NODE"] == "HVN"

    def test_lvn(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_volume_node="LVN")
        )
        assert result["PROFILE_VOLUME_NODE"] == "LVN"

    def test_poc(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_volume_node="POC")
        )
        assert result["PROFILE_VOLUME_NODE"] == "POC"

    def test_unknown_stays_none(self):
        result = build_profile_context(
            snapshot=_make_snapshot(profile_volume_node="UNKNOWN")
        )
        assert result["PROFILE_VOLUME_NODE"] == "NONE"


class TestOverrides:
    def test_override_grade(self):
        result = build_profile_context(overrides={"PROFILE_TICKER_GRADE": "A"})
        assert result["PROFILE_TICKER_GRADE"] == "A"

    def test_unknown_override_ignored(self):
        result = build_profile_context(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result
