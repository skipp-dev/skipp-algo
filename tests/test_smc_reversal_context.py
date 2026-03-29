"""Tests for smc_reversal_context builder."""
from __future__ import annotations

import pandas as pd
import pytest

from scripts.smc_reversal_context import DEFAULTS, build_reversal_context


# ── Helpers ─────────────────────────────────────────────────────────

def _make_signals(**kwargs) -> dict:
    """Build a signals dict with sensible test values."""
    base = {
        "htf_structure_ok": False,
        "htf_bullish_pattern": False,
        "htf_bearish_pattern": False,
        "htf_bullish_divergence": False,
        "htf_bearish_divergence": False,
        "fvg_confirm_ok": False,
        "vwap_hold_ok": False,
        "retrace_pct": 100.0,
        "volume_confirm": False,
        "close_strength_ok": False,
        "momentum_positive": False,
        "higher_low_formed": False,
        "volume_follow_through": False,
    }
    base.update(kwargs)
    return base


def _make_snapshot(**kwargs) -> pd.DataFrame:
    """Build a single-row DataFrame from signal keys."""
    sigs = _make_signals(**kwargs)
    return pd.DataFrame([sigs])


# ── Test classes ────────────────────────────────────────────────────

class TestNoReversalContext:
    """No signals → all defaults, inactive."""

    def test_defaults_no_snapshot(self):
        result = build_reversal_context()
        assert result == DEFAULTS

    def test_defaults_empty_snapshot(self):
        result = build_reversal_context(snapshot=pd.DataFrame())
        assert result == DEFAULTS

    def test_defaults_no_signals(self):
        result = build_reversal_context(signals={})
        assert result == DEFAULTS

    def test_inactive_weak_signals(self):
        """Single weak signal → still inactive (setup < 2)."""
        sig = _make_signals(htf_structure_ok=True)
        result = build_reversal_context(signals=sig)
        assert result["REVERSAL_CONTEXT_ACTIVE"] is False
        assert result["SETUP_SCORE"] == 1


class TestBullishReversalContext:
    """Strong bullish HTF signals → active reversal context."""

    @pytest.fixture()
    def result(self):
        sig = _make_signals(
            htf_structure_ok=True,
            htf_bullish_pattern=True,
            htf_bullish_divergence=True,
            fvg_confirm_ok=True,
            vwap_hold_ok=True,
            retrace_pct=50.0,
            volume_confirm=True,
            close_strength_ok=True,
            momentum_positive=True,
            higher_low_formed=True,
            volume_follow_through=True,
        )
        return build_reversal_context(signals=sig)

    def test_active(self, result):
        assert result["REVERSAL_CONTEXT_ACTIVE"] is True

    def test_setup_score_max(self, result):
        assert result["SETUP_SCORE"] == 5

    def test_confirm_score_max(self, result):
        assert result["CONFIRM_SCORE"] == 5

    def test_follow_through_max(self, result):
        assert result["FOLLOW_THROUGH_SCORE"] == 5

    def test_htf_booleans(self, result):
        assert result["HTF_STRUCTURE_OK"] is True
        assert result["HTF_BULLISH_PATTERN"] is True
        assert result["HTF_BEARISH_PATTERN"] is False
        assert result["HTF_BULLISH_DIVERGENCE"] is True
        assert result["HTF_BEARISH_DIVERGENCE"] is False

    def test_confluence(self, result):
        assert result["FVG_CONFIRM_OK"] is True
        assert result["VWAP_HOLD_OK"] is True
        assert result["RETRACE_OK"] is True


