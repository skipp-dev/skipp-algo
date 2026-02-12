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
        # Strategy usually takes more args (orderId, legacyMsg)
        strat_sig = r'f_tp_json\(action, orderId, legacyMsg\) =>'
        # Indicator takes action only
        ind_sig = r'f_tp_json\(action\) =>'
        
        self.assertRegex(self.strat_text, strat_sig, "Strategy missing f_tp_json function")
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
        """Verify ChoCH exits respect minimum grace period (v6.2.6).
        
        structHit for LONG exit uses breakLong (bearish) + (isChoCH_Short and canChochExit)
        structHit for SHORT cover uses breakShort (bullish) + (isChoCH_Long and canChochExit)
        canChochExit enforces a minimum 2-bar hold before ChoCH can trigger exit.
        """
        # Verify Long Exit: breakLong (bearish EMA break) for pos==1 exit
        long_exit = r'structHit = \(\(breakLong and canStructExit\) or \(isChoCH_Short and canChochExit\)\)'
        self.assertRegex(self.strat_text, long_exit, "Strategy long exit fail-safe missing")
        
        # Verify Short Cover: breakShort (bullish EMA break) for pos==-1 cover
        short_cover = r'structHit = \(\(breakShort and canStructExit\) or \(isChoCH_Long and canChochExit\)\)'
        self.assertRegex(self.strat_text, short_cover, "Strategy short cover fail-safe missing")

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
        
        define_pattern = r'allowRevBypass\s*=\s*allowNeuralReversals and barstate\.isconfirmed and cooldownOkSafe and \(isChoCH_Long or isChoCH_Short\)'
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
