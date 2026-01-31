import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE_PATH = ROOT / "SkippALGO_Strategy.pine"


class TestSkippAlgoStrategyPine(unittest.TestCase):
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = PINE_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_version_6(self):
        self.assertRegex(self.text, r"//@version=6")

    def test_no_semicolons(self):
        # Pine Script v6 forbids end-of-line semicolons
        count = 0
        for i, line in enumerate(self.lines, 1):
            if line.strip().endswith(";"):
                # Exclude comments
                if "//" in line:
                    idx = line.index("//")
                    content = line[:idx].strip()
                    if content.endswith(";"):
                        count += 1
                        print(f"Line {i} has semicolon: {line}")
                else:
                    count += 1
                    print(f"Line {i} has semicolon: {line}")
        self.assertEqual(count, 0, f"Found {count} lines ending with semicolons")

    def test_table_clear_has_bounds(self):
        # Strategy also updated to 33 rows?
        self.assertIn("table.clear(gT, 0, 0, 4, 33)", self.text)
        self.assertNotRegex(self.text, r"table\.clear\(\s*gT\s*\)")

    def test_f_prob_exists(self):
         self.assertRegex(self.text, r"f_prob\(up, n, alpha\) =>")

    def test_f_chance_word_exists(self):
        # Should be synced with Indicator
         self.assertRegex(self.text, r"f_chance_word\(\) =>")

    def test_target_profiles_usage(self):
        # Verify inputs are used in string concatenation
        self.assertIn('"Multi-Profile (See Settings). Fast: " + fcTargetF', self.text)
        
    def test_new_ui_helpers(self):
        # Verify CI/Reliability helpers are present (v6.1 UI)
        self.assertRegex(self.text, r"f_ci95_halfwidth\(p, n\) =>")
        self.assertRegex(self.text, r"f_rel_label\(p, nBin, total, canCal\) =>")

if __name__ == "__main__":
    unittest.main()