class TestBearishReversalContext:
    """Bearish HTF signals → active reversal context."""

    @pytest.fixture()
    def result(self):
        sig = _make_signals(
            htf_structure_ok=True,
            htf_bearish_pattern=True,
            htf_bearish_divergence=True,
            fvg_confirm_ok=True,
            retrace_pct=38.2,
        )
        return build_reversal_context(signals=sig)

    def test_active(self, result):
        assert result["REVERSAL_CONTEXT_ACTIVE"] is True

    def test_setup_score(self, result):
        # structure + pattern + divergence + fvg + retrace = 5
        assert result["SETUP_SCORE"] == 5

    def test_bearish_flags(self, result):
        assert result["HTF_BEARISH_PATTERN"] is True
        assert result["HTF_BEARISH_DIVERGENCE"] is True
        assert result["HTF_BULLISH_PATTERN"] is False


class TestConfirmedFollowThrough:
    """Good confirm + follow-through signals."""

    @pytest.fixture()
    def result(self):
        sig = _make_signals(
            htf_structure_ok=True,
            htf_bullish_pattern=True,
            fvg_confirm_ok=True,
            vwap_hold_ok=True,
            retrace_pct=45.0,
            volume_confirm=True,
            momentum_positive=True,
            higher_low_formed=True,
            volume_follow_through=True,
        )
        return build_reversal_context(signals=sig)

    def test_confirm_score(self, result):
        # fvg + vwap + retrace + volume_confirm + close_strength = 4
        assert result["CONFIRM_SCORE"] == 4

    def test_follow_through_score(self, result):
        # htf + vwap + momentum + higher_low + volume_ft = 5
        assert result["FOLLOW_THROUGH_SCORE"] == 5


class TestFailedRetrace:
    """Retrace > 61.8% → RETRACE_OK false, reduces scores."""

    def test_retrace_failed(self):
        sig = _make_signals(
            htf_structure_ok=True,
            htf_bullish_pattern=True,
            fvg_confirm_ok=True,
            retrace_pct=75.0,
        )
        result = build_reversal_context(signals=sig)
        assert result["RETRACE_OK"] is False
        # structure + pattern + fvg = 3, retrace fails
        assert result["SETUP_SCORE"] == 3

    def test_vwap_failed(self):
        sig = _make_signals(
            htf_structure_ok=True,
            htf_bullish_pattern=True,
            fvg_confirm_ok=True,
            vwap_hold_ok=False,
            retrace_pct=50.0,
        )
        result = build_reversal_context(signals=sig)
        assert result["VWAP_HOLD_OK"] is False
        # confirm: fvg + retrace = 2 (no vwap, no volume_confirm, no close_strength)
        assert result["CONFIRM_SCORE"] == 2


class TestSnapshotExtraction:
    """Signal extraction from DataFrame."""

    def test_from_snapshot(self):
        snap = _make_snapshot(
            htf_structure_ok=True,
            htf_bullish_pattern=True,
            fvg_confirm_ok=True,
            retrace_pct=40.0,
        )
        result = build_reversal_context(snapshot=snap)
        assert result["HTF_STRUCTURE_OK"] is True
        assert result["HTF_BULLISH_PATTERN"] is True
        assert result["FVG_CONFIRM_OK"] is True
        assert result["RETRACE_OK"] is True

    def test_from_snapshot_with_symbol(self):
        snap = _make_snapshot(htf_structure_ok=True, retrace_pct=30.0)
        snap["symbol"] = "BTCUSD"
        result = build_reversal_context(snapshot=snap, symbol="BTCUSD")
        assert result["HTF_STRUCTURE_OK"] is True


class TestOverrides:
    """Manual overrides take precedence."""

    def test_override_score(self):
        result = build_reversal_context(overrides={"SETUP_SCORE": 4})
        assert result["SETUP_SCORE"] == 4

    def test_override_active(self):
        result = build_reversal_context(
            overrides={"REVERSAL_CONTEXT_ACTIVE": True, "SETUP_SCORE": 5}
        )
        assert result["REVERSAL_CONTEXT_ACTIVE"] is True

    def test_unknown_key_ignored(self):
        result = build_reversal_context(overrides={"UNKNOWN_FIELD": 42})
        assert "UNKNOWN_FIELD" not in result
