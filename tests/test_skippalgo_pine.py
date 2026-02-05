"""
Test suite for SkippALGO.pine (Indicator).

Validates the indicator script against expected patterns and configuration.
"""
import pathlib
import re
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

    def test_engine_inputs(self):
        """Verify signal engine inputs exist (no branding)."""
        self.assertIn('engine', self.text)
        self.assertNotIn('Gainz', self.text)
        self.assertIn('"Hybrid"', self.text)
        self.assertIn('"Breakout"', self.text)
        self.assertIn('useForecastGateEntry', self.text)
        self.assertIn('pbLookback', self.text)

    def test_trade_gate_inputs(self):
        """Ensure separate trade-gate sample thresholds are defined."""
        self.assertIn('tradeMinBinSamples', self.text)
        self.assertIn('tradeMinTotalSamples', self.text)

    def test_rel_filter_default_horizon(self):
        """Default filter horizon should be F3 for faster gate responsiveness."""
        self.assertIn('relFilterTF  = input.string("F3"', self.text)
        
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

    def test_trend_regime_block_present(self):
        """Ensure trendUp/trendDn are defined (parity with strategy)."""
        self.assertIn("atrNormHere = atr / math.max(close, 0.0001)", self.text)
        self.assertIn("trendReg = f_trend_regime(emaF, emaS, atrNormHere)", self.text)
        self.assertIn("trendUp  = trendReg == 1.0", self.text)
        self.assertIn("trendDn  = trendReg == -1.0", self.text)

    def test_risk_temp_declared_once(self):
        """Ensure risk temp locals (newStop/Tp/Trail) are declared a single time to avoid redeclare errors."""
        self.assertEqual(len(re.findall(r"^float newStop\s*= na", self.text, flags=re.MULTILINE)), 1)
        self.assertEqual(len(re.findall(r"^float newTp\s*= na", self.text, flags=re.MULTILINE)), 1)
        self.assertEqual(len(re.findall(r"^float newTrail\s*= na", self.text, flags=re.MULTILINE)), 1)

    def test_forecast_pack_block_present(self):
        """Ensure all tfF1..tfF7 packs exist with direct tuple destructuring."""
        for i in range(1, 8):
            self.assertIn(f"[t{i}, c{i}, h{i}, l{i}", self.text)
            self.assertIn(f"= f_tf_pack(tfF{i})", self.text)

    def test_decision_quality_uses_trade_gate_thresholds(self):
        """Decision gate should use tradeMin* thresholds rather than calMinSamples."""
        self.assertIn("tradeMinBinSamples", self.text)
        self.assertIn("tradeMinTotalSamples", self.text)

    def test_trade_gate_thresholds_allow_zero(self):
        """Trade gate thresholds should treat 0 as disabled (<= 0 comparisons)."""
        self.assertRegex(self.text, r"tradeMinBinSamples\s*<=\s*0")
        self.assertRegex(self.text, r"tradeMinTotalSamples\s*<=\s*0")

if __name__ == "__main__":
    unittest.main()
