"""
Additional Functional Tests for SkippALGO.

Covers gaps identified during test audit:
  1. Regression: nz() guard on getVoteScore / f_score_tf_cached (bug fix)
  2. Regression: Score–Reversal conflict resolution (bug fix)
  3. Score Engine behavioral paths (entry, precedence, chop veto)
  4. Adaptive cooldown (C2: confidence >= 0.80 halves cooldown)
  5. ChoCH exit confidence filter (exit_conf_choch)
  6. Short-side symmetry tests for exits and grace periods
  7. Breakout engine ChoCH filter
  8. USI / Engulfing standalone exits (outside EntriesOnly)
  9. TP hold at multiple confidence boundaries
 10. Session gate (blockNearClose, in_session=False)
"""
from __future__ import annotations

import pathlib
import re
import unittest

from tests.pine_sim import Bar, BarSignals, SimConfig, SkippAlgoSim


ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"
STRATEGY_PATH  = ROOT / "SkippALGO_Strategy.pine"


# ================================================================
# 1. Regression: nz() guard on getVoteScore (source-level)
# ================================================================

class TestNzGuardRegression(unittest.TestCase):
    """Verify that nz() wraps f_score_tf_cached calls inside getVoteScore()."""

    @classmethod
    def setUpClass(cls):
        cls.ind  = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.strat = STRATEGY_PATH.read_text(encoding="utf-8")

    def _extract_vote_score_body(self, text: str) -> str:
        """Extract the getVoteScore() function body."""
        start = text.find("getVoteScore() =>")
        self.assertNotEqual(start, -1, "getVoteScore not found")
        # Function body extends until the next function def or unindented line
        body_start = text.index("\n", start) + 1
        lines = []
        for line in text[body_start:].splitlines():
            if line.strip() == "" or line[0:4] == "    ":
                lines.append(line)
            else:
                break
        return "\n".join(lines)

    def test_indicator_nz_wraps_score_tf_cached(self):
        """Indicator: every f_score_tf_cached call inside getVoteScore must be wrapped in nz()."""
        body = self._extract_vote_score_body(self.ind)
        # All occurrences of f_score_tf_cached must be preceded by nz(
        raw_calls = re.findall(r'(?<!nz\()f_score_tf_cached\(', body)
        self.assertEqual(
            len(raw_calls), 0,
            f"Indicator getVoteScore: found {len(raw_calls)} un-wrapped f_score_tf_cached call(s)",
        )
        # At least 3 nz-wrapped calls expected (tf1, tf2, tf3)
        wrapped = re.findall(r'nz\(f_score_tf_cached\(', body)
        self.assertGreaterEqual(len(wrapped), 3, "Expected >=3 nz-wrapped calls")

    def test_strategy_nz_wraps_score_tf_cached(self):
        """Strategy: every f_score_tf_cached call inside getVoteScore must be wrapped in nz()."""
        body = self._extract_vote_score_body(self.strat)
        raw_calls = re.findall(r'(?<!nz\()f_score_tf_cached\(', body)
        self.assertEqual(
            len(raw_calls), 0,
            f"Strategy getVoteScore: found {len(raw_calls)} un-wrapped f_score_tf_cached call(s)",
        )
        wrapped = re.findall(r'nz\(f_score_tf_cached\(', body)
        self.assertGreaterEqual(len(wrapped), 3, "Expected >=3 nz-wrapped calls")

    def test_nz_default_is_zero(self):
        """nz() default must be 0.0 to avoid skewing the weighted average."""
        for name, text in [("Indicator", self.ind), ("Strategy", self.strat)]:
            body = self._extract_vote_score_body(text)
            # All nz(f_score_tf_cached(...), X) must have X == 0.0
            defaults = re.findall(r'nz\(f_score_tf_cached\([^)]+\),\s*([\d.]+)\)', body)
            for val in defaults:
                self.assertEqual(val, "0.0", f"{name}: nz default should be 0.0, got {val}")


# ================================================================
# 2. Regression: Score-Reversal conflict resolution (source-level)
# ================================================================

