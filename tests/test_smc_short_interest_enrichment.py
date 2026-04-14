"""Tests for scripts/smc_short_interest_enrichment.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_short_interest_enrichment import compute_short_interest_enrichment


class TestComputeShortInterestEnrichment:

    def _mock_fmp(self, si_map: dict[str, float]) -> MagicMock:
        fmp = MagicMock()
        fmp.get_short_interest.return_value = si_map
        return fmp

    def test_high_short_interest_detected(self) -> None:
        fmp = self._mock_fmp({"AAPL": 5.0, "GME": 35.0, "AMC": 22.0})
        result = compute_short_interest_enrichment(["AAPL", "GME", "AMC"], fmp)
        assert "GME" in result["high_short_interest_tickers"]
        assert "AMC" in result["high_short_interest_tickers"]
        assert "AAPL" not in result["high_short_interest_tickers"]

    def test_squeeze_risk_threshold(self) -> None:
        fmp = self._mock_fmp({"GME": 45.0, "TSLA": 8.0})
        result = compute_short_interest_enrichment(["GME", "TSLA"], fmp)
        assert "GME" in result["short_squeeze_risk_tickers"]
        assert "TSLA" not in result["short_squeeze_risk_tickers"]

    def test_empty_input(self) -> None:
        fmp = self._mock_fmp({})
        result = compute_short_interest_enrichment([], fmp)
        assert result["short_squeeze_risk_tickers"] == []
        assert result["high_short_interest_tickers"] == []

    def test_market_average(self) -> None:
        fmp = self._mock_fmp({"A": 10.0, "B": 20.0, "C": 30.0})
        result = compute_short_interest_enrichment(["A", "B", "C"], fmp)
        assert result["market_short_interest_avg"] == 20.0

    def test_extreme_flag(self) -> None:
        fmp = self._mock_fmp({"A": 50.0, "B": 40.0, "C": 30.0})
        result = compute_short_interest_enrichment(["A", "B", "C"], fmp)
        assert result["market_short_interest_avg"] >= 25.0
        assert result["short_interest_extreme"] is True

    def test_return_shape(self) -> None:
        fmp = self._mock_fmp({"AAPL": 5.0})
        result = compute_short_interest_enrichment(["AAPL"], fmp)
        assert set(result.keys()) == {
            "short_squeeze_risk_tickers",
            "high_short_interest_tickers",
            "market_short_interest_avg",
            "short_interest_extreme",
        }
