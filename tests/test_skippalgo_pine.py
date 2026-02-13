"""
Test suite for SkippALGO.pine (Indicator).

Validates the indicator script against expected patterns and configuration.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"

class TestSkippAlgoIndicator(unittest.TestCase):
    """Basic structure tests for the indicator script."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_version_6(self):
        """Verify Pine Script version 6."""
        self.assertRegex(self.text, r"//@version=6")

    def test_is_indicator(self):
        """Verify this is an indicator() declaration."""
        self.assertIn("indicator(", self.text)
        self.assertNotIn("strategy(", self.text)

    def test_engine_inputs(self):
        """Verify signal engine inputs exist (no branding)."""
        self.assertIn('engine', self.text)
        self.assertIn('"Hybrid"', self.text)
        self.assertIn('"Breakout"', self.text)
        self.assertIn('useForecastGateEntry', self.text)
        self.assertIn('pbLookback', self.text)

    def test_trade_gate_inputs(self):
        """Ensure separate trade-gate sample thresholds are defined."""
        self.assertIn('tradeMinBinSamples', self.text)
        self.assertIn('tradeMinTotalSamples', self.text)

    def test_rel_filter_default_horizon(self):
        """Default filter horizon should be F3 for faster gate responsiveness."""
        self.assertIn('relFilterTF  = input.string("F3"', self.text)
        
    def test_risk_inputs(self):
        """Verify ATR risk inputs."""
        self.assertIn('useAtrRisk', self.text)
        self.assertIn('stopATR', self.text)
        self.assertIn('tpATR', self.text)

    def test_no_semicolons(self):
        """Pine Script v6 forbids end-of-line semicolons."""
        count = 0
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped.endswith(";"):
                if "//" in line:
                    idx = line.index("//")
                    content = line[:idx].strip()
                    if content.endswith(";"):
                        count += 1
                else:
                    count += 1
        self.assertEqual(count, 0, f"Found {count} lines ending with semicolons")

    def test_trend_regime_block_present(self):
        """Ensure trendUp/trendDn are defined (parity with strategy)."""
        self.assertIn("atrNormHere = atr / math.max(close, 0.0001)", self.text)
        self.assertIn("trendReg = f_trend_regime(emaF, emaS, atrNormHere)", self.text)
        self.assertIn("trendUp  = trendReg == 1.0", self.text)
        self.assertIn("trendDn  = trendReg == -1.0", self.text)

    def test_risk_temp_declared_once(self):
        """Parent-scope float newStop/Tp/Trail = na removed to avoid shadow;
        buy branch tuple [newStop, ...] provides the declarations."""
        self.assertEqual(len(re.findall(r"^float newStop\s*= na", self.text, flags=re.MULTILINE)), 0)
        self.assertEqual(len(re.findall(r"^float newTp\s*= na", self.text, flags=re.MULTILINE)), 0)
        self.assertEqual(len(re.findall(r"^float newTrail\s*= na", self.text, flags=re.MULTILINE)), 0)
        # Buy branch tuple still present
        self.assertIn("[newStop, newTp, newTrail] = f_set_risk_on_entry(true", self.text)

    def test_forecast_pack_block_present(self):
        """Ensure all tfF1..tfF7 packs exist with direct tuple destructuring."""
        for i in range(1, 8):
            # Patch A: checking for raw unpacking
            self.assertIn(f"[t{i}_r, c{i}_r, h{i}_r, l{i}_r", self.text)
            self.assertIn(f"= f_tf_pack(tfF{i})", self.text)

    def test_decision_quality_uses_trade_gate_thresholds(self):
        """Decision gate should use tradeMin* thresholds rather than calMinSamples."""
        self.assertIn("tradeMinBinSamples", self.text)
        self.assertIn("tradeMinTotalSamples", self.text)

    def test_trade_gate_thresholds_allow_zero(self):
        """Trade gate thresholds should treat 0 as disabled (<= 0 comparisons)."""
        self.assertRegex(self.text, r"tradeMinBinSamples\s*<=\s*0")
        self.assertRegex(self.text, r"tradeMinTotalSamples\s*<=\s*0")

    # --- Deferred-items feature tests ---

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

    def test_pre_signal_core_variables_exist(self):
        """PRE-signal path defines core state and pulse variables."""
        self.assertIn("preBuyNow = false", self.text)
        self.assertIn("preShortNow = false", self.text)
        self.assertIn("preBuyPrev = (preBuyNow[1] == true)", self.text)
        self.assertIn("preShortPrev = (preShortNow[1] == true)", self.text)
        self.assertIn("preBuyPulse = showPreEntryLabels and preBuyNow and not preBuyPrev", self.text)
        self.assertIn("preShortPulse = showPreEntryLabels and preShortNow and not preShortPrev", self.text)

    def test_pre_signal_distance_metrics_exist(self):
        """PRE labels should expose distance-to-trigger in points and ATR units."""
        self.assertIn("float preGapLong  = na", self.text)
        self.assertIn("float preGapShort = na", self.text)
        self.assertIn("float preGapATR_L =", self.text)
        self.assertIn("float preGapATR_S =", self.text)

    def test_pre_signal_engine_paths_compute_gap(self):
        """All engines should compute PRE gap distance before label rendering."""
        self.assertIn('if engine == "Hybrid"', self.text)
        self.assertIn('else if engine == "Breakout"', self.text)
        self.assertIn('else if engine == "Trend+Pullback"', self.text)
        self.assertIn("else // Loose", self.text)
        self.assertIn("preGapLong  := (not na(emaF)) ? math.max(0.0, emaF - close) : na", self.text)
        self.assertIn("preGapLong  := (not na(lastSwingHigh)) ? math.max(0.0, lastSwingHigh - close) : na", self.text)
        self.assertIn("preGapLong  := nearFlipUp ? (emaS - emaF) : nearReclaimUp ? (emaF - close) : na", self.text)
        self.assertIn("preGapLong  := nearEmaFUp  ? (emaF - close) : na", self.text)

    def test_pre_labels_are_dynamic_label_new_not_plotshape(self):
        """PRE labels are rendered via label.new helper with dynamic text payload."""
        self.assertIn("var label[] _preLabels = array.new_label(0)", self.text)
        self.assertIn("MAX_PRE_LABELS = 60", self.text)
        self.assertIn("f_pre_label(x, y, txt, sty, txtCol, bgCol) =>", self.text)
        self.assertIn("lbl = label.new(x, y, txt, style=sty, textcolor=txtCol, color=bgCol, size=size.small)", self.text)
        self.assertIn('"PRE-BUY\\nGap: " + _gapTxt + "\\npU: " + _pTxt + "\\nConf: " + _cTxt', self.text)
        self.assertIn('"PRE-SHORT\\nGap: " + _gapTxt + "\\npD: " + _pTxt + "\\nConf: " + _cTxt', self.text)
        self.assertNotIn('plotshape(preBuyPulse, title="PRE-BUY"', self.text)
        self.assertNotIn('plotshape(preShortPulse, title="PRE-SHORT"', self.text)


