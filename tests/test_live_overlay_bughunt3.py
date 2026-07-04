"""
Regression tests — Round 3 bug-hunt (ringbuffer feature-branch review findings).

Confirmed bugs found and fixed:

  B23 – LiquidityClusterDetector._risk_level divided by current_price.
        ZeroDivisionError on current_price == 0 (defective data).
        Fix: degenerate prices (<= 0, non-finite) classify as "high" risk.

  B24 – BrokenFractalDetector.fractal_history grew without bound (one dict
        per non-breaking bar) in the long-running daemon.
        Fix: capped via MAX_FRACTAL_HISTORY (only the last 3 are read).

  B25 – TripleConfluenceNavigator HTF-bias check compared against
        direction.split(...)[0], which is always "" — every non-neutral
        HTF bias rejected every signal, including aligned ones.
        Fix: compare htf_bias directly against the signal direction.

  B26 – SmtSniperValidator.risk_reward_ratio was computed as
        distance_to_sl / distance_to_sl (always 1.0, regardless of TP/SL).
        Fix: reward distance (TP1) over risk distance — 1.5 by construction.

  B27 – VolatilityFilter used the *current* close as prev_close in the
        True-Range formula, so gaps never widened the ATR.
        Fix: track the actual previous close; also cap atr_history (leak).

  B28 – StrongImpulseDetector.active_impulses grew without bound; the
        router never calls update_phase, so entries were never removed.
        Fix: stale impulses are pruned on every detect/update call.

  B29 – EnsembleSignalRouter.signal_history grew without bound.
        Fix: capped via MAX_SIGNAL_HISTORY.

  B30 – SmcSignalDetector._calculate_atr was dead code (returned half the
        range, not an ATR) and self.atr_history was never read.
        Fix: removed; candle history capped (only the last 3 are read).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.live_overlay_daemon.ensemble_signal_router import EnsembleSignalRouter
from services.live_overlay_daemon.smc_advanced_patterns import (
    BrokenFractalDetector,
    LiquidityClusterDetector,
)
from services.live_overlay_daemon.smc_signal_detector import Candle, SmcSignalDetector
from services.live_overlay_daemon.smt_sniper_validator import SmtSniperValidator
from services.live_overlay_daemon.strong_impulse_detector import (
    ImpulsePhase,
    ImpulseSignal,
    StrongImpulseDetector,
)
from services.live_overlay_daemon.triple_confluence_navigator import (
    TripleConfluenceNavigator,
)
from services.live_overlay_daemon.volatility_filter import VolatilityFilter

# ============================================================
# B23 – _risk_level: degenerate current_price must not crash
# ============================================================

class TestRiskLevelDegeneratePrice:
    def test_zero_price_does_not_raise(self):
        assert LiquidityClusterDetector()._risk_level(100.0, 0.0) == "high"

    def test_negative_price_does_not_raise(self):
        assert LiquidityClusterDetector()._risk_level(100.0, -5.0) == "high"

    def test_nan_price_does_not_raise(self):
        assert LiquidityClusterDetector()._risk_level(100.0, float("nan")) == "high"

    def test_normal_prices_unchanged(self):
        det = LiquidityClusterDetector()
        assert det._risk_level(100.0, 100.5) == "high"    # < 1% away
        assert det._risk_level(100.0, 103.0) == "medium"  # ~2.9% away
        assert det._risk_level(100.0, 120.0) == "low"     # ~16.7% away


# ============================================================
# B24 – BrokenFractalDetector: history must stay bounded
# ============================================================

class TestBrokenFractalHistoryBounded:
    def test_history_capped_over_many_bars(self):
        det = BrokenFractalDetector()
        # Constant bars never break structure -> every bar appends history.
        for i in range(10_000):
            det.detect(bar_index=i, high=100.0, low=99.0, close=99.5)
        assert len(det.fractal_history) <= det.MAX_FRACTAL_HISTORY

    def test_detection_still_works_after_trim(self):
        det = BrokenFractalDetector()
        for i in range(det.MAX_FRACTAL_HISTORY * 3):
            det.detect(bar_index=i, high=100.0, low=99.0, close=99.5)
        # Break above the tracked high must still be detected.
        bf = det.detect(bar_index=99_999, high=105.0, low=99.0, close=104.0)
        assert bf is not None
        assert bf.break_direction == "up"
        assert bf.confirmed is True


# ============================================================
# B25 – HTF-bias alignment
# ============================================================

class TestHtfBiasAlignment:
    def test_matching_bias_allows_signal(self):
        assert TripleConfluenceNavigator._htf_aligned("long", "long") is True
        assert TripleConfluenceNavigator._htf_aligned("short", "short") is True

    def test_opposing_bias_rejects_signal(self):
        assert TripleConfluenceNavigator._htf_aligned("long", "short") is False
        assert TripleConfluenceNavigator._htf_aligned("short", "long") is False

    def test_neutral_bias_allows_all(self):
        assert TripleConfluenceNavigator._htf_aligned("neutral", "long") is True
        assert TripleConfluenceNavigator._htf_aligned("neutral", "short") is True


# ============================================================
# B26 – risk_reward_ratio must reflect TP1/SL, not 1.0
# ============================================================

class TestSmtRiskReward:
    def _emit_signal(self):
        v = SmtSniperValidator(quality_threshold=70.0)
        common = dict(
            atr=1.0,
            structure_score=1.0,
            correlated_markets={"ES": "short", "NQ": "short"},
            recent_momentum=1.0,
        )
        # Bar 1 builds sweep-detector history (no signal possible yet).
        assert v.validate_entry(bar_index=1, high=100.0, low=99.0, close=99.5, **common) is None
        # Bar 2 sweeps a full ATR below the prior low -> short signal.
        return v.validate_entry(bar_index=2, high=99.0, low=98.0, close=98.5, **common)

    def test_risk_reward_is_tp1_over_sl_distance(self):
        signal = self._emit_signal()
        assert signal is not None
        # TP1 is placed at 1.5x the SL distance by construction.
        assert signal.risk_reward_ratio == pytest.approx(1.5)

    def test_risk_reward_consistent_with_own_levels(self):
        signal = self._emit_signal()
        assert signal is not None
        reward = abs(signal.take_profit_1 - signal.entry_price)
        risk = abs(signal.entry_price - signal.stop_loss)
        assert signal.risk_reward_ratio == pytest.approx(reward / risk)


# ============================================================
# B27 – VolatilityFilter: True Range must use the previous close
# ============================================================

class TestVolatilityFilterPrevClose:
    def test_gap_up_widens_true_range(self):
        f = VolatilityFilter(atr_period=14, sma_period=20)
        f.calculate_atr(high=101.0, low=99.0, close=100.0)  # first bar: TR = 2.0
        # Gap up: TR = max(1.0, |111-100|, |110-100|) = 11.0 -> avg = 6.5.
        # With the old bug (prev_close = current close) TR was 1.0 -> avg 1.5.
        result = f.calculate_atr(high=111.0, low=110.0, close=110.5)
        assert result == pytest.approx((2.0 + 11.0) / 2)

    def test_atr_history_stays_bounded(self):
        f = VolatilityFilter(atr_period=14, sma_period=20)
        for i in range(5_000):
            base = 100.0 + (i % 7) * 0.1
            f.calculate_atr(high=base + 1.0, low=base - 1.0, close=base)
        assert len(f.atr_history) <= max(f.sma_period, f.atr_period)
        # The ratio path still works on the capped window.
        ratio = f.get_atr_ratio()
        assert ratio is not None and ratio > 0

    def test_reset_clears_prev_close(self):
        f = VolatilityFilter()
        f.calculate_atr(high=101.0, low=99.0, close=100.0)
        f.reset()
        assert f.prev_close is None
        assert f.atr_history == []


# ============================================================
# B28 – StrongImpulseDetector: stale impulses must be pruned
# ============================================================

def _impulse(bar_index: int) -> ImpulseSignal:
    return ImpulseSignal(
        bar_index=bar_index,
        phase=ImpulsePhase.IGNITION,
        direction="long",
        ignition_bar=bar_index,
        propulsion_strength=7.0,
        entry_price=100.0,
        invalidation_level=99.0,
        target_1=101.0,
        target_2=102.0,
        target_3=103.0,
        confirmation_bars=0,
    )


class TestActiveImpulsesPruned:
    def test_detect_prunes_stale_entries(self):
        det = StrongImpulseDetector()
        det.active_impulses[0] = _impulse(0)
        det.active_impulses[90] = _impulse(90)
        # A quiet candle at bar 100: no new impulse, but pruning must run.
        det.detect_impulse(
            bar_index=100, open=100.0, high=100.1, low=99.9, close=100.0,
            atr=1.0, recent_momentum=0.0, volume_ratio=1.0,
        )
        assert 0 not in det.active_impulses        # age 100 > MAX_IMPULSE_AGE_BARS
        assert 90 in det.active_impulses            # age 10, still active

    def test_update_phase_prunes_stale_entries(self):
        det = StrongImpulseDetector()
        det.active_impulses[0] = _impulse(0)
        updated = det.update_phase(bar_index=200, high=101.0, low=99.0, close=100.0)
        assert updated == []
        assert det.active_impulses == {}


# ============================================================
# B29 – EnsembleSignalRouter: signal history must stay bounded
# ============================================================

class TestSignalHistoryBounded:
    def test_record_signal_caps_history(self):
        router = EnsembleSignalRouter()
        for _ in range(router.MAX_SIGNAL_HISTORY + 100):
            router._record_signal(object())
        assert len(router.signal_history) == router.MAX_SIGNAL_HISTORY
        assert router.get_signal_history(limit=20) == router.signal_history[-20:]


# ============================================================
# B30 – SmcSignalDetector: dead ATR helper removed, history bounded
# ============================================================

class TestSmcSignalDetectorCleanup:
    def test_dead_atr_helper_removed(self):
        assert not hasattr(SmcSignalDetector, "_calculate_atr")
        assert not hasattr(SmcSignalDetector(), "atr_history")

    def test_candle_history_stays_bounded(self):
        det = SmcSignalDetector()
        for i in range(1_000):
            det.process_candle(
                Candle(bar_index=i, open=100.0, high=101.0, low=99.0, close=100.5, volume=1000)
            )
        assert len(det.history) <= 10
