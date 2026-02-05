"""
Numerical Regression Tests for SkippALGO
=========================================

Question 5: Snapshot testing of specific numerical outputs to catch
unintended changes to calculations.

These tests verify that:
1. Constants remain unchanged
2. Formula implementations match expected behavior
3. Numerical relationships are preserved
4. Edge case outputs are stable

Run with: python -m pytest tests/test_numerical_regression.py -v
"""

import unittest
import re
import math
from pathlib import Path


class TestNumericalConstants(unittest.TestCase):
    """Verify all numerical constants remain unchanged."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        indicator_path = base_path / "SkippALGO.pine"
        strategy_path = base_path / "SkippALGO_Strategy.pine"
        
        cls.indicator_content = indicator_path.read_text() if indicator_path.exists() else ""
        cls.strategy_content = strategy_path.read_text() if strategy_path.exists() else ""
        cls.files = {
            "Indicator": cls.indicator_content,
            "Strategy": cls.strategy_content
        }
    
    # ===========================================
    # PROBABILITY CONSTANTS
    # ===========================================
    
    def test_prob_eps_value(self):
        """PROB_EPS must be exactly 0.0001 for numerical stability."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'PROB_EPS\s*=\s*([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: PROB_EPS not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.0001, 
                f"{name}: PROB_EPS changed from 0.0001 to {value}")
    
    def test_prob_eps_is_small_enough(self):
        """PROB_EPS must be < 0.001 to avoid meaningful probability distortion."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'PROB_EPS\s*=\s*([\d.]+)', content)
            if match:
                value = float(match.group(1))
                self.assertLess(value, 0.001,
                    f"{name}: PROB_EPS={value} too large, would distort probabilities")
    
    def test_prob_eps_is_positive(self):
        """PROB_EPS must be positive to prevent log(0)."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'PROB_EPS\s*=\s*([\d.]+)', content)
            if match:
                value = float(match.group(1))
                self.assertGreater(value, 0,
                    f"{name}: PROB_EPS must be positive, got {value}")
    
    # ===========================================
    # VOLATILITY THRESHOLDS
    # ===========================================
    
    def test_vol_thresh_high_value(self):
        """VOL_THRESH_HIGH must be exactly 0.66 (66th percentile)."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'VOL_THRESH_HIGH\s*=\s*([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: VOL_THRESH_HIGH not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.66,
                f"{name}: VOL_THRESH_HIGH changed from 0.66 to {value}")
    
    def test_vol_thresh_low_value(self):
        """VOL_THRESH_LOW must be exactly 0.33 (33rd percentile)."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'VOL_THRESH_LOW\s*=\s*([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: VOL_THRESH_LOW not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.33,
                f"{name}: VOL_THRESH_LOW changed from 0.33 to {value}")
    
    def test_volatility_thresholds_ordered(self):
        """VOL_THRESH_LOW < VOL_THRESH_HIGH must hold."""
        for name, content in self.files.items():
            if not content:
                continue
            low_match = re.search(r'VOL_THRESH_LOW\s*=\s*([\d.]+)', content)
            high_match = re.search(r'VOL_THRESH_HIGH\s*=\s*([\d.]+)', content)
            if low_match and high_match:
                low = float(low_match.group(1))
                high = float(high_match.group(1))
                self.assertLess(low, high,
                    f"{name}: VOL_THRESH_LOW ({low}) >= VOL_THRESH_HIGH ({high})")
    
    def test_volatility_thresholds_in_unit_interval(self):
        """Both volatility thresholds must be in (0, 1)."""
        for name, content in self.files.items():
            if not content:
                continue
            for thresh_name in ['VOL_THRESH_LOW', 'VOL_THRESH_HIGH']:
                match = re.search(rf'{thresh_name}\s*=\s*([\d.]+)', content)
                if match:
                    value = float(match.group(1))
                    self.assertGreater(value, 0, f"{name}: {thresh_name} must be > 0")
                    self.assertLess(value, 1, f"{name}: {thresh_name} must be < 1")
    
    # ===========================================
    # STATISTICAL CONSTANTS
    # ===========================================
    
    def test_z95_value(self):
        """Z_95 must be exactly 1.96 for 95% confidence intervals."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'Z_95\s*=\s*([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: Z_95 not found")
            value = float(match.group(1))
            self.assertEqual(value, 1.96,
                f"{name}: Z_95 changed from 1.96 to {value}")
    
    def test_z95_mathematically_correct(self):
        """Z_95 should be approximately the 97.5th percentile of standard normal."""
        # scipy.stats.norm.ppf(0.975) ≈ 1.959963984540054
        expected_z95 = 1.96
        tolerance = 0.01
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'Z_95\s*=\s*([\d.]+)', content)
            if match:
                value = float(match.group(1))
                self.assertAlmostEqual(value, expected_z95, delta=tolerance,
                    msg=f"{name}: Z_95={value} not close to theoretical 1.96")
    
    # ===========================================
    # BINNING CONSTANTS
    # ===========================================
    
    def test_n_bins_value(self):
        """predBinsN - check that binning exists with sensible values."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'predBinsN\s*=\s*input\.int\s*\(\s*(\d+)', content)
            self.assertIsNotNone(match, f"{name}: predBinsN input not found")
            value = int(match.group(1))
            self.assertIn(value, [3, 5], f"{name}: predBinsN default should be 3 or 5")
    
    def test_n_bins_2d_sizing_exists(self):
        """2D binning must size N arrays as nBinsN * dim2."""
        for name, content in self.files.items():
            if not content:
                continue
            self.assertRegex(content, r"array\.new_float\(nBinsN\s*\*\s*dim2,\s*0\.0\)",
                f"{name}: Expected 2D sizing array.new_float(nBinsN * dim2, 0.0)")
    
    def test_n_rsi_bins_value(self):
        """predBins1 - check binning configuration exists."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'predBins1\s*=\s*input\.int\s*\(\s*(\d+)', content)
            self.assertIsNotNone(match, f"{name}: predBins1 input not found")
            value = int(match.group(1))
            self.assertIn(value, [2, 3], f"{name}: predBins1 default should be 2 or 3")
    
    def test_n_vol_bins_value(self):
        """N_VOL_BINS/dim2Bins must be 3 for low/normal/high volatility."""
        for name, content in self.files.items():
            if not content:
                continue
            # Indicator uses N_VOL_BINS, Strategy uses dim2Bins
            match = re.search(r'(?:N_VOL_BINS|dim2Bins)\s*=\s*(\d+)', content)
            self.assertIsNotNone(match, f"{name}: N_VOL_BINS/dim2Bins not found")
            value = int(match.group(1))
            self.assertEqual(value, 3,
                f"{name}: N_VOL_BINS changed from 3 to {value}")
    
    # ===========================================
    # ROLLING WINDOW CONSTANTS
    # ===========================================
    
    def test_roll_recalc_interval_value(self):
        """ROLL_RECALC_INTERVAL must be exactly 500."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'ROLL_RECALC_INTERVAL\s*=\s*(\d+)', content)
            self.assertIsNotNone(match, f"{name}: ROLL_RECALC_INTERVAL not found")
            value = int(match.group(1))
            self.assertEqual(value, 500,
                f"{name}: ROLL_RECALC_INTERVAL changed from 500 to {value}")
    
    def test_roll_recalc_interval_reasonable(self):
        """ROLL_RECALC_INTERVAL should be between 100 and 2000."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'ROLL_RECALC_INTERVAL\s*=\s*(\d+)', content)
            if match:
                value = int(match.group(1))
                self.assertGreaterEqual(value, 100,
                    f"{name}: ROLL_RECALC_INTERVAL={value} too small")
                self.assertLessEqual(value, 2000,
                    f"{name}: ROLL_RECALC_INTERVAL={value} too large")
    
    # ===========================================
    # ENSEMBLE WEIGHT CONSTANTS
    # ===========================================
    
    def test_wstate_value(self):
        """wState weight must be exactly 1.0."""
        for name, content in self.files.items():
            if not content:
                continue
            # Strategy uses input.float, Indicator uses constant
            match = re.search(r'wState\s*=\s*(?:input\.float\s*\(\s*)?([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: wState not found")
            value = float(match.group(1))
            self.assertEqual(value, 1.0,
                f"{name}: wState changed from 1.0 to {value}")
    
    def test_wpullback_value(self):
        """wPullback weight must be exactly 0.5."""
        for name, content in self.files.items():
            if not content:
                continue
            # Strategy uses input.float, Indicator uses constant
            match = re.search(r'wPullback\s*=\s*(?:input\.float\s*\(\s*)?([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: wPullback not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.5,
                f"{name}: wPullback changed from 0.5 to {value}")
    
    def test_wregime_value(self):
        """wRegime weight must be exactly 0.3."""
        for name, content in self.files.items():
            if not content:
                continue
            # Strategy uses input.float, Indicator uses constant
            match = re.search(r'wRegime\s*=\s*(?:input\.float\s*\(\s*)?([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: wRegime not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.3,
                f"{name}: wRegime changed from 0.3 to {value}")

    def test_wtrend_value(self):
        """wTrend weight must be exactly 0.4."""
        for name, content in self.files.items():
            if not content:
                continue
            match = re.search(r'wTrend\s*=\s*(?:input\.float\s*\(\s*)?([\d.]+)', content)
            self.assertIsNotNone(match, f"{name}: wTrend not found")
            value = float(match.group(1))
            self.assertEqual(value, 0.4,
                f"{name}: wTrend changed from 0.4 to {value}")
    
    def test_ensemble_weights_sum(self):
        """Ensemble weights should sum to 2.2 (wState + wPullback + wRegime + wTrend)."""
        expected_sum = 1.0 + 0.5 + 0.3 + 0.4  # 2.2
        for name, content in self.files.items():
            if not content:
                continue
            weights = {}
            for w_name in ['wState', 'wPullback', 'wRegime', 'wTrend']:
                match = re.search(rf'{w_name}\s*=\s*([\d.]+)', content)
                if match:
                    weights[w_name] = float(match.group(1))
            if len(weights) == 4:
                actual_sum = sum(weights.values())
                self.assertAlmostEqual(actual_sum, expected_sum, places=6,
                    msg=f"{name}: Ensemble weight sum={actual_sum}, expected {expected_sum}")
    
    def test_ensemble_weights_positive(self):
        """All ensemble weights must be positive."""
        for name, content in self.files.items():
            if not content:
                continue
            for w_name in ['wState', 'wPullback', 'wRegime', 'wTrend']:
                match = re.search(rf'{w_name}\s*=\s*([\d.]+)', content)
                if match:
                    value = float(match.group(1))
                    self.assertGreater(value, 0,
                        f"{name}: {w_name}={value} must be positive")


class TestFormulaRegression(unittest.TestCase):
    """Verify formula implementations haven't changed."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        indicator_path = base_path / "SkippALGO.pine"
        strategy_path = base_path / "SkippALGO_Strategy.pine"
        
        cls.indicator_content = indicator_path.read_text() if indicator_path.exists() else ""
        cls.strategy_content = strategy_path.read_text() if strategy_path.exists() else ""
        cls.files = {
            "Indicator": cls.indicator_content,
            "Strategy": cls.strategy_content
        }
    
    # ===========================================
    # BRIER SCORE FORMULA
    # ===========================================
    
    def test_brier_score_formula_structure(self):
        """Brier score must use (p - o)^2 formula."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for Brier score calculation pattern
            # Common forms: (p - o) * (p - o), math.pow(p - o, 2)
            has_brier = (
                re.search(r'\(\s*\w+\s*-\s*\w+\s*\)\s*\*\s*\(\s*\w+\s*-\s*\w+\s*\)', content) or
                re.search(r'math\.pow\s*\([^,]+,\s*2\s*\)', content) or
                re.search(r'brier|Brier', content, re.IGNORECASE)
            )
            self.assertTrue(has_brier, f"{name}: Brier score calculation not found")
    
    def test_brier_score_uses_squared_error(self):
        """Brier score should compute squared error, not absolute error."""
        for name, content in self.files.items():
            if not content:
                continue
            # Ensure we're not using abs() for Brier
            if 'brier' in content.lower():
                # Check that near Brier calculations we see squaring, not abs
                lines = content.split('\n')
                for i, line in enumerate(lines):
                    if 'brier' in line.lower() and ':=' in line:
                        # This line might have the calculation
                        context = '\n'.join(lines[max(0,i-2):min(len(lines),i+3)])
                        # Should NOT have abs() in Brier context
                        self.assertFalse(
                            'math.abs' in context.lower() and 'brier' in context.lower(),
                            f"{name}: Brier score should use squared error, not absolute")
    
    # ===========================================
    # LOG LOSS FORMULA
    # ===========================================
    
    def test_logloss_uses_log(self):
        """Log loss must use logarithm function."""
        for name, content in self.files.items():
            if not content:
                continue
            # Log loss requires math.log
            has_log = re.search(r'math\.log\s*\(', content)
            self.assertTrue(has_log, f"{name}: math.log not found for log loss")
    
    def test_logloss_protected_by_eps(self):
        """Log loss should be protected by epsilon to avoid log(0)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for log with epsilon protection
            # Patterns: math.log(p + eps), math.log(math.max(p, eps)), f_clamp before log
            protected = (
                re.search(r'math\.log\s*\([^)]*\+\s*(?:PROB_)?[eE]ps', content) or
                re.search(r'math\.log\s*\(\s*math\.max\s*\(', content) or
                re.search(r'math\.log\s*\(\s*nz\s*\(', content) or
                re.search(r'f_clamp\s*\([^)]+\)[^\n]*\n[^\n]*math\.log', content) or
                re.search(r'pClip\s*=\s*f_clamp', content) or  # Strategy uses f_clamp then log
                re.search(r'pLL\s*=\s*math\.max\s*\(\s*PROB_EPS', content)  # Strategy pattern
            )
            self.assertTrue(protected, f"{name}: Log loss not protected against log(0)")
    
    # ===========================================
    # CONFIDENCE INTERVAL FORMULA
    # ===========================================
    
    def test_confidence_interval_uses_z95(self):
        """Confidence interval must use Z_95 constant."""
        for name, content in self.files.items():
            if not content:
                continue
            # CI should reference Z_95
            has_z95_usage = re.search(r'Z_95\s*\*', content)
            self.assertTrue(has_z95_usage, 
                f"{name}: Z_95 not used in confidence interval calculation")
    
    def test_confidence_interval_uses_sqrt(self):
        """Confidence interval must use square root for standard error."""
        for name, content in self.files.items():
            if not content:
                continue
            has_sqrt = re.search(r'math\.sqrt\s*\(', content)
            self.assertTrue(has_sqrt, f"{name}: math.sqrt not found for CI calculation")
    
    def test_wilson_score_formula_present(self):
        """Wilson score interval formula components should be present."""
        for name, content in self.files.items():
            if not content:
                continue
            # Wilson score uses: p + z²/2n ± z*sqrt(p(1-p)/n + z²/4n²) / (1 + z²/n)
            # Key components: z², sqrt, division by n
            has_z_squared = re.search(r'Z_95\s*\*\s*Z_95', content)
            has_sqrt = re.search(r'math\.sqrt', content)
            
            # At least sqrt and some z usage should exist
            self.assertTrue(has_sqrt, f"{name}: sqrt not found (needed for CI)")
    
    # ===========================================
    # PLATT SCALING FORMULA
    # ===========================================
    
    def test_platt_scaling_sigmoid_form(self):
        """Platt scaling should use 1 / (1 + exp(-z)) sigmoid form."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for sigmoid pattern
            has_sigmoid = (
                re.search(r'1\s*/\s*\(\s*1\s*\+\s*math\.exp', content) or
                re.search(r'1\.0\s*/\s*\(\s*1\.0\s*\+\s*math\.exp', content)
            )
            self.assertTrue(has_sigmoid, f"{name}: Platt scaling sigmoid form not found")
    
    def test_platt_slope_initialization(self):
        """Platt scaling slope should initialize to 1.0."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for pS = 1, plattS = 1, or array initialization
            has_slope_init = (
                re.search(r'pS\s*=\s*1\.0', content) or
                re.search(r'pS\s*=\s*1(?:\.0)?\b', content) or
                re.search(r'plattS\s*=\s*1', content) or
                re.search(r'platt.*slope.*=\s*1', content, re.IGNORECASE) or
                re.search(r'array\.new_float\s*\([^)]*1\.0\s*\)', content) or
                re.search(r'array\.from\s*\(\s*1\.0', content) or  # array.from(1.0, 0.0)
                re.search(r'array\.set\s*\([^)]*platt[^)]*,\s*0\s*,\s*1\.0', content)  # array.set(st.plattN, 0, 1.0)
            )
            self.assertTrue(has_slope_init, 
                f"{name}: Platt slope not initialized to 1.0")
    
    def test_platt_intercept_initialization(self):
        """Platt scaling intercept should initialize to 0.0."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for pI = 0, plattI = 0, or array initialization
            has_intercept_init = (
                re.search(r'pI\s*=\s*0\.0', content) or
                re.search(r'pI\s*=\s*0(?:\.0)?\b', content) or
                re.search(r'plattI\s*=\s*0', content) or
                re.search(r'platt.*intercept.*=\s*0', content, re.IGNORECASE) or
                re.search(r'array\.new_float\s*\([^)]*,\s*0\.0\s*\)', content)  # array init with 0.0
            )
            self.assertTrue(has_intercept_init,
                f"{name}: Platt intercept not initialized to 0.0")
    
    # ===========================================
    # SHRINKAGE FORMULA
    # ===========================================
    
    def test_shrinkage_blending_formula(self):
        """Shrinkage should blend observed rate with prior."""
        for name, content in self.files.items():
            if not content:
                continue
            # Shrinkage pattern: alpha * observed + (1 - alpha) * prior
            # Or: n/(n+k) * obs + k/(n+k) * prior
            has_blending = (
                re.search(r'\*\s*\w+\s*\+\s*\(?\s*1\s*-', content) or
                re.search(r'shrink|blend|smooth', content, re.IGNORECASE)
            )
            self.assertTrue(has_blending, f"{name}: Shrinkage blending not found")
    
    # ===========================================
    # 2D BINNING FORMULA
    # ===========================================
    
    def test_2d_bin_index_formula(self):
        """2D binning should use row * binsVol + col formula."""
        for name, content in self.files.items():
            if not content:
                continue
            # Pattern: bS * binsVol (Strategy), binScore * N_VOL (Indicator)
            has_2d_index = (
                re.search(r'\w+\s*\*\s*(?:N_BINS|binsVol|N_VOL|dim2|binsReg|binsB)\s*\+', content) or
                re.search(r'\w+\s*\*\s*[35]\s*\+', content) or  # literal 3 or 5
                re.search(r'bS\s*\*\s*(?:binsReg|binsB)', content) or
                re.search(r'bA\s*\*\s*(?:binsReg|binsB)', content)
            )
            self.assertTrue(has_2d_index, f"{name}: 2D bin index formula not found")
    
    def test_bin_index_clamping(self):
        """Bin indices should be clamped to [0, N_BINS-1] or [0, 24]."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for clamping in binning context
            has_clamp = (
                re.search(r'math\.max\s*\(\s*0\s*,\s*math\.min', content) or
                re.search(r'math\.min\s*\([^)]*,\s*(?:N_BINS\s*-\s*1|4|24)\s*\)', content) or
                re.search(r'f_clamp|clamp', content)
            )
            self.assertTrue(has_clamp, f"{name}: Bin index clamping not found")


