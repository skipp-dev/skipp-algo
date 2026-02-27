"""Tests for Benzinga Financial Data adapter.

Covers:
- BenzingaFinancialAdapter (all methods)
- Standalone wrapper functions
- Retry logic, error handling, edge cases
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from newsstack_fmp.ingest_benzinga_financial import (
    BARS_URL,
    FUNDAMENTALS_BASE,
    INSTRUMENTS_URL,
    LOGOS_URL,
    OPTIONS_ACTIVITY_URL,
    SEARCH_URL,
    SECURITY_URL,
    TICKER_DETAIL_URL,
    BenzingaFinancialAdapter,
    _request_with_retry,
    _sanitize_exc,
    _sanitize_url,
    fetch_benzinga_auto_complete,
    fetch_benzinga_company_profile,
    fetch_benzinga_financials,
    fetch_benzinga_fundamentals,
    fetch_benzinga_logos,
    fetch_benzinga_options_activity,
    fetch_benzinga_price_history,
    fetch_benzinga_ticker_detail,
)


# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def adapter() -> Generator[BenzingaFinancialAdapter, None, None]:
    """BenzingaFinancialAdapter with a dummy key."""
    a = BenzingaFinancialAdapter("test_key_12345")
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
# Constructor
# ═══════════════════════════════════════════════════════════════


class TestBenzingaFinancialAdapterInit:
    """Tests for BenzingaFinancialAdapter initialization."""

    def test_missing_key_raises(self):
        with pytest.raises(RuntimeError, match="BENZINGA_API_KEY"):
            BenzingaFinancialAdapter("")

    def test_none_key_raises(self):
        with pytest.raises(RuntimeError, match="BENZINGA_API_KEY"):
            BenzingaFinancialAdapter(None)  # type: ignore[arg-type]

    def test_valid_key_creates(self):
        a = BenzingaFinancialAdapter("valid_key")
        assert a.api_key == "valid_key"
        a.close()


# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════


class TestSanitizeUrl:
    def test_strips_apikey(self):
        url = "https://api.benzinga.com?apikey=secret123&other=ok"
        assert "secret123" not in _sanitize_url(url)
        assert "other=ok" in _sanitize_url(url)

    def test_strips_token(self):
        url = "https://api.benzinga.com?token=abc123&foo=bar"
        assert "abc123" not in _sanitize_url(url)

    def test_no_token_unchanged(self):
        url = "https://api.benzinga.com?foo=bar"
        assert _sanitize_url(url) == url


class TestSanitizeExc:
    def test_strips_from_exception(self):
        exc = Exception("Error at token=mykey123 in request")
        result = _sanitize_exc(exc)
        assert "mykey123" not in result
        assert "token=***" in result


# ═══════════════════════════════════════════════════════════════
# Fundamentals methods
# ═══════════════════════════════════════════════════════════════


class TestFetchFundamentals:
    def test_fetch_fundamentals(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [{"company": "AAPL", "companyProfile": {}}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_fundamentals("AAPL")
            assert len(result) == 1
            assert result[0]["company"] == "AAPL"

    def test_fetch_financials(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [{"ticker": "AAPL", "balanceSheet": {}}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_financials("AAPL", period="12M", report_type="A")
            assert len(result) == 1

    def test_fetch_valuation_ratios(self, adapter: BenzingaFinancialAdapter):
        data = [{"pe": 25.5, "pb": 12.3}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_valuation_ratios("AAPL")
            assert len(result) == 1
            assert result[0]["pe"] == 25.5

    def test_fetch_earning_ratios(self, adapter: BenzingaFinancialAdapter):
        data = [{"dilutedEPS": 6.12}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_earning_ratios("AAPL")
            assert len(result) == 1

    def test_fetch_operation_ratios(self, adapter: BenzingaFinancialAdapter):
        data = [{"grossMargin": 0.45}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_operation_ratios("AAPL")
            assert len(result) == 1

    def test_fetch_share_class(self, adapter: BenzingaFinancialAdapter):
        data = [{"sharesOutstanding": 15000000000}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_share_class("AAPL")
            assert len(result) == 1

    def test_fetch_earning_reports(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [{"eps": 2.10, "revenue": "120B"}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_earning_reports("AAPL")
            assert len(result) == 1

    def test_fetch_alpha_beta(self, adapter: BenzingaFinancialAdapter):
        data = [{"alpha": 0.05, "beta": 1.2}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_alpha_beta("AAPL")
            assert len(result) == 1

    def test_fetch_company_profile(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [{"sector": "Technology", "industry": "Consumer Electronics"}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_company_profile("AAPL")
            assert len(result) == 1
            assert result[0]["sector"] == "Technology"

    def test_fetch_company(self, adapter: BenzingaFinancialAdapter):
        data = [{"name": "Apple Inc", "ticker": "AAPL"}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_company("AAPL")
            assert len(result) == 1

    def test_fetch_share_class_profile_history(self, adapter: BenzingaFinancialAdapter):
        data = [{"date": "2025-01-01", "sharesOutstanding": 15000000000}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_share_class_profile_history("AAPL")
            assert len(result) == 1

    def test_fetch_asset_classification(self, adapter: BenzingaFinancialAdapter):
        data = [{"gicsSector": "Information Technology"}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_asset_classification("AAPL")
            assert len(result) == 1

    def test_fetch_summary(self, adapter: BenzingaFinancialAdapter):
        data = [{"ticker": "AAPL", "marketCap": 3000000000000}]
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_summary("AAPL")
            assert len(result) == 1


# ═══════════════════════════════════════════════════════════════
# Market Data methods
# ═══════════════════════════════════════════════════════════════


class TestMarketData:
    def test_fetch_price_history(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"open": 150.0, "high": 155.0, "low": 149.0, "close": 154.0, "volume": 1000000},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_price_history("AAPL", "2025-01-01", "2025-01-31")
            assert len(result) == 1
            assert result[0]["close"] == 154.0

    def test_fetch_chart(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"open": 150.0, "close": 152.0, "time": "09:30"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_chart("AAPL", "1d", interval="15M")
            assert len(result) == 1

    def test_fetch_auto_complete(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"symbol": "AAPL", "name": "Apple Inc", "exchange": "NASDAQ"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_auto_complete("AAPL", limit=5)
            assert len(result) == 1
            assert result[0]["symbol"] == "AAPL"

    def test_fetch_security(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"symbol": "AAPL", "exchange": "NASDAQ", "country": "US", "currency": "USD"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_security("AAPL")
            assert len(result) == 1

    def test_fetch_instruments(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"ticker": "AAPL", "marketCap": 3000000000000, "sector": "Technology"},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_instruments(sector="Technology", market_cap_gt="1b")
            assert len(result) == 1

    def test_fetch_logos(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [{"logo_url": "https://example.com/aapl.png"}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_logos("AAPL")
            assert len(result) == 1

    def test_fetch_ticker_detail(self, adapter: BenzingaFinancialAdapter):
        data = {"result": [
            {"ticker": "AAPL", "peers": ["MSFT", "GOOG"], "percentile": 95},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_ticker_detail("AAPL")
            assert len(result) == 1

    def test_fetch_options_activity(self, adapter: BenzingaFinancialAdapter):
        data = {"options_activity": [
            {"ticker": "AAPL", "type": "CALL", "strike": 200, "volume": 5000},
        ]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_options_activity("AAPL")
            assert len(result) == 1
            assert result[0]["type"] == "CALL"


# ═══════════════════════════════════════════════════════════════
# Edge cases
# ═══════════════════════════════════════════════════════════════


class TestEdgeCases:
    def test_empty_dict_response(self, adapter: BenzingaFinancialAdapter):
        """Empty dict returns empty list."""
        with patch.object(adapter.client, "get", return_value=_mock_response({})):
            result = adapter.fetch_fundamentals("AAPL")
            assert result == []

    def test_non_json_response(self, adapter: BenzingaFinancialAdapter):
        """Non-JSON response raises ValueError."""
        r = MagicMock(spec=httpx.Response)
        r.status_code = 200
        r.json.side_effect = ValueError("Not JSON")
        r.headers = {"content-type": "text/html"}
        r.raise_for_status = MagicMock()
        r.url = "https://api.benzinga.com/test"
        with patch.object(adapter.client, "get", return_value=r):
            with pytest.raises(ValueError, match="non-JSON"):
                adapter.fetch_fundamentals("AAPL")

    def test_string_response_returns_empty(self, adapter: BenzingaFinancialAdapter):
        """String response returns empty list."""
        with patch.object(adapter.client, "get", return_value=_mock_response("not a list")):
            result = adapter.fetch_fundamentals("AAPL")
            assert result == []

    def test_dict_fallback_finds_first_list(self, adapter: BenzingaFinancialAdapter):
        """Dict without recognized keys falls back to first list value."""
        data = {"custom_key": [{"ticker": "AAPL"}]}
        with patch.object(adapter.client, "get", return_value=_mock_response(data)):
            result = adapter.fetch_fundamentals("AAPL")
            assert len(result) == 1

    def test_isin_cik_params_passed(self, adapter: BenzingaFinancialAdapter):
        """Optional params like isin and cik should be included in request."""
        with patch.object(adapter.client, "get", return_value=_mock_response([])) as mock_get:
            adapter.fetch_fundamentals("AAPL", isin="US0378331005", cik="0000320193")
            call_args = mock_get.call_args
            params = call_args[1]["params"] if "params" in call_args[1] else call_args[0][1]
            assert params.get("isin") == "US0378331005" or "US0378331005" in str(params)

    def test_options_activity_date_params(self, adapter: BenzingaFinancialAdapter):
        """Options activity date filters should be passed correctly."""
        with patch.object(adapter.client, "get", return_value=_mock_response([])) as mock_get:
            adapter.fetch_options_activity("AAPL", date_from="2025-01-01", date_to="2025-01-31")
            call_args = mock_get.call_args
            params = call_args[1]["params"] if "params" in call_args[1] else call_args[0][1]
            assert "2025-01-01" in str(params)
            assert "2025-01-31" in str(params)


# ═══════════════════════════════════════════════════════════════
# Standalone wrapper functions
# ═══════════════════════════════════════════════════════════════


class TestStandaloneWrappers:
    """Test the convenience standalone functions."""

    def test_fetch_benzinga_fundamentals(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_fundamentals.return_value = [{"company": "AAPL"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_fundamentals("key", "AAPL")
            assert len(result) == 1
            mock_inst.close.assert_called_once()

    def test_fetch_benzinga_financials(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_financials.return_value = [{"balanceSheet": {}}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_financials("key", "AAPL")
            assert len(result) == 1
            mock_inst.close.assert_called_once()

    def test_fetch_benzinga_company_profile(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_company_profile.return_value = [{"sector": "Tech"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_company_profile("key", "AAPL")
            assert len(result) == 1

    def test_fetch_benzinga_options_activity(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_options_activity.return_value = [{"type": "CALL"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_options_activity("key", "AAPL")
            assert len(result) == 1

    def test_fetch_benzinga_ticker_detail(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_ticker_detail.return_value = [{"ticker": "AAPL"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_ticker_detail("key", "AAPL")
            assert len(result) == 1

    def test_fetch_benzinga_price_history(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_price_history.return_value = [{"close": 150.0}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_price_history("key", "AAPL", "2025-01-01", "2025-01-31")
            assert len(result) == 1

    def test_fetch_benzinga_logos(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_logos.return_value = [{"logo_url": "https://..."}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_logos("key", "AAPL")
            assert len(result) == 1

    def test_fetch_benzinga_auto_complete(self):
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_auto_complete.return_value = [{"symbol": "AAPL"}]
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_auto_complete("key", "AAPL")
            assert len(result) == 1

    def test_wrapper_returns_empty_on_error(self):
        """Standalone wrappers should return empty list on error, not crash."""
        with patch("newsstack_fmp.ingest_benzinga_financial.BenzingaFinancialAdapter") as MockAdapter:
            mock_inst = MagicMock()
            mock_inst.fetch_fundamentals.side_effect = RuntimeError("API error")
            MockAdapter.return_value = mock_inst

            result = fetch_benzinga_fundamentals("key", "AAPL")
            assert result == []
            mock_inst.close.assert_called_once()


# ═══════════════════════════════════════════════════════════════
# Retry logic
# ═══════════════════════════════════════════════════════════════


class TestRetryLogic:
    def test_retries_on_429(self):
        """Should retry on 429 status code."""
        r429 = MagicMock(spec=httpx.Response)
        r429.status_code = 429
        r429.raise_for_status = MagicMock()

        r200 = _mock_response({"result": [{"ok": True}]})

        client = MagicMock()
        client.get.side_effect = [r429, r200]

        with patch("newsstack_fmp.ingest_benzinga_financial.time.sleep"):
            result = _request_with_retry(client, "https://test.com", {})
            assert result.status_code == 200
            assert client.get.call_count == 2

    def test_retries_on_500(self):
        """Should retry on 500 status code."""
        r500 = MagicMock(spec=httpx.Response)
        r500.status_code = 500
        r500.raise_for_status = MagicMock()

        r200 = _mock_response([{"ok": True}])

        client = MagicMock()
        client.get.side_effect = [r500, r200]

        with patch("newsstack_fmp.ingest_benzinga_financial.time.sleep"):
            result = _request_with_retry(client, "https://test.com", {})
            assert result.status_code == 200

    def test_retries_on_connect_error(self):
        """Should retry on httpx.ConnectError."""
        r200 = _mock_response([])

        client = MagicMock()
        client.get.side_effect = [httpx.ConnectError("fail"), r200]

        with patch("newsstack_fmp.ingest_benzinga_financial.time.sleep"):
            result = _request_with_retry(client, "https://test.com", {})
            assert result.status_code == 200

    def test_raises_after_max_retries(self):
        """Should raise after exhausting retries."""
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("persistent fail")

        with patch("newsstack_fmp.ingest_benzinga_financial.time.sleep"):
            with pytest.raises(httpx.ConnectError):
                _request_with_retry(client, "https://test.com", {})
