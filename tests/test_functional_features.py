"""
Functional and feature-level tests for SkippALGO behavior.

These tests are intentionally behavior-driven (simulated execution), not just
string/regex checks. They cover:
  1) Entry gate functionality
  2) Open-window + strict-mode behavior
  3) Engine-specific scenarios
  4) Risk/exit behavior
  5) Reversal features
  6) Feature-flag matrix
  7) Property-style invariants
  8) Golden-master snapshots
"""

from __future__ import annotations

import random
import unittest

from tests.pine_sim import Bar, BarSignals, SimConfig, SkippAlgoSim


class TestFunctionalGateBehavior(unittest.TestCase):
    def _run_one(self, **cfg_overrides):
        cfg = SimConfig(engine="Hybrid", hybrid_long_trigger=True, **cfg_overrides)
        sim = SkippAlgoSim(cfg)
        return sim.process_bar(Bar(), BarSignals())

    def test_reliability_gate_blocks_entry(self):
        r = self._run_one(reliability_ok=False)
        self.assertFalse(r.allow_entry)
        self.assertFalse(r.did_buy)

    def test_evidence_gate_blocks_entry(self):
        r = self._run_one(evidence_ok=False)
        self.assertFalse(r.allow_entry)
        self.assertFalse(r.did_buy)

    def test_eval_gate_blocks_entry(self):
        r = self._run_one(eval_ok=False)
        self.assertFalse(r.allow_entry)
        self.assertFalse(r.did_buy)

    def test_decision_final_blocks_when_abstain_enabled(self):
        r = self._run_one(abstain_gate=True, decision_final=False)
        self.assertFalse(r.allow_entry)
        self.assertFalse(r.did_buy)

    def test_all_gates_true_allows_entry(self):
        r = self._run_one(
            reliability_ok=True,
            evidence_ok=True,
            eval_ok=True,
            abstain_gate=True,
            decision_final=True,
        )
        self.assertTrue(r.allow_entry)
        self.assertTrue(r.did_buy)


class TestOpenWindowAndStrictBehavior(unittest.TestCase):
    def test_strict_disabled_inside_open_window(self):
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            use_strict_alert_mode=True,
            in_rev_open_window=True,
        )
        sim = SkippAlgoSim(cfg)
        r0 = sim.process_bar(Bar(), BarSignals())
        self.assertFalse(r0.strict_alerts_enabled)
        self.assertTrue(r0.alert_buy_cond)

    def test_strict_delays_buy_outside_open_window(self):
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
        r1 = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r0.did_buy)
        self.assertFalse(r0.alert_buy_cond)
        self.assertTrue(r1.alert_buy_cond)

    def test_open_window_reversal_floor_is_zero(self):
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            in_rev_open_window_long=True,
            p_u=0.10,
            rev_min_prob=0.95,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(r.rev_buy_min_prob_floor, 0.0)
        self.assertTrue(r.prob_ok_global)
        self.assertTrue(r.did_buy)


class TestEngineFeatureScenarios(unittest.TestCase):
    def test_hybrid_buy_path(self):
        sim = SkippAlgoSim(SimConfig(engine="Hybrid", hybrid_long_trigger=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_breakout_buy_path(self):
        sim = SkippAlgoSim(SimConfig(engine="Breakout", trend_up=True, breakout_long=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_trend_pullback_buy_path(self):
        sim = SkippAlgoSim(SimConfig(engine="Trend+Pullback", trend_flip_up=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)

    def test_loose_buy_path(self):
        sim = SkippAlgoSim(SimConfig(engine="Loose", cross_close_ema_f_up=True))
        r = sim.process_bar(Bar(), BarSignals())
        self.assertTrue(r.did_buy)


class TestRiskExitFeatureBehavior(unittest.TestCase):
    def test_struct_exit_respects_grace(self):
        cfg = SimConfig(allow_neural_reversals=True, exit_grace_bars=3)
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))  # enter

        r1 = sim.process_bar(Bar(), BarSignals(break_long=True))
        r2 = sim.process_bar(Bar(), BarSignals(break_long=True))
        r3 = sim.process_bar(Bar(), BarSignals(break_long=True))
        r4 = sim.process_bar(Bar(), BarSignals(break_long=True))

        self.assertFalse(r1.did_exit)
        self.assertFalse(r2.did_exit)
        self.assertFalse(r3.did_exit)
        self.assertTrue(r4.did_exit)

    def test_risk_exit_bypasses_grace(self):
        cfg = SimConfig(allow_neural_reversals=True, exit_grace_bars=10)
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="SL"))
        self.assertTrue(r.did_exit)
        self.assertEqual(r.exit_reason, "SL")

    def test_tp_can_be_held_when_conf_high(self):
        cfg = SimConfig(
            allow_neural_reversals=True,
            confidence=0.95,
            exit_conf_tp=0.90,
        )
        sim = SkippAlgoSim(cfg)
        sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        r = sim.process_bar(Bar(), BarSignals(risk_hit=True, risk_msg="TP"))
        self.assertFalse(r.did_exit)


class TestReversalFeatureBehavior(unittest.TestCase):
    def test_reversal_blocked_below_floor_without_open_window(self):
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            p_u=0.20,
            rev_min_prob=0.50,
            in_rev_open_window_long=False,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertEqual(r.rev_buy_min_prob_floor, 0.25)
        self.assertFalse(r.prob_ok_global)
        self.assertFalse(r.did_buy)

    def test_reversal_short_works_with_open_window_short_bypass(self):
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            in_rev_open_window_short=True,
            p_d=0.05,
            rev_min_prob=0.95,
        )
        sim = SkippAlgoSim(cfg)
        r = sim.process_bar(Bar(), BarSignals(is_choch_short=True))
        self.assertTrue(r.prob_ok_global_s)
        self.assertTrue(r.did_short)


