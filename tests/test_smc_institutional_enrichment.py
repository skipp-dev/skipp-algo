"""Tests for scripts/smc_institutional_enrichment.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_institutional_enrichment import compute_institutional_enrichment


class TestComputeInstitutionalEnrichment:

    def _mock_fmp(self, holders_by_symbol: dict[str, list[dict]]) -> MagicMock:
        fmp = MagicMock()
        fmp.get_institutional_holders.side_effect = lambda s: holders_by_symbol.get(s, [])
        return fmp

    def test_accumulation_detected(self) -> None:
        holders = [
            {"shares": 1100, "previousShares": 1000},
            {"shares": 2200, "previousShares": 2000},
        ]
        fmp = self._mock_fmp({"AAPL": holders})
        result = compute_institutional_enrichment(["AAPL"], fmp)
        assert "AAPL" in result["institutional_accumulation_tickers"]

    def test_distribution_detected(self) -> None:
        holders = [
            {"shares": 900, "previousShares": 1000},
            {"shares": 1800, "previousShares": 2000},
        ]
        fmp = self._mock_fmp({"AAPL": holders})
        result = compute_institutional_enrichment(["AAPL"], fmp)
        assert "AAPL" in result["institutional_distribution_tickers"]

    def test_no_data(self) -> None:
        fmp = self._mock_fmp({})
        result = compute_institutional_enrichment(["AAPL"], fmp)
        assert result["institutional_data_available"] is False

    def test_return_shape(self) -> None:
        fmp = self._mock_fmp({})
        result = compute_institutional_enrichment([], fmp)
        assert set(result.keys()) == {
            "institutional_accumulation_tickers",
            "institutional_distribution_tickers",
            "institutional_data_available",
        }
