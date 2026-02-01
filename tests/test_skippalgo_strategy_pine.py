"""
Test suite for SkippALGO_Strategy.pine.

Validates the strategy script against expected patterns and catches
regressions. NOTE: The strategy script currently uses the OLD global array
pattern (~100+ arrays) rather than the TfState UDT pattern from SkippALGO.pine.

This test suite documents the current state and includes tests that will
FAIL when the TfState migration is applied - serving as both documentation
and a migration guide.
"""
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "SkippALGO_Strategy.pine"


class TestSkippAlgoStrategyBasics(unittest.TestCase):
    """Basic structure tests for the strategy script."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_version_6(self):
        """Verify Pine Script version 6."""
        self.assertRegex(self.text, r"//@version=6")

    def test_is_strategy_not_indicator(self):
        """Verify this is a strategy() declaration, not indicator()."""
        self.assertIn("strategy(", self.text)
        self.assertNotIn("indicator(", self.text)

    def test_no_semicolons(self):
        """Pine Script v6 forbids end-of-line semicolons."""
        count = 0
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped.endswith(";"):
                # Exclude comments
                if "//" in line:
                    idx = line.index("//")
                    content = line[:idx].strip()
                    if content.endswith(";"):
                        count += 1
                else:
                    count += 1
        self.assertEqual(count, 0, f"Found {count} lines ending with semicolons")

    def test_strategy_entry_calls(self):
        """Verify strategy entry/close calls are present."""
        self.assertIn('strategy.entry("L", strategy.long', self.text)
        self.assertIn('strategy.entry("S", strategy.short', self.text)
        self.assertIn('strategy.close("L")', self.text)
        self.assertIn('strategy.close("S")', self.text)


class TestSkippAlgoStrategyForecasting(unittest.TestCase):
    """Tests for forecast calibration system."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_f_process_tf_exists(self):
        """Verify f_process_tf function is defined."""
        self.assertIn("f_process_tf(", self.text)

    def test_seven_forecast_horizons(self):
        """Verify all 7 forecast timeframe horizons are processed."""
        for i in range(1, 8):
            self.assertIn(f"tfF{i}", self.text)
            self.assertIn(f"newF{i}", self.text)
            self.assertIn(f"outScore{i}", self.text)

    def test_multi_profile_target_support(self):
        """Verify Fast/Mid/Slow target profile system."""
        self.assertIn("fcTargetF", self.text)
        self.assertIn("fcTargetM", self.text)
        self.assertIn("fcTargetS", self.text)
        self.assertIn("f_get_params(tf)", self.text)

    def test_ensemble_scoring(self):
        """Verify ensemble scoring system with weights."""
        self.assertIn("f_ensemble(", self.text)
        self.assertIn("ens_wA", self.text)
        self.assertIn("ens_wB", self.text)
        self.assertIn("ens_wC", self.text)

    def test_2d_binning(self):
        """Verify 2D binning (Score × Volatility)."""
        self.assertIn("f_bin2D(", self.text)
        self.assertIn("predBinsN", self.text)
        self.assertIn("predBins1", self.text)
        self.assertIn("dim2Bins", self.text)

    def test_platt_scaling(self):
        """Verify Platt scaling calibration."""
        self.assertIn("f_platt_prob(", self.text)
        self.assertIn("f_logit(", self.text)
        self.assertIn("f_sigmoid(", self.text)
        self.assertIn("usePlatt", self.text)