class TestFeatureFlagMatrix(unittest.TestCase):
    def test_flag_matrix_hybrid(self):
        matrix = [
            ("fc_gate_long_safe", False),
            ("enh_long_ok", False),
            ("vol_ok", False),
            ("set_ok_long", False),
            ("pullback_long_ok", False),
            ("macro_gate_long", False),
            ("mtf_ok_long", False),
            ("dd_ok", False),
        ]
        for flag, value in matrix:
            with self.subTest(flag=flag):
                kwargs = dict(engine="Hybrid", hybrid_long_trigger=True)
                kwargs[flag] = value
                sim = SkippAlgoSim(SimConfig(**kwargs))
                r = sim.process_bar(Bar(), BarSignals())
                self.assertFalse(r.did_buy, f"{flag}=False should block Hybrid BUY")


class TestPhase1ScaffoldInvariance(unittest.TestCase):
    def test_phase1_flags_do_not_change_default_behavior(self):
        bars = [Bar() for _ in range(6)]
        sigs = [
            BarSignals(is_choch_long=True),
            BarSignals(),
            BarSignals(risk_hit=True, risk_msg="SL"),
            BarSignals(is_choch_short=True),
            BarSignals(),
            BarSignals(risk_hit=True, risk_msg="SL"),
        ]

        base_sim = SkippAlgoSim(SimConfig(cooldown_bars=0, exit_grace_bars=0, enable_shorts=True))
        p1_sim = SkippAlgoSim(SimConfig(
            cooldown_bars=0,
            exit_grace_bars=0,
            enable_shorts=True,
            use_zero_lag_trend_core=True,
            trend_core_mode="AdaptiveHybrid",
            use_regime_classifier2=True,
            regime_auto_preset=True,
        ))

        base_trace = [
            (r.did_buy, r.did_short, r.did_exit, r.did_cover, r.pos_after)
            for r in base_sim.run_scenario(bars, sigs)
        ]
        p1_trace = [
            (r.did_buy, r.did_short, r.did_exit, r.did_cover, r.pos_after)
            for r in p1_sim.run_scenario(bars, sigs)
        ]

        self.assertEqual(base_trace, p1_trace)


