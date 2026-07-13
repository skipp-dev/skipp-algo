"""Tests for Benzinga Calendar new endpoints: dividends, splits, IPOs, guidance, retail.

These endpoints were added to BenzingaCalendarAdapter alongside the existing
ratings, earnings, economics, and conference-calls methods.
"""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from newsstack_fmp.ingest_benzinga_calendar import BenzingaCalendarAdapter

# Also test terminal_poller wrappers
from terminal_poller import (
    fetch_benzinga_dividends,
    fetch_benzinga_ipos,
    fetch_benzinga_splits,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def adapter(monkeypatch: pytest.MonkeyPatch) -> Generator[BenzingaCalendarAdapter, None, None]:
    """BenzingaCalendarAdapter with a dummy key, pinned to the direct route.

    dividends/splits/ipos default to the Massive reroute now (decoupled from
    the news provider flag); these tests exercise the direct calendar path.
    """
    monkeypatch.setenv("BENZINGA_MARKET_DATA_PROVIDER", "direct")
    a = BenzingaCalendarAdapter("test_key_12345")
    yield a
    a.close()


def _mock_response(data: Any, status_code: int = 200) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = data
    r.headers = {"content-type": "application/json"}
    r.raise_for_status = MagicMock()
    r.url = "https://api.benzinga.com/test"
    return r


# ═══════════════════════════════════════════════════════════════
# Dividends
# ═══════════════════════════════════════════════════════════════


class TestFetchDividends:
    def test_returns_items(self, adapter: BenzingaCalendarAdapter):
        data = {"dividends": [
            {"ticker": "AAPL", "dividend": 0.25, "ex_date": "2025-02-07"},
            {"ticker": "MSFT", "dividend": 0.75, "ex_date": "2025-02-14"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_dividends(date_from="2025-02-01", date_to="2025-02-28")
            assert len(result) == 2
            assert result[0]["ticker"] == "AAPL"

    def test_empty_response(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"dividends": []})):
            result = adapter.fetch_dividends()
            assert result == []

    def test_importance_filter(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"dividends": []})) as mock_get:
            adapter.fetch_dividends(importance=1)
            call_args = mock_get.call_args
            params = call_args[1].get("params", call_args[0][1] if len(call_args[0]) > 1 else {})
            assert "importance" in str(params) or "1" in str(params)


# ═══════════════════════════════════════════════════════════════
# Splits
# ═══════════════════════════════════════════════════════════════


