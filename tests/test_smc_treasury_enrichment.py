"""Tests for treasury enrichment integration in build_enrichment."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))


class TestTreasuryEnrichmentBlock:
    """Test the treasury block dict structure that build_enrichment produces."""

    def test_normal_yield_curve(self) -> None:
        block = {
            "treasury_10y_yield": 4.25,
            "treasury_2y_yield": 3.80,
            "yield_curve_spread": 0.45,
            "yield_curve_inverted": False,
        }
        assert block["yield_curve_spread"] > 0
        assert block["yield_curve_inverted"] is False

    def test_inverted_yield_curve(self) -> None:
        block = {
            "treasury_10y_yield": 3.80,
            "treasury_2y_yield": 4.25,
            "yield_curve_spread": -0.45,
            "yield_curve_inverted": True,
        }
        assert block["yield_curve_spread"] < 0
        assert block["yield_curve_inverted"] is True

    def test_flat_yield_curve(self) -> None:
        block = {
            "treasury_10y_yield": 4.00,
            "treasury_2y_yield": 4.00,
            "yield_curve_spread": 0.0,
            "yield_curve_inverted": False,
        }
        assert block["yield_curve_spread"] == 0.0
        assert block["yield_curve_inverted"] is False

    def test_return_shape(self) -> None:
        block = {
            "treasury_10y_yield": 4.0,
            "treasury_2y_yield": 3.5,
            "yield_curve_spread": 0.5,
            "yield_curve_inverted": False,
        }
        assert set(block.keys()) == {
            "treasury_10y_yield",
            "treasury_2y_yield",
            "yield_curve_spread",
            "yield_curve_inverted",
        }

    def test_fmp_client_get_treasury_yields(self) -> None:
        from smc_fmp_client import SMCFMPClient
        fmp = MagicMock(spec=SMCFMPClient)
        fmp.get_treasury_yields.return_value = {
            "2y": 4.25, "10y": 3.80, "spread": -0.45, "inverted": True,
        }
        yields = fmp.get_treasury_yields()
        assert yields["inverted"] is True
        assert yields["spread"] < 0
