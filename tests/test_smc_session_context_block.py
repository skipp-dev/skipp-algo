"""Tests for smc_session_context_block — session context layer (v5.2).

Covers:
- neutral/default mode (no snapshot, no timestamp)
- session classification (ASIA, LONDON, NY_AM, NY_PM, NONE)
- killzone detection
- bullish MSS/FVG scenario
- bearish MSS/FVG scenario
- direction bias derivation
- context score computation
- override merging
"""
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from scripts.smc_session_context_block import DEFAULTS, build_session_context_block


# ── Helpers ──────────────────────────────────────────────────────


def _make_snapshot(**kwargs) -> pd.DataFrame:
    defaults = {
        "symbol": "AAPL",
        "session_mss_bull": False,
        "session_mss_bear": False,
        "session_structure_state": "NEUTRAL",
        "session_fvg_bull_active": False,
        "session_fvg_bear_active": False,
        "session_bpr_active": False,
        "session_range_top": 0.0,
        "session_range_bottom": 0.0,
        "session_mean": 0.0,
        "session_vwap": 0.0,
        "session_target_bull": 0.0,
        "session_target_bear": 0.0,
    }
    defaults.update(kwargs)
    return pd.DataFrame([defaults])


def _ts(hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 6, 15, hour, minute, 0, tzinfo=timezone.utc)


# ═════════════════════════════════════════════════════════════════
# 1. Neutral / Default mode
# ═════════════════════════════════════════════════════════════════


class TestNeutralDefaults:
    def test_no_args_returns_defaults_keys(self):
        result = build_session_context_block(timestamp=_ts(21, 0))
        for key in DEFAULTS:
            assert key in result, f"Missing key: {key}"

    def test_none_snapshot_returns_defaults(self):
        result = build_session_context_block(snapshot=None, timestamp=_ts(21, 0))
        assert result["SESSION_MSS_BULL"] is False
        assert result["SESSION_DIRECTION_BIAS"] == "NEUTRAL"

    def test_empty_snapshot_returns_defaults(self):
        result = build_session_context_block(snapshot=pd.DataFrame(), timestamp=_ts(21, 0))
        assert result["SESSION_CONTEXT_SCORE"] == 0

    def test_all_keys_present(self):
        result = build_session_context_block(timestamp=_ts(21, 0))
        assert set(result.keys()) == set(DEFAULTS.keys())


# ═════════════════════════════════════════════════════════════════
# 2. Session classification
# ═════════════════════════════════════════════════════════════════


class TestSessionClassification:
    def test_asia_session(self):
        result = build_session_context_block(timestamp=_ts(2, 0))
        assert result["SESSION_CONTEXT"] == "ASIA"

    def test_london_session(self):
        result = build_session_context_block(timestamp=_ts(9, 0))
        assert result["SESSION_CONTEXT"] == "LONDON"

    def test_ny_am_session(self):
        result = build_session_context_block(timestamp=_ts(14, 0))
        assert result["SESSION_CONTEXT"] == "NY_AM"

    def test_ny_pm_session(self):
        result = build_session_context_block(timestamp=_ts(18, 0))
        assert result["SESSION_CONTEXT"] == "NY_PM"

    def test_outside_session(self):
        result = build_session_context_block(timestamp=_ts(21, 0))
        assert result["SESSION_CONTEXT"] == "NONE"


# ═════════════════════════════════════════════════════════════════
# 3. Killzone detection
# ═════════════════════════════════════════════════════════════════


class TestKillzone:
    def test_in_asia_killzone(self):
        result = build_session_context_block(timestamp=_ts(2, 0))
        assert result["IN_KILLZONE"] is True

    def test_in_london_killzone(self):
        result = build_session_context_block(timestamp=_ts(8, 30))
        assert result["IN_KILLZONE"] is True

    def test_in_ny_killzone(self):
        result = build_session_context_block(timestamp=_ts(14, 30))
        assert result["IN_KILLZONE"] is True

    def test_outside_killzone(self):
        result = build_session_context_block(timestamp=_ts(12, 0))
        assert result["IN_KILLZONE"] is False


# ═════════════════════════════════════════════════════════════════
# 4. Bullish session scenario
# ═════════════════════════════════════════════════════════════════


