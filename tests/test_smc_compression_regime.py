"""Tests for smc_compression_regime — compression/ATR regime layer (v5.1).

Covers all four ATR regime states + squeeze on/released + momentum bias.
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_compression_regime import DEFAULTS, build_compression_regime


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "atr_14": 2.0,
        "atr_14_20d_mean": 2.0,
        "bb_width": 5.0,
        "kc_width": 5.0,
        "bb_width_prev": 5.0,
        "kc_width_prev": 5.0,
        "momentum_value": 0.0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


# ═══════════════════════════════════════════════════════════════
# 1. Defaults
# ═══════════════════════════════════════════════════════════════


class TestDefaults:
    def test_no_snapshot_returns_defaults(self):
        assert build_compression_regime() == DEFAULTS

    def test_all_keys_present(self):
        result = build_compression_regime()
        for key in DEFAULTS:
            assert key in result


# ═══════════════════════════════════════════════════════════════
# 2. ATR Regime States
# ═══════════════════════════════════════════════════════════════


class TestATRRegime:
    def test_compression(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(atr_14=1.0, atr_14_20d_mean=2.0)
        )
        assert result["ATR_REGIME"] == "COMPRESSION"
        assert result["ATR_RATIO"] == 0.5

    def test_normal(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(atr_14=2.0, atr_14_20d_mean=2.0)
        )
        assert result["ATR_REGIME"] == "NORMAL"
        assert result["ATR_RATIO"] == 1.0

    def test_expansion(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(atr_14=3.5, atr_14_20d_mean=2.0)
        )
        assert result["ATR_REGIME"] == "EXPANSION"
        assert result["ATR_RATIO"] == 1.75

    def test_exhaustion(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(atr_14=5.0, atr_14_20d_mean=2.0)
        )
        assert result["ATR_REGIME"] == "EXHAUSTION"
        assert result["ATR_RATIO"] == 2.5


# ═══════════════════════════════════════════════════════════════
# 3. Squeeze states
# ═══════════════════════════════════════════════════════════════


class TestSqueeze:
    def test_squeeze_on_bb_inside_kc(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(bb_width=3.0, kc_width=5.0)
        )
        assert result["SQUEEZE_ON"] is True
        assert result["SQUEEZE_RELEASED"] is False

    def test_squeeze_released(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(
                bb_width=5.0, kc_width=5.0,
                bb_width_prev=3.0, kc_width_prev=5.0,
            )
        )
        assert result["SQUEEZE_ON"] is False
        assert result["SQUEEZE_RELEASED"] is True

    def test_no_squeeze(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(bb_width=5.0, kc_width=5.0)
        )
        assert result["SQUEEZE_ON"] is False
        assert result["SQUEEZE_RELEASED"] is False


# ═══════════════════════════════════════════════════════════════
# 4. Momentum bias
# ═══════════════════════════════════════════════════════════════


class TestMomentumBias:
    def test_bullish_momentum(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(momentum_value=2.5)
        )
        assert result["SQUEEZE_MOMENTUM_BIAS"] == "BULLISH"

    def test_bearish_momentum(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(momentum_value=-1.3)
        )
        assert result["SQUEEZE_MOMENTUM_BIAS"] == "BEARISH"

    def test_neutral_momentum(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(momentum_value=0.0)
        )
        assert result["SQUEEZE_MOMENTUM_BIAS"] == "NEUTRAL"


# ═══════════════════════════════════════════════════════════════
# 5. Overrides
# ═══════════════════════════════════════════════════════════════


class TestOverrides:
    def test_override_atr_regime(self):
        result = build_compression_regime(
            snapshot=_make_snapshot(atr_14=5.0, atr_14_20d_mean=2.0),
            overrides={"ATR_REGIME": "NORMAL"},
        )
        assert result["ATR_REGIME"] == "NORMAL"
