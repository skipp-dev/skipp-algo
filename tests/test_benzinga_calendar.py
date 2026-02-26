"""Extensive tests for Benzinga Calendar, Movers, and Quotes adapters.

Covers:
- BenzingaCalendarAdapter (ratings, earnings, economics, conference calls)
- fetch_benzinga_movers()
- fetch_benzinga_quotes()
- WIIM boost in _classify_item()
- terminal_poller wrapper functions
- Error handling, retries, edge cases
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from newsstack_fmp.ingest_benzinga_calendar import (
    CALENDAR_BASE,
    BenzingaCalendarAdapter,
    _request_with_retry,
    _sanitize_exc,
    _sanitize_url,
    fetch_benzinga_movers,
    fetch_benzinga_quotes,
)

# ═══════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════

@pytest.fixture
def adapter() -> BenzingaCalendarAdapter:
    """BenzingaCalendarAdapter with a dummy key."""
    a = BenzingaCalendarAdapter("test_key_12345")
    yield a
    a.close()


@pytest.fixture
def sample_ratings_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v2.1/calendar/ratings response."""
    return {
        "ratings": [
            {
                "id": "r1",
                "ticker": "AAPL",
                "date": "2025-01-20",
                "time": "09:30:00",
                "action_company": "Upgrades",
                "action_pt": "Raises",
                "analyst": "GS",
                "analyst_name": "John Doe",
                "pt_current": "250",
                "pt_prior": "220",
                "rating_current": "Buy",
                "rating_prior": "Neutral",
                "importance": "3",
                "updated": 1737380000,
            },
            {
                "id": "r2",
                "ticker": "NVDA",
                "date": "2025-01-20",
                "action_company": "Downgrades",
                "action_pt": "Lowers",
                "analyst": "MS",
                "analyst_name": "Jane Smith",
                "pt_current": "140",
                "pt_prior": "160",
                "rating_current": "Hold",
                "rating_prior": "Buy",
                "importance": "4",
                "updated": 1737380100,
            },
        ]
    }


@pytest.fixture
def sample_earnings_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v2.1/calendar/earnings response."""
    return {
        "earnings": [
            {
                "ticker": "AAPL",
                "date": "2025-01-28",
                "eps": "2.10",
                "eps_est": "2.05",
                "eps_prior": "1.90",
                "eps_surprise": "0.05",
                "eps_surprise_percent": "2.44",
                "revenue": "120B",
                "revenue_est": "118B",
                "revenue_prior": "110B",
                "revenue_surprise": "2B",
                "period": "Q1",
                "period_year": "2025",
                "importance": "5",
                "updated": 1737380000,
            },
        ]
    }


@pytest.fixture
def sample_economics_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v2.1/calendar/economics response."""
    return {
        "economics": [
            {
                "id": "e1",
                "event_name": "Non-Farm Payrolls",
                "country": "US",
                "date": "2025-02-07",
                "time": "08:30:00",
                "actual": "256K",
                "consensus": "165K",
                "prior": "212K",
                "importance": "5",
                "updated": 1737380000,
            },
            {
                "id": "e2",
                "event_name": "CPI Year-over-Year",
                "country": "US",
                "date": "2025-02-12",
                "time": "08:30:00",
                "actual": "",
                "consensus": "2.9%",
                "prior": "2.7%",
                "importance": "5",
                "updated": 1737380100,
            },
        ]
    }


@pytest.fixture
def sample_conference_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v2.1/calendar/conference-calls response."""
    return {
        "conference": [
            {
                "ticker": "MSFT",
                "date": "2025-01-29",
                "start_time": "17:00",
                "period": "Q2",
                "webcast_url": "https://events.example.com/msft-q2",
                "updated": 1737380000,
            },
        ]
    }


@pytest.fixture
def sample_movers_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v1/market/movers response."""
    return {
        "result": {
            "gainers": [
                {
                    "symbol": "XYZ",
                    "companyName": "XYZ Corp",
                    "price": 42.50,
                    "change": 5.30,
                    "changePercent": 14.25,
                    "volume": 12000000,
                    "averageVolume": 3000000,
                    "marketCap": 2500000000,
                    "gicsSectorName": "Technology",
                },
            ],
            "losers": [
                {
                    "symbol": "ABC",
                    "companyName": "ABC Inc",
                    "price": 15.20,
                    "change": -3.10,
                    "changePercent": -16.94,
                    "volume": 8000000,
                    "averageVolume": 2000000,
                    "marketCap": 800000000,
                    "gicsSectorName": "Healthcare",
                },
            ],
        }
    }