class TestSkippAlgoIndicatorEntryExitLabels(unittest.TestCase):
    """Explicit regression checks for BUY / REV-BUY / EXIT wiring and payloads."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = INDICATOR_PATH.read_text(encoding="utf-8")

    def test_buy_and_rev_buy_label_flags_exist(self):
        """BUY and REV-BUY label flags must stay split."""
        self.assertIn("labelRevBuy   = buyEvent and isRevBuy", self.text)
        self.assertIn("labelBuy      = buyEvent and not isRevBuy", self.text)

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
        """Indicator should expose BUY/EXIT alert conditions."""
        self.assertRegex(self.text, r'alertcondition\(alertBuyCond,\s*title="BUY"')
        self.assertRegex(self.text, r'alertcondition\(alertExitCond,\s*title="EXIT"')


class TestSkippAlgoIndicatorStrictAlerts(unittest.TestCase):
    """Regression checks for strict alert mode entry delay + open-window bypass."""

    text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = INDICATOR_PATH.read_text(encoding="utf-8")

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
        self.assertIn("strictAlertsEnabled = useStrictAlertConfirm and not inRevOpenWindow", self.text)

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
        self.assertIn("REV_BUY_PROB_FLOOR", self.text)
        self.assertIn("revBuyMinProbFloor = REV_BUY_PROB_FLOOR", self.text)
        self.assertIn("probOkGlobal    = (not na(pU) and pU >= revBuyMinProbFloor)", self.text)

if __name__ == "__main__":
    unittest.main()
