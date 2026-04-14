"""Tests for scripts/smc_sector_rotation_enrichment.py."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_sector_rotation_enrichment import compute_sector_rotation


class TestComputeSectorRotation:

    def test_leading_and_lagging(self) -> None:
        data = [
            {"sector": "Technology", "changesPercentage": 2.5},
            {"sector": "Energy", "changesPercentage": 1.8},
            {"sector": "Utilities", "changesPercentage": -1.2},
            {"sector": "Healthcare", "changesPercentage": -0.5},
        ]
        result = compute_sector_rotation(data)
        assert "Technology" in result["sector_leading"]
        assert "Utilities" in result["sector_lagging"]
        assert result["sector_strongest"] == "Technology"
        assert result["sector_weakest"] == "Utilities"

    def test_empty_data(self) -> None:
        result = compute_sector_rotation([])
        assert result["sector_leading"] == []
        assert result["sector_lagging"] == []
        assert result["sector_strongest"] == ""
        assert result["sector_weakest"] == ""

    def test_single_sector(self) -> None:
        data = [{"sector": "Tech", "changesPercentage": 1.0}]
        result = compute_sector_rotation(data)
        assert result["sector_strongest"] == "Tech"
        assert result["sector_weakest"] == "Tech"

    def test_return_shape(self) -> None:
        data = [{"sector": "Tech", "changesPercentage": 0.5}]
        result = compute_sector_rotation(data)
        assert set(result.keys()) == {
            "sector_leading", "sector_lagging",
            "sector_strongest", "sector_weakest",
        }