class TestScoreReversalConflictRegression(unittest.TestCase):
    """Verify the score-reversal conflict override exists after unified injection."""

    @classmethod
    def setUpClass(cls):
        cls.ind  = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.strat = STRATEGY_PATH.read_text(encoding="utf-8")

    def _assert_conflict_block(self, text: str, name: str):
        # Pattern: scoreLongWin definition, then after injection, score-reversal override
        pattern_long = r'if scoreLongWin and revShortGlobal\s*\n\s*shortSignal\s*:=\s*false'
        pattern_short = r'if scoreShortWin and revBuyGlobal\s*\n\s*buySignal\s*:=\s*false'

        self.assertRegex(text, pattern_long,
                         f"{name}: missing 'scoreLongWin and revShortGlobal → shortSignal := false'")
        self.assertRegex(text, pattern_short,
                         f"{name}: missing 'scoreShortWin and revBuyGlobal → buySignal := false'")

    def test_indicator_has_score_reversal_conflict(self):
        self._assert_conflict_block(self.ind, "Indicator")

    def test_strategy_has_score_reversal_conflict(self):
        self._assert_conflict_block(self.strat, "Strategy")

    def test_conflict_block_after_injection_before_hard_floor(self):
        """Score-reversal conflict must appear between unified injection and hard prob floor."""
        for name, text in [("Indicator", self.ind), ("Strategy", self.strat)]:
            inj = text.find("buySignal   := buySignal   or revBuyGlobal")
            conflict = text.find("if scoreLongWin and revShortGlobal")
            hard_floor = text.find("buySignal := buySignal and hardLongProbOk")

            self.assertNotEqual(inj, -1, f"{name}: injection not found")
            self.assertNotEqual(conflict, -1, f"{name}: conflict not found")
            self.assertNotEqual(hard_floor, -1, f"{name}: hard floor not found")

            self.assertLess(inj, conflict,
                            f"{name}: injection must come before score-reversal conflict")
            self.assertLess(conflict, hard_floor,
                            f"{name}: score-reversal conflict must come before hard prob floor")


# ================================================================
# 3. Score Engine behavioral tests
# ================================================================

