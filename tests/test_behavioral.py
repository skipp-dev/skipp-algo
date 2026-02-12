"""
Behavioral tests for SkippALGO using the Pine Script simulator.

These tests go beyond regex/structure checks — they verify actual
control-flow behavior by running scenario-based simulations through
a Python transpilation of the core Pine Script logic.

Test categories:
  1. Entry guard reachability (reversal bypass)
  2. State machine invariants (no EXIT without BUY)
  3. Conflict resolution (simultaneous buy+short)
  4. Exit grace periods (ChoCH gating)
  5. Multi-bar lifecycle scenarios
  6. All four engine types
  7. Edge cases (cooldown, double-direction ChoCH, etc.)
"""
import unittest
from tests.pine_sim import SkippAlgoSim, SimConfig, SimState, Bar, BarSignals, BarResult


def make_bars(n: int, **overrides) -> list[Bar]:
    """Create n identical bars with optional overrides."""
    return [Bar(**overrides) for _ in range(n)]


def make_signals(n: int, **overrides) -> list[BarSignals]:
    """Create n identical signal sets with optional overrides."""
    return [BarSignals(**overrides) for _ in range(n)]


def idle_bar() -> tuple[Bar, BarSignals]:
    """A bar with no signals — advances time."""
    return Bar(), BarSignals()