class TestFetchSplits:
    def test_returns_items(self, adapter: BenzingaCalendarAdapter):
        data = {"stock-splits": [
            {"ticker": "NVDA", "ratio": "10:1", "date_ex": "2024-06-10"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_splits(date_from="2024-06-01")
            assert len(result) == 1
            assert result[0]["ratio"] == "10:1"

    def test_empty_response(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"stock-splits": []})):
            result = adapter.fetch_splits()
            assert result == []


# ═══════════════════════════════════════════════════════════════
# IPOs
# ═══════════════════════════════════════════════════════════════


class TestFetchIPOs:
    def test_returns_items(self, adapter: BenzingaCalendarAdapter):
        data = {"ipos": [
            {"ticker": "RDDT", "name": "Reddit", "pricing_date": "2024-03-21",
             "price_min": 31.0, "price_max": 34.0, "deal_status": "Priced"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_ipos(date_from="2024-03-01")
            assert len(result) == 1
            assert result[0]["name"] == "Reddit"

    def test_empty_response(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"ipos": []})):
            result = adapter.fetch_ipos()
            assert result == []


# ═══════════════════════════════════════════════════════════════
# Guidance
# ═══════════════════════════════════════════════════════════════


class TestFetchGuidance:
    def test_returns_items(self, adapter: BenzingaCalendarAdapter):
        data = {"guidance": [
            {"ticker": "AAPL", "period": "Q1", "period_year": "2025",
             "eps_guidance_est": "1.50", "revenue_guidance_est": "120B"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_guidance(date_from="2025-01-01")
            assert len(result) == 1
            assert result[0]["ticker"] == "AAPL"

    def test_empty_response(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"guidance": []})):
            result = adapter.fetch_guidance()
            assert result == []


# ═══════════════════════════════════════════════════════════════
# Retail
# ═══════════════════════════════════════════════════════════════


class TestFetchRetail:
    def test_returns_items(self, adapter: BenzingaCalendarAdapter):
        data = {"retail": [
            {"ticker": "WMT", "name": "Walmart", "period": "Q4",
             "sss": "3.2%", "sss_est": "2.5%", "retail_surprise": "0.7%"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_retail(date_from="2025-01-01")
            assert len(result) == 1
            assert result[0]["ticker"] == "WMT"

    def test_empty_response(self, adapter: BenzingaCalendarAdapter):
        with patch.object(adapter.client, "get", return_value=_mock_response({"retail": []})):
            result = adapter.fetch_retail()
            assert result == []


# ═══════════════════════════════════════════════════════════════
# Terminal poller wrappers
# ═══════════════════════════════════════════════════════════════


class TestTerminalPollerWrappers:
    """Test the terminal_poller.py wrapper functions for new calendar endpoints."""

    def test_fetch_benzinga_dividends_wraps(self):
        with patch("terminal_poller.BenzingaCalendarAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_dividends.return_value = [{"ticker": "AAPL"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_dividends("key", date_from="2025-01-01")
            assert len(result) == 1
            mock_inst.close.assert_called_once()

    def test_fetch_benzinga_splits_wraps(self):
        with patch("terminal_poller.BenzingaCalendarAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_splits.return_value = [{"ticker": "NVDA"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_splits("key")
            assert len(result) == 1

    def test_fetch_benzinga_ipos_wraps(self):
        with patch("terminal_poller.BenzingaCalendarAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_ipos.return_value = [{"ticker": "RDDT"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_ipos("key")
            assert len(result) == 1

    # fetch_benzinga_guidance / fetch_benzinga_retail wrapper tests removed
    # 2026-07-09: those terminal wrappers were retired (no Massive route; free
    # key being replaced). The adapter methods stay covered by TestFetchGuidance
    # / TestFetchRetail above.

    def test_wrapper_returns_empty_on_error(self):
        """Wrappers should return empty list on exception, not crash."""
        with patch("terminal_poller.BenzingaCalendarAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_dividends.side_effect = RuntimeError("API down")
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_dividends("key")
            assert result == []
            mock_inst.close.assert_called_once()

    def test_wrapper_returns_empty_when_adapter_none(self):
        """If BenzingaCalendarAdapter is None (import failed), return []."""
        with patch("terminal_poller.BenzingaCalendarAdapter", None):
            result = fetch_benzinga_dividends("key")
            assert result == []


# ═══════════════════════════════════════════════════════════════
# Massive-native routing (BENZINGA_PROVIDER=massive) for div/splits/ipos
# ═══════════════════════════════════════════════════════════════


class TestMassiveCalendarRouting:
    """With BENZINGA_PROVIDER=massive, dividends/splits/ipos fetch from the
    Massive reference endpoints and map to the Benzinga row shape the UI uses.
    Ratings/earnings/economics/guidance/retail/conf-calls have no Massive route
    and stay on the direct calendar path unchanged."""

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_dividends_massive_maps_rows(self, mock_req, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
        resp = MagicMock()
        resp.json.return_value = {"results": [{
            "ticker": "aapl", "cash_amount": 0.25, "ex_dividend_date": "2026-07-10",
            "pay_date": "2026-07-20", "record_date": "2026-07-11", "frequency": 4,
        }]}
        mock_req.return_value = resp

        adapter = BenzingaCalendarAdapter("k")
        rows = adapter.fetch_dividends(date_from="2026-07-01", date_to="2026-07-31")
        adapter.close()

        # hit the Massive reference host, not api.benzinga.com
        assert "api.massive.com/v3/reference/dividends" in mock_req.call_args.args[1]
        assert rows == [{
            "ticker": "AAPL", "date": "2026-07-10", "ex_date": "2026-07-10",
            "payable_date": "2026-07-20", "record_date": "2026-07-11",
            "dividend": 0.25, "frequency": 4,
        }]

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_splits_massive_maps_ratio(self, mock_req, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
        resp = MagicMock()
        resp.json.return_value = {"results": [{
            "ticker": "nvda", "execution_date": "2026-07-15", "split_from": 1, "split_to": 10,
        }]}
        mock_req.return_value = resp

        adapter = BenzingaCalendarAdapter("k")
        rows = adapter.fetch_splits(date_from="2026-07-01")
        adapter.close()

        assert "api.massive.com/v3/reference/splits" in mock_req.call_args.args[1]
        assert rows == [{"ticker": "NVDA", "date": "2026-07-15", "date_ex": "2026-07-15", "ratio": "10:1"}]

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_ipos_massive_maps_rows(self, mock_req, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
        resp = MagicMock()
        resp.json.return_value = {"results": [{
            "ticker": "RDDT", "issuer_name": "Reddit Inc", "primary_exchange": "XNYS",
            "listing_date": "2026-07-12", "lowest_offer_price": 31.0, "highest_offer_price": 34.0,
            "ipo_status": "pending", "total_offer_size": 748000000,
        }]}
        mock_req.return_value = resp

        adapter = BenzingaCalendarAdapter("k")
        rows = adapter.fetch_ipos(date_from="2026-07-01")
        adapter.close()

        assert "api.massive.com/vX/reference/ipos" in mock_req.call_args.args[1]
        assert rows[0]["ticker"] == "RDDT"
        assert rows[0]["name"] == "Reddit Inc"
        assert rows[0]["pricing_date"] == "2026-07-12"
        assert rows[0]["price_min"] == 31.0 and rows[0]["price_max"] == 34.0
        assert rows[0]["deal_status"] == "pending"

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_dividends_direct_route_under_override(self, mock_req, monkeypatch: pytest.MonkeyPatch):
        # Market data defaults to Massive; the direct calendar host is only hit
        # under the explicit BENZINGA_MARKET_DATA_PROVIDER=direct override —
        # NOT via the news BENZINGA_PROVIDER flag (decoupled, #3341/#3342).
        monkeypatch.setenv("BENZINGA_MARKET_DATA_PROVIDER", "direct")
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"dividends": [{"ticker": "AAPL"}]}
        mock_req.return_value = resp

        adapter = BenzingaCalendarAdapter("k")
        adapter.fetch_dividends()
        adapter.close()

        # direct override hits the Benzinga calendar host
        assert "api.benzinga.com/api/v2.1/calendar/dividends" in mock_req.call_args.args[1]

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_dividends_massive_fail_soft(self, mock_req, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("BENZINGA_PROVIDER", "massive")
        mock_req.side_effect = Exception("boom")
        adapter = BenzingaCalendarAdapter("k")
        assert adapter.fetch_dividends() == []
        adapter.close()
