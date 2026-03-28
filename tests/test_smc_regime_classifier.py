"""Tests for scripts/smc_regime_classifier.py."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_regime_classifier import classify_market_regime


class TestRiskOff:

    def test_risk_off_extreme_vix(self) -> None:
        result = classify_market_regime(vix_level=40.0, macro_bias=0.0)
        assert result["regime"] == "RISK_OFF"
        assert any("extreme" in r.lower() for r in result["reasons"])

    def test_risk_off_negative_bias(self) -> None:
        result = classify_market_regime(vix_level=18.0, macro_bias=-0.6)
        assert result["regime"] == "RISK_OFF"
        assert any("negative" in r.lower() for r in result["reasons"])

    def test_risk_off_elevated_vix_negative_bias(self) -> None:
        result = classify_market_regime(vix_level=28.0, macro_bias=-0.2)
        assert result["regime"] == "RISK_OFF"


class TestRiskOn:

    def test_risk_on_broad(self) -> None:
        sectors = [{"sector": f"S{i}", "changesPercentage": 1.0} for i in range(8)]
        result = classify_market_regime(
            vix_level=12.0, macro_bias=0.5, sector_performance=sectors
        )
        assert result["regime"] == "RISK_ON"
        assert result["sector_breadth"] >= 0.6

    def test_risk_on_low_vix(self) -> None:
        result = classify_market_regime(vix_level=10.0, macro_bias=0.1)
        assert result["regime"] == "RISK_ON"

    def test_risk_on_very_broad_breadth(self) -> None:
        sectors = [{"sector": f"S{i}", "changesPercentage": 0.3} for i in range(10)]
        result = classify_market_regime(vix_level=20.0, macro_bias=0.1, sector_performance=sectors)
        assert result["regime"] == "RISK_ON"


class TestRotation:

    def test_rotation_mixed(self) -> None:
        sectors = (
            [{"sector": f"Lead{i}", "changesPercentage": 1.5} for i in range(3)]
            + [{"sector": f"Lag{i}", "changesPercentage": -1.5} for i in range(3)]
            + [{"sector": "Mid0", "changesPercentage": 0.1}]
        )
        result = classify_market_regime(
            vix_level=20.0, macro_bias=0.1, sector_performance=sectors
        )
        assert result["regime"] == "ROTATION"
        assert 0.3 <= result["sector_breadth"] <= 0.7


class TestNeutral:

    def test_neutral_default(self) -> None:
        result = classify_market_regime(vix_level=None, macro_bias=0.0)
        assert result["regime"] == "NEUTRAL"

    def test_neutral_middling(self) -> None:
        result = classify_market_regime(vix_level=20.0, macro_bias=0.1)
        assert result["regime"] == "NEUTRAL"


class TestEdgeCases:

    def test_none_vix_handled(self) -> None:
        result = classify_market_regime(vix_level=None, macro_bias=0.2)
        assert result["regime"] in ("RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL")
        assert result["vix_level"] is None

    def test_empty_sectors(self) -> None:
        result = classify_market_regime(vix_level=18.0, macro_bias=0.0, sector_performance=[])
        assert result["sector_breadth"] == 0.0

    def test_return_shape(self) -> None:
        result = classify_market_regime(vix_level=20.0, macro_bias=0.0)
        assert set(result.keys()) == {"regime", "vix_level", "macro_bias", "sector_breadth", "reasons"}
        assert isinstance(result["reasons"], list)