class TestEntryGuardReachability(unittest.TestCase):
    """
    Test that the entry evaluation block is reachable under
    the correct conditions, especially the reversal bypass path.
    """

    def test_reversal_bypass_when_allowentry_false(self):
        """
        KEY BEHAVIORAL TEST:
        allowEntry=false, allowRescue=false,
        allowNeuralReversals=true, cooldownOkSafe=true,
        isChoCH_Long=true
        => entry block reached, buySignal=true (via revBuyGlobal)
        """
        cfg = SimConfig(
            reliability_ok=False,  # makes allowEntry false
            allow_neural_reversals=True,
            p_u=0.60,
            vol_ok=True,
            macro_gate_long=True,
            dd_ok=True,
        )
        sim = SkippAlgoSim(cfg)
        bar = Bar()
        sigs = BarSignals(is_choch_long=True)

        result = sim.process_bar(bar, sigs)

        self.assertFalse(result.allow_entry, "allowEntry should be false")
        self.assertFalse(result.allow_rescue, "allowRescue should be false")
        self.assertTrue(result.allow_rev_bypass, "allowRevBypass should be true")
        self.assertTrue(result.entry_block_reached, "entry block must be reachable")
        self.assertTrue(result.rev_buy_global, "revBuyGlobal should fire")
        self.assertTrue(result.buy_signal, "buySignal should be true")
        self.assertTrue(result.did_buy, "should execute BUY")
        self.assertEqual(result.pos_after, 1, "pos should be LONG")

    def test_reversal_bypass_short_when_allowentry_false(self):
        """Same test for SHORT direction."""
        cfg = SimConfig(
            evidence_ok=False,  # makes allowEntry false
            allow_neural_reversals=True,
            p_d=0.60,
            vol_ok=True,
            macro_gate_short=True,
            dd_ok=True,
            enable_shorts=True,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals(is_choch_short=True))

        self.assertFalse(result.allow_entry)
        self.assertTrue(result.allow_rev_bypass)
        self.assertTrue(result.rev_short_global)
        self.assertTrue(result.short_signal)
        self.assertTrue(result.did_short)
        self.assertEqual(result.pos_after, -1)

    def test_reversal_blocked_when_neural_reversals_disabled(self):
        """allowNeuralReversals=false => no bypass, block stays unreachable."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=False,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(result.allow_rev_bypass)
        self.assertFalse(result.entry_block_reached)
        self.assertFalse(result.did_buy)

    def test_reversal_blocked_when_no_choch(self):
        """No ChoCH event => no bypass, even if other conditions pass."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals())  # no ChoCH

        self.assertFalse(result.allow_rev_bypass)
        self.assertFalse(result.entry_block_reached)

    def test_reversal_blocked_during_cooldown(self):
        """Reversal must respect cooldown."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            cooldown_bars=5,
        )
        sim = SkippAlgoSim(cfg)

        # Force a recent signal by setting last_signal_bar
        sim.state.last_signal_bar = 0
        sim.state.bar_index = 3  # only 3 bars since signal

        result = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(result.allow_rev_bypass, "cooldown should block bypass")
        self.assertFalse(result.entry_block_reached)

    def test_standard_entry_still_works(self):
        """When allowEntry is true, standard engine triggers work."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals())

        self.assertTrue(result.allow_entry)
        self.assertTrue(result.entry_block_reached)
        self.assertTrue(result.did_buy)

    def test_rescue_path_works(self):
        """Impulse candle bypasses allowEntry."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=False,
            engine="Hybrid",
            hybrid_long_trigger=True,
        )
        sim = SkippAlgoSim(cfg)
        bar = Bar(open=99.0, close=102.0)  # bullish impulse
        sigs = BarSignals(is_impulse=True)

        result = sim.process_bar(bar, sigs)

        self.assertFalse(result.allow_entry)
        self.assertTrue(result.allow_rescue)
        self.assertTrue(result.entry_block_reached)


class TestStateMachineInvariants(unittest.TestCase):
    """
    Test that the state machine never produces impossible transitions.
    """

    def test_no_exit_without_buy(self):
        """EXIT is impossible when pos==0 (flat)."""
        sim = SkippAlgoSim()
        # Send exit-triggering signals while flat
        result = sim.process_bar(Bar(), BarSignals(
            break_long=True,
            risk_hit=True,
            risk_msg="SL",
        ))
        self.assertFalse(result.did_exit, "cannot EXIT when flat")
        self.assertEqual(result.pos_after, 0)

    def test_no_cover_without_short(self):
        """COVER is impossible when pos==0."""
        sim = SkippAlgoSim()
        result = sim.process_bar(Bar(), BarSignals(
            break_short=True,
            risk_hit=True,
            risk_msg="SL",
        ))
        self.assertFalse(result.did_cover, "cannot COVER when flat")
        self.assertEqual(result.pos_after, 0)

    def test_no_buy_when_already_long(self):
        """Cannot BUY when already in a LONG position."""
        cfg = SimConfig(engine="Hybrid", hybrid_long_trigger=True)
        sim = SkippAlgoSim(cfg)

        # First bar: BUY
        r1 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r1.did_buy)

        # Advance past cooldown
        for _ in range(cfg.cooldown_bars + 1):
            sim.process_bar(*idle_bar())

        # Second entry attempt while already long
        r2 = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r2.did_buy, "cannot BUY when already LONG")
        self.assertEqual(r2.pos_after, 1)

    def test_buy_exit_buy_lifecycle(self):
        """Full BUY → EXIT → BUY lifecycle."""
        cfg = SimConfig(engine="Hybrid", hybrid_long_trigger=True, exit_grace_bars=2)
        sim = SkippAlgoSim(cfg)

        # Bar 0: BUY
        r0 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r0.did_buy)
        self.assertEqual(r0.pos_after, 1)

        # Bars 1-2: hold (advance past grace)
        for _ in range(2):
            sim.process_bar(*idle_bar())

        # Bar 3: EXIT via structure break
        r3 = sim.process_bar(Bar(), BarSignals(break_long=True))
        self.assertTrue(r3.did_exit)
        self.assertEqual(r3.pos_after, 0)

        # Advance past cooldown. Because hybrid_long_trigger stays True,
        # BUY fires automatically once cooldown expires.
        rebuy_found = False
        for _ in range(cfg.cooldown_bars + 2):
            r = sim.process_bar(Bar(), BarSignals())
            if r.did_buy:
                rebuy_found = True
                break
        self.assertTrue(rebuy_found, "should re-enter BUY after cooldown")
        self.assertEqual(sim.state.pos, 1)

    def test_pos_only_changes_on_signal(self):
        """pos stays constant without signals."""
        sim = SkippAlgoSim()
        for _ in range(20):
            r = sim.process_bar(*idle_bar())
            self.assertEqual(r.pos_after, 0, "pos should stay flat without signals")


class TestConflictResolution(unittest.TestCase):
    """Test that simultaneous buy+short signals cancel each other."""

    def test_buy_and_short_both_cancel(self):
        """If both buy and short trigger, neither fires."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            hybrid_short_trigger=True,
            enable_shorts=True,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals())

        self.assertTrue(result.raw_buy_signal, "raw buy should have fired")
        self.assertTrue(result.raw_short_signal, "raw short should have fired")
        self.assertFalse(result.buy_signal, "buy should be cancelled")
        self.assertFalse(result.short_signal, "short should be cancelled")
        self.assertFalse(result.did_buy)
        self.assertFalse(result.did_short)
        self.assertEqual(result.pos_after, 0, "should stay flat")

    def test_double_choch_same_bar_cancels(self):
        """Both isChoCH_Long and isChoCH_Short on same bar => cancel."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_u=0.60,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals(
            is_choch_long=True,
            is_choch_short=True,
        ))

        self.assertTrue(result.allow_rev_bypass)
        self.assertTrue(result.rev_buy_global)
        self.assertTrue(result.rev_short_global)
        self.assertTrue(result.raw_buy_signal)
        self.assertTrue(result.raw_short_signal)
        # Conflict resolution kills both
        self.assertFalse(result.buy_signal)
        self.assertFalse(result.short_signal)
        self.assertEqual(result.pos_after, 0)

    def test_only_buy_fires_when_short_disabled(self):
        """enableShorts=false => only buy fires, no conflict."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            hybrid_short_trigger=True,
            enable_shorts=False,
        )
        sim = SkippAlgoSim(cfg)
        result = sim.process_bar(Bar(), BarSignals())

        self.assertTrue(result.buy_signal)
        self.assertFalse(result.short_signal)
        self.assertTrue(result.did_buy)


