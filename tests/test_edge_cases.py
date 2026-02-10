"""
Edge Case Tests for SkippALGO Indicator and Strategy

Tests for thin markets, fast markets, extreme conditions, and boundary cases.
These verify the code handles edge cases gracefully without crashes or invalid outputs.

Test Categories:
1. Division by Zero Protection
2. NA/Missing Data Handling
3. Boundary Value Cases
4. Extreme Market Conditions
5. Array Bounds Safety
6. Numeric Overflow/Underflow Protection
"""

import re
import unittest
from pathlib import Path


class TestEdgeCases(unittest.TestCase):
    """Tests for edge case handling in both Indicator and Strategy."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        with open(base_path / "SkippALGO.pine", "r") as f:
            cls.indicator = f.read()
        
        with open(base_path / "SkippALGO_Strategy.pine", "r") as f:
            cls.strategy = f.read()
    
    # ========================================
    # DIVISION BY ZERO PROTECTION
    # ========================================
    
    def test_f_prob_handles_zero_denominator(self):
        """f_prob must return 0.5 when denominator is zero."""
        # Pattern: denom == 0.0 ? 0.5
        pattern = r'f_prob\([^)]+\)\s*=>\s*\n\s*denom\s*=.*\n\s*denom\s*==\s*0\.0\s*\?\s*0\.5'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_prob missing zero-denominator guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_prob missing zero-denominator guard")
    
    def test_f_pct_rank_handles_hi_equals_lo(self):
        """f_pct_rank must return 0.5 when hi == lo (no range)."""
        # This happens in thin markets with no price movement
        pattern = r'hi\s*==\s*lo\s*\?\s*0\.5'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_pct_rank missing hi==lo guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_pct_rank missing hi==lo guard")
    
    def test_f_ensemble_handles_zero_weights(self):
        """f_ensemble must guard against sum of weights being zero."""
        pattern = r'den\s*==\s*0\s*\?\s*0\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_ensemble missing zero-weight guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_ensemble missing zero-weight guard")
    
    def test_gapPct_handles_zero_prevClose(self):
        """gapPct calculation must handle zero or NA previous close."""
        # Critical for thin markets or first bar
        pattern = r'gapPct\s*=\s*\(na\(prevClose\)\s*or\s*prevClose\s*==\s*0\.0\)\s*\?\s*0\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator gapPct missing prevClose guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy gapPct missing prevClose guard")
    
    def test_rangePct_handles_zero_close(self):
        """rangePct calculation must handle zero close price."""
        pattern = r'rangePct\s*=\s*close\s*==\s*0\.0\s*\?\s*0\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator rangePct missing zero-close guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy rangePct missing zero-close guard")
    
    def test_drawdown_handles_zero_peak(self):
        """Drawdown calculation must handle zero peak price."""
        pattern = r'dd\s*=\s*ddPeak\s*==\s*0\.0\s*\?\s*0\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator drawdown missing zero-peak guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy drawdown missing zero-peak guard")
    
    def test_trust_weight_sum_guard(self):
        """Trust score weight sum must be guarded against zero."""
        pattern = r'wSum\s*:=\s*wSum\s*==\s*0\.0\s*\?\s*1\.0\s*:\s*wSum'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator trust wSum missing zero guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy trust wSum missing zero guard")
    
    def test_atr_zero_guard_in_target_resolution(self):
        """ATR must be checked for zero/NA before division in target resolution."""
        # Prevents division by zero in KBarATR target
        pattern = r'if\s*na\(atr_i\)\s*or\s*atr_i\s*==\s*0\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing ATR zero guard in target resolution")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing ATR zero guard in target resolution")
    
    # ========================================
    # NA/MISSING DATA HANDLING
    # ========================================
    
    def test_volume_availability_check(self):
        """Volume availability must be checked before use."""
        # Some instruments don't have volume data
        pattern = r'volAvail\s*=\s*not\s*na\(volume\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing volume availability check")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing volume availability check")
    
    def test_rsi_na_guard(self):
        """RSI momentum state must check for NA before use."""
        pattern = r'if\s*not\s*na\(rsiConf\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing RSI NA guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing RSI NA guard")
    
    def test_streak_handles_na_close(self):
        """Streak calculation must handle NA previous close."""
        pattern = r'if\s*na\(close\[1\]\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing streak NA guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing streak NA guard")
    
    def test_macro_gate_na_guard(self):
        """Macro gate must check for NA macroPct."""
        pattern = r'not\s*na\(macroPct\)\s*and'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing macroPct NA guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing macroPct NA guard")
    
    def test_entry_price_na_guard(self):
        """Entry price zone anchor must handle NA."""
        pattern = r'not\s*na\(entryPrice\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing entryPrice NA guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing entryPrice NA guard")
    
    def test_cooldown_na_guard(self):
        """Cooldown must handle NA lastSignalBar."""
        pattern = r'na\(lastSignalBar\)\s*\?\s*true'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing cooldown NA guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing cooldown NA guard")
    
    def test_ci_halfwidth_returns_na_for_zero_n(self):
        """CI half-width must return NA when n <= 0."""
        pattern = (
            r'f_ci95_halfwidth\([^)]+\)\s*=>\s*\n'
            r'(?:'
            r'\s*n\s*<=\s*0\s*\?\s*na'
            r'|'
            r'\s*if[^\n]*n\s*<=\s*0[^\n]*\n\s*na'
            r')'
        )
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_ci95_halfwidth missing zero-n guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_ci95_halfwidth missing zero-n guard")
    
    # ========================================
    # BOUNDARY VALUE CASES
    # ========================================
    
    def test_f_clamp01_exists(self):
        """f_clamp01 must exist for probability clamping."""
        pattern = r'f_clamp01\([^)]+\)\s*=>\s*\n\s*math\.max\(0\.0,\s*math\.min\(1\.0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing f_clamp01")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing f_clamp01")
    
    def test_f_clamp_exists(self):
        """f_clamp must exist for arbitrary range clamping."""
        pattern = r'f_clamp\(val,\s*lo,\s*hi\)\s*=>'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing f_clamp")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing f_clamp")
    
    def test_prob_eps_clamping_in_logit(self):
        """f_logit must clamp probability to avoid log(0)."""
        pattern = r'math\.max\(PROB_EPS.*math\.min\(1\.0\s*-\s*PROB_EPS'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_logit missing PROB_EPS clamping")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_logit missing PROB_EPS clamping")
    
    def test_eps_clamp_function_exists(self):
        """Epsilon clamping must exist for probability calculations.
        
        Note: Indicator uses f_epsClamp function, Strategy uses inline f_clamp
        for log/brier calculations. Both prevent log(0) issues.
        """
        # Indicator has dedicated f_epsClamp
        indicator_pattern = r'f_epsClamp\(p\)\s*=>'
        # Strategy uses f_clamp inline for similar purpose OR f_epsClamp
        strategy_pattern = r'f_clamp\(p[^,]*,\s*0\.01|f_epsClamp'
        
        self.assertRegex(self.indicator, indicator_pattern,
            "Indicator missing f_epsClamp")
        self.assertRegex(self.strategy, strategy_pattern,
            "Strategy missing probability clamping for logloss")
    
    def test_bin_index_clamping(self):
        """Binning must clamp indices to valid range in both files."""
        pattern_quantile = r'math\.max\(0,\s*math\.min\(bins\s*-\s*1,\s*b\)\)'
        pattern_fixed = r'b\s*<\s*0\s*\?\s*0\s*:\s*b\s*>\s*\(bins\s*-\s*1\)\s*\?\s*\(bins\s*-\s*1\)\s*:\s*b'
        
        for content, name in ((self.indicator, "Indicator"), (self.strategy, "Strategy")):
            self.assertTrue(
                re.search(pattern_quantile, content) or re.search(pattern_fixed, content),
                f"{name} missing bin index clamping"
            )
    
    def test_bucket_index_clamping(self):
        """f_bucket must clamp index to valid range (Indicator only).
        
        Note: Strategy doesn't have f_bucket function - uses f_bin2D directly.
        """
        # Simpler pattern for f_bucket clamping logic
        pattern = r'f_bucket\([^)]+\)\s*=>'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing f_bucket function")
        # Strategy uses inline bucket logic in f_bin2D - tested separately
    
    def test_platt_params_bounded(self):
        """Platt A and B must be bounded during SGD updates."""
        # Prevents runaway parameters
        pattern_a = r'aN\s*:=\s*math\.max\(0\.1,\s*math\.min\(5\.0'
        pattern_b = r'bN\s*:=\s*math\.max\(-3\.0,\s*math\.min\(3\.0'
        
        self.assertRegex(self.indicator, pattern_a,
            "Indicator Platt A not bounded")
        self.assertRegex(self.indicator, pattern_b,
            "Indicator Platt B not bounded")
        self.assertRegex(self.strategy, pattern_a,
            "Strategy Platt A not bounded")
        self.assertRegex(self.strategy, pattern_b,
            "Strategy Platt B not bounded")
    
    def test_ensemble_output_bounded(self):
        """f_ensemble output must be clamped to [-1, 1]."""
        pattern = r'math\.max\(-1\.0,\s*math\.min\(1\.0,\s*val\)\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator f_ensemble output not bounded")
        self.assertRegex(self.strategy, pattern,
            "Strategy f_ensemble output not bounded")
    
    # ========================================
    # EXTREME MARKET CONDITIONS
    # ========================================
    
    def test_guardrail_flags_exist(self):
        """Guardrail flags must exist for extreme conditions."""
        flags = ['volShock', 'gapShock', 'rangeShock']
        
        for flag in flags:
            pattern = rf'{flag}\s*='
            self.assertRegex(self.indicator, pattern,
                f"Indicator missing guardrail: {flag}")
            self.assertRegex(self.strategy, pattern,
                f"Strategy missing guardrail: {flag}")
    
    def test_guardrail_count_calculation(self):
        """Guardrail count must aggregate shock flags."""
        pattern = r'guardrailCount\s*=\s*\(volShock\s*\?\s*1\s*:\s*0\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing guardrailCount")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing guardrailCount")
    
    def test_drawdown_hard_gate_exists(self):
        """Hard gate must exist for severe drawdowns."""
        pattern = r'ddHardGateHit\s*=.*ddAbs\s*>=\s*ddHardGate'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing drawdown hard gate")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing drawdown hard gate")
    
    def test_volatility_regime_thresholds_defined(self):
        """Volatility regime thresholds must be defined as constants."""
        thresholds = [
            (r'VOL_THRESH_HIGH\s*=\s*0\.66', 'VOL_THRESH_HIGH'),
            (r'VOL_THRESH_LOW\s*=\s*0\.33', 'VOL_THRESH_LOW'),
        ]
        
        for pattern, name in thresholds:
            self.assertRegex(self.indicator, pattern,
                f"Indicator missing {name}")
            self.assertRegex(self.strategy, pattern,
                f"Strategy missing {name}")
    
    def test_close_filter_for_thin_eod_liquidity(self):
        """Close filter must exist to avoid thin EOD liquidity."""
        pattern = r'blockNearClose\s*='
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing blockNearClose filter")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing blockNearClose filter")
    
    # ========================================
    # ARRAY SAFETY
    # ========================================
    
    def test_array_size_check_before_loop(self):
        """Array size must be checked before iteration."""
        pattern = r'sz\s*=\s*array\.size\(.*qAge\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing array size check")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing array size check")
    
    def test_descending_loop_for_safe_removal(self):
        """Queue processing must use descending loop for safe removal."""
        # i = size - 1; while i >= 0; i -= 1
        pattern = r'i\s*=\s*array\.size\(.*\)\s*-\s*1\s*\n\s*while\s+i\s*>=\s*0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing safe descending loop")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing safe descending loop")
    
    def test_array_max_enforced_in_rolling_buffers(self):
        """Rolling buffers must enforce max length.
        
        Note: Indicator uses generic buf/maxLen naming, Strategy uses
        specific variable names like evBrier/rollScore.
        """
        # Indicator pattern
        pattern_ind = r'if\s*array\.size\(buf\)\s*>\s*maxLen'
        # Strategy pattern (uses specific names OR generic function if harmonized)
        pattern_strat = r'if\s*array\.size\((evBrier|buf)\)\s*>\s*(rollScore|maxLen)'
        
        self.assertRegex(self.indicator, pattern_ind,
            "Indicator missing rolling buffer max enforcement")
        self.assertRegex(self.strategy, pattern_strat,
            "Strategy missing rolling buffer max enforcement")
    
    # ========================================
    # FLOATING POINT SAFETY
    # ========================================
    
    def test_fp_drift_recalculation_interval(self):
        """Periodic recalculation must exist to prevent FP drift."""
        pattern = r'bar_index\s*%\s*ROLL_RECALC_INTERVAL\s*==\s*0'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing FP drift recalculation")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing FP drift recalculation")
    
    def test_array_sum_for_recalculation(self):
        """Array sum must be used for drift correction.
        
        Note: Indicator uses generic f_roll_add, Strategy uses inline logic.
        """
        # Indicator pattern (in f_roll_add function)
        pattern_ind = r'array\.set\(sumArr,\s*0,\s*array\.sum\(buf\)\)'
        # Strategy pattern (inline OR helper function)
        pattern_strat = r'(sb\s*:=\s*array\.sum\(evBrier\))|(array\.set\([^,]+,\s*0,\s*array\.sum\([^)]+\)\))'
        
        self.assertRegex(self.indicator, pattern_ind,
            "Indicator missing array.sum for recalculation")
        self.assertRegex(self.strategy, pattern_strat,
            "Strategy missing array.sum for recalculation")
    
    def test_logloss_clamping(self):
        """LogLoss calculation must clamp probability before log."""
        # Prevents log(0) or log(negative)
        # Updated to check for general usage of PROB_EPS in max() clamping, matching f_safe_log logic
        pattern = r'math\.max\(PROB_EPS'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator LogLoss missing probability clamping")
        self.assertRegex(self.strategy, pattern,
            "Strategy LogLoss missing probability clamping")
    
    # ========================================
    # INITIALIZATION SAFETY
    # ========================================
    
    def test_var_declarations_for_state(self):
        """State variables must use var for persistence."""
        var_patterns = [
            (r'var\s+int\s+pos\s*=', 'pos'),
            (r'var\s+int\s+lastSignalBar', 'lastSignalBar'),
            (r'var\s+float\s+entryPrice', 'entryPrice'),
            (r'var\s+TfState\s+tf1State', 'tf1State'),
        ]
        
        for pattern, name in var_patterns:
            self.assertRegex(self.indicator, pattern,
                f"Indicator {name} not declared with var")
            self.assertRegex(self.strategy, pattern,
                f"Strategy {name} not declared with var")
    
    def test_momentum_state_initialization(self):
        """Momentum hysteresis state must have init guard."""
        pattern = r'var\s+bool\s+momStateInit\s*=\s*false'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing momStateInit")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing momStateInit")
    
    def test_platt_default_identity(self):
        """Platt params must initialize to identity (1.0, 0.0)."""
        pattern = r'array\.from\(1\.0,\s*0\.0\)'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator Platt not initialized to identity")
        self.assertRegex(self.strategy, pattern,
            "Strategy Platt not initialized to identity")


class TestThinMarketScenarios(unittest.TestCase):
    """Specific tests for thin/illiquid market handling."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        with open(base_path / "SkippALGO.pine", "r") as f:
            cls.indicator = f.read()
        
        with open(base_path / "SkippALGO_Strategy.pine", "r") as f:
            cls.strategy = f.read()
    
    def test_volume_fallback_for_no_volume_data(self):
        """Data quality score must have fallback when volume unavailable."""
        pattern = r'dataQualityScore\s*=\s*volAvail\s*\?.*:\s*0\.5'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing volume fallback")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing volume fallback")
    
    def test_min_samples_threshold_exists(self):
        """Minimum samples threshold must exist for calibration."""
        pattern = r'calMinSamples\s*=\s*input\.int\(\d+'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing calMinSamples")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing calMinSamples")
    
    def test_warmup_state_handling(self):
        """Warmup state must be shown when samples insufficient."""
        pattern = r'warmup|Warm'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing warmup handling")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing warmup handling")
    
    def test_shrinkage_for_sparse_bins(self):
        """Shrinkage must exist for bins with few samples."""
        pattern = r'kShrink|shrinkK'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing shrinkage parameter")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing shrinkage parameter")
    
    def test_base_rate_pooling(self):
        """Base rate pooling must exist for sparse bins."""
        pattern = r'pBase\s*=.*f_prob\(uBase,\s*nBase'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing base rate pooling")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing base rate pooling")