class TestSkippAlgoStrategyEvaluation(unittest.TestCase):
    """Tests for live evaluation system (Brier, LogLoss, ECE, Drift)."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_eval_update_function(self):
        """Verify evaluation update function exists."""
        self.assertIn("f_eval_update_one(", self.text)

    def test_eval_get_function(self):
        """Verify evaluation getter function exists."""
        self.assertIn("f_eval_get(", self.text)

    def test_brier_score_calculation(self):
        """Verify Brier score calculation."""
        self.assertIn("f_brier(", self.text)
        
    def test_logloss_calculation(self):
        """Verify LogLoss calculation."""
        self.assertIn("f_logloss(", self.text)

    def test_evaluation_display(self):
        """Verify evaluation section in table."""
        self.assertIn("showEvalSection", self.text)
        self.assertIn("f_rowEval(", self.text)


class TestSkippAlgoStrategyGlobalArraysStatus(unittest.TestCase):
    """
    Tests documenting the CURRENT architecture using global arrays.
    
    The Strategy script still uses the old pattern with ~100+ global arrays.
    These tests will need updating when TfState UDT migration is applied.
    """
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_has_global_count_arrays(self):
        """CURRENT: Strategy uses global cntN1..7 arrays."""
        for i in range(1, 8):
            # Note: Pine uses variable spacing; match just the array names
            self.assertIn(f"cntN{i}", self.text)
            self.assertIn(f"upN{i}", self.text)

    def test_has_global_queue_arrays(self):
        """CURRENT: Strategy uses global qEntry1..7 arrays."""
        for i in range(1, 8):
            # Note: Pine uses variable spacing; use regex-like matching
            self.assertIn(f"qEntry{i}", self.text)
            self.assertIn(f"qAge{i}", self.text)

    def test_has_global_brier_stats_arrays(self):
        """CURRENT: Strategy uses global brierStatsN1..7 arrays."""
        for i in range(1, 8):
            self.assertIn(f"var float[] brierStatsN{i} = array.new_float", self.text)
            self.assertIn(f"var float[] brierStats1{i} = array.new_float", self.text)

    def test_has_global_eval_arrays(self):
        """CURRENT: Strategy uses global evBrierN1..7 arrays."""
        for i in range(1, 8):
            self.assertIn(f"evBrierN{i}", self.text)
            self.assertIn(f"evLogN{i}", self.text)

    def test_no_tfstate_udt(self):
        """CURRENT: Strategy does NOT have TfState UDT (needs migration)."""
        # This should FAIL when migration is applied
        self.assertNotIn("type TfState", self.text)

    def test_no_f_init_tf_state(self):
        """CURRENT: Strategy does NOT have f_init_tf_state (needs migration)."""
        # This should FAIL when migration is applied
        self.assertNotIn("f_init_tf_state(", self.text)

    def test_f_process_tf_long_signature(self):
        """CURRENT: f_process_tf has many individual array parameters."""
        # The current signature passes many arrays individually
        # After migration, it should accept TfState st
        self.assertIn("cntN, upN, cnt1, up1,", self.text)
        self.assertIn("qBinN, qBin1, qEntry, qAtr", self.text)
        # Should NOT have TfState parameter yet
        self.assertNotIn("TfState st,", self.text)


class TestSkippAlgoStrategyUXHelpers(unittest.TestCase):
    """
    Tests for UX display helpers.
    
    These check whether the new UX helpers from SkippALGO.pine are present.
    CURRENT: Strategy is missing these - they need to be ported.
    """
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_has_puptext_function(self):
        """Strategy has f_pupText display function."""
        self.assertIn("f_pupText(", self.text)

    def test_has_pred_symbol_function(self):
        """Strategy has prediction symbol function."""
        self.assertIn("f_predSymbolP(", self.text)

    def test_has_pred_color_function(self):
        """Strategy has prediction color function."""
        self.assertIn("f_predColorP(", self.text)

    def test_missing_f_profile(self):
        """CURRENT: Strategy is MISSING f_profile helper (needs porting)."""
        # This should FAIL when UX helpers are ported
        self.assertNotIn("f_profile(tf) =>", self.text)

    def test_missing_f_target_for_tf(self):
        """CURRENT: Strategy is MISSING f_target_for_tf helper."""
        self.assertNotIn("f_target_for_tf(tf) =>", self.text)

    def test_missing_f_target_label(self):
        """CURRENT: Strategy is MISSING f_target_label helper."""
        self.assertNotIn("f_target_label(tf) =>", self.text)

    def test_missing_f_unc_pp(self):
        """CURRENT: Strategy is MISSING f_unc_pp (CI band helper)."""
        self.assertNotIn("f_unc_pp(p, n) =>", self.text)

    def test_missing_f_strength_label_fc(self):
        """CURRENT: Strategy is MISSING f_strength_label_fc."""
        self.assertNotIn("f_strength_label_fc(nBin) =>", self.text)

    def test_missing_f_prob_range_text(self):
        """CURRENT: Strategy is MISSING f_prob_range_text."""
        self.assertNotIn("f_prob_range_text(p, nBin) =>", self.text)


class TestSkippAlgoStrategyConsistency(unittest.TestCase):
    """Tests for consistency between shared logic."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_has_f_clamp01(self):
        """Verify f_clamp01 utility exists."""
        self.assertIn("f_clamp01(", self.text)

    def test_has_f_pct_rank(self):
        """Verify f_pct_rank utility exists."""
        self.assertIn("f_pct_rank(", self.text)

    def test_has_f_tfLabel(self):
        """Verify timeframe label utility exists."""
        self.assertIn("f_tfLabel(", self.text)

    def test_has_f_confColor(self):
        """Verify confidence color utility exists."""
        self.assertIn("f_confColor(", self.text)

    def test_has_f_fmtVol(self):
        """Verify volume formatting utility exists."""
        self.assertIn("f_fmtVol(", self.text)

    def test_has_tf_pack_function(self):
        """Verify f_tf_pack for MTF data retrieval."""
        self.assertIn("f_tf_pack(tf) =>", self.text)
        self.assertIn("request.security(", self.text)

    def test_has_cal_update_function(self):
        """Verify calibration update function."""
        self.assertIn("f_cal_update(", self.text)

    def test_has_cal_cur_function(self):
        """Verify current calibration getter."""
        self.assertIn("f_cal_cur(", self.text)


class TestSkippAlgoStrategyAlerts(unittest.TestCase):
    """Tests for alert system."""
    
    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_buy_alert(self):
        """Verify BUY alert condition."""
        self.assertIn('alertcondition(buySignal,', self.text)

    def test_exit_alert(self):
        """Verify EXIT alert condition."""
        self.assertIn('alertcondition(exitSignal,', self.text)

    def test_short_alert(self):
        """Verify SHORT alert condition."""
        self.assertIn('alertcondition(shortSignal,', self.text)

    def test_cover_alert(self):
        """Verify COVER alert condition."""
        self.assertIn('alertcondition(coverSignal,', self.text)


if __name__ == "__main__":
    unittest.main()
