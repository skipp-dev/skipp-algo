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

    def test_table_clear_has_bounds(self):
        self.assertIn("table.clear(gT, 0, 0, 4, 33)", self.text)
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
        pattern = r'else if pathTiePolicy == "Neutral"\s+doUpdate := false'
        match = re.search(pattern, self.text)
        self.assertTrue(match, "Neutral tie policy logic not found or incorrect (should set doUpdate := false)")

    def test_table_formatting_logic(self):
        # Check for merge_cells usage
        self.assertIn("table.merge_cells(gT, 1, 32, 4, 32)", self.text)
        self.assertIn("table.merge_cells(gT, 1, 33, 4, 33)", self.text)
        
        # Check targetDesc definition exists (multiline or single line)
        self.assertIn('targetDesc =', self.text)
        # Updated for Multi-Profile support
        self.assertIn('"Multi-Profile (See Settings). Fast: " + fcTargetF', self.text)
        
    def test_process_tf_signature(self):
        # Check that f_process_tf has the new comprehensive signature
        self.assertIn("f_process_tf(newTfBar, sA,", self.text)
        self.assertIn("fcTgt, kB, aThr, pH, tpA, slA,", self.text)
        self.assertIn("plattN, platt1,", self.text)

    def test_forecast_readability_update(self):
        # Check for new input
        self.assertIn('fcDisplay = input.string("Up% (N)"', self.text)
        
        # Check for new pupText logic lines
        self.assertIn('"Warm " + str.tostring(n) + "/"', self.text)
        self.assertIn('fcDisplay == "Edge pp (N)"', self.text)
        
        # SkippALGO.pine uses f_chance_word() for header, not pHdrN variable
        self.assertIn('cw = f_chance_word()', self.text)
        self.assertIn('cw + " chance(N)"', self.text)
        
        # Check for Note update
        self.assertIn("Forecast: Shrinkage k=5.0 active", self.text)


if __name__ == "__main__":
    unittest.main()
