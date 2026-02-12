"""
Cross-Validation Tests: Indicator vs Strategy Consistency

This module validates that SkippALGO.pine (Indicator) and SkippALGO_Strategy.pine
produce consistent forecasts by checking structural and functional alignment.

What SHOULD match:
- All constants (PROB_EPS, VOL_THRESH_*, Z_95, etc.)
- Core functions (f_prob, f_logit, f_bin2D, f_ensemble, f_cal_cur, etc.)
- TfState UDT fields
- Calibration logic (Platt scaling, shrinkage)
- Forecast display calculations

What MAY differ:
- Entry/exit logic (Strategy has strategy.entry/exit calls)
- Signal generation (buySignal, shortSignal, etc.)
- Some display helpers (Strategy may omit some Indicator-only visuals)
"""
import unittest
import re
import os

INDICATOR_PATH = os.path.join(os.path.dirname(__file__), '..', 'SkippALGO.pine')
STRATEGY_PATH = os.path.join(os.path.dirname(__file__), '..', 'SkippALGO_Strategy.pine')


class TestIndicatorStrategyConsistency(unittest.TestCase):
    """Cross-validation tests between Indicator and Strategy."""
    
    @classmethod
    def setUpClass(cls):
        with open(INDICATOR_PATH, 'r') as f:
            cls.indicator = f.read()
        with open(STRATEGY_PATH, 'r') as f:
            cls.strategy = f.read()
    
    # ========================================
    # CONSTANTS CONSISTENCY
    # ========================================
    
    def test_constants_match(self):
        """All mathematical constants must be identical."""
        constants = [
            ('PROB_EPS', r'PROB_EPS\s*=\s*([\d.]+)'),
            ('VOL_THRESH_HIGH', r'VOL_THRESH_HIGH\s*=\s*([\d.]+)'),
            ('VOL_THRESH_LOW', r'VOL_THRESH_LOW\s*=\s*([\d.]+)'),
            ('Z_95', r'Z_95\s*=\s*([\d.]+)'),
            ('ROLL_RECALC_INTERVAL', r'ROLL_RECALC_INTERVAL\s*=\s*(\d+)'),
        ]
        
        for name, pattern in constants:
            ind_match = re.search(pattern, self.indicator)
            strat_match = re.search(pattern, self.strategy)
            
            self.assertIsNotNone(ind_match, f"Indicator missing constant: {name}")
            self.assertIsNotNone(strat_match, f"Strategy missing constant: {name}")
            
            ind_val = ind_match.group(1)
            strat_val = strat_match.group(1)
            self.assertEqual(ind_val, strat_val, 
                f"Constant {name} mismatch: Indicator={ind_val}, Strategy={strat_val}")
    
    def test_calibration_defaults_match(self):
        """Calibration parameters must have same defaults."""
        params = [
            ('alphaN', r'alphaN\s*=\s*input\.float\(([\d.]+)'),
            ('alpha1', r'alpha1\s*=\s*input\.float\(([\d.]+)'),
            ('calMinSamples', r'calMinSamples\s*=\s*input\.int\((\d+)'),
            ('predUpThr', r'predUpThr\s*=\s*input\.float\(([\d.]+)'),
            ('predDnThr', r'predDnThr\s*=\s*input\.float\(([\d.]+)'),
        ]
        
        for name, pattern in params:
            ind_match = re.search(pattern, self.indicator)
            strat_match = re.search(pattern, self.strategy)
            
            self.assertIsNotNone(ind_match, f"Indicator missing param: {name}")
            self.assertIsNotNone(strat_match, f"Strategy missing param: {name}")
            
            ind_val = ind_match.group(1)
            strat_val = strat_match.group(1)
            self.assertEqual(ind_val, strat_val, 
                f"Param {name} default mismatch: Indicator={ind_val}, Strategy={strat_val}")
    
    def test_ensemble_weights_match(self):
        """Ensemble weight variable names and defaults must match."""
        weights = [
            ('wState', r'wState\s*=\s*input\.float\(([\d.]+)'),
            ('wPullback', r'wPullback\s*=\s*input\.float\(([\d.]+)'),
            ('wRegime', r'wRegime\s*=\s*input\.float\(([\d.]+)'),
        ]
        
        for name, pattern in weights:
            ind_match = re.search(pattern, self.indicator)
            strat_match = re.search(pattern, self.strategy)
            
            self.assertIsNotNone(ind_match, f"Indicator missing weight: {name}")
            self.assertIsNotNone(strat_match, f"Strategy missing weight: {name}")
            
            ind_val = ind_match.group(1)
            strat_val = strat_match.group(1)
            self.assertEqual(ind_val, strat_val, 
                f"Weight {name} default mismatch: Indicator={ind_val}, Strategy={strat_val}")
    
    # ========================================
    # CORE FUNCTIONS CONSISTENCY
    # ========================================
    
    def test_f_prob_logic_match(self):
        """f_prob division guard must be identical."""
        pattern = r'f_prob\([^)]+\)\s*=>\s*\n\s*([^\n]+denom[^\n]+)\n\s*([^\n]+)'
        
        ind_match = re.search(pattern, self.indicator)
        strat_match = re.search(pattern, self.strategy)
        
        self.assertIsNotNone(ind_match, "Indicator missing f_prob")
        self.assertIsNotNone(strat_match, "Strategy missing f_prob")
        
        # Both should have the denom == 0.0 check
        self.assertIn('denom == 0.0 ? 0.5', self.indicator)
        self.assertIn('denom == 0.0 ? 0.5', self.strategy)
    
    def test_f_logit_uses_prob_eps(self):
        """f_logit must use PROB_EPS constant in both files."""
        # Check for PROB_EPS usage in f_logit
        pattern = r'f_logit\([^)]+\)\s*=>\s*\n\s*pc\s*=\s*math\.max\(PROB_EPS'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator f_logit should use PROB_EPS")
        self.assertRegex(self.strategy, pattern, 
            "Strategy f_logit should use PROB_EPS")
    
    def test_f_bin2D_boundary_logic_match(self):
        """f_bin2D must use quantile bins + regime binning in both files."""
        pattern_bin2d = r'f_bin2D\([^)]+\)\s*=>'
        pattern_quantile = r'f_bin_quantile\('
        pattern_regime = r'f_regime_bin\('
        pattern_flatten = r'int\(\s*\w+\s*\*\s*\w+\s*\+\s*\w+\s*\)'
        
        for content, name in ((self.indicator, "Indicator"), (self.strategy, "Strategy")):
            self.assertRegex(content, pattern_bin2d, f"{name} missing f_bin2D")
            self.assertRegex(content, pattern_quantile, f"{name} missing quantile binning")
            self.assertRegex(content, pattern_regime, f"{name} missing regime binning")
            self.assertRegex(content, pattern_flatten, f"{name} missing 2D flatten formula")
    
    def test_f_pct_rank_division_guard(self):
        """f_pct_rank must have hi==lo guard in both."""
        pattern = r'hi\s*==\s*lo\s*\?\s*0\.5'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator f_pct_rank should have hi==lo guard")
        self.assertRegex(self.strategy, pattern, 
            "Strategy f_pct_rank should have hi==lo guard")
    
    def test_f_ensemble_division_guard(self):
        """f_ensemble must have den==0 guard in both."""
        pattern = r'den\s*==\s*0\s*\?\s*0\.0'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator f_ensemble should have den==0 guard")
        self.assertRegex(self.strategy, pattern, 
            "Strategy f_ensemble should have den==0 guard")
    
    def test_f_clamp_exists_in_both(self):
        """f_clamp(val, lo, hi) must exist in both files."""
        pattern = r'f_clamp\(val,\s*lo,\s*hi\)\s*=>'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing f_clamp(val, lo, hi)")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing f_clamp(val, lo, hi)")
    
    # ========================================
    # TFSTATE UDT CONSISTENCY
    # ========================================
    
    def test_tfstate_fields_match(self):
        """TfState UDT must have same fields in both files."""
        # Extract TfState type definition block (up to next major section)
        pattern = r'type TfState\n([\s\S]+?)(?=\n(?://\s*Helper|f_init_tf_state|var TfState))'
        
        ind_match = re.search(pattern, self.indicator)
        strat_match = re.search(pattern, self.strategy)
        
        self.assertIsNotNone(ind_match, "Indicator missing TfState UDT")
        self.assertIsNotNone(strat_match, "Strategy missing TfState UDT")
        
        # Extract field names - capture 'type[]  fieldName' declarations
        field_pattern = r'(int|float)\[\]\s+(\w+)'
        ind_fields = set(re.findall(field_pattern, ind_match.group(1)))  # type: ignore
        strat_fields = set(re.findall(field_pattern, strat_match.group(1)))  # type: ignore
        
        # Core calibration fields must match
        core_fields = ['cntN', 'upN', 'cnt1', 'up1', 'plattN', 'platt1', 
                       'brierStatsN', 'brierStats1', 'llStatsN', 'llStats1']
        
        for field in core_fields:
            ind_has = any(f[1] == field for f in ind_fields)
            strat_has = any(f[1] == field for f in strat_fields)
            self.assertTrue(ind_has, f"Indicator TfState missing field: {field}")
            self.assertTrue(strat_has, f"Strategy TfState missing field: {field}")
    
    def test_f_init_tf_state_exists(self):
        """f_init_tf_state() helper must exist in both."""
        # Pattern accepts optional parameters
        pattern = r'f_init_tf_state\([^)]*\)\s*=>'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing f_init_tf_state()")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing f_init_tf_state()")
    
    def test_seven_tfstate_variables(self):
        """Both must have tf1State through tf7State."""
        for i in range(1, 8):
            var_name = f'tf{i}State'
            pattern = rf'var\s+TfState\s+{var_name}\s*='
            
            self.assertRegex(self.indicator, pattern, 
                f"Indicator missing {var_name}")
            self.assertRegex(self.strategy, pattern, 
                f"Strategy missing {var_name}")
    
    # ========================================
    # PLATT SCALING CONSISTENCY
    # ========================================
    
    def test_platt_scaling_functions_exist(self):
        """Platt scaling functions must exist in both."""
        functions = ['f_sigmoid', 'f_platt_prob']
        
        for func in functions:
            pattern = rf'{func}\([^)]+\)\s*=>'
            self.assertRegex(self.indicator, pattern, 
                f"Indicator missing {func}")
            self.assertRegex(self.strategy, pattern, 
                f"Strategy missing {func}")
    
    def test_platt_sgd_update_exists(self):
        """Platt SGD update logic must exist in both."""
        # Check for gradient descent update pattern (uses lrPlattEff with A2 momentum)
        pattern = r'a[N1]\s*:=\s*math\.max\([^)]+,\s*math\.min\([^)]+,\s*a[N1]\s*-\s*lrPlattEff\s*\*\s*(?:eff[Dd]a|da)'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing Platt SGD update")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing Platt SGD update")
    
    # ========================================
    # CALIBRATION DIAGNOSTICS CONSISTENCY
    # ========================================
    
    # NOTE: Calibration diagnostics panel removed from both files (token-limit reduction).
    # Tests test_diagnostics_panel_exists_in_indicator and
    # test_diagnostics_horizon_exists_in_indicator removed.

    # ========================================
    # EVALUATION METRICS CONSISTENCY
    # ========================================
    
    def test_evaluation_functions_exist(self):
        """Evaluation helper functions must exist in both."""
        functions = ['f_brier', 'f_logloss', 'f_eval_get']
        
        for func in functions:
            pattern = rf'{func}\([^)]+\)\s*=>'
            self.assertRegex(self.indicator, pattern, 
                f"Indicator missing {func}")
            self.assertRegex(self.strategy, pattern, 
                f"Strategy missing {func}")
    
    def test_fp_drift_prevention_exists(self):
        """FP drift prevention (ROLL_RECALC_INTERVAL) must be used in both."""
        pattern = r'bar_index\s*%\s*ROLL_RECALC_INTERVAL\s*==\s*0'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing FP drift prevention")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing FP drift prevention")
    
    # ========================================
    # TARGET CONFIGURATION CONSISTENCY
    # ========================================
    
    def test_target_profiles_exist(self):
        """Multi-profile target configurations must exist in both."""
        profiles = ['fcTargetF', 'fcTargetM', 'fcTargetS']
        
        for profile in profiles:
            pattern = rf'{profile}\s*=\s*input\.string'
            self.assertRegex(self.indicator, pattern, 
                f"Indicator missing {profile}")
            self.assertRegex(self.strategy, pattern, 
                f"Strategy missing {profile}")
    
    def test_f_get_params_exists(self):
        """f_get_params() helper for target selection must exist in both."""
        pattern = r'f_get_params\(tf\)\s*=>'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing f_get_params")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing f_get_params")


