"""
Test suite for SkippALGO.pine (Indicator).

Validates the indicator script against expected patterns and configuration.
"""
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
INDICATOR_PATH = ROOT / "SkippALGO.pine"

class TestSkippAlgoIndicator(unittest.TestCase):
    """Basic structure tests for the indicator script."""
    
    text: str = ""
    lines: list[str] = []

    @classmethod
    def setUpClass(cls):
        cls.text = INDICATOR_PATH.read_text(encoding="utf-8")
        cls.lines = cls.text.splitlines()

    def test_version_6(self):
        """Verify Pine Script version 6."""
        self.assertRegex(self.text, r"//@version=6")

    def test_is_indicator(self):
        """Verify this is an indicator() declaration."""
        self.assertIn("indicator(", self.text)
        self.assertNotIn("strategy(", self.text)

    def test_gainz_inputs(self):
        """Verify new Gainz engine inputs exist."""
        self.assertIn('engine', self.text)
        self.assertIn('"Gainz Hybrid"', self.text)
        self.assertIn('useForecastGateEntry', self.text)
        self.assertIn('pbLookback', self.text)
        
    def test_risk_inputs(self):
        """Verify ATR risk inputs."""
        self.assertIn('useAtrRisk', self.text)
        self.assertIn('stopATR', self.text)
        self.assertIn('tpATR', self.text)

    def test_no_semicolons(self):
        """Pine Script v6 forbids end-of-line semicolons."""
        count = 0
        for i, line in enumerate(self.lines, 1):
            stripped = line.strip()
            if stripped.endswith(";"):
                if "//" in line:
                    idx = line.index("//")
                    content = line[:idx].strip()
                    if content.endswith(";"):
                        count += 1
                else:
                    count += 1
        self.assertEqual(count, 0, f"Found {count} lines ending with semicolons")

if __name__ == "__main__":
    unittest.main()
