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
        # Check for gradient descent update pattern
        pattern = r'a[N1]\s*:=\s*math\.max\([^)]+,\s*math\.min\([^)]+,\s*a[N1]\s*-\s*lrPlatt\s*\*\s*da'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing Platt SGD update")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing Platt SGD update")
    
    # ========================================
    # CALIBRATION DIAGNOSTICS CONSISTENCY
    # ========================================
    
    def test_diagnostics_panel_exists_in_both(self):
        """Calibration diagnostics panel must exist in both."""
        pattern = r'showDiagPanel\s*=\s*input\.bool'
        
        self.assertRegex(self.indicator, pattern, 
            "Indicator missing diagnostics panel input")
        self.assertRegex(self.strategy, pattern, 
            "Strategy missing diagnostics panel input")
    
    def test_diagnostics_horizon_options_match(self):
        """Diagnostics horizon options must be identical."""
        pattern = r'diagHorizon\s*=\s*input\.string\("[^"]+",\s*"[^"]+",\s*options\s*=\s*\[([^\]]+)\]'
        
        ind_match = re.search(pattern, self.indicator)
        strat_match = re.search(pattern, self.strategy)
        
        self.assertIsNotNone(ind_match, "Indicator missing diagHorizon options")
        self.assertIsNotNone(strat_match, "Strategy missing diagHorizon options")
        
        self.assertEqual(ind_match.group(1), strat_match.group(1),
            "diagHorizon options mismatch between files")
    
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


if __name__ == '__main__':
    unittest.main()
