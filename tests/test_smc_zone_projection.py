"""Tests for smc_zone_projection — zone projection layer (v5.2).

Covers:
- neutral/default mode
- bullish projection scenario
- bearish projection scenario
- trap risk classification
- spread quality classification
- zone decay
- projection score
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_zone_projection import DEFAULTS, build_zone_projection


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "zone_proj_target_bull": 0.0,
        "zone_proj_target_bear": 0.0,
        "zone_proj_retest_expected": False,
        "zone_proj_trap_risk": "",
        "zone_proj_sweep_depth": 0.0,
        "zone_proj_spread_bps": 2.5,
        "zone_proj_htf_aligned": False,
        "zone_proj_decay_bars": 0,
        "zone_proj_confidence": 0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_zone_projection()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_zone_projection(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_zone_projection(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_zone_projection()
        assert set(result.keys()) == set(DEFAULTS.keys())


class TestBullishProjection:
    @pytest.fixture()
    def result(self):
        return build_zone_projection(
            snapshot=_make_snapshot(
                zone_proj_target_bull=110.0,
                zone_proj_htf_aligned=True,
                zone_proj_spread_bps=1.0,
                zone_proj_confidence=4,
            )
        )

    def test_target_bull(self, result):
        assert result["ZONE_PROJ_TARGET_BULL"] == 110.0

    def test_htf_aligned(self, result):
        assert result["ZONE_PROJ_HTF_ALIGNED"] is True

    def test_spread_tight(self, result):
        assert result["ZONE_PROJ_SPREAD_QUALITY"] == "TIGHT"

    def test_bias_bullish(self, result):
        assert result["ZONE_PROJ_BIAS"] == "BULLISH"

    def test_score_high(self, result):
        assert result["ZONE_PROJ_SCORE"] >= 4


class TestBearishProjection:
    @pytest.fixture()
    def result(self):
        return build_zone_projection(
            snapshot=_make_snapshot(
                zone_proj_target_bear=90.0,
                zone_proj_sweep_depth=0.7,
            )
        )

    def test_target_bear(self, result):
        assert result["ZONE_PROJ_TARGET_BEAR"] == 90.0

    def test_trap_risk_high(self, result):
        assert result["ZONE_PROJ_TRAP_RISK"] == "HIGH"


class TestTrapRiskClassification:
    def test_explicit_medium(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_trap_risk="MEDIUM")
        )
        assert result["ZONE_PROJ_TRAP_RISK"] == "MEDIUM"

    def test_inferred_high(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_sweep_depth=0.7)
        )
        assert result["ZONE_PROJ_TRAP_RISK"] == "HIGH"

    def test_inferred_medium(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_sweep_depth=0.35)
        )
        assert result["ZONE_PROJ_TRAP_RISK"] == "MEDIUM"

    def test_inferred_low(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_sweep_depth=0.1)
        )
        assert result["ZONE_PROJ_TRAP_RISK"] == "LOW"

    def test_none(self):
        result = build_zone_projection(snapshot=_make_snapshot())
        assert result["ZONE_PROJ_TRAP_RISK"] == "NONE"


class TestSpreadQuality:
    def test_tight(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_spread_bps=1.0)
        )
        assert result["ZONE_PROJ_SPREAD_QUALITY"] == "TIGHT"

    def test_wide(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_spread_bps=6.0)
        )
        assert result["ZONE_PROJ_SPREAD_QUALITY"] == "WIDE"

    def test_normal(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_spread_bps=3.0)
        )
        assert result["ZONE_PROJ_SPREAD_QUALITY"] == "NORMAL"


class TestDecayBars:
    def test_decay_preserved(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_decay_bars=15)
        )
        assert result["ZONE_PROJ_DECAY_BARS"] == 15

    def test_negative_clamped(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(zone_proj_decay_bars=-5)
        )
        assert result["ZONE_PROJ_DECAY_BARS"] == 0


class TestProjectionScore:
    def test_zero_no_data(self):
        result = build_zone_projection(snapshot=_make_snapshot())
        assert result["ZONE_PROJ_SCORE"] == 1  # NONE trap risk gives +1

    def test_max_score(self):
        result = build_zone_projection(
            snapshot=_make_snapshot(
                zone_proj_target_bull=110.0,
                zone_proj_htf_aligned=True,
                zone_proj_spread_bps=1.0,
                zone_proj_confidence=4,
            )
        )
        assert result["ZONE_PROJ_SCORE"] == 5


class TestOverrides:
    def test_override_bias(self):
        result = build_zone_projection(overrides={"ZONE_PROJ_BIAS": "BEARISH"})
        assert result["ZONE_PROJ_BIAS"] == "BEARISH"

    def test_unknown_override_ignored(self):
        result = build_zone_projection(overrides={"NOT_A_FIELD": 42})
        assert "NOT_A_FIELD" not in result