class TestPhase2RegimeBehavior(unittest.TestCase):
    def test_trend_regime_lowers_choch_threshold_and_allows_entry(self):
        # Baseline: fails ChoCH filter at 0.50
        base = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            choch_min_prob=0.50,
            p_u=0.48,
        ))
        r_base = base.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertFalse(r_base.did_buy)
        self.assertAlmostEqual(r_base.choch_min_prob_eff, 0.50, places=6)

        # Phase-2 TREND tuning: ChoCH min prob drops by 0.03 to 0.47 -> pass
        tuned = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            choch_min_prob=0.50,
            p_u=0.48,
            use_regime_classifier2=True,
            regime_auto_preset=True,
            regime2_state=1,
        ))
        r_tuned = tuned.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertAlmostEqual(r_tuned.choch_min_prob_eff, 0.47, places=6)
        self.assertTrue(r_tuned.did_buy)

    def test_vol_shock_regime_raises_choch_threshold_and_blocks_entry(self):
        # Baseline: passes ChoCH filter at 0.50
        base = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            allow_neural_reversals=False,
            choch_min_prob=0.50,
            p_u=0.55,
        ))
        r_base = base.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertTrue(r_base.did_buy)

        # Phase-2 VOL_SHOCK tuning: ChoCH min prob rises by 0.08 to 0.58 -> block
        tuned = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            allow_neural_reversals=False,
            choch_min_prob=0.50,
            p_u=0.55,
            use_regime_classifier2=True,
            regime_auto_preset=True,
            regime2_state=4,
        ))
        r_tuned = tuned.process_bar(Bar(), BarSignals(is_choch_long=True))
        self.assertAlmostEqual(r_tuned.choch_min_prob_eff, 0.58, places=6)
        self.assertFalse(r_tuned.did_buy)

    def test_effective_abstain_override_conf_blocks_in_vol_shock(self):
        # Base override threshold: 0.85 -> confidence 0.88 can bypass weak decision
        base = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            abstain_gate=True,
            decision_ok_safe=False,
            decision_final=False,
            confidence=0.88,
            abstain_override_conf=0.85,
            use_effective_abstain_override=True,
        ))
        r_base = base.process_bar(Bar(), BarSignals())
        self.assertTrue(r_base.allow_entry)
        self.assertTrue(r_base.did_buy)

        # VOL_SHOCK raises override threshold to 0.93 -> same confidence no longer bypasses
        tuned = SkippAlgoSim(SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            abstain_gate=True,
            decision_ok_safe=False,
            decision_final=False,
            confidence=0.88,
            abstain_override_conf=0.85,
            use_effective_abstain_override=True,
            use_regime_classifier2=True,
            regime_auto_preset=True,
            regime2_state=4,
        ))
        r_tuned = tuned.process_bar(Bar(), BarSignals())
        self.assertAlmostEqual(r_tuned.abstain_override_conf_eff, 0.93, places=6)
        self.assertFalse(r_tuned.allow_entry)
        self.assertFalse(r_tuned.did_buy)


class TestPhase3RegimeHysteresisBehavior(unittest.TestCase):
    def test_regime_flapping_is_damped_by_min_hold(self):
        sim = SkippAlgoSim(SimConfig(
            use_regime_classifier2=True,
            regime_auto_preset=True,
            regime_min_hold_bars=2,
            regime_shock_release_delta=5.0,
            regime_atr_shock_pct=85.0,
        ))

        bars = [Bar() for _ in range(4)]
        sigs = [
            BarSignals(raw_regime2_state=1, regime_atr_pct=70.0),
            BarSignals(raw_regime2_state=3, regime_atr_pct=70.0),
            BarSignals(raw_regime2_state=3, regime_atr_pct=70.0),
            BarSignals(raw_regime2_state=3, regime_atr_pct=70.0),
        ]

        res = sim.run_scenario(bars, sigs)
        regime_trace = [r.regime2_state_eff for r in res]
        hold_trace = [r.regime2_hold_bars for r in res]

        # Starts TREND, suppresses early flip to CHOP, then switches once min-hold is satisfied.
        self.assertEqual(regime_trace, [1, 1, 1, 3])
        self.assertEqual(hold_trace, [0, 1, 2, 0])

    def test_vol_shock_sticky_release_snapshot(self):
        sim = SkippAlgoSim(SimConfig(
            use_regime_classifier2=True,
            regime_auto_preset=True,
            regime_min_hold_bars=0,
            regime_shock_release_delta=5.0,
            regime_atr_shock_pct=85.0,
        ))

        bars = [Bar() for _ in range(3)]
        sigs = [
            BarSignals(raw_regime2_state=4, regime_atr_pct=90.0),  # enter shock
            BarSignals(raw_regime2_state=1, regime_atr_pct=84.0),  # above release line (80) -> stay shock
            BarSignals(raw_regime2_state=1, regime_atr_pct=79.0),  # cooled below line -> release to trend
        ]

        res = sim.run_scenario(bars, sigs)
        snapshot = {
            "regime": [r.regime2_state_eff for r in res],
            "choch_min_prob_eff": [round(r.choch_min_prob_eff, 2) for r in res],
        }

        self.assertEqual(snapshot, {
            "regime": [4, 4, 1],
            "choch_min_prob_eff": [0.58, 0.58, 0.47],
        })


