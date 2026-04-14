"""Tests for scripts/smc_analyst_enrichment.py."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_analyst_enrichment import compute_analyst_enrichment


class TestComputeAnalystEnrichment:

    def _mock_fmp(self, estimates_by_sym: dict[str, list], profiles_by_sym: dict[str, dict]) -> MagicMock:
        fmp = MagicMock()
        fmp.get_analyst_estimates.side_effect = lambda s, **kw: estimates_by_sym.get(s, [])
        fmp.get_company_profile.side_effect = lambda s: profiles_by_sym.get(s, None)
        return fmp

    def test_strong_buy_detected(self) -> None:
        estimates = {"AAPL": [{"analystStrongBuy": 15, "analystBuy": 10,
                               "analystHold": 3, "analystSell": 1,
                               "analystStrongSell": 0, "estimatedEpsAvg": 0}]}
        profiles = {"AAPL": {"price": 150}}
        fmp = self._mock_fmp(estimates, profiles)
        result = compute_analyst_enrichment(["AAPL"], fmp)
        assert "AAPL" in result["analyst_strong_buy_tickers"]

    def test_high_upside_detected(self) -> None:
        estimates = {"AAPL": [{"analystStrongBuy": 5, "analystBuy": 5,
                               "analystHold": 5, "analystSell": 5,
                               "analystStrongSell": 0, "estimatedEpsAvg": 200}]}
        profiles = {"AAPL": {"price": 100}}
        fmp = self._mock_fmp(estimates, profiles)
        result = compute_analyst_enrichment(["AAPL"], fmp)
        assert "AAPL" in result["analyst_high_upside_tickers"]

    def test_empty_input(self) -> None:
        fmp = self._mock_fmp({}, {})
        result = compute_analyst_enrichment([], fmp)
        assert result["analyst_strong_buy_tickers"] == []

    def test_return_shape(self) -> None:
        fmp = self._mock_fmp({}, {})
        result = compute_analyst_enrichment([], fmp)
        assert set(result.keys()) == {
            "analyst_strong_buy_tickers",
            "analyst_underperform_tickers",
            "analyst_high_upside_tickers",
        }
