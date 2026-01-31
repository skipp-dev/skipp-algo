import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PINE_PATH = ROOT / "SkippALGO_Strategy.pine"


class TestSkippAlgoStrategy(unittest.TestCase):
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

    def test_f_process_tf_usage(self):
        # f_process_tf calls should match definition
        # We check that arguments match the input names (ens_wA vs wState issue check)
        # In Strategy, inputs ARE ens_wA, ens_wB, ens_wC.
        # So we check that the calls usage these variables.
        pattern = r"alphaN,\s*alpha1,\s*kShrink,\s*ens_wA,\s*ens_wB,\s*ens_wC\)"
        self.assertRegex(self.text, pattern, "Correct variable names not found in f_process_tf calls")

    def test_div_by_zero_fix_f_pullback_score(self):
        # The line 'dist = (c - ef) / (na(atrVal) ? c*0.01 : atrVal)' was causing potential div by zero and was unused
        bad_line = r"dist\s*=\s*\(c\s*-\s*ef\)\s*/\s*\(na\(atrVal\)\s*\?\s*c\*0\.01\s*:\s*atrVal\)"
        self.assertNotRegex(self.text, bad_line, "Found potentially dangerous div-by-zero line in f_pullback_score")
        
    def test_entryNow_replaced_by_cNow(self):
        # Verify cNow is used instead of entryNow
        self.assertNotRegex(self.text, r"array\.push\(qEntry,\s*entryNow\)")
        self.assertRegex(self.text, r"array\.push\(qEntry,\s*cNow\)")

if __name__ == "__main__":
    unittest.main()
