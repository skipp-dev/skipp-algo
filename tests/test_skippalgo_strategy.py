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

    def test_reactive_arrays_sized_for_2d_binning(self):
        """
        Regression test for runtime error:
        'Error on bar 0: In array.get() function. Index 4 is out of bounds, array size is 2.'
        
        The (1) reactive arrays (cnt11, up11, etc.) must be sized for 2D binning
        (predBins1 * dim2Bins) since f_bin2D is used, not 1D (predBins1).
        """
        import re
        # Check that (1) arrays use 2D sizing: predBins1 * dim2Bins
        pattern_2d = r"array\.new_int\(predBins1\s*\*\s*dim2Bins,\s*0\)"
        matches_2d = re.findall(pattern_2d, self.text)
        
        # Should have 14 matches (cnt1x and up1x for F1-F7)
        self.assertGreaterEqual(len(matches_2d), 14, 
            f"Expected at least 14 (1) arrays with 2D sizing (predBins1 * dim2Bins), found {len(matches_2d)}")
        
        # Verify NO (1) arrays use old 1D sizing pattern
        bad_pattern = r"cnt1\d\s*=\s*array\.new_int\(predBins1,\s*0\)"
        self.assertNotRegex(self.text, bad_pattern, 
            "Found (1) array with incorrect 1D sizing - will cause array bounds error with f_bin2D")

if __name__ == "__main__":
    unittest.main()
