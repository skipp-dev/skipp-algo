"""
Test suite for SkippALGO_Strategy.pine.

Validates the strategy script against expected patterns and catches
regressions.

This suite acts as living documentation for the current Strategy architecture
(including the TfState UDT pattern and related forecasting/evaluation helpers).
If the strategy is refactored in the future, update these tests alongside the
implementation to keep expectations in sync.
"""
import pathlib
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
        self.assertIn('strategy.close("L"', self.text)
        self.assertIn('strategy.close("S"', self.text)


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
            self.assertIn(f"tfCloseF{i}", self.text)
            self.assertIn(f"outScore{i}", self.text)

    def test_multi_profile_target_support(self):
        """Verify Fast/Mid/Slow target profile system."""
        self.assertIn("fcTargetF", self.text)
        self.assertIn("fcTargetM", self.text)
        self.assertIn("fcTargetS", self.text)
        self.assertIn("f_get_params(tf)", self.text)

    def test_ensemble_scoring(self):
        """Verify ensemble scoring system with weights."""
        self.assertIn("f_ensemble4(", self.text)
        # After harmonization, Strategy uses same names as Indicator
        self.assertIn("wState", self.text)
        self.assertIn("wPullback", self.text)
        self.assertIn("wRegime", self.text)

    def test_2d_binning(self):
        """Verify 2D binning (Score × Volatility)."""
        self.assertIn("f_bin2D(", self.text)
        self.assertIn("predBinsN", self.text)
        self.assertIn("predBins1", self.text)
        self.assertIn("dim2Bins", self.text)

    def test_platt_scaling(self):
        """Verify Platt scaling calibration (f_platt_prob removed as dead code; core functions remain)."""
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

    def test_brier_score_calculation(self):
        """Verify Brier score calculation."""
        self.assertIn("f_brier(", self.text)
        
    def test_logloss_calculation(self):
        """Verify LogLoss calculation."""
        self.assertIn("f_logloss(", self.text)

    def test_evaluation_gating(self):
        """Verify evaluation section gating via showEvalSection input."""
        self.assertIn("showEvalSection", self.text)


class TestSkippAlgoStrategyTfStateArchitecture(unittest.TestCase):
    """
    Tests verifying the TfState UDT pattern migration.
    
    The Strategy script now uses the same TfState UDT pattern as the indicator,
    replacing ~100+ global arrays with 7 TfState objects.
    """
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_has_tfstate_udt(self):
        """Strategy has TfState UDT definition."""
        self.assertIn("type TfState", self.text)

    def test_has_f_init_tf_state(self):
        """Strategy has f_init_tf_state helper."""
        self.assertIn("f_init_tf_state(", self.text)

    def test_has_seven_tfstate_variables(self):
        """Strategy has tf1State through tf7State."""
        for i in range(1, 8):
            self.assertIn(f"tf{i}State", self.text)

    def test_tfstate_has_calibration_fields(self):
        """TfState UDT has calibration fields (cntN, upN, etc)."""
        self.assertIn("float[] cntN", self.text)
        self.assertIn("float[] upN", self.text)
        self.assertIn("float[] cnt1", self.text)
        self.assertIn("float[] up1", self.text)

    def test_tfstate_has_queue_fields(self):
        """TfState UDT has queue fields (qEntry, qAge, etc)."""
        self.assertIn("float[] qEntry", self.text)
        self.assertIn("int[]   qAge", self.text)
        self.assertIn("int[]   qBinN", self.text)

    def test_tfstate_has_evaluation_fields(self):
        """TfState UDT has evaluation fields."""
        self.assertIn("float[] evBrierN", self.text)
        self.assertIn("float[] evLogN", self.text)
        self.assertIn("float[] evBrier1", self.text)

    def test_f_reset_tf_uses_tfstate(self):
        """f_reset_tf accepts TfState parameter."""
        self.assertIn("f_reset_tf(TfState st)", self.text)

    def test_f_process_tf_uses_tfstate(self):
        """f_process_tf includes TfState st parameter."""
        self.assertIn("TfState st,", self.text)

    def test_no_orphaned_global_arrays(self):
        """No old-style global arrays (cntN1, upN1, etc)."""
        # These old patterns should be gone
        self.assertNotIn("var int[] cntN1 ", self.text)
        self.assertNotIn("var int[] upN1 ", self.text)
        self.assertNotIn("var float[] evBrierN1 = array.new_float", self.text)