class TestPropertyStyleInvariants(unittest.TestCase):
    def test_randomized_invariants(self):
        rng = random.Random(42)
        sim = SkippAlgoSim(SimConfig(cooldown_bars=1, exit_grace_bars=2))

        open_long = False
        open_short = False

        for _ in range(500):
            bar = Bar(
                open=100 + rng.uniform(-2, 2),
                high=102 + rng.uniform(-2, 2),
                low=98 + rng.uniform(-2, 2),
                close=100 + rng.uniform(-2, 2),
                volume=1000 + rng.uniform(-200, 200),
            )
            sig = BarSignals(
                is_choch_long=rng.random() < 0.08,
                is_choch_short=rng.random() < 0.08,
                break_long=rng.random() < 0.06,
                break_short=rng.random() < 0.06,
                is_impulse=rng.random() < 0.05,
                risk_hit=rng.random() < 0.05,
                risk_msg="SL" if rng.random() < 0.5 else "TP",
                stale_exit=rng.random() < 0.02,
            )
            r = sim.process_bar(bar, sig)

            # domain invariants
            self.assertIn(r.pos_after, (-1, 0, 1))
            self.assertFalse(r.did_buy and r.did_short)
            self.assertFalse(r.did_exit and r.did_cover)

            # transition invariants
            if r.did_exit:
                self.assertEqual(r.pos_before, 1)
                self.assertEqual(r.pos_after, 0)
            if r.did_cover:
                self.assertEqual(r.pos_before, -1)
                self.assertEqual(r.pos_after, 0)
            if r.did_buy:
                self.assertEqual(r.pos_before, 0)
                self.assertEqual(r.pos_after, 1)
            if r.did_short:
                self.assertEqual(r.pos_before, 0)
                self.assertEqual(r.pos_after, -1)

            # no orphan exits/covers
            if r.did_buy:
                open_long = True
            if r.did_short:
                open_short = True
            if r.did_exit:
                self.assertTrue(open_long)
                open_long = False
            if r.did_cover:
                self.assertTrue(open_short)
                open_short = False


class TestGoldenMasterSnapshots(unittest.TestCase):
    def test_snapshot_reversal_lifecycle(self):
        cfg = SimConfig(
            reliability_ok=False,
            allow_neural_reversals=True,
            enable_shorts=True,
            cooldown_bars=0,
            exit_grace_bars=0,
            p_u=0.60,
            p_d=0.60,
        )
        sim = SkippAlgoSim(cfg)
        bars = [Bar() for _ in range(5)]
        sigs = [
            BarSignals(is_choch_long=True),
            BarSignals(risk_hit=True, risk_msg="SL"),
            BarSignals(is_choch_short=True),
            BarSignals(risk_hit=True, risk_msg="SL"),
            BarSignals(),
        ]

        results = sim.run_scenario(bars, sigs)

        event_trace = [
            "BUY" if r.did_buy else
            "SHORT" if r.did_short else
            "EXIT" if r.did_exit else
            "COVER" if r.did_cover else
            "-"
            for r in results
        ]

        # Golden master
        self.assertEqual(event_trace, ["BUY", "EXIT", "SHORT", "COVER", "-"])

        counts = {
            "buy": sum(r.did_buy for r in results),
            "short": sum(r.did_short for r in results),
            "exit": sum(r.did_exit for r in results),
            "cover": sum(r.did_cover for r in results),
        }
        self.assertEqual(counts, {"buy": 1, "short": 1, "exit": 1, "cover": 1})

    def test_snapshot_strict_delay(self):
        cfg = SimConfig(
            engine="Hybrid",
            hybrid_long_trigger=True,
            use_strict_alert_mode=True,
            in_rev_open_window=False,
            strict_mtf_long_ok=True,
            strict_choch_long_ok=True,
            cooldown_bars=0,
        )
        sim = SkippAlgoSim(cfg)

        r0 = sim.process_bar(Bar(), BarSignals())
        r1 = sim.process_bar(Bar(), BarSignals())

        snapshot = {
            "did_buy": [r0.did_buy, r1.did_buy],
            "alert_buy": [r0.alert_buy_cond, r1.alert_buy_cond],
            "strict_enabled": [r0.strict_alerts_enabled, r1.strict_alerts_enabled],
        }

        self.assertEqual(snapshot, {
            "did_buy": [True, False],
            "alert_buy": [False, True],
            "strict_enabled": [True, True],
        })


if __name__ == "__main__":
    unittest.main()
