import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE_PATH = ROOT / "SkippALGO_Strategy.pine"
INDICATOR_PATH = ROOT / "SkippALGO.pine"


class TestSkippAlgoStrategy(unittest.TestCase):
    text: str = ""
    lines: list[str] = []
    indicator_text: str = ""

    @classmethod
    def setUpClass(cls):
        cls.text = PINE_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()
        cls.indicator_text = INDICATOR_PATH.read_text(encoding="utf-8")

    def test_version_6(self):
        self.assertRegex(self.text, r"//@version=6")

    def test_no_semicolons(self):
        # Pine Script v6 forbids end-of-line semicolons
        count = 0
        for i, line in enumerate(self.lines, 1):
            if line.strip().endswith(";"):
                # Exclude comments
                if "//" in line:
                    idx = line.index("//")
                    content = line[:idx].strip()
                    if content.endswith(";"):
                        count += 1
                        print(f"Line {i} has semicolon: {line}")
                else:
                    count += 1
                    print(f"Line {i} has semicolon: {line}")
        self.assertEqual(count, 0, f"Found {count} lines ending with semicolons")

    def test_f_process_tf_usage(self):
        # f_process_tf calls should match definition
        # After 4-factor ensemble upgrade, now includes wTrend
        pattern = r"alphaN,\s*alpha1,\s*kShrink,\s*wState,\s*wPullback,\s*wRegime,\s*wTrend\)"
        self.assertRegex(self.text, pattern, "Correct variable names not found in f_process_tf calls")

    def test_div_by_zero_fix_f_pullback_score(self):
        # The line 'dist = (c - ef) / (na(atrVal) ? c*0.01 : atrVal)' was causing potential div by zero and was unused
        bad_line = r"dist\s*=\s*\(c\s*-\s*ef\)\s*/\s*\(na\(atrVal\)\s*\?\s*c\*0\.01\s*:\s*atrVal\)"
        self.assertNotRegex(self.text, bad_line, "Found potentially dangerous div-by-zero line in f_pullback_score")
        
    def test_entryNow_replaced_by_cNow(self):
        # Verify cNow is used instead of entryNow (now via TfState st.qEntry)
        self.assertNotRegex(self.text, r"array\.push\(.*qEntry,\s*entryNow\)")
        self.assertRegex(self.text, r"array\.push\(st\.qEntry,\s*cNow\)")

    def test_reactive_arrays_sized_for_2d_binning(self):
        """
        Regression test for runtime error:
        'Error on bar 0: In array.get() function. Index 4 is out of bounds, array size is 2.'
        
        The (1) reactive arrays (cnt1, up1) inside TfState must be sized for 2D binning
        (nBins1 * dim2) since f_bin2D is used, not 1D (predBins1).
        """
        # With TfState pattern, check that f_init_tf_state uses 2D sizing for cnt1/up1
        # Pattern: array.new_float(nBins1 * dim2, 0.0) for cnt1 and up1
        pattern_2d = r"array\.new_float\(nBins1\s*\*\s*dim2,\s*0\.0\)"
        matches_2d = re.findall(pattern_2d, self.text)
        
        # Should have at least 2 matches (cnt1 and up1 in f_init_tf_state)
        self.assertGreaterEqual(len(matches_2d), 2, 
            f"Expected at least 2 (1) arrays with 2D sizing in f_init_tf_state, found {len(matches_2d)}")
        
        # Verify TfState initialization exists
        self.assertIn("f_init_tf_state(", self.text)

    def test_forecast_display_headers(self):
        # Ensure forecast display input and dynamic headers exist
        self.assertIn('fcDisplay = input.string("Up% (N)"', self.text)
        self.assertIn('pHdrN = fcDisplay == "Edge pp (N)" ? "Edge(N)" : "Up%(N)"', self.text)
        self.assertIn('pHdr1 = fcDisplay == "Edge pp (N)" ? "Edge(1)" : "Up%(1)"', self.text)

    def test_ensemble_weights_used_in_display(self):
        # Display probabilities should use the same ensemble weights as calibration
        # Updated for 4-factor ensemble (includes wTrend)
        self.assertIn("sEns = f_ensemble4(sA, sB, sC, sD, wState, wPullback, wRegime, wTrend)", self.text)

    def test_defaults_match_indicator_targets(self):
        # Mid targets
        self.assertIn('atrThrM   = input.float(0.50, "ATR Thr"', self.text)
        self.assertIn('pathHM    = input.int(8, "Path H"', self.text)
        self.assertIn('tpATRM    = input.float(0.80, "Path TP"', self.text)
        self.assertIn('slATRM    = input.float(1.00, "Path SL"', self.text)

        # Slow targets
        self.assertIn('fcTargetS = input.string("PathTPvsSL", "Target"', self.text)
        self.assertIn('kBarsS    = input.int(10, "k bars"', self.text)
        self.assertIn('atrThrS   = input.float(1.00, "ATR Thr"', self.text)
        self.assertIn('pathHS    = input.int(12, "Path H"', self.text)
        self.assertIn('tpATRS    = input.float(1.00, "Path TP"', self.text)
        self.assertIn('slATRS    = input.float(1.00, "Path SL"', self.text)

    def test_ensemble_defaults_match_indicator(self):
        # After harmonization, Strategy uses same variable names as Indicator
        self.assertIn('wState    = input.float(1.0, "Weight: State (Outlook)"', self.text)
        self.assertIn('wPullback = input.float(0.5, "Weight: Pullback Depth"', self.text)
        self.assertIn('wRegime   = input.float(0.3, "Weight: Vol Regime"', self.text)

        # Ensure indicator still defines the same weights for parity
        self.assertIn('wState    = input.float(1.0, "Weight: State (Outlook)"', self.indicator_text)
        self.assertIn('wPullback = input.float(0.5, "Weight: Pullback Depth"', self.indicator_text)
        self.assertIn('wRegime   = input.float(0.3, "Weight: Vol Regime"', self.indicator_text)

    def test_ensemble_implementation_matches_indicator(self):
        # Strategy should use the same normalized weighted average as indicator
        self.assertIn("num = wA * sA + wB * sB + wC * sC", self.text)
        self.assertIn("den = wA + wB + wC", self.text)
        self.assertIn("val = den == 0 ? 0.0 : num / den", self.text)
        self.assertIn("math.max(-1.0, math.min(1.0, val))", self.text)

        # Ensure old non-linear mapping is not present
        self.assertNotIn("f_clamp01((raw + 1.0) * 0.5) * 2.0 - 1.0", self.text)

    def test_trade_gate_inputs(self):
        """Ensure separate trade-gate sample thresholds are defined."""
        self.assertIn('tradeMinBinSamples', self.text)
        self.assertIn('tradeMinTotalSamples', self.text)

    def test_rel_filter_default_horizon(self):
        """Default filter horizon should be F3 for faster gate responsiveness."""
        self.assertIn('relFilterTF  = input.string("F3"', self.text)

    def test_trend_regime_block_present(self):
        """Catch missing trendUp/trendDn definitions (undeclared identifiers)."""
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
            self.assertIn(f"[t{i}, c{i}, h{i}, l{i}", self.text)
            self.assertIn(f"= f_tf_pack(tfF{i})", self.text)

    def test_decision_quality_uses_trade_gate_thresholds(self):
        """Decision gate should use tradeMin* thresholds rather than calMinSamples."""
        self.assertIn("tradeMinBinSamples", self.text)
        self.assertIn("tradeMinTotalSamples", self.text)

    def test_can_logic_uses_totals_and_forecast_gate(self):
        # Ensure totals are computed via f_sum_int_array in the loop body
        self.assertIn("f_sum_int_array(cntN)", self.text)
        self.assertIn("f_sum_int_array(cnt1)", self.text)

        # Ensure totals are extracted via array.get from loop-computed arrays
        self.assertIn("totF1N = array.get(totFNArr, 0)", self.text)
        self.assertIn("totF7N = array.get(totFNArr, 6)", self.text)
        self.assertIn("totF11 = array.get(totF1Arr, 0)", self.text)
        self.assertIn("totF17 = array.get(totF1Arr, 6)", self.text)

        # Ensure can flags are extracted via array.get from loop-computed arrays
        self.assertIn("canF1N = array.get(canFNArr, 0)", self.text)
        self.assertIn("canF7N = array.get(canFNArr, 6)", self.text)
        self.assertIn("canF11 = array.get(canF1Arr, 0)", self.text)
        self.assertIn("canF17 = array.get(canF1Arr, 6)", self.text)

        # Ensure loop uses f_get_total_samples and forecastAllowed gate
        self.assertIn("f_get_total_samples(tfSel,", self.text)
        self.assertIn("forecastAllowed and (not na(totN) and totN > 0)", self.text)

    def test_new_risk_features_exist(self):
        """Ensure Breakeven, Stalemate, and Session Filter inputs are present."""
        self.assertIn("useBreakeven =", self.text)
        self.assertIn("useStalemate =", self.text)
        self.assertIn("useSessionFilter =", self.text)
        
        # Ensure logic variables are initialized
        self.assertIn("isBeHit :=", self.text)
        self.assertRegex(self.text, r"staleExit\s*=")
        self.assertRegex(self.text, r"enBar\s*=")

if __name__ == "__main__":
    unittest.main()