class TestIntentionalDifferences(unittest.TestCase):
    """Document and verify intentional differences between files."""
    
    @classmethod
    def setUpClass(cls):
        with open(INDICATOR_PATH, 'r') as f:
            cls.indicator = f.read()
        with open(STRATEGY_PATH, 'r') as f:
            cls.strategy = f.read()
    
    def test_strategy_has_strategy_calls(self):
        """Strategy must have strategy.entry/exit calls."""
        self.assertIn('strategy.entry', self.strategy)
        self.assertIn('strategy.close', self.strategy)
        self.assertNotIn('strategy.entry', self.indicator)
    
    def test_indicator_is_indicator(self):
        """Indicator must declare itself as indicator."""
        self.assertRegex(self.indicator, r'indicator\(')
        self.assertNotRegex(self.indicator, r'strategy\(')
    
    def test_strategy_is_strategy(self):
        """Strategy must declare itself as strategy."""
        self.assertRegex(self.strategy, r'strategy\(')
        self.assertNotRegex(self.strategy, r'^indicator\(', 
            msg="Strategy should not have indicator() at start")

    # ========================================
    # STRUCTURAL PARITY — inputs, alerts, duplicates
    # ========================================

    def test_input_count_parity(self):
        """Indicator and Strategy should have similar input.* declaration counts."""
        ind_inputs = len(re.findall(r'\binput\.\w+\s*\(', self.indicator))
        strat_inputs = len(re.findall(r'\binput\.\w+\s*\(', self.strategy))
        # Allow up to 10 extra inputs in Strategy (strategy-specific toggles)
        self.assertAlmostEqual(ind_inputs, strat_inputs, delta=10,
            msg=f"Input count diverged: Indicator={ind_inputs}, Strategy={strat_inputs}")

    def test_alert_titles_match(self):
        """Core alert titles (BUY/SHORT/EXIT/COVER) should exist in both files.
        Strategy may have additional alerts (e.g. Regime) that Indicator lacks."""
        ind_alerts = set(re.findall(r'alertcondition\([^,]+,\s*title\s*=\s*"([^"]+)"', self.indicator))
        strat_alerts = set(re.findall(r'alertcondition\([^,]+,\s*title\s*=\s*"([^"]+)"', self.strategy))
        # Every indicator alert title should also exist in the strategy
        missing_in_strat = ind_alerts - strat_alerts
        self.assertEqual(missing_in_strat, set(),
            f"Alert titles in Indicator but not Strategy: {missing_in_strat}")

    def test_no_duplicate_function_definitions(self):
        """Each function should be defined at most once per file (prevents copy-paste duplication)."""
        func_pattern = re.compile(r'^(\w+)\([^)]*\)\s*=>', re.MULTILINE)
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            funcs = func_pattern.findall(content)
            seen = {}
            duplicates = []
            for fn in funcs:
                if fn in seen:
                    duplicates.append(fn)
                seen[fn] = True
            self.assertEqual(duplicates, [],
                f"{name} has duplicate function definitions: {duplicates}")