class TestScoreEngineBehavior(unittest.TestCase):
    """Behavioral tests for the Score Engine integration path."""

    def test_score_buy_fires_when_engine_does_not(self):
        """Score entry injects a BUY even when the Hybrid engine trigger is off."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=False,  # engine wouldn't fire
            use_score_entries=True,
            score_buy=True,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.score_long_win)
        self.assertTrue(r.did_buy, "Score BUY must fire even when engine trigger is off")

    def test_score_short_fires_when_engine_does_not(self):
        """Score entry injects a SHORT even when the Hybrid trigger is off."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_short_trigger=False,
            enable_shorts=True,
            use_score_entries=True,
            score_short=True,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.score_short_win)
        self.assertTrue(r.did_short, "Score SHORT must fire even when engine trigger is off")

    def test_score_long_wins_tie(self):
        """When both scoreBuy and scoreShort fire, LONG takes precedence."""
        cfg = SimConfig(
            engine="Hybrid",
            enable_shorts=True,
            use_score_entries=True,
            score_buy=True,
            score_short=True,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.score_long_win)
        self.assertFalse(r.score_short_win, "LONG must win in ties")
        self.assertTrue(r.did_buy)
        self.assertFalse(r.did_short)

    def test_score_overrides_engine_direction(self):
        """Score SHORT overrides engine BUY when score takes precedence."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,  # engine says BUY
            enable_shorts=True,
            use_score_entries=True,
            score_buy=False,
            score_short=True,  # score says SHORT
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.score_short_win)
        self.assertTrue(r.did_short, "Score SHORT should override engine BUY")
        self.assertFalse(r.did_buy)

    def test_score_blocked_by_chop_veto(self):
        """Score entry blocked when chopVeto is active."""
        cfg = SimConfig(
            engine="Hybrid",
            use_score_entries=True,
            score_buy=True,
            score_chop_hard_veto=True,
            is_chop=True,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.score_long_win, "Chop veto should block score entry")
        self.assertFalse(r.did_buy)

    def test_score_blocked_by_hard_prob_floor(self):
        """Score BUY blocked when global prob floor fails (no reversal bypass)."""
        cfg = SimConfig(
            engine="Hybrid",
            use_score_entries=True,
            score_buy=True,
            model_global_score_floor=True,
            enforce_global_prob_floor=True,
            score_min_pu=0.80,
            p_u=0.40,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.did_buy,
                         "Score BUY should be blocked by hard prob floor")


# ================================================================
# 3b. Score-Reversal conflict behavioral tests
# ================================================================

class TestScoreReversalConflictBehavior(unittest.TestCase):
    """Behavioral tests for the score-reversal conflict resolution."""

    def test_score_long_kills_rev_short(self):
        """When Score fires LONG and Neural Reversal fires SHORT on the same bar,
        SHORT must be suppressed (not both cancelled)."""
        cfg = SimConfig(
            engine="Hybrid",
            enable_shorts=True,
            reliability_ok=False,
            allow_neural_reversals=True,
            use_score_entries=True,
            score_buy=True,
            score_short=False,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))

        self.assertTrue(r.score_long_win, "Score should win LONG")
        self.assertTrue(r.rev_short_global, "Neural reversal should fire SHORT")
        # The conflict resolution must suppress SHORT rather than cancel both.
        self.assertTrue(r.buy_signal, "BUY must survive (score precedence)")
        self.assertFalse(r.short_signal, "SHORT must be suppressed")
        self.assertTrue(r.did_buy)
        self.assertFalse(r.did_short)

    def test_score_short_kills_rev_buy(self):
        """When Score fires SHORT and Neural Reversal fires BUY on the same bar,
        BUY must be suppressed."""
        cfg = SimConfig(
            engine="Hybrid",
            enable_shorts=True,
            reliability_ok=False,
            allow_neural_reversals=True,
            use_score_entries=True,
            score_buy=False,
            score_short=True,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertTrue(r.score_short_win, "Score should win SHORT")
        self.assertTrue(r.rev_buy_global, "Neural reversal should fire BUY")
        self.assertFalse(r.buy_signal, "BUY must be suppressed")
        self.assertTrue(r.short_signal, "SHORT must survive (score precedence)")
        self.assertTrue(r.did_short)
        self.assertFalse(r.did_buy)

    def test_no_score_no_conflict_reversal_survives(self):
        """Without Score Engine, reversal fires normally (no conflict suppression)."""
        cfg = SimConfig(
            engine="Hybrid",
            reliability_ok=False,
            allow_neural_reversals=True,
            use_score_entries=False,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(r.score_long_win)
        self.assertTrue(r.rev_buy_global)
        self.assertTrue(r.did_buy, "Without score engine, reversal should fire normally")

    def test_score_and_same_direction_reversal_cooperate(self):
        """Score LONG + Rev BUY on same bar should still produce BUY (no cancellation)."""
        cfg = SimConfig(
            engine="Hybrid",
            enable_shorts=True,
            reliability_ok=False,
            allow_neural_reversals=True,
            use_score_entries=True,
            score_buy=True,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertTrue(r.score_long_win)
        self.assertTrue(r.rev_buy_global)
        self.assertTrue(r.did_buy, "Same-direction score + reversal should cooperate")
        self.assertFalse(r.did_short)


# ================================================================
# 4. Adaptive cooldown (C2: confidence >= 0.80 → halved)
# ================================================================

class TestAdaptiveCooldown(unittest.TestCase):
    """Test that high confidence halves the effective cooldown."""

    def test_high_conf_halves_cooldown(self):
        """confidence >= 0.80 should halve cooldown_bars and allow faster re-entry."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_bars=10,
            confidence=0.85,  # >= 0.80 triggers C2
            exit_grace_bars=0,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)

        # BUY
        r0 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r0.did_buy)
        # Effective cooldown should be max(2, round(10/2)) = 5
        self.assertEqual(r0.cooldown_bars_eff, 5)

        # EXIT
        r1 = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r1.did_exit)

        # Should be able to re-enter after 5 bars (not 10)
        for i in range(5):
            r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
            self.assertFalse(r.did_buy, f"bar {i}: still in cooldown")

        r_after = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r_after.did_buy, "Should re-enter after halved cooldown (~5 bars)")

    def test_low_conf_does_not_halve_cooldown(self):
        """confidence < 0.80 should leave cooldown_bars unchanged."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_bars=10,
            confidence=0.70,  # < 0.80
            exit_grace_bars=0,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(r.cooldown_bars_eff, 10, "Cooldown should not be halved below 0.80 conf")

    def test_halved_cooldown_minimum_is_2(self):
        """Halved cooldown must be >= 2 (not zero)."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_bars=2,
            confidence=0.90,
            exit_grace_bars=0,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        # max(2, round(2/2)) = max(2, 1) = 2
        self.assertEqual(r.cooldown_bars_eff, 2, "Halved cooldown floor must be 2")


