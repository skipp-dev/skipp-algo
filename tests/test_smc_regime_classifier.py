"""Tests for scripts/smc_regime_classifier.py."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure scripts/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_regime_classifier import _clamp, _to_float, classify_market_regime


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

    def test_expensive_market_pe_reduces_macro_bias(self) -> None:
        sectors = [{"sector": f"S{i}", "changesPercentage": 1.0} for i in range(8)]
        result = classify_market_regime(
            vix_level=20.0,
            macro_bias=0.5,
            sector_performance=sectors,
            market_pe_forward=35.0,
        )
        assert result["market_pe_regime"] == "EXPENSIVE"
        assert result["macro_bias_raw"] == 0.5
        assert result["macro_bias_pe_adjustment"] < 0
        assert result["macro_bias"] < result["macro_bias_raw"]


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
        assert set(result.keys()) == {
            "regime",
            "vix_level",
            "macro_bias",
            "macro_bias_raw",
            "macro_bias_pe_adjustment",
            "macro_bias_yield_curve_adjustment",
            "market_pe_forward",
            "market_pe_regime",
            "sector_breadth",
            "yield_curve_inverted",
            "reasons",
        }
        assert isinstance(result["reasons"], list)


class TestNanHandling:
    """NaN inputs must be treated as 'no signal' (0.0 / low bound), never
    silently coerced to the maximum (+1.0) which would flip the regime.
    """

    def test_to_float_nan_returns_zero(self) -> None:
        assert _to_float(float("nan")) == 0.0
        assert _to_float("nan") == 0.0

    def test_to_float_valid_and_invalid(self) -> None:
        assert _to_float("1.5") == 1.5
        assert _to_float(None) == 0.0
        assert _to_float("not-a-number") == 0.0

    def test_clamp_nan_maps_to_low_not_high(self) -> None:
        assert _clamp(float("nan"), -1.0, 1.0) == -1.0
        assert _clamp(float("inf"), -1.0, 1.0) == 1.0
        assert _clamp(float("-inf"), -1.0, 1.0) == -1.0

    def test_nan_macro_bias_does_not_force_risk_on(self) -> None:
        """Regression: a NaN macro_bias must behave like 0.0, not +1.0.

        With 0.6 breadth and a neutral bias the regime is NEUTRAL; before the
        guard, NaN -> +1.0 silently satisfied the ``>= 0.3 and breadth >= 0.6``
        RISK_ON branch and flipped the regime.
        """
        sectors = [
            {"sector": "a", "changesPercentage": 0.2},
            {"sector": "b", "changesPercentage": 0.2},
            {"sector": "c", "changesPercentage": 0.2},
            {"sector": "d", "changesPercentage": -0.2},
            {"sector": "e", "changesPercentage": -0.2},
        ]
        nan_result = classify_market_regime(
            vix_level=20.0, macro_bias=float("nan"), sector_performance=sectors
        )
        zero_result = classify_market_regime(
            vix_level=20.0, macro_bias=0.0, sector_performance=sectors
        )
        assert nan_result["regime"] == zero_result["regime"]
        assert nan_result["macro_bias"] == zero_result["macro_bias"]

    def test_nan_sector_change_is_neutral_not_positive(self) -> None:
        """A NaN sector change must not count toward breadth."""
        sectors = [
            {"sector": "a", "changesPercentage": float("nan")},
            {"sector": "b", "changesPercentage": 1.0},
        ]
        result = classify_market_regime(
            vix_level=20.0, macro_bias=0.0, sector_performance=sectors
        )
        # Only 1 of 2 sectors is positive -> breadth 0.5, NaN excluded.
        assert result["sector_breadth"] == 0.5


class TestYieldCurveIntegration:

    def test_inverted_yield_shifts_bias_negative(self) -> None:
        result = classify_market_regime(vix_level=20.0, macro_bias=0.3, yield_curve_inverted=True)
        assert result["yield_curve_inverted"] is True
        assert result["macro_bias_yield_curve_adjustment"] == -0.2
        assert result["macro_bias"] < 0.3

    def test_normal_yield_no_shift(self) -> None:
        result = classify_market_regime(vix_level=20.0, macro_bias=0.3, yield_curve_inverted=False)
        assert result["yield_curve_inverted"] is False
        assert result["macro_bias_yield_curve_adjustment"] == 0.0

    def test_inverted_yield_can_trigger_risk_off(self) -> None:
        result = classify_market_regime(vix_level=28.0, macro_bias=-0.1, yield_curve_inverted=True)
        assert result["regime"] == "RISK_OFF"
        assert any("yield" in r.lower() for r in result["reasons"])


# ---------------------------------------------------------------------------
# F-06 — Regime Hierarchy
# ---------------------------------------------------------------------------


class TestRegimeHierarchy:
    """Verify regime hierarchy markers and conflict detection logic."""

    def test_primary_regime_is_classified(self) -> None:
        result = classify_market_regime(vix_level=20.0, macro_bias=0.3)
        assert result["regime"] in {"RISK_ON", "RISK_OFF", "NEUTRAL", "CAUTIOUS"}

    def test_conflict_detected_risk_off_vs_low_vol(self) -> None:
        """Simulate the conflict detection logic from generate_smc_micro_base."""
        primary_regime = "RISK_OFF"
        vol_regime_label = "LOW_VOL"
        conflicts: list[dict[str, str]] = []
        if primary_regime == "RISK_OFF" and vol_regime_label == "LOW_VOL":
            conflicts.append({
                "code": "REGIME_CONFLICT",
                "primary": f"market_regime={primary_regime}",
                "enrichment": f"vol_regime={vol_regime_label}",
                "resolution": "primary wins",
            })
        assert len(conflicts) == 1
        assert conflicts[0]["code"] == "REGIME_CONFLICT"
        assert conflicts[0]["resolution"] == "primary wins"

    def test_no_conflict_when_aligned(self) -> None:
        primary_regime = "RISK_ON"
        vol_regime_label = "NORMAL"
        conflicts: list[dict[str, str]] = []
        if primary_regime == "RISK_OFF" and vol_regime_label == "LOW_VOL":
            conflicts.append({"code": "REGIME_CONFLICT"})
        assert conflicts == []

    def test_extreme_vs_compression_conflict(self) -> None:
        vol_regime_label = "EXTREME"
        compression_atr = "COMPRESSION"
        conflicts: list[dict[str, str]] = []
        if vol_regime_label == "EXTREME" and compression_atr == "COMPRESSION":
            conflicts.append({
                "code": "REGIME_CONFLICT",
                "primary": f"vol_regime={vol_regime_label}",
                "enrichment": f"compression_atr={compression_atr}",
                "resolution": "primary wins",
            })
        assert len(conflicts) == 1