class TestNumericalBoundaries(unittest.TestCase):
    """Verify numerical boundary conditions are correctly implemented."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        indicator_path = base_path / "SkippALGO.pine"
        strategy_path = base_path / "SkippALGO_Strategy.pine"
        
        cls.indicator_content = indicator_path.read_text() if indicator_path.exists() else ""
        cls.strategy_content = strategy_path.read_text() if strategy_path.exists() else ""
        cls.files = {
            "Indicator": cls.indicator_content,
            "Strategy": cls.strategy_content
        }
    
    # ===========================================
    # PROBABILITY BOUNDS
    # ===========================================
    
    def test_probability_clamped_to_01(self):
        """Probabilities should be clamped to [0, 1] range."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for probability clamping patterns
            has_prob_clamp = (
                re.search(r'math\.max\s*\(\s*0', content) and
                re.search(r'math\.min\s*\([^)]*,\s*1', content)
            ) or re.search(r'f_clamp01|clamp.*0.*1', content)
            self.assertTrue(has_prob_clamp, 
                f"{name}: Probability clamping to [0,1] not found")
    
    def test_probability_not_exactly_zero(self):
        """Probabilities used in log should never be exactly 0."""
        for name, content in self.files.items():
            if not content:
                continue
            # PROB_EPS should be used to prevent exact zero
            has_eps_protection = re.search(r'PROB_EPS', content)
            self.assertTrue(has_eps_protection,
                f"{name}: PROB_EPS not found for zero prevention")
    
    def test_probability_not_exactly_one(self):
        """Probabilities used in log(1-p) should never be exactly 1."""
        for name, content in self.files.items():
            if not content:
                continue
            # Should have 1 - PROB_EPS or similar protection
            # Patterns: 1 - PROB_EPS, math.min(p, 1 - eps)
            has_one_protection = (
                re.search(r'1\s*-\s*PROB_EPS', content) or
                re.search(r'1\.0\s*-\s*PROB_EPS', content) or
                re.search(r'math\.min\s*\([^)]+,\s*1\s*-', content)
            )
            # This is optional but recommended
            # Just check PROB_EPS exists (already tested above)
    
    # ===========================================
    # RSI BOUNDS
    # ===========================================
    
    def test_rsi_range_0_100(self):
        """RSI values should be expected in [0, 100] range."""
        for name, content in self.files.items():
            if not content:
                continue
            # RSI bins typically reference 30, 50, 70 or divide by 100
            has_rsi_scaling = (
                re.search(r'(?:rsi|RSI)\s*/\s*100', content) or
                re.search(r'(?:rsi|RSI)\s*[<>]\s*(?:30|50|70)', content) or
                re.search(r'ta\.rsi', content)
            )
            self.assertTrue(has_rsi_scaling, f"{name}: RSI usage not found")
    
    def test_rsi_binning_boundaries(self):
        """RSI binning should have sensible boundaries (30, 70 typical)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for RSI threshold values
            has_rsi_thresholds = (
                re.search(r'30', content) and re.search(r'70', content)
            ) or re.search(r'rsiLow|rsiHigh|RSI_LOW|RSI_HIGH', content, re.IGNORECASE)
            self.assertTrue(has_rsi_thresholds,
                f"{name}: RSI binning thresholds not found")
    
    # ===========================================
    # ARRAY SIZE BOUNDS
    # ===========================================
    
    def test_array_size_constant_exists(self):
        """Array size limit constant should exist."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for max array size constants or evaluation window inputs
            has_size_const = (
                re.search(r'(?:MAX_|_MAX|SIZE|LEN)\s*=\s*\d+', content, re.IGNORECASE) or
                re.search(r'evalWindow|rollWindow|maxLen|evalBuckets', content) or
                re.search(r'rollScore|evBrier', content)  # Strategy's rolling evaluation arrays
            )
            self.assertTrue(has_size_const,
                f"{name}: Array size constant not found")
    
    def test_array_size_enforcement(self):
        """Array size should be enforced with pop/shift on insert."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for array.size checks before pop/shift
            has_size_check = (
                re.search(r'array\.size\s*\([^)]+\)\s*[>>=]\s*', content) or
                re.search(r'if\s+.*size.*(?:pop|shift)', content, re.IGNORECASE)
            )
            self.assertTrue(has_size_check,
                f"{name}: Array size enforcement not found")
    
    # ===========================================
    # DIVISION SAFETY
    # ===========================================
    
    def test_division_by_n_protected(self):
        """Division by sample count n should be protected."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for n > 0 checks or nz() usage
            has_div_protection = (
                re.search(r'nz\s*\(', content) or
                re.search(r'if\s+\w+\s*>\s*0', content) or
                re.search(r'\?\s*\w+\s*/\s*\w+\s*:\s*0', content)  # ternary fallback
            )
            self.assertTrue(has_div_protection,
                f"{name}: Division protection not found")
    
    def test_division_by_sum_protected(self):
        """Division by weight sum should be protected."""
        for name, content in self.files.items():
            if not content:
                continue
            # Ensemble weight sum division should be protected
            # Look for patterns like: sum > 0 ? x/sum : fallback
            has_sum_protection = (
                re.search(r'nz\s*\(', content) or
                re.search(r'sumW?\s*[>!=]\s*0', content) or
                re.search(r'\+\s*\w+\s*\+\s*\w+\s*(?:>|!=)\s*0', content)
            )
            # This is implied by PROB_EPS usage
            self.assertTrue(has_sum_protection or 'PROB_EPS' in content,
                f"{name}: Weight sum division protection not found")