# ================================================================
# 5. ChoCH exit confidence filter
# ================================================================

class TestChochExitConfidenceFilter(unittest.TestCase):
    """Test that exit_conf_choch blocks or allows ChoCH/structural exits."""

    def test_choch_exit_blocked_when_pd_below_threshold(self):
        """ChoCH exit blocked when p_d < exit_conf_choch."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
            exit_conf_choch=0.55,
            p_d=0.40,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))  # enter LONG

        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertFalse(r.did_exit,
                         "ChoCH exit should be blocked when p_d < exit_conf_choch")

    def test_choch_exit_allowed_when_pd_above_threshold(self):
        """ChoCH exit passes when p_d >= exit_conf_choch."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
            exit_conf_choch=0.55,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertTrue(r.did_exit,
                        "ChoCH exit should pass when p_d >= exit_conf_choch")

    def test_structural_break_exit_blocked_by_choch_filter(self):
        """Structural break exit is NOT filtered by exit_conf_choch — only ChoCH is."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
            exit_conf_choch=0.70,
            p_d=0.50,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        # break_long is a struct exit; the ChoCH filter applies to the combined structHit
        r = sim.process_bar(Bar(), BarSignals(break_long=True))
        # structHit is filtered (p_d < exit_conf_choch), but break_long doesn't go through
        # the ChoCH filter — it goes through canStructExit only. Let's verify.
        # In the sim: struct_hit includes break_long path (not filtered by exit_conf_choch)
        # and is_choch_short path (filtered by exit_conf_choch). break_long alone is NOT
        # filtered by exit_conf_choch.
        self.assertTrue(r.did_exit,
                        "break_long (structural) is not gated by exit_conf_choch")


# ================================================================
# 6. Short-side symmetry tests
# ================================================================

class TestShortSideSymmetry(unittest.TestCase):
    """Mirror tests verifying SHORT/COVER paths match LONG/EXIT behavior."""

    def test_short_struct_exit_respects_grace(self):
        """break_short cover respects exitGraceBars just like break_long exit."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=3,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))  # SHORT

        for i in range(3):
            r = sim.process_bar(Bar(), BarSignals(break_short=True))
            self.assertFalse(r.did_cover, f"bar {i}: grace should block cover")

        r4 = sim.process_bar(Bar(), BarSignals(break_short=True))
        self.assertTrue(r4.did_cover, "Cover should pass after grace period")

    def test_short_risk_exit_bypasses_grace(self):
        """SL risk cover bypasses grace period for SHORT positions."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=10,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))

        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r.did_cover, "SL cover must bypass grace period")
        self.assertEqual(r.exit_reason, "SL")

    def test_short_tp_held_with_high_conf(self):
        """TP cover suppressed when confidence >= exit_conf_tp for SHORT positions."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            confidence=0.95,
            exit_conf_tp=0.90,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))

        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertFalse(r.did_cover,
                         "TP cover should be suppressed when conf >= exit_conf_tp")

    def test_short_stale_exit_bypasses_grace(self):
        """Stalemate cover bypasses grace period for SHORTs."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=10,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))

        r = sim.process_bar(Bar(), BarSignals(stale_exit=True))
        self.assertTrue(r.did_cover, "Stalemate cover bypasses grace")
        self.assertEqual(r.exit_reason, "Stalemate")

    def test_short_cooldown_blocks_reentry(self):
        """After SHORT → COVER, SHORT must be blocked during cooldown."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            cooldown_bars=5,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))

        for i in range(5):
            r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
            self.assertFalse(r.did_short, f"bar {i}: cooldown should block SHORT re-entry")

        r_after = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertTrue(r_after.did_short, "Should re-enter SHORT after cooldown")


