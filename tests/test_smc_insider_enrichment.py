"""Tests for scripts/smc_insider_enrichment.py."""
from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from smc_insider_enrichment import compute_insider_enrichment


class TestComputeInsiderEnrichment:

    def _mock_fmp(self, txns_by_symbol: dict[str, list[dict]]) -> MagicMock:
        fmp = MagicMock()
        fmp.get_insider_trading.side_effect = lambda s, **kw: txns_by_symbol.get(s, [])
        return fmp

    def test_buying_detected(self) -> None:
        recent = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        txns = {"AAPL": [
            {"transactionDate": recent, "transactionType": "P-Purchase",
             "securitiesTransacted": 5000, "price": 150},
        ]}
        fmp = self._mock_fmp(txns)
        result = compute_insider_enrichment(["AAPL"], fmp)
        assert "AAPL" in result["insider_buying_tickers"]

    def test_heavy_selling_detected(self) -> None:
        recent = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        txns = {"TSLA": [
            {"transactionDate": recent, "transactionType": "S-Sale",
             "securitiesTransacted": 20000, "price": 200},
        ]}
        fmp = self._mock_fmp(txns)
        result = compute_insider_enrichment(["TSLA"], fmp)
        assert "TSLA" in result["insider_selling_heavy_tickers"]

    def test_small_transaction_ignored(self) -> None:
        recent = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        txns = {"AAPL": [
            {"transactionDate": recent, "transactionType": "P-Purchase",
             "securitiesTransacted": 100, "price": 10},
        ]}
        fmp = self._mock_fmp(txns)
        result = compute_insider_enrichment(["AAPL"], fmp)
        assert result["insider_buying_tickers"] == []

    def test_empty_input(self) -> None:
        fmp = self._mock_fmp({})
        result = compute_insider_enrichment([], fmp)
        assert result["insider_buying_tickers"] == []
        assert result["insider_selling_heavy_tickers"] == []

    def test_return_shape(self) -> None:
        fmp = self._mock_fmp({})
        result = compute_insider_enrichment([], fmp)
        assert set(result.keys()) == {
            "insider_buying_tickers",
            "insider_selling_heavy_tickers",
        }
