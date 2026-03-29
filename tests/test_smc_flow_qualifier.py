"""Tests for smc_flow_qualifier — flow qualification layer (v5.1).

Covers:
- neutral/default mode (no snapshot)
- strong bullish flow
- strong bearish flow
- ATS spike up / down
- ATS bullish / bearish sequence
- override merging
"""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_flow_qualifier import DEFAULTS, build_flow_qualifier


# ── Helpers ──────────────────────────────────────────────────────


def _make_snapshot(**kwargs) -> pd.DataFrame:
    """Single-row snapshot with sensible defaults."""
    defaults = {
        "symbol": "AAPL",
        "volume_today": 100_000,
        "volume_avg_20d": 100_000,
        "trade_count_today": 5000,
        "trade_count_avg_20d": 5000,
        "avg_trade_size": 200.0,
        "avg_trade_size_20d_mean": 200.0,
        "avg_trade_size_20d_std": 20.0,
        "buy_volume_pct": 50.0,
        "ats_rising_streak": 0,
        "ats_falling_streak": 0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


# ═════════════════════════════════════════════════════════════════
# 1. Neutral / Default mode
# ═════════════════════════════════════════════════════════════════


class TestNeutralDefaults:
    def test_no_snapshot_returns_defaults(self):
        result = build_flow_qualifier()
        assert result == DEFAULTS

    def test_none_snapshot_returns_defaults(self):
        result = build_flow_qualifier(snapshot=None)
        assert result == DEFAULTS

    def test_empty_snapshot_returns_defaults(self):
        result = build_flow_qualifier(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_all_keys_present(self):
        result = build_flow_qualifier()
        for key in DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_balanced_row_is_neutral(self):
        result = build_flow_qualifier(snapshot=_make_snapshot())
        assert result["REL_VOL"] == 1.0
        assert result["REL_ACTIVITY"] == 1.0
        assert result["REL_SIZE"] == 1.0
        assert result["DELTA_PROXY_PCT"] == 0.0
        assert result["ATS_STATE"] == "NEUTRAL"
        assert result["FLOW_LONG_OK"] is True
        assert result["FLOW_SHORT_OK"] is True


# ═════════════════════════════════════════════════════════════════
# 2. Strong bullish flow
# ═════════════════════════════════════════════════════════════════


class TestStrongBullishFlow:
    @pytest.fixture()
    def result(self):
        return build_flow_qualifier(
            snapshot=_make_snapshot(
                volume_today=250_000,
                volume_avg_20d=100_000,
                buy_volume_pct=85.0,
                trade_count_today=12000,
                trade_count_avg_20d=5000,
            )
        )

    def test_rel_vol_elevated(self, result):
        assert result["REL_VOL"] == 2.5

    def test_rel_activity_elevated(self, result):
        assert result["REL_ACTIVITY"] == 2.4

    def test_delta_strongly_positive(self, result):
        assert result["DELTA_PROXY_PCT"] == 70.0

    def test_flow_long_ok(self, result):
        assert result["FLOW_LONG_OK"] is True

    def test_flow_short_blocked(self, result):
        assert result["FLOW_SHORT_OK"] is False


# ═════════════════════════════════════════════════════════════════
# 3. Strong bearish flow
# ═════════════════════════════════════════════════════════════════


class TestStrongBearishFlow:
    @pytest.fixture()
    def result(self):
        return build_flow_qualifier(
            snapshot=_make_snapshot(
                volume_today=200_000,
                volume_avg_20d=100_000,
                buy_volume_pct=15.0,
            )
        )

    def test_delta_strongly_negative(self, result):
        assert result["DELTA_PROXY_PCT"] == -70.0

    def test_flow_short_ok(self, result):
        assert result["FLOW_SHORT_OK"] is True

    def test_flow_long_blocked(self, result):
        assert result["FLOW_LONG_OK"] is False


# ═════════════════════════════════════════════════════════════════
# 4. ATS spike
# ═════════════════════════════════════════════════════════════════


class TestATSSpike:
    def test_spike_up(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(
                avg_trade_size=300.0,
                avg_trade_size_20d_mean=200.0,
                avg_trade_size_20d_std=20.0,
            )
        )
        assert result["ATS_SPIKE_UP"] is True
        assert result["ATS_SPIKE_DOWN"] is False
        assert result["ATS_STATE"] == "SPIKE_UP"

    def test_spike_down(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(
                avg_trade_size=100.0,
                avg_trade_size_20d_mean=200.0,
                avg_trade_size_20d_std=20.0,
            )
        )
        assert result["ATS_SPIKE_DOWN"] is True
        assert result["ATS_SPIKE_UP"] is False
        assert result["ATS_STATE"] == "SPIKE_DOWN"

    def test_no_spike_neutral(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(
                avg_trade_size=205.0,
                avg_trade_size_20d_mean=200.0,
                avg_trade_size_20d_std=20.0,
            )
        )
        assert result["ATS_SPIKE_UP"] is False
        assert result["ATS_SPIKE_DOWN"] is False

    def test_ats_value_populated(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(avg_trade_size=350.0)
        )
        assert result["ATS_VALUE"] == 350.0


# ═════════════════════════════════════════════════════════════════
# 5. ATS sequence
# ═════════════════════════════════════════════════════════════════


class TestATSSequence:
    def test_bullish_sequence(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(ats_rising_streak=5)
        )
        assert result["ATS_BULLISH_SEQUENCE"] is True
        assert result["ATS_BEARISH_SEQUENCE"] is False

    def test_bearish_sequence(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(ats_falling_streak=4)
        )
        assert result["ATS_BEARISH_SEQUENCE"] is True
        assert result["ATS_BULLISH_SEQUENCE"] is False

    def test_no_sequence_short_streak(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(ats_rising_streak=2)
        )
        assert result["ATS_BULLISH_SEQUENCE"] is False

    def test_no_sequence_zero(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(ats_rising_streak=0, ats_falling_streak=0)
        )
        assert result["ATS_BULLISH_SEQUENCE"] is False
        assert result["ATS_BEARISH_SEQUENCE"] is False


# ═════════════════════════════════════════════════════════════════
# 6. Overrides
# ═════════════════════════════════════════════════════════════════


class TestOverrides:
    def test_override_replaces_computed(self):
        result = build_flow_qualifier(
            snapshot=_make_snapshot(buy_volume_pct=85.0),
            overrides={"DELTA_PROXY_PCT": 0.0, "FLOW_SHORT_OK": True},
        )
        assert result["DELTA_PROXY_PCT"] == 0.0
        assert result["FLOW_SHORT_OK"] is True

    def test_unknown_override_ignored(self):
        result = build_flow_qualifier(overrides={"BOGUS": 42})
        assert "BOGUS" not in result