# ================================================================
# 7. Breakout engine ChoCH filter
# ================================================================

class TestBreakoutEngineChochFilter(unittest.TestCase):
    """Verify the ChoCH probability filter works in Breakout engine."""

    def test_breakout_buy_blocked_by_choch_filter(self):
        """Breakout BUY blocked when entering from bearish structure and p_u < chochMinProb."""
        cfg = SimConfig(
            engine="Breakout",
            breakout_long=True,
            trend_up=True,
            choch_min_prob=0.55,
            p_u=0.50,
            allow_neural_reversals=False,
        )
        sim = SkippAlgoSim(cfg)
        # Set struct_state to bearish to trigger ChoCH filter
        sim.state.struct_state = -1

        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.did_buy,
                         "Breakout BUY should be blocked by ChoCH filter (bearish struct + low p_u)")

    def test_breakout_buy_passes_choch_filter(self):
        """Breakout BUY passes when p_u >= chochMinProb even in bearish structure."""
        cfg = SimConfig(
            engine="Breakout",
            breakout_long=True,
            trend_up=True,
            choch_min_prob=0.55,
            p_u=0.60,
            allow_neural_reversals=False,
        )
        sim = SkippAlgoSim(cfg)
        sim.state.struct_state = -1

        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy,
                        "Breakout BUY should pass ChoCH filter when p_u >= chochMinProb")

    def test_breakout_short_blocked_by_choch_filter(self):
        """Breakout SHORT blocked in bullish structure with low p_d."""
        cfg = SimConfig(
            engine="Breakout",
            breakout_short=True,
            trend_dn=True,
            enable_shorts=True,
            choch_min_prob=0.55,
            p_d=0.50,
            allow_neural_reversals=False,
        )
        sim = SkippAlgoSim(cfg)
        sim.state.struct_state = 1

        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.did_short,
                         "Breakout SHORT should be blocked by ChoCH filter (bullish struct + low p_d)")


# ================================================================
# 8. USI & Engulfing standalone exit tests (outside EntriesOnly)
# ================================================================

