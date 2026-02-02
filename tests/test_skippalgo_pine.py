import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE_PATH = ROOT / "SkippALGO.pine"


class TestSkippAlgoPine(unittest.TestCase):
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = PINE_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

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

    def test_table_clear_has_bounds(self):
        self.assertIn("table.clear(gT, 0, 0, tblCols - 1, 15)", self.text)
        self.assertNotRegex(self.text, r"table\.clear\(\s*gT\s*\)")

    def test_newF_uses_precomputed_change(self):
        for line in self.lines:
            if re.match(r"\s*newF\d\s*=", line):
                self.assertNotRegex(line, r"ta\.change\(")

    def test_no_inline_cross_in_loose_engine(self):
        for line in self.lines:
            if "buySignal" in line or "shortSignal" in line:
                self.assertNotRegex(line, r"ta\.crossover\(")
                self.assertNotRegex(line, r"ta\.crossunder\(")

    def test_cross_variables_defined(self):
        self.assertIn("crossClose_EmaF_up", self.text)
        self.assertIn("crossClose_EmaF_down", self.text)
        self.assertIn("crossClose_EmaS_up", self.text)
        self.assertIn("crossClose_EmaS_down", self.text)

    def test_neutral_tie_policy_implemented(self):
        # Check that Neutral policy sets doUpdate to false
        # We look for the specific block structure
        pattern = r'else if pathTiePolicy == "Neutral"[\s\S]{0,120}?(outcome := 0|doUpdate := false)'
        match = re.search(pattern, self.text)
        self.assertTrue(match, "Neutral tie policy logic not found or incorrect (should set doUpdate := false)")

    def test_table_formatting_logic(self):
        # Check for 3-way header usage
        self.assertIn('table.cell(gT, 5, 8, "Up(N)"', self.text)
        self.assertIn('table.cell(gT, 6, 8, "Flat(N)"', self.text)
        self.assertIn('table.cell(gT, 7, 8, "Down(N)"', self.text)
        self.assertRegex(self.text, r'table\.cell\(gT,\s*(8|11),\s*8,\s*"Label"')
        
        # Check targetDesc definition exists (multiline or single line)
        self.assertIn('targetDesc =', self.text)
        # Updated for Multi-Profile support
        self.assertIn('"Multi-Profile (See Settings). Fast: " + fcTargetF', self.text)
        
    def test_process_tf_signature(self):
        # Check that f_process_tf uses TfState pattern (_hid marks unused param)
        self.assertIn("f_process_tf(_hid, _tf, newTfBar, sA,", self.text)
        self.assertIn("TfState st,", self.text)
        self.assertIn("fcTgt, kB, aThr, pH, tpA, slA,", self.text)

    def test_evaluation_metrics_implementation(self):
        # Verify the presence of float(na) initialization which is critical for v6 type inference
        self.assertIn("ece = float(na)", self.text)
        self.assertIn("maxErr = float(na)", self.text)

        # Verify the gate logic for evaluation updates
        self.assertIn('canEval = (evalMode == "History+Live") or barstate.isrealtime', self.text)
        self.assertIn('if canEval', self.text)
        self.assertNotIn('if not canEval\n        return', self.text) # Should be removed

        # Check for Brier Score calculation function
        self.assertRegex(self.text, r"f_brier\(p, y\) =>")
        # f_brier uses d * d instead of math.pow
        self.assertIn("d = p - y", self.text)
        self.assertIn("d * d", self.text)

        # Check for Log Loss calculation function
        self.assertRegex(self.text, r"f_logloss\(p, y\) =>")
        self.assertIn("math.log(pc)", self.text)

        # Verify table helpers for evaluation are present (tbl param added to avoid global scope)
        self.assertIn("f_rowEval(tbl, tf, hid, rRow) =>", self.text)
        self.assertIn("f_eval_get(hid) =>", self.text)


    def test_forecast_readability_update(self):
        # Check for new input
        self.assertIn('fcDisplay = input.string("Up% (N)"', self.text)
        
        # Check for new pupText logic lines
        self.assertIn('"Warm " + str.tostring(n) + "/"', self.text)
        self.assertIn('fcDisplay == "Edge pp (N)"', self.text)
        
        # Check for target-specific forecast labels
        self.assertIn('f_target_label(tf)', self.text)
        self.assertIn('f_strength_label_fc(nBin)', self.text)
        


    def test_new_ui_helpers(self):
        # Verify CI/Reliability helpers are present (v6.1 UI)
        self.assertRegex(self.text, r"f_ci95_halfwidth\(p, n\) =>")
        self.assertRegex(self.text, r"f_rel_label\(p, nBin, total, canCal\) =>")

    def test_entryNow_replaced_by_cNow(self):
        # entryNow was a bug, should be replaced by cNow in f_process_tf
        # Now uses TfState st.qEntry etc
        self.assertNotRegex(self.text, r"array\.push\(qEntry,\s*entryNow\)")
        self.assertNotRegex(self.text, r"array\.push\(qMaxH,\s*entryNow\)")
        self.assertNotRegex(self.text, r"array\.push\(qMinL,\s*entryNow\)")
        # Verify cNow is used instead with st. prefix
        self.assertRegex(self.text, r"array\.push\(st\.qEntry,\s*cNow\)")
        self.assertRegex(self.text, r"array\.push\(st\.qMaxH,\s*cNow\)")
        self.assertRegex(self.text, r"array\.push\(st\.qMinL,\s*cNow\)")

    def test_calAlphaN_replaced_by_alphaN(self):
        # Regression test for undefined variable errors in f_process_tf calls
        undefined_vars = ["calAlphaN", "calAlpha1", "ens_wA", "ens_wB", "ens_wC"]
        for var in undefined_vars:
            self.assertNotRegex(self.text, fr"\b{var}\b", f"Found undefined variable '{var}' in text")

        # Verify TfState pattern is used in f_process_tf calls
        # Pattern: tf1State, (parameters)
        self.assertIn("tf1State,", self.text)
        self.assertIn("tf2State,", self.text)
        # Updated to 4-factor ensemble with wTrend
        self.assertIn("alphaN, alpha1, kShrink, wState, wPullback, wRegime, wTrend)", self.text)

    def test_div_by_zero_fix_f_pullback_score(self):
        # The line 'dist = (c - ef) / (na(atrVal) ? c*0.01 : atrVal)' was causing potential div by zero and was unused
        bad_line = r"dist\s*=\s*\(c\s*-\s*ef\)\s*/\s*\(na\(atrVal\)\s*\?\s*c\*0\.01\s*:\s*atrVal\)"
        self.assertNotRegex(self.text, bad_line, "Found potentially dangerous div-by-zero line in f_pullback_score")

    def test_reactive_arrays_sized_for_2d_binning(self):
        """
        Regression test for TfState architecture.
        Arrays are now encapsulated in TfState UDT, sized during initialization.
        """
        # Check that TfState is properly defined
        self.assertIn("type TfState", self.text)
        
        # Check for cnt1 and up1 fields in TfState (float arrays)
        self.assertIn("float[] cnt1", self.text)
        self.assertIn("float[] up1", self.text)
        
        # Check that f_init_tf_state creates properly sized arrays
        self.assertIn("f_init_tf_state(int nBinsN, int nBins1, int dim2, int evBuckets)", self.text)
        
        # Verify TfState instances are created
        self.assertIn("var TfState tf1State = f_init_tf_state(predBinsN, predBins1, dim2Bins, evalBuckets)", self.text)

    def test_ut_bot_overlay_presence(self):
        # Inputs
        self.assertIn("grpUt       = \"UT Bot Verification\"", self.text)
        self.assertIn("utShow      = input.bool(false, \"Show UT Bot Overlay\"", self.text)
        self.assertIn("utKey       = input.float(1.0, \"Key Value\"", self.text)
        self.assertIn("utAtrPeriod = input.int(10, \"ATR Period\"", self.text)
        self.assertIn("utUseHA     = input.bool(false, \"Use Heikin Ashi\"", self.text)

        # Core logic markers
        self.assertIn("utSrc = utUseHA ? request.security(ticker.heikinashi", self.text)
        self.assertIn("utXATR = ta.atr(utAtrPeriod)", self.text)
        self.assertIn("utNLoss = utKey * utXATR", self.text)
        self.assertIn("utXATRTrailingStop", self.text)
        self.assertIn("utBuy  = utSrc > utXATRTrailingStop and utAbove", self.text)
        self.assertIn("utSell = utSrc < utXATRTrailingStop and utBelow", self.text)

        # Visuals and alerts
        self.assertIn("plotshape(utShow and utBuy", self.text)
        self.assertIn("plotshape(utShow and utSell", self.text)
        self.assertIn("barcolor(utShow and utBarBuy", self.text)
        self.assertIn("alertcondition(utBuy,  \"UT Bot Long\"", self.text)
        self.assertIn("alertcondition(utSell, \"UT Bot Short\"", self.text)

    # ========== New tests for UX upgrades (v6.2) ==========

    def test_forecast_profile_helpers(self):
        """Test that forecast profile mapping functions are present."""
        # f_profile maps TF to Fast/Mid/Slow
        self.assertIn('f_profile(tf) =>', self.text)
        self.assertIn('"Fast"', self.text)
        self.assertIn('"Mid"', self.text)
        self.assertIn('"Slow"', self.text)
        
        # f_target_for_tf returns the active target type for that TF
        self.assertIn('f_target_for_tf(tf) =>', self.text)
        self.assertIn('prof == "Fast" ? fcTargetF', self.text)

    def test_target_label_function(self):
        """Test f_target_label returns human-readable labels."""
        self.assertIn('f_target_label(tf) =>', self.text)
        # Labels for each target type
        self.assertIn('"Next-up"', self.text)
        self.assertIn('"Up-close"', self.text)
        self.assertIn('"ATR-hit"', self.text)
        self.assertIn('"TP-first"', self.text)

    def test_uncertainty_band_helpers(self):
        """Test f_unc_pp for binomial CI calculation."""
        self.assertIn('f_unc_pp(p, n) =>', self.text)
        # Uses Z_95 constant for 95% CI
        self.assertIn('Z_95 * math.sqrt', self.text)

    def test_strength_label_fc_function(self):
        """Test sample-strength labeling for forecast display."""
        self.assertIn('f_strength_label_fc(nBin) =>', self.text)
        self.assertIn('nBin < calMinSamples ? "weak"', self.text)

    def test_prob_range_text_function(self):
        """Test probability range formatting like '34–46%'."""
        self.assertIn('f_prob_range_text(p, nBin) =>', self.text)
        # Check for bounded range calculation
        self.assertIn('lo = math.max(0.0, p - band)', self.text)
        self.assertIn('hi = math.min(1.0, p + band)', self.text)

    def test_chance_text_uses_target_label(self):
        """Test that f_chance_text shows target-specific labels."""
        # f_chance_text should call f_target_label
        self.assertIn('f_chance_text(tf, pUp, nBin, total, canCal) =>', self.text)
        self.assertIn('f_target_label(tf)', self.text)

    def test_data_text_uses_range_format(self):
        """Test that f_data_text shows explicit range instead of ±pp."""
        self.assertIn('f_data_text(pUp, nBin, total, canCal) =>', self.text)
        # Should call f_prob_range_text
        self.assertIn('rng = f_prob_range_text(pUp, nBin)', self.text)
        # Should NOT use old ± format in the output string (but comments are fine)
        # Check that we're not outputting ±pp format (old pattern)
        self.assertNotIn('str.tostring(hw * 100.0, "#.0") + "pp"', self.text)

    def test_tfstate_evaluation_fields(self):
        """Test TfState UDT contains all evaluation-related fields."""
        # Evaluation arrays for head N
        self.assertIn('float[] evBrierN', self.text)
        self.assertIn('float[] evLogN', self.text)
        self.assertIn('float[] evYS_N', self.text)
        self.assertIn('float[] evYL_N', self.text)
        self.assertIn('int[]   evCalCntN', self.text)
        # Evaluation arrays for head 1
        self.assertIn('float[] evBrier1', self.text)
        self.assertIn('float[] evLog1', self.text)

    def test_f_rowFc_passes_tf_parameter(self):
        """Test f_rowFc passes tf to display helpers."""
        self.assertIn('f_rowFc(tf, pN, nBinN, totN_, canN_, p1, nBin1, tot1_, can1_, rRow) =>', self.text)
        # Should use tf when calling helpers
        self.assertIn('txtChanceN = f_chance_text(tf, pN, nBinN, totN_, canN_)', self.text)
        self.assertIn('txtChance1 = f_chance_text(tf, p1, nBin1, tot1_, can1_)', self.text)

    def test_forecast_header_simplified(self):
        """Test forecast header uses 3-way labels."""
        self.assertIn('table.cell(gT, 5, 8, "Up(N)"', self.text)
        self.assertIn('table.cell(gT, 6, 8, "Flat(N)"', self.text)
        self.assertIn('table.cell(gT, 7, 8, "Down(N)"', self.text)

    def test_no_orphaned_global_arrays(self):
        """Regression: ensure old global arrays have been replaced by TfState."""
        # These old array names should NOT exist as standalone var declarations
        old_arrays = [
            "var int[] cntN1 =",
            "var int[] upN1 =",
            "var float[] qEntry1 =",
            "var float[] brierStatsN1 =",
        ]
        for arr in old_arrays:
            self.assertNotIn(arr, self.text, f"Found orphaned global array: {arr}")

    def test_f_eval_on_resolve_uses_tfstate(self):
        """Test evaluation scoring uses TfState parameter."""
        self.assertIn('f_eval_on_resolve(TfState st, pN, p1, isUpBool) =>', self.text)
        # Should reference st.evBrierN etc
        self.assertIn('st.evBrierN', self.text)
        self.assertIn('st.evSumBrierN', self.text)


if __name__ == "__main__":
    unittest.main()
