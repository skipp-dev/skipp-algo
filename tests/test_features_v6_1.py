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
        """Verify ChoCH exits bypass the grace period (Fail-Safe).
        
        structHit for LONG exit uses breakLong (bearish) + isChoCH_Short
        structHit for SHORT cover uses breakShort (bullish) + isChoCH_Long
        """
        # Verify Long Exit: breakLong (bearish EMA break) for pos==1 exit
        long_exit = r'structHit = \(\(breakLong and canStructExit\) or isChoCH_Short\)'
        self.assertRegex(self.strat_text, long_exit, "Strategy long exit fail-safe missing")
        
        # Verify Short Cover: breakShort (bullish EMA break) for pos==-1 cover
        short_cover = r'structHit = \(\(breakShort and canStructExit\) or isChoCH_Long\)'
        self.assertRegex(self.strat_text, short_cover, "Strategy short cover fail-safe missing")

    def test_stale_reversal_filter(self):
        """Verify Stale Reversal Filter Logic."""
        # Should check for recency (<= 5 bars) OR high volume
        recency = r'bool revRecencyOkL\s*=\s*\(not na\(barsSinceChoCH_L\)\) and \(barsSinceChoCH_L <= \d+ or volRatioG >= 1.0\)'
        self.assertRegex(self.strat_text, recency, "Strategy stale reversal filter (Long) missing")

if __name__ == '__main__':
    unittest.main()