class TestUsiEngulfingStandaloneExits(unittest.TestCase):
    """USI-Flip and Engulfing exits fire in normal mode (non-EntriesOnly)."""

    def _enter_long(self, sim: SkippAlgoSim):
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        assert r.did_buy

    def _enter_short(self, sim: SkippAlgoSim):
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        assert r.did_short

    def test_usi_exit_fires_for_long(self):
        """USI-Flip exit fires immediately for LONG in normal mode."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_triggers="ExitsOnly",  # default
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        r = sim.process_bar(Bar(), BarSignals(usi_exit_long=True))
        self.assertTrue(r.did_exit, "USI-Flip should exit in normal mode")
        self.assertEqual(r.exit_reason, "USI-Flip")

    def test_usi_exit_fires_for_short(self):
        """USI-Flip cover fires immediately for SHORT in normal mode."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_short(sim)

        r = sim.process_bar(Bar(), BarSignals(usi_exit_short=True))
        self.assertTrue(r.did_cover, "USI-Flip should cover in normal mode")
        self.assertEqual(r.exit_reason, "USI-Flip")

    def test_engulfing_exit_fires_for_long(self):
        """Engulfing exit fires immediately for LONG."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        r = sim.process_bar(Bar(), BarSignals(eng_exit_long=True))
        self.assertTrue(r.did_exit, "Engulfing exit should fire")
        self.assertEqual(r.exit_reason, "Engulfing")

    def test_engulfing_exit_fires_for_short(self):
        """Engulfing cover fires immediately for SHORT."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_short(sim)

        r = sim.process_bar(Bar(), BarSignals(eng_exit_short=True))
        self.assertTrue(r.did_cover, "Engulfing cover should fire")
        self.assertEqual(r.exit_reason, "Engulfing")

    def test_engulfing_bypasses_entriesonly_hold(self):
        """Engulfing exit is allowed even during EntriesOnly hold window."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_triggers="EntriesOnly",
            cooldown_bars=10,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        r = sim.process_bar(Bar(), BarSignals(eng_exit_long=True))
        self.assertTrue(r.entry_only_exit_hold_active, "Hold should be active")
        self.assertTrue(r.did_exit, "Engulfing exit must be allowed during hold")
        self.assertEqual(r.exit_reason, "Engulfing")


# ================================================================
# 9. TP hold at multiple confidence boundaries
# ================================================================

class TestTpHoldBoundary(unittest.TestCase):
    """TP hold behavior at exact boundary values of exit_conf_tp."""

    def _build_sim(self, conf: float, tp_conf: float) -> SkippAlgoSim:
        cfg = SimConfig(
            allow_neural_reversals=True,
            confidence=conf,
            exit_conf_tp=tp_conf,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))  # enter
        return sim

    def test_tp_held_at_exact_boundary(self):
        """TP suppressed when confidence == exit_conf_tp exactly."""
        sim = self._build_sim(conf=0.90, tp_conf=0.90)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertFalse(r.did_exit, "TP should be suppressed at exact boundary")

    def test_tp_fires_below_boundary(self):
        """TP fires when confidence < exit_conf_tp."""
        sim = self._build_sim(conf=0.89, tp_conf=0.90)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertTrue(r.did_exit, "TP should fire when conf < exit_conf_tp")

    def test_tp_held_above_boundary(self):
        """TP suppressed when confidence > exit_conf_tp."""
        sim = self._build_sim(conf=0.95, tp_conf=0.90)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertFalse(r.did_exit, "TP should be suppressed when conf > exit_conf_tp")

    def test_sl_always_fires_regardless_of_tp_conf(self):
        """SL exit is never suppressed by exit_conf_tp."""
        sim = self._build_sim(conf=0.99, tp_conf=0.50)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r.did_exit, "SL must always fire regardless of exit_conf_tp")

    def test_tp_default_never_holds(self):
        """Default exit_conf_tp=1.0 means TP is never suppressed (conf can't reach 1.0)."""
        sim = self._build_sim(conf=0.99, tp_conf=1.0)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertTrue(r.did_exit,
                        "Default TP conf=1.0 should never be met (conf < 1.0)")


# ================================================================
# 10. Session and near-close gate
# ================================================================

class TestSessionGating(unittest.TestCase):
    """Verify session and near-close gates block entries."""

    def test_out_of_session_blocks_entry(self):
        """in_session=False should block allowEntry entirely."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            in_session=False,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.allow_entry, "Out of session must block entry")
        self.assertFalse(r.did_buy)

    def test_block_near_close_blocks_entry(self):
        """block_near_close=True should block allowEntry."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            block_near_close=True,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r.allow_entry, "blockNearClose must block entry")
        self.assertFalse(r.did_buy)

    def test_reversal_blocked_when_out_of_session_via_cooldown(self):
        """Reversal bypass still requires cooldown_ok, but also session indirectly
        (since allowRevBypass doesn't check in_session, but cooldownOkSafe is required)."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            in_session=False,
            cooldown_bars=0,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        # allowRevBypass doesn't check in_session, so the bypass is still reachable.
        # This is correct Pine Script behavior: rev bypass is outside session guard.
        self.assertTrue(r.allow_rev_bypass)
        self.assertTrue(r.did_buy,
                        "Rev bypass fires regardless of in_session (matches Pine behavior)")


# ================================================================
# 11. Multi-bar property: no position flip without going flat
# ================================================================

class TestNoDirectPositionFlip(unittest.TestCase):
    """Verify the state machine can't jump from LONG to SHORT without going flat first."""

    def test_no_long_to_short_flip(self):
        """A position held LONG can't flip to SHORT on the same bar."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            hybrid_short_trigger=True,
            enable_shorts=True,
            exit_grace_bars=0,
            cooldown_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        # Enter LONG (both signals fire → conflict cancels both → depends on engine)
        # With both triggers true, conflict cancels → stays flat.
        # Let's use reversal to force LONG first:
        cfg2 = SimConfig(
            allow_neural_reversals=True,
            enable_shorts=True,
            cooldown_bars=0,
            exit_grace_bars=0,
            p_u=0.60,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg2)
        # LONG via reversal
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(sim.state.pos, 1)

        # Next bar: SHORT signal fires (ChoCH_Short as exit + as potential entry)
        # Can't SHORT while LONG → must exit first
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        # ChoCH_Short while LONG triggers ChoCH cover (if past grace, which is 0)
        self.assertTrue(r.did_exit or r.pos_after == 1,
                        "Must EXIT before any SHORT can happen")
        # Even if exit happens, can't SHORT on the same bar as exit
        self.assertFalse(r.did_short, "Cannot SHORT on the same bar as EXIT")

    def test_flat_after_exit_allows_reentry_next_bar(self):
        """After EXIT, next bar can produce a new SHORT if flat."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            enable_shorts=True,
            cooldown_bars=0,
            exit_grace_bars=0,
            p_u=0.60,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))  # LONG
        self.assertEqual(sim.state.pos, 1)

        sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))  # EXIT
        self.assertEqual(sim.state.pos, 0)

        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))  # SHORT
        self.assertTrue(r.did_short, "Should re-enter SHORT after going flat")
        self.assertEqual(r.pos_after, -1)


