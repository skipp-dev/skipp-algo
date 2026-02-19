"""
Test suite for SkippALGO v6.1 features (TradersPost, Liquidity Sweeps, Fail-Safe).
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STRATEGY_PATH = ROOT / "SkippALGO_Strategy.pine"
INDICATOR_PATH = ROOT / "SkippALGO.pine"

class TestSkippAlgoV6_1(unittest.TestCase):
    """Verify v6.1.x feature implementation."""
    
    strat_text: str = ""
    ind_text: str = ""

    @classmethod
    def setUpClass(cls):
        if STRATEGY_PATH.exists():
            cls.strat_text = STRATEGY_PATH.read_text(encoding="utf-8")
        if INDICATOR_PATH.exists():
            cls.ind_text = INDICATOR_PATH.read_text(encoding="utf-8")

    def test_traderspost_json_inputs(self):
        """Verify JSON payload inputs exist."""
        # Check Strategy
        self.assertIn('useJsonAlerts = input.bool', self.strat_text, "Strategy missing useJsonAlerts input")
        self.assertIn('"Enable JSON Webhook Payloads"', self.strat_text, "Strategy missing JSON input label")
        
        # Check Indicator
        self.assertIn('useJsonAlerts = input.bool', self.ind_text, "Indicator missing useJsonAlerts input")

    def test_traderspost_function(self):
        """Verify f_tp_json function definition."""
        # Strategy may use either legacy multi-arg signature or one-arg indicator-style signature.
        strat_sigs = [
            r'f_tp_json\(action\) =>',
            r'f_tp_json\(action,\s*orderId,\s*legacyMsg\) =>',
        ]
        # Indicator takes action only
        ind_sig = r'f_tp_json\(action\) =>'

        self.assertTrue(any(re.search(sig, self.strat_text) for sig in strat_sigs),
                        "Strategy missing f_tp_json function")
        self.assertRegex(self.ind_text, ind_sig, "Indicator missing f_tp_json function")
        
        # Verify it uses str.format with JSON structure
        # Use simple string match for the start to avoid regex quote escaping hell
        # NOTE: Regex requires escaping { and } even inside the string, else {0} is interpreted as "repeat 0 times"
        json_pattern = r"str\.format\('\{\{\"ticker\": \"\{0\}\", \"action\": \"\{1\}\""
        self.assertRegex(self.strat_text, json_pattern, "Strategy JSON format incorrect")

    def test_liquidity_sweeps_inputs(self):
        """Verify Liquidity Sweep inputs."""
        self.assertIn('useLiqSweep', self.strat_text, "Strategy missing useLiqSweep input")
        self.assertIn('liqSweepLookback', self.strat_text, "Strategy missing liqSweepLookback input")

    def test_liquidity_sweeps_logic(self):
        """Verify Sweep detection logic (SMC)."""
        # Bull Sweep: Low below swing low, Close above swing low
        bull_sweep = r'bool isSweep_Bull = not na\(lastSwingLow\) and \(low < lastSwingLow\) and \(close > lastSwingLow\)'
        self.assertRegex(self.strat_text, bull_sweep, "Strategy missing isSweep_Bull logic")
        
        # Gate logic
        gate_bull = r'bool smcOkL = \(not useLiqSweep\) or sweepRecent_Bull'
        self.assertRegex(self.strat_text, gate_bull, "Strategy missing smcOkL gate")

    def test_choch_failsafe_exit(self):
        """Verify fail-safe exit architecture markers exist in current implementation."""
        has_long_break = (
            'breakLong  = (useStrictEmaExit ? crossClose_EmaS_down : trendFlipDown) or trendFlipDown' in self.strat_text or
            'breakLong  = crossClose_EmaS_down or trendFlipDown' in self.strat_text
        )
        has_short_break = (
            'breakShort = (useStrictEmaExit ? crossClose_EmaS_up   : trendFlipUp)   or trendFlipUp' in self.strat_text or
            'breakShort = crossClose_EmaS_up   or trendFlipUp' in self.strat_text
        )
        self.assertTrue(has_long_break, "Strategy long break fail-safe missing")
        self.assertTrue(has_short_break, "Strategy short break fail-safe missing")

        has_exit_model = (
            'exitSignal := riskExitHit or usiExitHit or engExitHit' in self.strat_text or
            'exitSignal := holdExceptionsOnly ? (riskExceptionHit or engExitHit) : (rHit or structHit or engExitHit)' in self.strat_text or
            'exitSignal := rHit or structHit or staleExit or engExitHit' in self.strat_text or
            'exitSignal := holdExceptionsOnly ? (riskExceptionHit or engExitHit) : (rHit or structHit or staleExit or engExitHit)' in self.strat_text
        )
        has_cover_model = (
            'coverSignal := riskExitHit or usiExitHit or engExitHit' in self.strat_text or
            'coverSignal := holdExceptionsOnly ? (riskExceptionHit or engExitHit) : (rHit or structHit or engExitHit)' in self.strat_text or
            'coverSignal := rHit or structHit or staleExit or engExitHit' in self.strat_text or
            'coverSignal := holdExceptionsOnly ? (riskExceptionHit or engExitHit) : (rHit or structHit or staleExit or engExitHit)' in self.strat_text
        )
        self.assertTrue(has_exit_model, "Strategy unified long exit model missing")
        self.assertTrue(has_cover_model, "Strategy unified short exit model missing")

    def test_stale_reversal_filter(self):
        """Verify Stale Reversal Filter Logic."""
        # Should check for recency (<= revRecencyBars) OR high volume
        recency = r'bool revRecencyOkL\s*=\s*\(not na\(barsSinceChoCH_L\)\) and \(barsSinceChoCH_L <= revRecencyBars or volRatioG >= 1.0\)'
        self.assertRegex(self.strat_text, recency, "Strategy stale reversal filter (Long) missing")

    def test_reversal_entry_gate(self):
        """Verify Neural Reversals bypass standard allowEntry gate."""
        # The main entry block should include allowRevBypass as an OR-bypass
        # pattern: allowRevBypass = allowNeuralReversals and barstate.isconfirmed and cooldownOkSafe and (...)
        #          if (pos == 0 and (allowEntry or allowRescue)) or allowRevBypass
        
        define_pattern = r'allowRevBypass\s*=\s*allowNeuralReversals and (?:barstate\.isconfirmed|signalGateConfirmed) and cooldownOkSafe and \(isChoCH_Long or isChoCH_Short\)'
        usage_pattern  = r'if \(pos == 0 and \(allowEntry or allowRescue\)\) or allowRevBypass'

        self.assertRegex(self.strat_text, define_pattern, "Strategy missing allowRevBypass definition")
        self.assertRegex(self.strat_text, usage_pattern,  "Strategy missing allowRevBypass usage in main loop")

        self.assertRegex(self.ind_text, define_pattern, "Indicator missing allowRevBypass definition")
        self.assertRegex(self.ind_text, usage_pattern,  "Indicator missing allowRevBypass usage in main loop")

    def test_unified_reversal_injection(self):
        """Verify unified Neural Reversal injection exists after ALL engine blocks.

        The injection must appear AFTER the engine if/else-if chain and BEFORE
        conflict resolution, ensuring all engines (including Loose) honour
        revBuyGlobal / revShortGlobal.
        """
        # Pattern: comment + guard + two injection lines must appear together
        injection_pattern = (
            r'// Unified Neural Reversal injection \(all engines, including Loose\)\s*\n'
            r'\s*if allowNeuralReversals\s*\n'
            r'\s*buySignal\s*:=\s*buySignal\s+or\s+revBuyGlobal\s*\n'
            r'\s*shortSignal\s*:=\s*shortSignal\s+or\s+revShortGlobal'
        )

        self.assertRegex(self.ind_text, injection_pattern,
                         "Indicator missing unified reversal injection after engine block")
        self.assertRegex(self.strat_text, injection_pattern,
                         "Strategy missing unified reversal injection after engine block")

        # The injection must appear BEFORE conflict resolution
        for label, text in [("Indicator", self.ind_text), ("Strategy", self.strat_text)]:
            import re
            inj_match = re.search(r'buySignal\s*:=\s*buySignal\s+or\s+revBuyGlobal', text)
            conflict_match = re.search(r'if buySignal and shortSignal', text)
            self.assertIsNotNone(inj_match, f"{label}: injection line not found")
            self.assertIsNotNone(conflict_match, f"{label}: conflict resolution not found")
            self.assertLess(inj_match.start(), conflict_match.start(),
                            f"{label}: reversal injection must appear before conflict resolution")

if __name__ == '__main__':
    unittest.main()
