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
        # We check that arguments match the input names (ens_wA vs wState issue check)
        # In Strategy, inputs ARE ens_wA, ens_wB, ens_wC.
        # So we check that the calls usage these variables.
        pattern = r"alphaN,\s*alpha1,\s*kShrink,\s*ens_wA,\s*ens_wB,\s*ens_wC\)"
        self.assertRegex(self.text, pattern, "Correct variable names not found in f_process_tf calls")

    def test_div_by_zero_fix_f_pullback_score(self):
        # The line 'dist = (c - ef) / (na(atrVal) ? c*0.01 : atrVal)' was causing potential div by zero and was unused
        bad_line = r"dist\s*=\s*\(c\s*-\s*ef\)\s*/\s*\(na\(atrVal\)\s*\?\s*c\*0\.01\s*:\s*atrVal\)"
        self.assertNotRegex(self.text, bad_line, "Found potentially dangerous div-by-zero line in f_pullback_score")
        
    def test_entryNow_replaced_by_cNow(self):
        # Verify cNow is used instead of entryNow
        self.assertNotRegex(self.text, r"array\.push\(qEntry,\s*entryNow\)")
        self.assertRegex(self.text, r"array\.push\(qEntry,\s*cNow\)")

    def test_reactive_arrays_sized_for_2d_binning(self):
        """
        Regression test for runtime error:
        'Error on bar 0: In array.get() function. Index 4 is out of bounds, array size is 2.'
        
        The (1) reactive arrays (cnt11, up11, etc.) must be sized for 2D binning
        (predBins1 * dim2Bins) since f_bin2D is used, not 1D (predBins1).
        """
        import re
        # Check that (1) arrays use 2D sizing: predBins1 * dim2Bins
        pattern_2d = r"array\.new_int\(predBins1\s*\*\s*dim2Bins,\s*0\)"
        matches_2d = re.findall(pattern_2d, self.text)
        
        # Should have 14 matches (cnt1x and up1x for F1-F7)
        self.assertGreaterEqual(len(matches_2d), 14, 
            f"Expected at least 14 (1) arrays with 2D sizing (predBins1 * dim2Bins), found {len(matches_2d)}")
        
        # Verify NO (1) arrays use old 1D sizing pattern
        bad_pattern = r"cnt1\d\s*=\s*array\.new_int\(predBins1,\s*0\)"
        self.assertNotRegex(self.text, bad_pattern, 
            "Found (1) array with incorrect 1D sizing - will cause array bounds error with f_bin2D")

    def test_forecast_display_headers(self):
        # Ensure forecast display input and dynamic headers exist
        self.assertIn('fcDisplay = input.string("Up% (N)"', self.text)
        self.assertIn('pHdrN = fcDisplay == "Edge pp (N)" ? "Edge(N)" : "Up%(N)"', self.text)
        self.assertIn('pHdr1 = fcDisplay == "Edge pp (N)" ? "Edge(1)" : "Up%(1)"', self.text)

    def test_ensemble_weights_used_in_display(self):
        # Display probabilities should use the same ensemble weights as calibration
        self.assertIn("sEns = f_ensemble(sA, sB, sC, ens_wA, ens_wB, ens_wC)", self.text)

    def test_defaults_match_indicator_targets(self):
        # Mid targets
        self.assertIn('atrThrM   = input.float(0.50, "ATR Thr"', self.text)
        self.assertIn('pathHM    = input.int(8, "Path H"', self.text)
        self.assertIn('tpATRM    = input.float(0.80, "Path TP"', self.text)
        self.assertIn('slATRM    = input.float(0.50, "Path SL"', self.text)

        # Slow targets
        self.assertIn('fcTargetS = input.string("PathTPvsSL", "Target"', self.text)
        self.assertIn('kBarsS    = input.int(10, "k bars"', self.text)
        self.assertIn('atrThrS   = input.float(1.00, "ATR Thr"', self.text)
        self.assertIn('pathHS    = input.int(12, "Path H"', self.text)
        self.assertIn('tpATRS    = input.float(1.20, "Path TP"', self.text)
        self.assertIn('slATRS    = input.float(0.80, "Path SL"', self.text)

    def test_ensemble_defaults_match_indicator(self):
        self.assertIn('ens_wA = input.float(1.0, "Weight A (Algo)"', self.text)
        self.assertIn('ens_wB = input.float(0.5, "Weight B (Pullback)"', self.text)
        self.assertIn('ens_wC = input.float(0.3, "Weight C (Regime)"', self.text)

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

    def test_can_logic_uses_totals_and_forecast_gate(self):
        # Ensure totals are computed via helper
        self.assertIn("f_sum_int_array(cntN1)", self.text)
        self.assertIn("f_sum_int_array(cnt11)", self.text)

        # Ensure can flags depend on enableForecast and totals
        self.assertIn("can1N = enableForecast and (totN1 > 0)", self.text)
        self.assertIn("can7N = enableForecast and (totN7 > 0)", self.text)
        self.assertIn("can11 = enableForecast and (tot11 > 0)", self.text)
        self.assertIn("can17 = enableForecast and (tot17 > 0)", self.text)

if __name__ == "__main__":
    unittest.main()