class TestBullishSession:
    @pytest.fixture()
    def result(self):
        return build_session_context_block(
            snapshot=_make_snapshot(
                session_mss_bull=True,
                session_fvg_bull_active=True,
                session_target_bull=105.0,
            ),
            timestamp=_ts(14, 30),
        )

    def test_mss_bull(self, result):
        assert result["SESSION_MSS_BULL"] is True

    def test_fvg_bull(self, result):
        assert result["SESSION_FVG_BULL_ACTIVE"] is True

    def test_target_bull(self, result):
        assert result["SESSION_TARGET_BULL"] == 105.0

    def test_direction_bullish(self, result):
        assert result["SESSION_DIRECTION_BIAS"] == "BULLISH"

    def test_score_high(self, result):
        assert result["SESSION_CONTEXT_SCORE"] >= 4


# ═════════════════════════════════════════════════════════════════
# 5. Bearish session scenario
# ═════════════════════════════════════════════════════════════════


class TestBearishSession:
    @pytest.fixture()
    def result(self):
        return build_session_context_block(
            snapshot=_make_snapshot(
                session_mss_bear=True,
                session_fvg_bear_active=True,
                session_target_bear=95.0,
            ),
            timestamp=_ts(8, 0),
        )

    def test_mss_bear(self, result):
        assert result["SESSION_MSS_BEAR"] is True

    def test_direction_bearish(self, result):
        assert result["SESSION_DIRECTION_BIAS"] == "BEARISH"


# ═════════════════════════════════════════════════════════════════
# 6. Context score
# ═════════════════════════════════════════════════════════════════


class TestContextScore:
    def test_zero_outside_session(self):
        result = build_session_context_block(timestamp=_ts(21, 0))
        assert result["SESSION_CONTEXT_SCORE"] == 0

    def test_one_in_session_no_kz(self):
        result = build_session_context_block(timestamp=_ts(12, 0))
        # 12:00 UTC is in London session (7–15:30) but NOT in London KZ (7–10)
        assert result["SESSION_CONTEXT"] == "LONDON"
        assert result["IN_KILLZONE"] is False
        assert result["SESSION_CONTEXT_SCORE"] == 1

    def test_max_score(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(
                session_mss_bull=True,
                session_fvg_bull_active=True,
                session_target_bull=110.0,
                session_structure_state="BULLISH",
                session_bpr_active=True,
            ),
            timestamp=_ts(8, 30),
        )
        assert result["SESSION_CONTEXT_SCORE"] == 7


# ═════════════════════════════════════════════════════════════════
# 7a. New v5.3 session context fields
# ═════════════════════════════════════════════════════════════════


class TestNewSessionFields:
    def test_structure_state_from_snapshot(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_structure_state="BULLISH"),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_STRUCTURE_STATE"] == "BULLISH"

    def test_structure_state_default(self):
        result = build_session_context_block(timestamp=_ts(14, 0))
        assert result["SESSION_STRUCTURE_STATE"] == "NEUTRAL"

    def test_bpr_active_from_snapshot(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_bpr_active=True),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_BPR_ACTIVE"] is True

    def test_range_top_bottom(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_range_top=105.5, session_range_bottom=100.0),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_RANGE_TOP"] == 105.5
        assert result["SESSION_RANGE_BOTTOM"] == 100.0

    def test_session_mean(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_mean=102.75),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_MEAN"] == 102.75

    def test_session_vwap(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_vwap=103.0),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_VWAP"] == 103.0

    def test_score_includes_structure_state(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_structure_state="BEARISH"),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_CONTEXT_SCORE"] >= 2  # session + structure_state

    def test_score_includes_bpr(self):
        result = build_session_context_block(
            snapshot=_make_snapshot(session_bpr_active=True),
            timestamp=_ts(14, 0),
        )
        assert result["SESSION_CONTEXT_SCORE"] >= 2  # session + bpr


# ═════════════════════════════════════════════════════════════════
# 7. Override merging
# ═════════════════════════════════════════════════════════════════


class TestOverrides:
    def test_override_session_context(self):
        result = build_session_context_block(
            timestamp=_ts(21, 0),
            overrides={"SESSION_CONTEXT": "CUSTOM"},
        )
        assert result["SESSION_CONTEXT"] == "CUSTOM"

    def test_unknown_override_ignored(self):
        result = build_session_context_block(
            timestamp=_ts(21, 0),
            overrides={"NOT_A_FIELD": 42},
        )
        assert "NOT_A_FIELD" not in result
