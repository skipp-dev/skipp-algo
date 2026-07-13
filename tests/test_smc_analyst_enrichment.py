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
        fmp.get_company_profile.side_effect = lambda s: profiles_by_sym.get(s)
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
            "analyst_data_available",
            "analyst_symbols_attempted",
            "analyst_symbols_failed",
            "analyst_failure_rate",
        }

    def test_provider_outage_distinguishable_from_no_signal(self) -> None:
        # Every symbol raises → total provider outage: data_available False,
        # failure_rate 1.0. This must be distinguishable from a valid day with
        # no analyst signal (below), where all three lists are ALSO empty.
        fmp = MagicMock()
        fmp.get_company_profile.side_effect = RuntimeError("provider down")
        result = compute_analyst_enrichment(["AAPL", "MSFT"], fmp)
        assert result["analyst_strong_buy_tickers"] == []
        assert result["analyst_data_available"] is False
        assert result["analyst_symbols_attempted"] == 2
        assert result["analyst_symbols_failed"] == 2
        assert result["analyst_failure_rate"] == 1.0

    def test_valid_response_no_signal_is_available(self) -> None:
        # Provider responds with balanced ratings (no strong buy / underperform /
        # high upside) → empty lists but data IS available and no failures.
        estimates = {"AAPL": [{"analystStrongBuy": 3, "analystBuy": 3,
                               "analystHold": 10, "analystSell": 2,
                               "analystStrongSell": 1, "estimatedEpsAvg": 100}]}
        profiles = {"AAPL": {"price": 150}}
        fmp = self._mock_fmp(estimates, profiles)
        result = compute_analyst_enrichment(["AAPL"], fmp)
        assert result["analyst_strong_buy_tickers"] == []
        assert result["analyst_data_available"] is True
        assert result["analyst_symbols_failed"] == 0
        assert result["analyst_failure_rate"] == 0.0