@pytest.fixture
def sample_quotes_response() -> dict[str, Any]:
    """Simulated Benzinga /api/v1/quoteDelayed response."""
    return {
        "quotes": [
            {
                "security": {"symbol": "AAPL", "name": "Apple Inc"},
                "quote": {
                    "last": 232.50,
                    "change": 3.25,
                    "changePercent": 1.42,
                    "open": 230.00,
                    "high": 233.80,
                    "low": 229.50,
                    "close": 232.50,
                    "volume": 55000000,
                    "fiftyTwoWeekHigh": 237.49,
                    "fiftyTwoWeekLow": 164.08,
                    "previousClose": 229.25,
                },
            },
            {
                "security": {"symbol": "NVDA", "name": "NVIDIA Corporation"},
                "quote": {
                    "last": 142.80,
                    "change": -2.10,
                    "changePercent": -1.45,
                    "open": 145.00,
                    "high": 146.00,
                    "low": 141.50,
                    "close": 142.80,
                    "volume": 45000000,
                    "fiftyTwoWeekHigh": 153.13,
                    "fiftyTwoWeekLow": 75.61,
                    "previousClose": 144.90,
                },
            },
        ]
    }


# ═══════════════════════════════════════════════════════════════
# URL Sanitisation Tests
# ═══════════════════════════════════════════════════════════════

class TestSanitisation:
    """Tests for URL and exception sanitisation helpers."""

    def test_sanitize_url_token(self):
        url = "https://api.benzinga.com/api/v2.1/calendar/ratings?token=SECRET123&pagesize=100"
        result = _sanitize_url(url)
        assert "SECRET123" not in result
        assert "token=***" in result
        assert "pagesize=100" in result

    def test_sanitize_url_apikey(self):
        url = "https://api.example.com/data?apikey=MY_SECRET&format=json"
        result = _sanitize_url(url)
        assert "MY_SECRET" not in result
        assert "apikey=***" in result

    def test_sanitize_url_no_key(self):
        url = "https://api.example.com/data?format=json"
        assert _sanitize_url(url) == url

    def test_sanitize_exc(self):
        exc = Exception("GET https://api.benzinga.com?token=SECRET123 failed")
        result = _sanitize_exc(exc)
        assert "SECRET123" not in result
        assert "token=***" in result

    def test_sanitize_exc_multiple_keys(self):
        exc = Exception("token=KEY1&apikey=KEY2")
        result = _sanitize_exc(exc)
        assert "KEY1" not in result
        assert "KEY2" not in result


# ═══════════════════════════════════════════════════════════════
# BenzingaCalendarAdapter Tests
# ═══════════════════════════════════════════════════════════════