class TestSkippAlgoStrategyUXHelpers(unittest.TestCase):
    """
    Tests for UX display helpers.
    
    These check whether the new UX helpers from SkippALGO.pine are present.
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

    def test_has_f_profile(self):
        """Strategy includes f_profile helper."""
        self.assertIn("f_profile(tf) =>", self.text)

    def test_has_f_target_for_tf(self):
        """Strategy includes f_target_for_tf helper."""
        self.assertIn("f_target_for_tf(tf) =>", self.text)

    def test_has_f_target_label(self):
        """Strategy includes f_target_label helper."""
        self.assertIn("f_target_label(tf) =>", self.text)

    def test_has_f_unc_pp(self):
        """Strategy includes f_unc_pp (CI band helper)."""
        self.assertIn("f_unc_pp(p, n) =>", self.text)

    def test_has_f_strength_label_fc(self):
        """Strategy includes f_strength_label_fc."""
        self.assertIn("f_strength_label_fc(nBin) =>", self.text)

    def test_has_f_prob_range_text(self):
        """Strategy includes f_prob_range_text."""
        self.assertIn("f_prob_range_text(p, nBin) =>", self.text)


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
        self.assertIn('alertcondition((not useAlertCalls) and alertBuyCond,', self.text)

    def test_exit_alert(self):
        """Verify EXIT alert condition."""
        self.assertIn('alertcondition((not useAlertCalls) and alertExitCond,', self.text)

    def test_short_alert(self):
        """Verify SHORT alert condition."""
        self.assertIn('alertcondition((not useAlertCalls) and alertShortCond,', self.text)

    def test_cover_alert(self):
        """Verify COVER alert condition."""
        self.assertIn('alertcondition((not useAlertCalls) and alertCoverCond,', self.text)


class TestSkippAlgoStrategyDeferredFeatures(unittest.TestCase):
    """Tests for deferred feature implementations (A2/A5/B1-B4/C1/C3/C4/D1/D2)."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_sgd_momentum_inputs(self):
        """A2: SGD momentum inputs exist."""
        self.assertIn("useSgdMomentum", self.text)
        self.assertIn("sgdBeta", self.text)

    def test_ece_recal_inputs(self):
        """A5: ECE-triggered recalibration inputs exist."""
        self.assertIn("useEceRecal", self.text)
        self.assertIn("eceRecalBoost", self.text)

    def test_smooth_trend_function(self):
        """D1: f_trend_strength function exists."""
        self.assertIn("f_trend_strength(", self.text)
        self.assertIn("useSmoothTrend", self.text)

    def test_roc_score_function(self):
        """B2: f_roc_score function exists."""
        self.assertIn("f_roc_score(", self.text)
        self.assertIn("rocLongOk", self.text)

    def test_vol_score_function(self):
        """B4: f_vol_score function exists."""
        self.assertIn("f_vol_score(", self.text)
        self.assertIn("volEnsLongOk", self.text)

    def test_ensemble6_function(self):
        """6-factor ensemble removed as dead code; 4-factor ensemble exists."""
        self.assertIn("f_ensemble4(", self.text)

    def test_adx_filter(self):
        """D2: ADX filter inputs and gate exist."""
        self.assertIn("useAdx", self.text)
        self.assertIn("adxLen", self.text)
        self.assertIn("adxThresh", self.text)
        self.assertIn("adxOk", self.text)

    def test_pre_momentum_filter(self):
        """C1: Pre-signal momentum filter exists."""
        self.assertIn("usePreMomentum", self.text)
        self.assertIn("preMomLongOk", self.text)

    def test_ema_accel_filter(self):
        """C3: EMA acceleration filter exists."""
        self.assertIn("useEmaAccel", self.text)
        self.assertIn("emaAccelLongOk", self.text)

    def test_vwap_filter(self):
        """C4: VWAP alignment filter exists."""
        self.assertIn("useVwap", self.text)
        self.assertIn("vwapLongOk", self.text)

    def test_enhancement_gates(self):
        """Enhancement composite gates exist and are wired into signals."""
        self.assertIn("enhLongOk", self.text)
        self.assertIn("enhShortOk", self.text)

    def test_momentum_fields_in_tfstate(self):
        """A2: TfState has momentum accumulator fields."""
        self.assertIn("float[] momPlattN", self.text)
        self.assertIn("float[] momPlatt1", self.text)