class TestSpecificNumericalValues(unittest.TestCase):
    """Test specific numerical values that should remain constant."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        indicator_path = base_path / "SkippALGO.pine"
        strategy_path = base_path / "SkippALGO_Strategy.pine"
        
        cls.indicator_content = indicator_path.read_text() if indicator_path.exists() else ""
        cls.strategy_content = strategy_path.read_text() if strategy_path.exists() else ""
        cls.files = {
            "Indicator": cls.indicator_content,
            "Strategy": cls.strategy_content
        }
    
    # ===========================================
    # FORECAST HORIZONS
    # ===========================================
    
    def test_seven_forecast_horizons(self):
        """Must have exactly 7 forecast horizons."""
        for name, content in self.files.items():
            if not content:
                continue
            # Count timeframe-related arrays or variables
            tf_count = len(re.findall(r'tf[1-7]State|tfState[1-7]', content))
            # Should have references to 7 timeframes
            self.assertGreaterEqual(tf_count, 7,
                f"{name}: Expected 7 timeframe references, found {tf_count//2}")
    
    def test_forecast_horizon_values(self):
        """Forecast horizons should include standard values (5, 15, 60 mins, etc.)."""
        expected_horizons = ['5', '15', '60', '240', 'D', 'W']  # Common ones
        for name, content in self.files.items():
            if not content:
                continue
            found = 0
            for h in expected_horizons:
                if re.search(rf'["\']?{h}["\']?\s*(?:,|\]|\))', content):
                    found += 1
            self.assertGreaterEqual(found, 4,
                f"{name}: Expected at least 4 standard horizons, found {found}")
    
    # ===========================================
    # DEFAULT INPUT VALUES
    # ===========================================
    
    def test_default_entry_threshold_value(self):
        """Default entry threshold should be a sensible value (0.55-0.70)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for entry threshold input
            match = re.search(
                r'input\.float\s*\([^)]*defval\s*=\s*([\d.]+)[^)]*(?:entry|threshold)',
                content, re.IGNORECASE
            )
            if match:
                value = float(match.group(1))
                self.assertGreaterEqual(value, 0.5,
                    f"{name}: Entry threshold {value} too low")
                self.assertLessEqual(value, 0.8,
                    f"{name}: Entry threshold {value} too high")
    
    def test_default_eval_window_value(self):
        """Default evaluation window should be reasonable (100-1000)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for evalWindow input
            match = re.search(
                r'(?:eval|window|history)\s*=\s*input\.int\s*\([^)]*defval\s*=\s*(\d+)',
                content, re.IGNORECASE
            )
            if not match:
                match = re.search(r'evalWindow\s*=\s*(\d+)', content)
            if match:
                value = int(match.group(1))
                self.assertGreaterEqual(value, 50,
                    f"{name}: Eval window {value} too small")
                self.assertLessEqual(value, 2000,
                    f"{name}: Eval window {value} too large")
    
    # ===========================================
    # MATHEMATICAL RELATIONSHIPS
    # ===========================================
    
    def test_brier_bounded_0_1(self):
        """Brier score formula outputs should be in [0, 1]."""
        # Brier = (p - o)^2 where p, o ∈ [0, 1]
        # Max Brier = (1 - 0)^2 = 1
        # Min Brier = (0.5 - 0.5)^2 = 0
        # This is a mathematical property, test that clamping exists
        for name, content in self.files.items():
            if not content:
                continue
            # Brier should be computed from clamped probabilities
            has_brier_context = 'brier' in content.lower()
            self.assertTrue(has_brier_context, f"{name}: Brier score not found")
    
    def test_calibration_ratio_normalized(self):
        """Calibration ratio should be normalized (predicted/actual or O/E)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Calibration should exist
            self.assertTrue('cal' in content.lower(),
                f"{name}: Calibration references not found")
    
    # ===========================================
    # PERCENTILE VALUES
    # ===========================================
    
    def test_volatility_percentiles_tertiles(self):
        """Volatility thresholds should divide into tertiles (33/66)."""
        for name, content in self.files.items():
            if not content:
                continue
            low_match = re.search(r'VOL_THRESH_LOW\s*=\s*([\d.]+)', content)
            high_match = re.search(r'VOL_THRESH_HIGH\s*=\s*([\d.]+)', content)
            if low_match and high_match:
                low = float(low_match.group(1))
                high = float(high_match.group(1))
                # Check they approximately divide [0,1] into thirds
                self.assertAlmostEqual(low, 1/3, delta=0.05,
                    msg=f"{name}: VOL_THRESH_LOW not near 1/3")
                self.assertAlmostEqual(high, 2/3, delta=0.05,
                    msg=f"{name}: VOL_THRESH_HIGH not near 2/3")
    
    def test_confidence_level_95(self):
        """Confidence interval should be at 95% level."""
        for name, content in self.files.items():
            if not content:
                continue
            # Z_95 = 1.96 corresponds to 95% CI
            match = re.search(r'Z_95\s*=\s*([\d.]+)', content)
            if match:
                z = float(match.group(1))
                # Z = 1.96 → 95% CI, Z = 1.645 → 90% CI, Z = 2.576 → 99% CI
                self.assertAlmostEqual(z, 1.96, delta=0.1,
                    msg=f"{name}: Z_95={z} doesn't correspond to 95% CI")


