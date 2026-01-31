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
        self.assertIn("table.clear(gT, 0, 0, 4, 25)", self.text)
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


if __name__ == "__main__":
    unittest.main()