class TestSkippAlgoStrategyPreSignals(unittest.TestCase):
    """Tests specifically for PRE-BUY / PRE-SHORT signal and label plumbing."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_pre_signal_core_variables_exist(self):
        """PRE-signal path defines state and pulse variables."""
        self.assertIn("preBuyNow = false", self.text)
        self.assertIn("preShortNow = false", self.text)
        self.assertIn("preBuyPrev = (preBuyNow[1] == true)", self.text)
        self.assertIn("preShortPrev = (preShortNow[1] == true)", self.text)
        self.assertIn("preBuyPulse = showPreEntryLabels and preBuyNow and not preBuyPrev", self.text)
        self.assertIn("preShortPulse = showPreEntryLabels and preShortNow and not preShortPrev", self.text)

    def test_pre_signal_distance_metrics_exist(self):
        """PRE labels should expose trigger distance in points and ATR units."""
        self.assertIn("float preGapLong  = na", self.text)
        self.assertIn("float preGapShort = na", self.text)
        self.assertIn("float preGapATR_L =", self.text)
        self.assertIn("float preGapATR_S =", self.text)

    def test_pre_signal_engine_paths_compute_gap(self):
        """All engines compute PRE gap distance to the next trigger."""
        self.assertIn('if engine == "Hybrid"', self.text)
        self.assertIn('else if engine == "Breakout"', self.text)
        self.assertIn('else if engine == "Trend+Pullback"', self.text)
        self.assertIn("else // Loose", self.text)
        self.assertIn("preGapLong  := (not na(emaF)) ? math.max(0.0, emaF - close) : na", self.text)
        self.assertIn("preGapLong  := (not na(lastSwingHigh)) ? math.max(0.0, lastSwingHigh - close) : na", self.text)
        self.assertIn("preGapLong  := nearFlipUp ? (emaS - emaF) : nearReclaimUp ? (emaF - close) : na", self.text)
        self.assertIn("preGapLong  := nearEmaFUp  ? (emaF - close) : na", self.text)

    def test_pre_labels_are_dynamic_label_new_not_plotshape(self):
        """PRE labels are rendered via label.new helper and include quality fields."""
        self.assertIn("var label[] _preLabels = array.new_label(0)", self.text)
        self.assertIn("MAX_PRE_LABELS = 100", self.text)
        self.assertIn("f_pre_label(x, y, txt, sty, txtCol, bgCol) =>", self.text)
        self.assertIn("lbl = label.new(x, y, txt, style=sty, textcolor=txtCol, color=bgCol, size=size.small)", self.text)
        self.assertIn('"PRE-BUY\\nGap: " + _gapTxt + "\\npU: " + _pTxt + "\\nConf: " + _cTxt', self.text)
        self.assertIn('"PRE-SHORT\\nGap: " + _gapTxt + "\\npD: " + _pTxt + "\\nConf: " + _cTxt', self.text)
        self.assertNotIn('plotshape(preBuyPulse, title="PRE-BUY"', self.text)
        self.assertNotIn('plotshape(preShortPulse, title="PRE-SHORT"', self.text)


class TestSkippAlgoStrategyEntryExitLabels(unittest.TestCase):
    """Explicit regression checks for BUY / REV-BUY / EXIT wiring and payloads."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_buy_and_rev_buy_label_flags_exist(self):
        """BUY and REV-BUY label flags must stay split."""
        self.assertIn("labelRevBuy   = buyEvent and isRevBuy", self.text)
        self.assertIn("labelBuy   = buyEvent and not isRevBuy", self.text)

    def test_buy_and_rev_buy_label_payloads(self):
        """BUY and REV-BUY labels should show probability and confidence."""
        self.assertIn('"REV-BUY\\npU: " + _probTxt + "\\nConf: " + _confTxt', self.text)
        self.assertIn('"BUY\\npU: " + _probTxt + "\\nConf: " + _confTxt', self.text)

    def test_exit_and_cover_label_payloads(self):
        """EXIT/COVER labels should include reason + held bars text."""
        self.assertIn("if showLongLabels and labelExit", self.text)
        self.assertIn('"EXIT" + entryTag + "\\n" + buyAgoTxt + exitSuffix + "\\n" + lastExitReason + "\\nHeld " + str.tostring(barsSinceEntry) + " bars"', self.text)
        self.assertIn('"COVER" + entryTag + "\\n" + shortAgoTxt + coverSuffix + "\\n" + lastExitReason + "\\nHeld " + str.tostring(barsSinceEntry) + " bars"', self.text)

    def test_buy_and_exit_alertconditions_exist(self):
        """Strategy should expose BUY/EXIT alertconditions (guarded by useAlertCalls)."""
        self.assertIn('alertcondition((not useAlertCalls) and alertBuyCond,', self.text)
        self.assertIn('alertcondition((not useAlertCalls) and alertExitCond,', self.text)