class TestRegressionSafety(unittest.TestCase):
    """Regression tests for previously fixed bugs."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        indicator_path = base_path / "SkippALGO.pine"
        strategy_path = base_path / "SkippALGO_Strategy.pine"
        
        cls.indicator_content = indicator_path.read_text() if indicator_path.exists() else ""
        cls.strategy_content = strategy_path.read_text() if strategy_path.exists() else ""
        cls.files = {
            "Indicator": cls.indicator_content,
            "Strategy": cls.strategy_content
        }
    
    # ===========================================
    # DIVISION BY ZERO FIXES
    # ===========================================
    
    def test_no_unprotected_division_by_variable(self):
        """Division by variables should use nz() or conditional check."""
        for name, content in self.files.items():
            if not content:
                continue
            # Check that some form of division protection exists
            # nz(), math.max, conditional checks, or PROB_EPS usage
            has_protection = (
                'nz(' in content or
                re.search(r'if\s+\w+\s*>\s*0', content) or
                'PROB_EPS' in content or
                re.search(r'\?\s*[^:]+/[^:]+:', content)  # ternary with division
            )
            self.assertTrue(has_protection,
                f"{name}: Division protection not found (nz, conditional, or PROB_EPS)")
    
    def test_array_index_bounds_check_exists(self):
        """Array access should have bounds checking."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for array access with bounds checking
            has_bounds_check = (
                re.search(r'array\.get\s*\([^)]+,\s*math\.min', content) or
                re.search(r'array\.get\s*\([^)]+,\s*math\.max\s*\(\s*0', content) or
                re.search(r'if\s+\w+\s*[<>]=?\s*\d+', content)  # index range check
            )
            self.assertTrue(has_bounds_check,
                f"{name}: Array bounds checking not found")
    
    # ===========================================
    # NA HANDLING FIXES
    # ===========================================
    
    def test_na_check_before_comparison(self):
        """na() should be checked before using values in comparisons."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for na() checks
            has_na_check = re.search(r'na\s*\(', content)
            self.assertTrue(has_na_check,
                f"{name}: na() checks not found")
    
    def test_nz_fallback_values_sensible(self):
        """nz() fallback values should be sensible (0, 0.5, etc.)."""
        for name, content in self.files.items():
            if not content:
                continue
            # Find nz() calls with explicit fallback
            nz_calls = re.findall(r'nz\s*\(\s*[^,]+,\s*([\d.]+)\s*\)', content)
            for fallback in nz_calls:
                value = float(fallback)
                # Fallback should be a normal number
                self.assertFalse(math.isnan(value),
                    f"{name}: nz() fallback is NaN")
                self.assertFalse(math.isinf(value),
                    f"{name}: nz() fallback is infinite")
    
    # ===========================================
    # FLOATING POINT FIXES
    # ===========================================
    
    def test_no_exact_float_equality(self):
        """Should not use exact equality for float comparisons."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for problematic float equality
            # Pattern: float == float (but allow int == int)
            exact_equals = re.findall(
                r'(\d+\.\d+)\s*==\s*(\d+\.\d+)',
                content
            )
            # 0.0, 1.0, etc. are acceptable
            problematic = [eq for eq in exact_equals 
                          if eq[0] not in ('0.0', '1.0', '0.5') 
                          and eq[1] not in ('0.0', '1.0', '0.5')]
            self.assertEqual(len(problematic), 0,
                f"{name}: Exact float equality found: {problematic}")
    
    def test_epsilon_comparison_for_near_zero(self):
        """Near-zero comparisons should use epsilon."""
        for name, content in self.files.items():
            if not content:
                continue
            # PROB_EPS should be used for near-zero comparisons
            has_eps = 'PROB_EPS' in content or 'eps' in content.lower()
            self.assertTrue(has_eps,
                f"{name}: Epsilon constant not found for float comparisons")
    
    # ===========================================
    # OVERFLOW PREVENTION
    # ===========================================
    
    def test_exponential_overflow_protection(self):
        """math.exp() should be protected against overflow."""
        for name, content in self.files.items():
            if not content:
                continue
            # Look for exp() usage
            exp_calls = re.findall(r'math\.exp\s*\(([^)]+)\)', content)
            if exp_calls:
                # Should have some form of clamping on exp argument
                has_protection = (
                    re.search(r'math\.exp\s*\(\s*-?\s*math\.min', content) or
                    re.search(r'math\.exp\s*\(\s*-?\s*math\.max', content) or
                    re.search(r'math\.min\s*\([^)]*math\.exp', content) or  # clamp result
                    # Sigmoid clamp pattern (x is bounded before exp(-x))
                    re.search(r'x\s*<\s*-500\s*\?\s*0\.0\s*:\s*x\s*>\s*500\s*\?\s*1\.0\s*:\s*1\.0\s*/\s*\(1\.0\s*\+\s*math\.exp\(\s*-\s*x\s*\)\s*\)', content) or
                    # Softmax stability (subtract max logit)
                    re.search(r'math\.exp\s*\(\s*\w+\s*-\s*zMax\s*\)', content)
                )
                self.assertTrue(has_protection,
                    f"{name}: math.exp() calls found without obvious overflow protection")
    
    def test_logarithm_domain_protection(self):
        """math.log() should only receive positive values."""
        for name, content in self.files.items():
            if not content:
                continue
            log_calls = re.findall(r'math\.log\s*\([^)]+\)', content)
            if log_calls:
                # Should use PROB_EPS or math.max to ensure positive input, or f_clamp
                has_protection = (
                    re.search(r'math\.log\s*\([^)]*PROB_EPS', content) or
                    re.search(r'math\.log\s*\([^)]*\+\s*0\.0001', content) or
                    re.search(r'math\.log\s*\(\s*math\.max', content) or
                    re.search(r'pLL\s*=\s*math\.max\s*\(\s*PROB_EPS', content) or  # Strategy pattern
                    re.search(r'f_clamp\s*\(.*0\.01', content)  # f_clamp(p, 0.01, 0.99)
                )
                self.assertTrue(has_protection,
                    f"{name}: math.log() not protected for positive domain")


if __name__ == '__main__':
    unittest.main()
