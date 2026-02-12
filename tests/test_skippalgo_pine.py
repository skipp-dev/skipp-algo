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
        """Parent-scope float newStop/Tp/Trail = na removed to avoid shadow;
        buy branch tuple [newStop, ...] provides the declarations."""
        self.assertEqual(len(re.findall(r"^float newStop\s*= na", self.text, flags=re.MULTILINE)), 0)
        self.assertEqual(len(re.findall(r"^float newTp\s*= na", self.text, flags=re.MULTILINE)), 0)
        self.assertEqual(len(re.findall(r"^float newTrail\s*= na", self.text, flags=re.MULTILINE)), 0)
        # Buy branch tuple still present
        self.assertIn("[newStop, newTp, newTrail] = f_set_risk_on_entry(true", self.text)

    def test_forecast_pack_block_present(self):
        """Ensure all tfF1..tfF7 packs exist with direct tuple destructuring."""
        for i in range(1, 8):
            # Patch A: checking for raw unpacking
            self.assertIn(f"[t{i}_r, c{i}_r, h{i}_r, l{i}_r", self.text)
            self.assertIn(f"= f_tf_pack(tfF{i})", self.text)

    def test_decision_quality_uses_trade_gate_thresholds(self):
        """Decision gate should use tradeMin* thresholds rather than calMinSamples."""
        self.assertIn("tradeMinBinSamples", self.text)
        self.assertIn("tradeMinTotalSamples", self.text)

    def test_trade_gate_thresholds_allow_zero(self):
        """Trade gate thresholds should treat 0 as disabled (<= 0 comparisons)."""
        self.assertRegex(self.text, r"tradeMinBinSamples\s*<=\s*0")
        self.assertRegex(self.text, r"tradeMinTotalSamples\s*<=\s*0")

    # --- Deferred-items feature tests ---

    def test_sgd_momentum_inputs(self):
        """A2: SGD momentum inputs exist."""
        self.assertIn("useSgdMomentum", self.text)
        self.assertIn("sgdBeta", self.text)

    def test_ece_recal_inputs(self):
        """A5: ECE-triggered recalibration inputs exist."""
        self.assertIn("useEceRecal", self.text)
        self.assertIn("eceRecalBoost", self.text)

    def test_smooth_trend_function(self):
        """D1: f_trend_strength function exists."""
        self.assertIn("f_trend_strength(", self.text)
        self.assertIn("useSmoothTrend", self.text)

    def test_roc_score_function(self):
        """B2: f_roc_score function exists."""
        self.assertIn("f_roc_score(", self.text)
        self.assertIn("rocLongOk", self.text)

    def test_vol_score_function(self):
        """B4: f_vol_score function exists."""
        self.assertIn("f_vol_score(", self.text)
        self.assertIn("volEnsLongOk", self.text)

    def test_ensemble6_function(self):
        """6-factor ensemble removed as dead code; 4-factor ensemble exists."""
        self.assertIn("f_ensemble4(", self.text)

    def test_adx_filter(self):
        """D2: ADX filter inputs and gate exist."""
        self.assertIn("useAdx", self.text)
        self.assertIn("adxLen", self.text)
        self.assertIn("adxThresh", self.text)
        self.assertIn("adxOk", self.text)

    def test_pre_momentum_filter(self):
        """C1: Pre-signal momentum filter exists."""
        self.assertIn("usePreMomentum", self.text)
        self.assertIn("preMomLongOk", self.text)

    def test_ema_accel_filter(self):
        """C3: EMA acceleration filter exists."""
        self.assertIn("useEmaAccel", self.text)
        self.assertIn("emaAccelLongOk", self.text)

    def test_vwap_filter(self):
        """C4: VWAP alignment filter exists."""
        self.assertIn("useVwap", self.text)
        self.assertIn("vwapLongOk", self.text)

    def test_enhancement_gates(self):
        """Enhancement composite gates exist and are wired into signals."""
        self.assertIn("enhLongOk", self.text)
        self.assertIn("enhShortOk", self.text)

    def test_momentum_fields_in_tfstate(self):
        """A2: TfState has momentum accumulator fields."""
        self.assertIn("float[] momPlattN", self.text)
        self.assertIn("float[] momPlatt1", self.text)

if __name__ == "__main__":
    unittest.main()