class TestBenzingaCalendarAdapter:
    """Tests for the BenzingaCalendarAdapter class."""

    def test_init_requires_api_key(self):
        with pytest.raises(RuntimeError, match="BENZINGA_API_KEY missing"):
            BenzingaCalendarAdapter("")

    def test_init_accepts_valid_key(self):
        adapter = BenzingaCalendarAdapter("valid_key")
        assert adapter.api_key == "valid_key"
        adapter.close()

    def test_close_closes_client(self):
        adapter = BenzingaCalendarAdapter("key")
        adapter.close()
        # Should not raise on double close
        adapter.close()

    # ── Ratings ────────────────────────────────────────────

    def test_fetch_ratings_success(self, adapter, sample_ratings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert len(result) == 2
            assert result[0]["ticker"] == "AAPL"
            assert result[1]["ticker"] == "NVDA"
            assert result[0]["action_company"] == "Upgrades"
            assert result[1]["action_company"] == "Downgrades"

    def test_fetch_ratings_with_date_range(self, adapter, sample_ratings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings(date_from="2025-01-01", date_to="2025-01-31")
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[date_from]"] == "2025-01-01"
            assert params["parameters[date_to]"] == "2025-01-31"

    def test_fetch_ratings_with_tickers(self, adapter, sample_ratings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings(tickers="AAPL,NVDA")
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[tickers]"] == "AAPL,NVDA"

    def test_fetch_ratings_with_updated_since(self, adapter, sample_ratings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings(updated_since=1737380000)
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[updated]"] == "1737380000"

    def test_fetch_ratings_with_importance(self, adapter, sample_ratings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings(importance=3)
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[importance]"] == "3"

    def test_fetch_ratings_empty_response(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ratings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert result == []

    # ── Earnings ───────────────────────────────────────────

    def test_fetch_earnings_success(self, adapter, sample_earnings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_earnings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_earnings()
            assert len(result) == 1
            assert result[0]["ticker"] == "AAPL"
            assert result[0]["period"] == "Q1"
            assert result[0]["eps_surprise"] == "0.05"

    def test_fetch_earnings_with_date_range(self, adapter, sample_earnings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_earnings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_earnings(date_from="2025-01-01", date_to="2025-02-28")
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[date_from]"] == "2025-01-01"
            assert params["parameters[date_to]"] == "2025-02-28"

    def test_fetch_earnings_empty(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"earnings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_earnings()
            assert result == []

    # ── Economics ───────────────────────────────────────────

    def test_fetch_economics_success(self, adapter, sample_economics_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_economics_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_economics()
            assert len(result) == 2
            assert result[0]["event_name"] == "Non-Farm Payrolls"
            assert result[0]["country"] == "US"
            assert result[1]["event_name"] == "CPI Year-over-Year"

    def test_fetch_economics_with_importance(self, adapter, sample_economics_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_economics_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_economics(importance=4)
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[importance]"] == "4"

    def test_fetch_economics_no_tickers_param(self, adapter, sample_economics_response):
        """Economics endpoint does not accept tickers parameter."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_economics_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_economics()
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert "parameters[tickers]" not in params

    # ── Conference Calls ───────────────────────────────────

    def test_fetch_conference_calls_success(self, adapter, sample_conference_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_conference_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_conference_calls()
            assert len(result) == 1
            assert result[0]["ticker"] == "MSFT"
            assert result[0]["period"] == "Q2"
            assert "webcast_url" in result[0]

    def test_fetch_conference_calls_with_tickers(self, adapter, sample_conference_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_conference_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_conference_calls(tickers="MSFT,AAPL")
            call_args = mock_get.call_args
            params = call_args.kwargs.get("params", call_args[1].get("params", {}))
            assert params["parameters[tickers]"] == "MSFT,AAPL"

    # ── Edge cases: _fetch_calendar ────────────────────────

    def test_fetch_calendar_list_response(self, adapter):
        """API returns a plain list instead of a dict wrapper."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [{"ticker": "X", "date": "2025-01-01"}]
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert len(result) == 1
            assert result[0]["ticker"] == "X"

    def test_fetch_calendar_unexpected_wrapper_key(self, adapter):
        """API returns a dict with an unexpected wrapper key."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": [{"ticker": "Y"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert len(result) == 1  # falls back to first list value

    def test_fetch_calendar_empty_dict(self, adapter):
        """API returns an empty dict."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert result == []

    def test_fetch_calendar_non_json_response(self, adapter):
        """API returns non-JSON content (e.g. HTML error page)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.headers = {"content-type": "text/html"}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response), \
                pytest.raises(ValueError, match="non-JSON"):
                adapter.fetch_ratings()

    def test_fetch_calendar_dict_with_no_lists(self, adapter):
        """API returns a dict with no list values."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "ok", "count": 0}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert result == []

    def test_fetch_calendar_non_dict_non_list(self, adapter):
        """API returns something weird (number, string)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = "OK"
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_ratings()
            assert result == []

    def test_fetch_calendar_underscore_key_fallback(self, adapter):
        """API returns data under underscored endpoint name."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"conference_calls": [{"ticker": "Z"}]}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            result = adapter.fetch_conference_calls()
            assert len(result) == 1


# ═══════════════════════════════════════════════════════════════
# Retry Logic Tests
# ═══════════════════════════════════════════════════════════════

class TestRetryLogic:
    """Tests for _request_with_retry."""

    def test_success_no_retry(self):
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 200
        resp.raise_for_status = MagicMock()
        client.get.return_value = resp

        result = _request_with_retry(client, "https://x.com", {})
        assert result == resp
        assert client.get.call_count == 1

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_retry_on_429(self, mock_sleep):
        client = MagicMock()
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()

        client.get.side_effect = [resp_429, resp_ok]
        result = _request_with_retry(client, "https://x.com", {})
        assert result == resp_ok
        assert client.get.call_count == 2
        mock_sleep.assert_called_once()

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_retry_on_500(self, mock_sleep):
        client = MagicMock()
        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()

        client.get.side_effect = [resp_500, resp_ok]
        result = _request_with_retry(client, "https://x.com", {})
        assert result == resp_ok

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_retry_on_connect_error(self, mock_sleep):
        client = MagicMock()
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()

        client.get.side_effect = [httpx.ConnectError("Connection refused"), resp_ok]
        result = _request_with_retry(client, "https://x.com", {})
        assert result == resp_ok

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_retry_exhausted_raises(self, mock_sleep):
        client = MagicMock()
        client.get.side_effect = httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            _request_with_retry(client, "https://x.com", {})
        assert client.get.call_count == 3

    def test_http_status_error_no_retry(self):
        """Non-retryable HTTP errors (e.g. 403) should raise immediately."""
        client = MagicMock()
        resp = MagicMock()
        resp.status_code = 403
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Forbidden", request=MagicMock(), response=resp,
        )
        client.get.return_value = resp

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(client, "https://x.com", {})
        assert client.get.call_count == 1

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_retry_on_read_timeout(self, mock_sleep):
        client = MagicMock()
        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.raise_for_status = MagicMock()

        client.get.side_effect = [httpx.ReadTimeout("timeout"), resp_ok]
        result = _request_with_retry(client, "https://x.com", {})
        assert result == resp_ok

    @patch("newsstack_fmp.ingest_benzinga_calendar.time.sleep")
    def test_max_retries_returns_last_response(self, mock_sleep):
        """After max retries with retryable status, the last response is returned."""
        client = MagicMock()
        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.raise_for_status.side_effect = httpx.HTTPStatusError(
            "Service Unavailable", request=MagicMock(), response=resp_503,
        )

        client.get.return_value = resp_503

        with pytest.raises(httpx.HTTPStatusError):
            _request_with_retry(client, "https://x.com", {})
        assert client.get.call_count == 3


# ═══════════════════════════════════════════════════════════════
# Market Movers Tests
# ═══════════════════════════════════════════════════════════════

class TestBenzingaMovers:
    """Tests for fetch_benzinga_movers."""

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_success(self, mock_req, sample_movers_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_movers_response
        mock_req.return_value = mock_resp

        result = fetch_benzinga_movers("test_key")
        assert len(result["gainers"]) == 1
        assert len(result["losers"]) == 1
        assert result["gainers"][0]["symbol"] == "XYZ"
        assert result["losers"][0]["symbol"] == "ABC"

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_empty_result(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"result": {"gainers": [], "losers": []}}
        mock_req.return_value = mock_resp

        result = fetch_benzinga_movers("test_key")
        assert result["gainers"] == []
        assert result["losers"] == []

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_fetch_failure(self, mock_req):
        mock_req.side_effect = Exception("Network error")

        result = fetch_benzinga_movers("test_key")
        assert result == {"gainers": [], "losers": []}

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_flat_response(self, mock_req):
        """API returns data directly under result (no nested result key)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"gainers": [{"symbol": "A"}], "losers": []}
        mock_req.return_value = mock_resp

        result = fetch_benzinga_movers("test_key")
        assert len(result["gainers"]) == 1

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_non_dict_response(self, mock_req):
        mock_resp = MagicMock()
        mock_resp.json.return_value = []
        mock_req.return_value = mock_resp

        result = fetch_benzinga_movers("test_key")
        assert result == {"gainers": [], "losers": []}


# ═══════════════════════════════════════════════════════════════
# Delayed Quotes Tests
# ═══════════════════════════════════════════════════════════════

class TestBenzingaQuotes:
    """Tests for fetch_benzinga_quotes."""

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_success(self, mock_req, sample_quotes_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_quotes_response
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("test_key", ["AAPL", "NVDA"])
        assert len(result) == 2
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["last"] == 232.50
        assert result[0]["change"] == 3.25
        assert result[0]["changePercent"] == 1.42
        assert result[1]["symbol"] == "NVDA"
        assert result[1]["last"] == 142.80
        assert result[1]["change"] == -2.10

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_empty_symbols(self, mock_req):
        result = fetch_benzinga_quotes("test_key", [])
        assert result == []
        mock_req.assert_not_called()

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_failure(self, mock_req):
        mock_req.side_effect = Exception("Timeout")

        result = fetch_benzinga_quotes("test_key", ["AAPL"])
        assert result == []

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_flatten_structure(self, mock_req):
        """Verify the nested security/quote structure is properly flattened."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "quotes": [{
                "security": {"symbol": "SPY", "name": "SPDR S&P 500"},
                "quote": {
                    "last": 500.0,
                    "change": 2.0,
                    "changePercent": 0.4,
                    "open": 498.0,
                    "high": 501.0,
                    "low": 497.0,
                    "close": 500.0,
                    "volume": 90000000,
                    "fiftyTwoWeekHigh": 510.0,
                    "fiftyTwoWeekLow": 400.0,
                    "previousClose": 498.0,
                },
            }]
        }
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("test_key", ["SPY"])
        assert len(result) == 1
        q = result[0]
        assert q["symbol"] == "SPY"
        assert q["name"] == "SPDR S&P 500"
        assert q["last"] == 500.0
        assert q["open"] == 498.0
        assert q["high"] == 501.0
        assert q["low"] == 497.0
        assert q["volume"] == 90000000
        assert q["fiftyTwoWeekHigh"] == 510.0
        assert q["fiftyTwoWeekLow"] == 400.0
        assert q["previousClose"] == 498.0

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_handles_missing_security(self, mock_req):
        """Handle quote items with missing security or quote keys."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "quotes": [
                {"security": None, "quote": {"last": 100}},
                {"quote": {"last": 200}},
                "not_a_dict",
            ]
        }
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("test_key", ["TEST"])
        assert len(result) == 2  # skips non-dict
        assert result[0]["symbol"] == ""  # None security
        assert result[0]["last"] == 100
        assert result[1]["symbol"] == ""  # missing security

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_list_response(self, mock_req):
        """API returns a plain list instead of dict with quotes key."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = [{
            "security": {"symbol": "A", "name": "Alpha"},
            "quote": {"last": 10.0},
        }]
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("test_key", ["A"])
        assert len(result) == 1
        assert result[0]["symbol"] == "A"

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_max_50_symbols(self, mock_req):
        """Verify API call is limited to 50 symbols."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"quotes": []}
        mock_req.return_value = mock_resp

        symbols = [f"SYM{i}" for i in range(100)]
        fetch_benzinga_quotes("test_key", symbols)

        call_args = mock_req.call_args
        params = call_args[0][2]  # positional arg 3
        sym_csv = params["symbols"]
        assert len(sym_csv.split(",")) == 50

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_uppercase_symbols(self, mock_req):
        """Verify symbols are uppercased."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"quotes": []}
        mock_req.return_value = mock_resp

        fetch_benzinga_quotes("test_key", ["aapl", "nvda"])

        call_args = mock_req.call_args
        params = call_args[0][2]
        assert params["symbols"] == "AAPL,NVDA"

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_fallback_close_for_last(self, mock_req):
        """When 'last' is None, fall back to 'close'."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "quotes": [{
                "security": {"symbol": "X"},
                "quote": {"last": None, "close": 42.0},
            }]
        }
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("test_key", ["X"])
        assert result[0]["last"] == 42.0


# ═══════════════════════════════════════════════════════════════
# WIIM Boost Tests
# ═══════════════════════════════════════════════════════════════

class TestWIIMBoost:
    """Tests for WIIM channel boost in _classify_item."""

    @pytest.fixture
    def tmp_store(self, tmp_path):
        from newsstack_fmp.store_sqlite import SqliteStore
        return SqliteStore(str(tmp_path / "wiim_test.db"))

    def _make_newsitem(self, channels: list[dict], item_id: str = "test1") -> Any:
        from newsstack_fmp.common_types import NewsItem
        return NewsItem(
            provider="benzinga_rest",
            item_id=item_id,
            published_ts=time.time() - 60,
            updated_ts=time.time(),
            headline="NVIDIA Reports Record Q4 Earnings",
            snippet="NVIDIA posted Q4 earnings that topped expectations",
            tickers=["NVDA"],
            url="https://www.benzinga.com/news/test",
            source="Benzinga",
            raw={
                "channels": channels,
                "tags": [{"name": "earnings"}],
            },
        )

    def test_wiim_channel_boosts_score(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "WIIM"}, {"name": "Earnings"}],
            item_id="wiim_test_1",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        assert len(results) >= 1
        ci = results[0]
        assert ci.is_wiim is True

    def test_no_wiim_channel(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "Earnings"}, {"name": "Tech"}],
            item_id="no_wiim_test_1",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        assert len(results) >= 1
        ci = results[0]
        assert ci.is_wiim is False

    def test_wiim_case_insensitive(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "wiim"}, {"name": "news"}],
            item_id="wiim_case_1",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        assert results[0].is_wiim is True

    def test_wiim_boost_increases_score(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        # Create two identical items, one with WIIM and one without
        item_no_wiim = self._make_newsitem(
            [{"name": "Earnings"}],
            item_id="compare_no_wiim",
        )
        item_wiim = self._make_newsitem(
            [{"name": "WIIM"}, {"name": "Earnings"}],
            item_id="compare_with_wiim",
        )

        now = datetime.now(UTC)
        results_no_wiim = _classify_item(item_no_wiim, tmp_store, now)
        results_wiim = _classify_item(item_wiim, tmp_store, now)

        assert results_no_wiim and results_wiim
        # WIIM item should have higher or equal score
        assert results_wiim[0].news_score >= results_no_wiim[0].news_score

    def test_wiim_score_capped_at_1(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "WIIM"}],
            item_id="wiim_cap_test",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        assert results[0].news_score <= 1.0
        assert results[0].relevance <= 1.0

    def test_wiim_in_to_dict(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "WIIM"}],
            item_id="wiim_dict_test",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        d = results[0].to_dict()
        assert "is_wiim" in d
        assert d["is_wiim"] is True

    def test_no_wiim_in_to_dict(self, tmp_store):
        from datetime import UTC, datetime

        from terminal_poller import _classify_item

        item = self._make_newsitem(
            [{"name": "Tech"}],
            item_id="no_wiim_dict_test",
        )
        results = _classify_item(item, tmp_store, datetime.now(UTC))
        d = results[0].to_dict()
        assert d["is_wiim"] is False


# ═══════════════════════════════════════════════════════════════
# Terminal Poller Wrapper Function Tests
# ═══════════════════════════════════════════════════════════════

class TestPollerWrappers:
    """Tests for the convenience wrapper functions in terminal_poller."""

    @patch("terminal_poller.BenzingaCalendarAdapter")
    def test_fetch_benzinga_ratings_wrapper(self, MockAdapter):
        from terminal_poller import fetch_benzinga_ratings

        mock_instance = MockAdapter.return_value
        mock_instance.fetch_ratings.return_value = [{"ticker": "AAPL"}]

        result = fetch_benzinga_ratings("key123", date_from="2025-01-01")
        assert result == [{"ticker": "AAPL"}]
        mock_instance.close.assert_called_once()

    @patch("terminal_poller.BenzingaCalendarAdapter")
    def test_fetch_benzinga_ratings_error(self, MockAdapter):
        from terminal_poller import fetch_benzinga_ratings

        mock_instance = MockAdapter.return_value
        mock_instance.fetch_ratings.side_effect = Exception("API error")

        result = fetch_benzinga_ratings("key123")
        assert result == []
        mock_instance.close.assert_called_once()

    @patch("terminal_poller.BenzingaCalendarAdapter")
    def test_fetch_benzinga_earnings_wrapper(self, MockAdapter):
        from terminal_poller import fetch_benzinga_earnings

        mock_instance = MockAdapter.return_value
        mock_instance.fetch_earnings.return_value = [{"ticker": "NVDA", "eps": "2.0"}]

        result = fetch_benzinga_earnings("key123", date_from="2025-01-01", date_to="2025-02-01")
        assert len(result) == 1
        assert result[0]["ticker"] == "NVDA"
        mock_instance.close.assert_called_once()

    @patch("terminal_poller.BenzingaCalendarAdapter")
    def test_fetch_benzinga_economics_wrapper(self, MockAdapter):
        from terminal_poller import fetch_benzinga_economics

        mock_instance = MockAdapter.return_value
        mock_instance.fetch_economics.return_value = [{"event_name": "NFP"}]

        result = fetch_benzinga_economics("key123", importance=4)
        assert result == [{"event_name": "NFP"}]
        mock_instance.close.assert_called_once()

    @patch("terminal_poller.fetch_benzinga_movers")
    def test_fetch_benzinga_market_movers_wrapper(self, mock_fn):
        from terminal_poller import fetch_benzinga_market_movers

        mock_fn.return_value = {"gainers": [{"symbol": "X"}], "losers": []}
        result = fetch_benzinga_market_movers("key123")
        assert result["gainers"][0]["symbol"] == "X"

    @patch("terminal_poller.fetch_benzinga_quotes")
    def test_fetch_benzinga_delayed_quotes_wrapper(self, mock_fn):
        from terminal_poller import fetch_benzinga_delayed_quotes

        mock_fn.return_value = [{"symbol": "AAPL", "last": 230.0}]
        result = fetch_benzinga_delayed_quotes("key123", ["AAPL"])
        assert result[0]["symbol"] == "AAPL"


# ═══════════════════════════════════════════════════════════════
# Adapter URL Construction Tests
# ═══════════════════════════════════════════════════════════════

class TestURLConstruction:
    """Verify correct URL construction for all endpoints."""

    def test_ratings_url(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ratings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings()
            url = mock_get.call_args[0][0]
            assert url == f"{CALENDAR_BASE}/ratings"

    def test_earnings_url(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"earnings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_earnings()
            url = mock_get.call_args[0][0]
            assert url == f"{CALENDAR_BASE}/earnings"

    def test_economics_url(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"economics": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_economics()
            url = mock_get.call_args[0][0]
            assert url == f"{CALENDAR_BASE}/economics"

    def test_conference_calls_url(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"conference-calls": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_conference_calls()
            url = mock_get.call_args[0][0]
            assert url == f"{CALENDAR_BASE}/conference-calls"

    def test_token_in_params(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ratings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings()
            params = mock_get.call_args.kwargs.get("params", mock_get.call_args[1].get("params", {}))
            assert params["token"] == "test_key_12345"

    def test_pagesize_in_params(self, adapter):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ratings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings(page_size=50)
            params = mock_get.call_args.kwargs.get("params", mock_get.call_args[1].get("params", {}))
            assert params["pagesize"] == "50"

    def test_no_optional_params_when_none(self, adapter):
        """Verify optional params (tickers, dates, etc.) are NOT sent when None."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"ratings": []}
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response) as mock_get:
            adapter.fetch_ratings()
            params = mock_get.call_args.kwargs.get("params", mock_get.call_args[1].get("params", {}))
            assert "parameters[updated]" not in params
            assert "parameters[tickers]" not in params
            assert "parameters[date_from]" not in params
            assert "parameters[date_to]" not in params
            assert "parameters[importance]" not in params


# ═══════════════════════════════════════════════════════════════
# Accept Header Tests
# ═══════════════════════════════════════════════════════════════

class TestAcceptHeader:
    """Verify the Accept: application/json header is set."""

    def test_calendar_adapter_accept_header(self):
        adapter = BenzingaCalendarAdapter("key")
        assert adapter.client.headers.get("accept") == "application/json"
        adapter.close()


# ═══════════════════════════════════════════════════════════════
# Integration-style Tests (end-to-end with mocked HTTP)
# ═══════════════════════════════════════════════════════════════

class TestEndToEnd:
    """End-to-end adapter tests using mocked HTTP transport."""

    def test_ratings_roundtrip(self, adapter, sample_ratings_response):
        """Full roundtrip test: construct adapter, fetch, parse, verify."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_ratings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            ratings = adapter.fetch_ratings(
                date_from="2025-01-01",
                date_to="2025-01-31",
                page_size=50,
            )

        assert len(ratings) == 2
        # Verify first rating has all expected fields
        r1 = ratings[0]
        assert r1["ticker"] == "AAPL"
        assert r1["action_company"] == "Upgrades"
        assert r1["analyst_name"] == "John Doe"
        assert r1["pt_current"] == "250"
        assert r1["pt_prior"] == "220"
        assert r1["rating_current"] == "Buy"
        assert r1["rating_prior"] == "Neutral"

    def test_earnings_roundtrip(self, adapter, sample_earnings_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_earnings_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            earnings = adapter.fetch_earnings(
                date_from="2025-01-01",
                date_to="2025-02-28",
                importance=3,
            )

        assert len(earnings) == 1
        e = earnings[0]
        assert e["ticker"] == "AAPL"
        assert e["eps_surprise"] == "0.05"
        assert e["period_year"] == "2025"

    def test_economics_roundtrip(self, adapter, sample_economics_response):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_economics_response
        mock_response.raise_for_status = MagicMock()

        with patch.object(adapter.client, "get", return_value=mock_response):
            econ = adapter.fetch_economics(importance=4)

        assert len(econ) == 2
        assert econ[0]["country"] == "US"

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_movers_roundtrip(self, mock_req, sample_movers_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_movers_response
        mock_req.return_value = mock_resp

        result = fetch_benzinga_movers("key")
        assert result["gainers"][0]["changePercent"] == 14.25
        assert result["losers"][0]["changePercent"] == -16.94

    @patch("newsstack_fmp.ingest_benzinga_calendar._request_with_retry")
    def test_quotes_roundtrip(self, mock_req, sample_quotes_response):
        mock_resp = MagicMock()
        mock_resp.json.return_value = sample_quotes_response
        mock_req.return_value = mock_resp

        result = fetch_benzinga_quotes("key", ["AAPL", "NVDA"])
        assert result[0]["fiftyTwoWeekHigh"] == 237.49
        assert result[1]["previousClose"] == 144.90


# ═══════════════════════════════════════════════════════════════
# ClassifiedItem is_wiim serialization tests
# ═══════════════════════════════════════════════════════════════

class TestClassifiedItemWIIM:
    """Test that is_wiim is properly handled in ClassifiedItem."""

    def test_classified_item_has_is_wiim(self):
        from terminal_poller import ClassifiedItem
        ci = ClassifiedItem(
            item_id="test1",
            ticker="AAPL",
            tickers_all=["AAPL"],
            headline="Test",
            snippet="",
            url=None,
            source="test",
            published_ts=time.time(),
            updated_ts=time.time(),
            provider="test",
            category="other",
            impact=0.5,
            clarity=0.5,
            polarity=0.5,
            news_score=0.5,
            cluster_hash="abc123",
            novelty_count=1,
            relevance=0.5,
            entity_count=1,
            sentiment_label="neutral",
            sentiment_score=0.0,
            event_class="UNKNOWN",
            event_label="other",
            materiality="LOW",
            recency_bucket="FRESH",
            age_minutes=5.0,
            is_actionable=True,
            source_tier="TIER_2",
            source_rank=2,
            channels=["WIIM"],
            tags=[],
            is_wiim=True,
        )
        assert ci.is_wiim is True
        d = ci.to_dict()
        assert d["is_wiim"] is True

    def test_classified_item_no_wiim(self):
        from terminal_poller import ClassifiedItem
        ci = ClassifiedItem(
            item_id="test2",
            ticker="NVDA",
            tickers_all=["NVDA"],
            headline="Test No WIIM",
            snippet="",
            url=None,
            source="test",
            published_ts=time.time(),
            updated_ts=time.time(),
            provider="test",
            category="other",
            impact=0.5,
            clarity=0.5,
            polarity=0.5,
            news_score=0.5,
            cluster_hash="abc124",
            novelty_count=1,
            relevance=0.5,
            entity_count=1,
            sentiment_label="neutral",
            sentiment_score=0.0,
            event_class="UNKNOWN",
            event_label="other",
            materiality="LOW",
            recency_bucket="FRESH",
            age_minutes=5.0,
            is_actionable=True,
            source_tier="TIER_2",
            source_rank=2,
            channels=["Earnings"],
            tags=[],
            is_wiim=False,
        )
        assert ci.is_wiim is False
        d = ci.to_dict()
        assert d["is_wiim"] is False