class TestExitGracePeriods(unittest.TestCase):
    """Test that exit grace periods work correctly."""

    def _enter_long(self, sim: SkippAlgoSim):
        """Helper: enter a long position via REV-BUY."""
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        assert r.did_buy, "setup: should have entered long"

    def test_choch_exit_blocked_during_grace(self):
        """ChoCH exit is blocked within the 2-bar grace period."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=5,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        # Bar 1 after entry: barsSinceEntry=0 (just entered), ChoCH exit should fail
        r1 = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertFalse(r1.did_exit, "ChoCH exit blocked at barsSinceEntry=0")
        self.assertEqual(r1.pos_after, 1)

        # Bar 2: barsSinceEntry=1, still blocked (need >= 2)
        r2 = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertFalse(r2.did_exit, "ChoCH exit blocked at barsSinceEntry=1")

        # Bar 3: barsSinceEntry=2, ChoCH exit should pass
        r3 = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertTrue(r3.did_exit, "ChoCH exit should pass at barsSinceEntry=2")
        self.assertEqual(r3.pos_after, 0)

    def test_struct_exit_blocked_during_full_grace(self):
        """Structure break exit respects full exitGraceBars."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=5,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        # Bars 1-5: break_long should be blocked (barsSinceEntry < 5)
        for i in range(5):
            r = sim.process_bar(Bar(), BarSignals(break_long=True))
            self.assertFalse(r.did_exit, f"struct exit blocked at barsSinceEntry={i}")

        # Bar 6: barsSinceEntry=5, struct exit should pass
        r6 = sim.process_bar(Bar(), BarSignals(break_long=True))
        self.assertTrue(r6.did_exit, "struct exit should pass at barsSinceEntry=5")

    def test_risk_exit_ignores_grace(self):
        """SL/TP risk exits are NOT subject to grace period."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=5,
        )
        sim = SkippAlgoSim(cfg)
        self._enter_long(sim)

        # Immediate risk exit
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r.did_exit, "risk exit should bypass grace")
        self.assertEqual(r.exit_reason, "SL")


class TestAllEngines(unittest.TestCase):
    """Test that each engine type can produce entries."""

    def test_hybrid_engine_buy(self):
        cfg = SimConfig(engine="Hybrid", hybrid_long_trigger=True)
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_breakout_engine_buy(self):
        cfg = SimConfig(engine="Breakout", breakout_long=True, trend_up=True)
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_trend_pullback_engine_buy(self):
        cfg = SimConfig(engine="Trend+Pullback", trend_flip_up=True)
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_loose_engine_buy(self):
        cfg = SimConfig(engine="Loose", cross_close_ema_f_up=True)
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_reversal_works_in_all_engines(self):
        """REV-BUY fires in all engines via unified post-engine injection."""
        for eng in ["Hybrid", "Breakout", "Trend+Pullback", "Loose"]:
            with self.subTest(engine=eng):
                cfg = SimConfig(
                    engine=eng,
                    reliability_ok=False,
                    allow_neural_reversals=True,
                    p_u=0.60,
                )
                sim = SkippAlgoSim(cfg)
                r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
                self.assertTrue(r.did_buy, f"REV-BUY should work in {eng} engine")

    def test_reversal_short_works_in_all_engines(self):
        """REV-SHORT fires in all engines via unified post-engine injection."""
        for eng in ["Hybrid", "Breakout", "Trend+Pullback", "Loose"]:
            with self.subTest(engine=eng):
                cfg = SimConfig(
                    engine=eng,
                    reliability_ok=False,
                    allow_neural_reversals=True,
                    enable_shorts=True,
                    p_d=0.60,
                )
                sim = SkippAlgoSim(cfg)
                r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
                self.assertTrue(r.did_short, f"REV-SHORT should work in {eng} engine")


class TestMultiBarScenarios(unittest.TestCase):
    """End-to-end multi-bar scenario tests."""

    def test_rev_buy_then_choch_exit_lifecycle(self):
        """REV-BUY entry → hold → ChoCH exit after grace."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            exit_grace_bars=3,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)

        bars = []
        sigs = []

        # Bar 0: REV-BUY via ChoCH_Long
        bars.append(Bar())
        sigs.append(BarSignals(is_choch_long=True))

        # Bars 1-2: hold (grace period)
        for _ in range(2):
            bars.append(Bar())
            sigs.append(BarSignals())

        # Bar 3: ChoCH_Short exit (barsSinceEntry=2, canChochExit=True since min(2,3)=2)
        bars.append(Bar())
        sigs.append(BarSignals(is_choch_short=True))

        results = sim.run_scenario(bars, sigs)

        self.assertTrue(results[0].did_buy, "bar 0: should BUY")
        self.assertFalse(results[1].did_exit, "bar 1: grace blocks exit")
        self.assertFalse(results[2].did_exit, "bar 2: grace blocks exit")
        self.assertTrue(results[3].did_exit, "bar 3: ChoCH exit after grace")
        self.assertEqual(results[3].pos_after, 0)

    def test_no_orphan_exit_labels_invariant(self):
        """
        Over a 50-bar random-ish scenario, every EXIT must be preceded
        by a BUY, and every COVER by a SHORT. No orphans.
        """
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            exit_grace_bars=2,
            cooldown_bars=2,
        )
        sim = SkippAlgoSim(cfg)

        # Alternate: entry triggers, hold, exit triggers
        bars = []
        sigs = []
        for i in range(50):
            bars.append(Bar())
            if i % 10 == 0:
                sigs.append(BarSignals())  # trigger entry (hybrid_long_trigger=True)
            elif i % 10 == 5:
                sigs.append(BarSignals(break_long=True))  # trigger exit
            else:
                sigs.append(BarSignals())  # idle

        results = sim.run_scenario(bars, sigs)

        # Verify invariant: every EXIT has a preceding BUY
        has_open_long = False
        has_open_short = False
        for i, r in enumerate(results):
            if r.did_buy:
                self.assertFalse(has_open_long, f"bar {i}: double BUY without EXIT")
                has_open_long = True
            if r.did_short:
                self.assertFalse(has_open_short, f"bar {i}: double SHORT without COVER")
                has_open_short = True
            if r.did_exit:
                self.assertTrue(has_open_long, f"bar {i}: EXIT without preceding BUY")
                has_open_long = False
            if r.did_cover:
                self.assertTrue(has_open_short, f"bar {i}: COVER without preceding SHORT")
                has_open_short = False

    def test_rev_buy_blocked_by_low_probability(self):
        """REV-BUY with p_u < 0.50 should not fire."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            p_u=0.40,  # too low
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertTrue(r.allow_rev_bypass, "bypass gate reached")
        self.assertTrue(r.entry_block_reached, "block entered")
        self.assertFalse(r.rev_buy_global, "revBuyGlobal blocked by low pU")
        self.assertFalse(r.did_buy)

    def test_rev_buy_blocked_by_macro_gate(self):
        """REV-BUY with macro_gate_long=false should not fire."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            macro_gate_long=False,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(r.rev_buy_global, "macro gate blocks revBuyGlobal")
        self.assertFalse(r.did_buy)

    def test_rev_buy_blocked_by_drawdown(self):
        """REV-BUY with dd_ok=false should not fire."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            dd_ok=False,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(r.rev_buy_global, "drawdown blocks revBuyGlobal")
        self.assertFalse(r.did_buy)

    def test_rev_buy_blocked_by_volume(self):
        """REV-BUY with vol_ok=false should not fire."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            vol_ok=False,
            p_u=0.60,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))

        self.assertFalse(r.rev_buy_global, "volume blocks revBuyGlobal")
        self.assertFalse(r.did_buy)

    def test_stale_exit_bypasses_grace(self):
        """Stalemate exit is not blocked by grace period."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            exit_grace_bars=10,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))  # BUY

        # Immediate stale exit
        r = sim.process_bar(Bar(), BarSignals(stale_exit=True))
        self.assertTrue(r.did_exit, "stale exit bypasses grace")
        self.assertEqual(r.exit_reason, "Stalemate")

    def test_short_cover_via_choch_long(self):
        """SHORT → hold → COVER via ChoCH_Long."""
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            p_d=0.60,
            exit_grace_bars=2,
        )
        sim = SkippAlgoSim(cfg)

        # Bar 0: SHORT via ChoCH_Short
        r0 = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertTrue(r0.did_short)

        # Bar 1: grace blocks
        r1 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertFalse(r1.did_cover, "grace blocks cover at barsSinceEntry=0")

        # Bar 2: grace blocks
        r2 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertFalse(r2.did_cover, "grace blocks cover at barsSinceEntry=1")

        # Bar 3: grace passes (barsSinceEntry=2 >= min(2,2))
        r3 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r3.did_cover, "cover should pass after grace")


class TestCooldownBehavior(unittest.TestCase):
    """Test that cooldown is properly enforced."""

    def test_cannot_reenter_during_cooldown(self):
        """After a BUY+EXIT, cannot re-enter within cooldown_bars."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            cooldown_bars=5,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)

        # BUY
        r0 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r0.did_buy)

        # EXIT immediately (exit_grace_bars=0 allows immediate struct exit)
        r1 = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r1.did_exit)

        # Try to re-enter (within cooldown)
        for i in range(5):
            r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
            self.assertFalse(r.did_buy, f"cooldown should block re-entry at bar {i}")

        # After cooldown expires
        r_after = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r_after.did_buy, "should re-enter after cooldown expires")