class TestSignalParity(unittest.TestCase):
    """Verify signal-affecting logic matches between Indicator and Strategy."""

    @classmethod
    def setUpClass(cls):
        with open(INDICATOR_PATH, 'r') as f:
            cls.indicator = f.read()
        with open(STRATEGY_PATH, 'r') as f:
            cls.strategy = f.read()

    # -- useInfiniteTP regression --

    def test_useInfiniteTP_guards_tp_on_entry(self):
        """Both files must set tpPx := useInfiniteTP ? na : ... on entry."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            hits = re.findall(r'tpPx\s*:=\s*useInfiniteTP\s*\?\s*na\s*:', content)
            self.assertEqual(len(hits), 2,
                f"{name}: expected 2 useInfiniteTP guards on entry (long+short), found {len(hits)}")

    def test_useInfiniteTP_guards_risk_decay(self):
        """Both files must gate TP tightening behind 'if not useInfiniteTP' in risk decay."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            hits = re.findall(r'if not useInfiniteTP', content)
            self.assertGreaterEqual(len(hits), 2,
                f"{name}: expected >=2 useInfiniteTP guards in risk decay (long+short), found {len(hits)}")

    def test_f_risk_exit_hit_checks_na_tpVal(self):
        """f_risk_exit_hit must check 'not na(tpVal)' before testing TP hit."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('not na(tpVal)', content,
                f"{name}: f_risk_exit_hit must check 'not na(tpVal)' before TP evaluation")

    # -- Reclaim parity --

    def test_reclaim_logic_matches(self):
        """Reclaim logic should be identical between files (strict cross only)."""
        pattern = re.compile(r'reclaimUp\s*=\s*(.+)')
        i_match = pattern.search(self.indicator)
        s_match = pattern.search(self.strategy)
        self.assertIsNotNone(i_match, "Indicator: reclaimUp not found")
        self.assertIsNotNone(s_match, "Strategy: reclaimUp not found")
        self.assertEqual(i_match.group(1).strip(), s_match.group(1).strip(),
            "reclaimUp logic diverges between Indicator and Strategy")

    # -- Conflict resolution parity --

    def test_conflict_resolution_kills_both(self):
        """Both files must cancel both signals when buy+short fire simultaneously."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('if buySignal and shortSignal', content,
                f"{name}: conflict resolution block missing")
            # Should NOT have trend-aligned preference
            self.assertNotIn('if trendUpSmooth', content,
                f"{name}: conflict resolution should kill both, not prefer trend-aligned")

    # -- Zone formula correctness --

    def test_zone_pullback_uses_pbDir(self):
        """Pullback zone formula should use directional pbDir, not hardcoded signs."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('pbDir', content,
                f"{name}: Pullback zone should use pbDir for directional bands")
            # No-op ternary regression: the two branches must NOT be identical
            aggr_lines = [l.strip() for l in content.splitlines()
                          if 'aggrLower' in l and 'zoneMode' in l]
            for line in aggr_lines:
                parts = line.split('?')
                if len(parts) == 2:
                    sym_branch = parts[1].split(':')[0].strip()
                    pb_branch = parts[1].split(':')[1].strip() if ':' in parts[1] else ''
                    self.assertNotEqual(sym_branch, pb_branch,
                        f"{name}: aggrLower Symmetric and Pullback branches must differ")

    # -- EP invariant regression --

    def test_ep_negative_triggers_invariant_and_clamp(self):
        """When eligPending < 0, EP must display as 0 and invOk must be false."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # 1) EP display must clamp via math.max(eligPending, 0)
            self.assertIn('math.max(eligPending, 0)', content,
                f"{name}: EP display must clamp negative values via math.max(eligPending, 0)")
            # 2) epNeg must be derived from eligPending < 0
            self.assertIn('epNeg = eligPending < 0', content,
                f"{name}: epNeg flag must be set from eligPending < 0")
            # 3) invOk must include (not epNeg)
            inv_lines = [l for l in content.splitlines() if 'invOk' in l and 'epNeg' in l]
            self.assertTrue(len(inv_lines) >= 1,
                f"{name}: invOk must incorporate epNeg into invariant check")
            self.assertTrue(any('not epNeg' in l for l in inv_lines),
                f"{name}: invOk must include '(not epNeg)' to propagate EP<0 as invariant breach")

    def test_enqCountElig_same_predicate_as_qUseForecast(self):
        """enqCountElig must increment on the same predicate as qUseForecast push."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # Both should use the same eligibility expression
            fc_pushes = re.findall(
                r'array\.push\(st\.qUseForecast,\s*(.+)\)', content)
            elig_guards = re.findall(
                r'if\s+(.+?)\n\s+st\.enqCountElig\s*\+=\s*1', content)
            self.assertGreaterEqual(len(fc_pushes), 2,
                f"{name}: expected >=2 qUseForecast pushes, found {len(fc_pushes)}")
            self.assertGreaterEqual(len(elig_guards), 2,
                f"{name}: expected >=2 enqCountElig guards, found {len(elig_guards)}")
            # The predicate pushed into qUseForecast must match the guard on enqCountElig
            for push_val, guard_val in zip(fc_pushes, elig_guards):
                self.assertEqual(push_val.strip(), guard_val.strip(),
                    f"{name}: qUseForecast push predicate '{push_val.strip()}' != "
                    f"enqCountElig guard '{guard_val.strip()}'")

    # -- showOpsRow independence --

    def test_showOpsRow_input_exists(self):
        """Both files must have a showOpsRow input toggle."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('showOpsRow', content,
                f"{name}: showOpsRow input missing")
            self.assertRegex(content, r'showOpsRow\s*=\s*input\.bool\(true',
                f"{name}: showOpsRow must default to true")

    def test_ops_row_independent_of_showEvalSection(self):
        """Ops row must render outside showEvalSection when showOpsRow is true."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # Must have a code path: showOpsRow and not showEvalSection
            self.assertIn('showOpsRow and not showEvalSection', content,
                f"{name}: ops row must have independent render path")

    # -- INV! latch --

    def test_inv_latch_exists(self):
        """Both files must have INV! first-failure latch variables and logic."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('invLatched', content,
                f"{name}: invLatched variable missing")
            self.assertIn('invLatchInfo', content,
                f"{name}: invLatchInfo variable missing")
            self.assertIn('INV(L)', content,
                f"{name}: INV(L) latched display string missing")

    def test_inv_latch_reset_on_eval_reset(self):
        """INV latch must be cleared when eval is reset (resetWhich == 'All')."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # Find the reset block and confirm latch is cleared
            reset_block = content[content.find('if doReset'):content.find('if doReset') + 500]
            self.assertIn('invLatched := false', reset_block,
                f"{name}: invLatched must be reset in doReset/All block")
            self.assertIn('invLatchInfo := ""', reset_block,
                f"{name}: invLatchInfo must be cleared in doReset/All block")

    def test_inv_latch_snapshot_includes_tf(self):
        """INV latch snapshot string must include the horizon TF label."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # invLatchInfo assignment should reference entryFcTF
            latch_lines = [l for l in content.splitlines() if 'invLatchInfo' in l and 'entryFcTF' in l]
            self.assertGreaterEqual(len(latch_lines), 1,
                f"{name}: invLatchInfo snapshot must include entryFcTF for TF identification")

    # -- EP decomposition --

    def test_ep_decomposition_exists(self):
        """Both files must decompose EP into maturing (m:) and stuck (s:) components."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('stuckThresh', content,
                f"{name}: stuckThresh (resolve horizon for EP decomposition) missing")
            # Must have m: and s: in EP display
            self.assertRegex(content, r'm:.*s:',
                f"{name}: EP decomposition must show m:/s: breakdown")

    def test_ep_stuck_boundary_uses_strict_greater(self):
        """EP stuck classification must use > threshold (not >=) to avoid counting resolve-bar items."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # In EP decomposition loop, stuck must be: age > stuckThresh (not >=)
            # Find all lines that classify stuck in EP context
            stuck_lines = [l.strip() for l in content.splitlines()
                          if 'stuckThresh' in l and ('> ' in l or '>=' in l) and 'qAge' not in l and '==' not in l]
            # Lines that set stuckThresh are OK, we want the comparison lines
            compare_lines = [l.strip() for l in content.splitlines()
                            if ('> stuckThresh' in l or '>= stuckThresh' in l)]
            for line in compare_lines:
                self.assertNotIn('>= stuckThresh', line,
                    f"{name}: EP stuck must use '> stuckThresh' not '>= stuckThresh' "
                    f"(age == threshold means resolving this bar, not stuck)")

    def test_ops_row_shows_tf_label(self):
        """Ops row must display the horizon TF and target type for context."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('entryFcTF', content,
                f"{name}: ops row must reference entryFcTF")
            # Must show a target label (Next/KBar/ATR/Path)
            self.assertIn('opsTfLbl', content,
                f"{name}: ops row must compute opsTfLbl target label")

    # -- Dynamic footer row --

    def test_footer_row_is_dynamic(self):
        """Footer row must adjust position based on visible sections."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('footerR', content,
                f"{name}: footerR dynamic row variable missing")
            self.assertRegex(content, r'showEvalSection\s*\?\s*21',
                f"{name}: footer must be at row 21 when eval is shown")

    # -- qSync EP suppression --

    def test_ep_decomp_guarded_by_qsync(self):
        """EP decomposition loop + string must be suppressed when qSync=false."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # The EP loop must be gated on qSync (both full row and ops-only row)
            self.assertRegex(content, r'if\s+qSync\s+and\s+q(Depth|SzO|SzEp)\s*>\s*0',
                f"{name}: EP decomp loop must be gated on 'if qSync and qDepth/qSzO > 0'")
            # The decomposition string must also check qSync
            self.assertRegex(content, r'qSync\s+and\s+\(ep(Mature|Mat)\s*>\s*0',
                f"{name}: EP decomp string in full row must be gated on qSync")

    def test_ep_decomp_no_dangling_qSzEp(self):
        """qSzEp must not be referenced without a corresponding assignment."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            lines = content.splitlines()
            has_ref = any('qSzEp' in l and 'qSzEp' not in l.split('=')[0] if '=' in l else 'qSzEp' in l for l in lines)
            has_def = any('qSzEp' in l.split('=')[0] for l in lines if '=' in l and '//' not in l.split('=')[0])
            if has_ref:
                self.assertTrue(has_def,
                    f"{name}: qSzEp is referenced but never assigned — dangling variable")


if __name__ == '__main__':
    unittest.main()