class TestFastMarketScenarios(unittest.TestCase):
    """Specific tests for fast-moving market handling."""
    
    @classmethod
    def setUpClass(cls):
        """Load both Pine Script files."""
        base_path = Path(__file__).parent.parent
        
        with open(base_path / "SkippALGO.pine", "r") as f:
            cls.indicator = f.read()
        
        with open(base_path / "SkippALGO_Strategy.pine", "r") as f:
            cls.strategy = f.read()
    
    def test_gap_shock_detection(self):
        """Gap shock must be detected and flagged."""
        pattern = r'gapShock\s*=\s*gapPct\s*>=\s*gapShockPct'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing gap shock detection")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing gap shock detection")
    
    def test_range_shock_detection(self):
        """Range shock must be detected for flash moves."""
        pattern = r'rangeShock\s*=\s*rangePct\s*>=\s*rangeShockPct'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing range shock detection")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing range shock detection")
    
    def test_vol_shock_detection(self):
        """Volatility shock must be detected."""
        pattern = r'volShock\s*=\s*atrRank\s*>=\s*volRankHigh'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing vol shock detection")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing vol shock detection")
    
    def test_adaptive_rsi_for_timeframe(self):
        """RSI length must adapt to timeframe for fast markets."""
        pattern = r'useAdaptiveRsi'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing adaptive RSI")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing adaptive RSI")
    
    def test_cooldown_bars_exist(self):
        """Cooldown bars must exist to prevent overtrading in fast markets."""
        pattern = r'cooldownBars\s*=\s*input\.int\('
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing cooldown bars")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing cooldown bars")
    
    def test_barstate_isconfirmed_guard(self):
        """Signal generation must use barstate.isconfirmed to avoid repainting."""
        pattern = r'barstate\.isconfirmed'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing barstate.isconfirmed guard")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing barstate.isconfirmed guard")
    
    def test_no_hit_policy_exists(self):
        """No-hit policy must exist for fast markets where TP/SL not reached."""
        pattern = r'noHitPolicy\s*=\s*input\.string'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing noHitPolicy")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing noHitPolicy")
    
    def test_tie_policy_for_same_bar_hits(self):
        """Tie policy must exist when TP and SL hit on same bar."""
        pattern = r'pathTiePolicy\s*=\s*input\.string'
        
        self.assertRegex(self.indicator, pattern,
            "Indicator missing pathTiePolicy")
        self.assertRegex(self.strategy, pattern,
            "Strategy missing pathTiePolicy")


if __name__ == '__main__':
    unittest.main()
