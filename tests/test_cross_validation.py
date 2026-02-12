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
        """Calibration helpers f_brier/f_logloss must exist in both files.
        
        NOTE: f_eval_get, f_rowEval removed from both files as part of the
        forecast table removal (Pine token limit compliance).
        """
        for func in ['f_brier', 'f_logloss']:
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

    # NOTE: test_ep_negative_triggers_invariant_and_clamp removed —
    #       EP display code (eligPendingRaw, epNeg, invOk) removed from
    #       both files as part of forecast table removal (token limit compliance).

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
    # NOTE: showOpsRow and ops row display removed from both files
    #       as part of forecast table removal (token limit compliance).

    # -- INV! latch --

    def test_inv_latch_exists(self):
        """Indicator must have INV! first-failure latch variables.
        
        NOTE: invLatched/invLatchInfo removed from Strategy with
        forecast table removal (token limit compliance).
        """
        self.assertIn('invLatched', self.indicator,
            "Indicator: invLatched variable missing")
        self.assertIn('invLatchInfo', self.indicator,
            "Indicator: invLatchInfo variable missing")

    def test_inv_latch_reset_on_eval_reset(self):
        """INV latch must be cleared when eval is reset (resetWhich == 'All').
        
        NOTE: Indicator only — latch removed from Strategy for token limit.
        """
        reset_block = self.indicator[self.indicator.find('if doReset'):self.indicator.find('if doReset') + 500]
        self.assertIn('invLatched := false', reset_block,
            "Indicator: invLatched must be reset in doReset/All block")
        self.assertIn('invLatchInfo := ""', reset_block,
            "Indicator: invLatchInfo must be cleared in doReset/All block")

    # -- EP decomposition --

    # NOTE: test_ep_decomposition_exists, test_ep_stuck_boundary_uses_strict_greater,
    #       and test_ops_row_shows_tf_label removed — EP decomposition display and
    #       ops row removed from both files for token limit compliance.

    # -- Dynamic footer row --

    def test_footer_row_is_fixed(self):
        """Footer row must be fixed at row 16 after forecast table removal."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertIn('merge_cells(gT, 0, 16, 4, 16)', content,
                f"{name}: footer must merge cells at fixed row 16")

    # -- qSync EP suppression --

    # NOTE: test_ep_decomp_guarded_by_qsync, test_ep_decomp_no_dangling_qSzEp,
    #       test_resolve_thresh_helper_exists, test_ep_naming_consistency,
    #       and test_eligpending_raw_clamped_split removed — EP decomposition
    #       display removed from both files for token limit compliance.

    # -- BUG 1 fix: Loose engine parity --

    def test_loose_engine_uses_enhOk(self):
        """Loose engine branch must include enhLongOk/enhShortOk in both files."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # Find the Loose engine block
            loose_idx = content.find('else // Loose')
            self.assertNotEqual(loose_idx, -1, f"{name}: Loose engine branch not found")
            # Get the ~200 chars after 'else // Loose' to capture both signal lines
            snippet = content[loose_idx:loose_idx+300]
            self.assertIn('enhLongOk', snippet,
                f"{name}: Loose engine buySignal missing 'enhLongOk'")
            self.assertIn('enhShortOk', snippet,
                f"{name}: Loose engine shortSignal missing 'enhShortOk'")

    # -- BUG 3 fix: barsSinceEntry decay alignment --

    def test_barsSinceEntry_zero_on_entry(self):
        """barsSinceEntry must be 0 (not 1) on entry bar → no decay on entry bar."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # The entry-bar assignment must be := 0
            self.assertRegex(content,
                r'if\s+pos\s*!=\s*pos\[1\]\s+and\s+pos\s*!=\s*0\s*\n\s*barsSinceEntry\s*:=\s*0',
                f"{name}: barsSinceEntry must be 0 on entry bar (not 1)")

    def test_canStructExit_uses_gte(self):
        """canStructExit must use >= (not >) to match 0-indexed barsSinceEntry."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            self.assertRegex(content,
                r'canStructExit\s*=\s*\(barsSinceEntry\s*>=\s*exitGraceBars\)',
                f"{name}: canStructExit must use >= with 0-indexed barsSinceEntry")

    # -- BUG 2 fix: RegSlope parity --

    def test_regslope_subsystem_exists_both(self):
        """RegSlope inputs, helpers, computation, and enhOk integration in both files."""
        for name, content in [("Indicator", self.indicator), ("Strategy", self.strategy)]:
            # Inputs
            self.assertIn('useRegSlope', content,
                f"{name}: useRegSlope input missing")
            self.assertIn('rsMaxRange', content,
                f"{name}: rsMaxRange input missing")
            self.assertIn('rsMinRange', content,
                f"{name}: rsMinRange input missing")
            # Helper functions
            self.assertIn('f_log_regression_single', content,
                f"{name}: f_log_regression_single helper missing")
            self.assertIn('f_calc_reg_slope_osc', content,
                f"{name}: f_calc_reg_slope_osc helper missing")
            # Computation vars
            self.assertIn('regSlopeLongOk', content,
                f"{name}: regSlopeLongOk variable missing")
            self.assertIn('regSlopeShortOk', content,
                f"{name}: regSlopeShortOk variable missing")
            # Safe coercion
            self.assertIn('regSlopeLongOkSafe', content,
                f"{name}: regSlopeLongOkSafe coercion missing")
            self.assertIn('regSlopeShortOkSafe', content,
                f"{name}: regSlopeShortOkSafe coercion missing")
            # Included in enhOk
            enh_long_idx = content.find('enhLongOk  =')
            self.assertNotEqual(enh_long_idx, -1, f"{name}: enhLongOk definition not found")
            enh_line = content[enh_long_idx:content.find('\n', enh_long_idx)]
            self.assertIn('regSlopeLongOkSafe', enh_line,
                f"{name}: enhLongOk must include regSlopeLongOkSafe")


if __name__ == '__main__':
    unittest.main()
