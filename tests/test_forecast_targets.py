"""
Test suite for SkippALGO v6.2 Forecast Targets (K-Bar, ATR, Path).
Verifies that the Pine Script contains the necessary inputs, logic, and data structures
described in the roadmap.
"""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"
STRATEGY_PATH = ROOT / "SkippALGO_Strategy.pine"

class TestForecastTargets(unittest.TestCase):
    """Verify Alternate Forecast Target implementation."""
    
    ind_text: str = ""
    strat_text: str = ""

    @classmethod
    def setUpClass(cls):
        if INDICATOR_PATH.exists():
            cls.ind_text = INDICATOR_PATH.read_text(encoding="utf-8")
        if STRATEGY_PATH.exists():
            cls.strat_text = STRATEGY_PATH.read_text(encoding="utf-8")
            
    def test_inputs_exist(self):
        """Verify new inputs for Forecast Targets are present."""
        # Check fcTarget inputs for Fast/Mid/Slow profiles
        self.assertIn('fcTargetF = input.string', self.ind_text, "Missing fcTargetF input")
        self.assertIn('fcTargetM = input.string', self.ind_text, "Missing fcTargetM input")
        
        # Check options
        options_regex = r'options=\["NextBar", "KBarReturn", "KBarATR", "PathTPvsSL"\]'
        self.assertRegex(self.ind_text, options_regex, "Missing Target Type options")
        
        # Check parameter inputs
        self.assertIn('kBarsF    = input.int', self.ind_text, "Missing kBars input")
        self.assertIn('tpATRF    = input.float', self.ind_text, "Missing Path TP input")
        self.assertIn('noHitPolicy   = input.string', self.ind_text, "Missing No-Hit Policy input")

    def test_data_structures(self):
        """Verify TfState type includes pending queues."""
        # We need to find the `type TfState` block and check for queue fields
        # Regex to find the type definition block
        type_def = re.search(r'type TfState\n(.*?)\n\n', self.ind_text, re.DOTALL)
        self.assertTrue(type_def, "Could not find TfState definition")
        
        content = type_def.group(1)
        self.assertIn('float[] qEntry', content, "Missing qEntry queue")
        self.assertIn('float[] qAtr', content, "Missing qAtr queue")
        self.assertIn('float[] qMaxH', content, "Missing qMaxH queue")
        self.assertIn('int[]   qAge', content, "Missing qAge queue")

    def test_process_logic_signatures(self):
        """Verify f_process_tf handles target types."""
        # Check for logic blocks matching target names
        self.assertIn('if fcTgt == "NextBar"', self.ind_text, "Missing NextBar logic")
        self.assertIn('else if fcTgt == "KBarReturn"', self.ind_text, "Missing KBarReturn logic")
        self.assertIn('else if fcTgt == "KBarATR"', self.ind_text, "Missing KBarATR logic")
        
        # PathTPvsSL logic (usually in the final else or named check)
        # The code uses `else // PathTPvsSL` comment or explicit check.
        # Let's search for the TP calculation line which is unique to Path logic
        tp_calc = r'tpPx = dir == 1 \? \(entry_i \+ tpA \* atr_i\) : \(entry_i - tpA \* atr_i\)'
        self.assertRegex(self.ind_text, tp_calc, "Missing Path TP calculation logic")

    def test_logic_expiration(self):
        """Verify queue expiration logic."""
        # Check for age check
        self.assertRegex(self.ind_text, r'if age_i >= kB', "Missing K-Bar age check")
        
        # Check for Path expiration
        self.assertRegex(self.ind_text, r'else if age_i >= pH', "Missing Path horizon check")
        
    def test_strategy_sync(self):
        """Verify Strategy file also has the updates."""
        self.assertIn('fcTargetF = input.string', self.strat_text, "Strategy missing inputs")
        self.assertIn('f_process_tf', self.strat_text, "Strategy should have main loop")
        
    def test_default_values(self):
        """Verify defaults match Recommendation."""
        # Roadmap recommends 0.5 TP / 0.3 SL approx
        # Current code has 0.5 and 0.3 defaults for F/M/S?
        # Let's check regex for default values
        
        # tpATRF defaults to 0.50?
        self.assertRegex(self.ind_text, r'tpATRF\s*=\s*input\.float\(0\.50', "Fast TP default mismatch")
        
        # slATRF defaults to 0.30?
        self.assertRegex(self.ind_text, r'slATRF\s*=\s*input\.float\(0\.30', "Fast SL default mismatch")

if __name__ == '__main__':
    unittest.main()