class TestSkippAlgoStrategyStrictAlerts(unittest.TestCase):
    """Regression checks for strict alert mode wiring and behavior contract."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = STRATEGY_PATH.read_text(encoding="utf-8")

    def test_strict_inputs_exist(self):
        self.assertIn("strictMtfMargin", self.text)
        self.assertIn("strictChochConfirmBars", self.text)
        self.assertIn("useAdaptiveStrictMargin", self.text)
        self.assertIn("strictAdaptiveRange", self.text)
        self.assertIn("strictAdaptiveLen", self.text)
        self.assertIn("showStrictSignalMarkers", self.text)
        self.assertIn("strictMarkerStyle", self.text)

    def test_open_window_fine_controls_exist(self):
        self.assertIn("revOpenWindowLongMins", self.text)
        self.assertIn("revOpenWindowShortMins", self.text)
        self.assertIn("revOpenWindowMode", self.text)
        self.assertIn("revOpenWindowEngine", self.text)
        self.assertIn("openWindowEngineOk", self.text)
        self.assertIn("openWindowBypassEntries", self.text)
        self.assertIn("inRevOpenWindowLong", self.text)
        self.assertIn("inRevOpenWindowShort", self.text)

    def test_strict_mode_disabled_in_open_window(self):
        self.assertIn("strictAlertsEnabled = not inRevOpenWindow", self.text)

    def test_strict_buy_short_use_one_bar_delay(self):
        self.assertIn("buyEventStrict = barstate.isconfirmed and buyEvent[1]", self.text)
        self.assertIn("shortEventStrict = barstate.isconfirmed and shortEvent[1]", self.text)

    def test_strict_conservative_filters_exist(self):
        self.assertIn("strictMtfLongOk", self.text)
        self.assertIn("strictMtfShortOk", self.text)
        self.assertIn("strictChochLongOk", self.text)
        self.assertIn("strictChochShortOk", self.text)
        self.assertIn("strictMtfMarginEff", self.text)
        self.assertIn("strictAtrRank", self.text)
        self.assertIn("strictBuyConfirmed", self.text)
        self.assertIn("strictShortConfirmed", self.text)

    def test_strict_signal_visualization_exists(self):
        self.assertIn("showStrictIcon", self.text)
        self.assertIn("showStrictLabel", self.text)
        self.assertIn("showLongLabels and showStrictIcon and strictBuyConfirmed", self.text)
        self.assertIn("showShortLabels and showStrictIcon and strictShortConfirmed", self.text)
        self.assertIn("showLongLabels and showStrictLabel and strictBuyConfirmed", self.text)
        self.assertIn("showShortLabels and showStrictLabel and strictShortConfirmed", self.text)
        self.assertIn('title="STRICT-CONF BUY"', self.text)
        self.assertIn('title="STRICT-CONF SHORT"', self.text)
        self.assertIn("STRICT-CONFIRMED BUY", self.text)
        self.assertIn("STRICT-CONFIRMED SHORT", self.text)

    def test_runtime_alert_payload_has_mode_and_delay(self):
        self.assertIn('"mode"', self.text)
        self.assertIn('"confirm_delay"', self.text)
        self.assertIn("mode=", self.text)
        self.assertIn("confirm_delay=", self.text)

    def test_alert_conditions_switch_strict_entries_only(self):
        self.assertIn("alertBuyCond   = strictAlertsEnabled ? buyEventStrict : buyEvent", self.text)
        self.assertIn("alertShortCond = strictAlertsEnabled ? shortEventStrict : shortEvent", self.text)
        self.assertIn("alertExitCond  = exitEvent", self.text)
        self.assertIn("alertCoverCond = coverEvent", self.text)

    def test_rev_buy_min_prob_floor_including_open_window(self):
        self.assertIn("revBuyMinProbFloor = 0.37", self.text)
        self.assertIn("bool probOkGlobal    = (not na(pU) and pU >= revBuyMinProbFloor)", self.text)


if __name__ == "__main__":
    unittest.main()