class TestStrictEventBehavior(unittest.TestCase):
    """Targeted simulation tests for strict alert event ordering."""

    def test_strict_buy_only_on_followup_bar(self):
        """In strict mode, BUY alert condition must trigger one bar after BUY event."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            use_strict_alert_mode=True,
            in_rev_open_window=False,
            strict_mtf_long_ok=True,
            strict_choch_long_ok=True,
        )
        sim = SkippAlgoSim(cfg)

        r0 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r0.did_buy, "bar 0 should execute BUY event")
        self.assertFalse(r0.alert_buy_cond, "strict BUY alert is delayed by one bar")

        r1 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r1.alert_buy_cond, "bar 1 should fire strict BUY alert condition")

    def test_exit_stays_same_bar_in_strict(self):
        """EXIT alert condition remains same-bar even with strict mode enabled."""
        cfg = SimConfig(
            allow_neural_reversals=True,
            use_strict_alert_mode=True,
            in_rev_open_window=False,
            exit_grace_bars=0,
        )
        sim = SkippAlgoSim(cfg)

        r0 = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r0.did_buy)

        r1 = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r1.did_exit)
        self.assertTrue(r1.alert_exit_cond, "EXIT alert condition should be same-bar")

    def test_strict_disabled_in_open_window(self):
        """Open-window should disable strict delay and fall back to normal event alerts."""
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            use_strict_alert_mode=True,
            in_rev_open_window=True,
        )
        sim = SkippAlgoSim(cfg)

        r0 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r0.did_buy)
        self.assertFalse(r0.strict_alerts_enabled, "strict should be disabled in open window")
        self.assertTrue(r0.alert_buy_cond, "falls back to normal same-bar BUY alert")


if __name__ == '__main__':
    unittest.main()