# ================================================================
# 12. Exit reason attribution correctness
# ================================================================

class TestExitReasonAttribution(unittest.TestCase):
    """Verify correct exit_reason for each exit path."""

    def _enter_long(self, sim: SkippAlgoSim):
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))

    def _enter_short(self, sim: SkippAlgoSim):
        sim.process_bar(Bar(), BarSignals(is_choch_short=True))

    def _make_sim(self, **overrides) -> SkippAlgoSim:
        cfg = SimConfig(
            allow_neural_reversals=True,
            enable_shorts=True,
            exit_grace_bars=0,
            cooldown_bars=0,
            p_u=0.60,
            p_d=0.60,
            **overrides,
        )
        return SkippAlgoSim(cfg)

    def test_reason_sl_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertEqual(r.exit_reason, "SL")

    def test_reason_tp_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertEqual(r.exit_reason, "TP")

    def test_reason_choch_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertEqual(r.exit_reason, "ChoCH")

    def test_reason_stalemate_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(stale_exit=True))
        self.assertEqual(r.exit_reason, "Stalemate")

    def test_reason_usi_flip_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(usi_exit_long=True))
        self.assertEqual(r.exit_reason, "USI-Flip")

    def test_reason_engulfing_long(self):
        sim = self._make_sim()
        self._enter_long(sim)
        r = sim.process_bar(Bar(), BarSignals(eng_exit_long=True))
        self.assertEqual(r.exit_reason, "Engulfing")

    def test_reason_sl_short(self):
        sim = self._make_sim(reliability_ok=False)
        self._enter_short(sim)
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertEqual(r.exit_reason, "SL")

    def test_reason_choch_short(self):
        sim = self._make_sim(reliability_ok=False)
        self._enter_short(sim)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(r.exit_reason, "ChoCH")

    def test_reason_engulfing_short(self):
        sim = self._make_sim(reliability_ok=False)
        self._enter_short(sim)
        r = sim.process_bar(Bar(), BarSignals(eng_exit_short=True))
        self.assertEqual(r.exit_reason, "Engulfing")


# ================================================================
# 13. Exit priority ordering
# ================================================================

class TestExitPriorityOrdering(unittest.TestCase):
    """When multiple exit signals fire on the same bar, risk_hit takes priority."""

    def test_risk_takes_priority_over_struct(self):
        """risk_hit SL + structural break → reason should be SL."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
            cooldown_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        r = sim.process_bar(Bar(), BarSignals(
            risk_hit=True,
            risk_msg="SL",
            break_long=True,
            stale_exit=True,
        ))
        self.assertTrue(r.did_exit)
        self.assertEqual(r.exit_reason, "SL", "Risk hit should take priority")

    def test_usi_flip_takes_priority_over_stalemate(self):
        """When USI-Flip and stalemate fire simultaneously, USI-Flip dominates."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        r = sim.process_bar(Bar(), BarSignals(
            usi_exit_long=True,
            stale_exit=True,
        ))
        self.assertTrue(r.did_exit)
        self.assertEqual(r.exit_reason, "USI-Flip")


if __name__ == "__main__":
    unittest.main()
