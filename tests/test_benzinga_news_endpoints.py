"""Tests for Benzinga news endpoints: top_news, channels, quantified_news.

Covers:
- fetch_benzinga_top_news()
- fetch_benzinga_channels()
- fetch_benzinga_quantified_news()
- Retry logic, error handling, edge cases
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest

# Ensure project root is on the path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from newsstack_fmp.ingest_benzinga import (
    fetch_benzinga_channels,
    fetch_benzinga_quantified_news,
    fetch_benzinga_top_news,
)


# ═══════════════════════════════════════════════════════════════
# fetch_benzinga_top_news
# ═══════════════════════════════════════════════════════════════


class TestFetchBenzingaTopNews:
    """Tests for fetch_benzinga_top_news()."""

    def _mock_response(self, data: Any, status_code: int = 200) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = status_code
        r.json.return_value = data
        r.headers = {"content-type": "application/json"}
        r.raise_for_status = MagicMock()
        r.url = "https://api.benzinga.com/api/v2/news/top?token=***"
        return r

    def test_returns_list_response(self):
        """If API returns a bare list, return it directly."""
        stories = [
            {"title": "AAPL hits record high", "author": "BZ", "created": "2025-01-20"},
            {"title": "NVDA earnings beat", "author": "BZ", "created": "2025-01-20"},
        ]
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(stories)

            result = fetch_benzinga_top_news("test_key")
            assert len(result) == 2
            assert result[0]["title"] == "AAPL hits record high"

    def test_returns_dict_with_articles_key(self):
        """If API wraps in {articles: [...]}, extract correctly."""
        data = {"articles": [{"title": "SPY up 2%"}]}
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(data)

            result = fetch_benzinga_top_news("test_key")
            assert len(result) == 1

    def test_returns_empty_on_error(self):
        """On network error, return empty list rather than crashing."""
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.side_effect = httpx.ConnectError("Connection refused")

            result = fetch_benzinga_top_news("test_key")
            assert result == []

    def test_channel_param_passed(self):
        """Channel filter should be passed as query param."""
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response([])

            fetch_benzinga_top_news("test_key", channel="Markets,Earnings")
            call_args = MockClient.return_value.get.call_args
            assert call_args[1]["params"]["channel"] == "Markets,Earnings"

    def test_limit_param(self):
        """Limit should be passed as string."""
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response([])

            fetch_benzinga_top_news("test_key", limit=50)
            call_args = MockClient.return_value.get.call_args
            assert call_args[1]["params"]["limit"] == "50"

    def test_empty_dict_response(self):
        """Empty dict with no recognized keys should return empty list."""
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response({})

            result = fetch_benzinga_top_news("test_key")
            assert result == []


# ═══════════════════════════════════════════════════════════════
# fetch_benzinga_channels
# ═══════════════════════════════════════════════════════════════


class TestFetchBenzingaChannels:
    """Tests for fetch_benzinga_channels()."""

    def _mock_response(self, data: Any, status_code: int = 200) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = status_code
        r.json.return_value = data
        r.headers = {"content-type": "application/json"}
        r.raise_for_status = MagicMock()
        r.url = "https://api.benzinga.com/api/v2/news/channels"
        return r

    def test_returns_list(self):
        channels = [{"name": "Markets", "id": "1"}, {"name": "Earnings", "id": "2"}]
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(channels)

            result = fetch_benzinga_channels("test_key")
            assert len(result) == 2
            assert result[0]["name"] == "Markets"

    def test_returns_dict_with_channels_key(self):
        data = {"channels": [{"name": "SEC", "id": "3"}]}
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(data)

            result = fetch_benzinga_channels("test_key")
            assert len(result) == 1
            assert result[0]["name"] == "SEC"

    def test_returns_empty_on_error(self):
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.side_effect = httpx.ReadTimeout("Timeout")

            result = fetch_benzinga_channels("test_key")
            assert result == []

    def test_pagination_params(self):
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response([])

            fetch_benzinga_channels("test_key", page_size=50, page=2)
            call_args = MockClient.return_value.get.call_args
            assert call_args[1]["params"]["pageSize"] == "50"
            assert call_args[1]["params"]["page"] == "2"


# ═══════════════════════════════════════════════════════════════
# fetch_benzinga_quantified_news
# ═══════════════════════════════════════════════════════════════


class TestFetchBenzingaQuantifiedNews:
    """Tests for fetch_benzinga_quantified_news()."""

    def _mock_response(self, data: Any, status_code: int = 200) -> MagicMock:
        r = MagicMock(spec=httpx.Response)
        r.status_code = status_code
        r.json.return_value = data
        r.headers = {"content-type": "application/json"}
        r.raise_for_status = MagicMock()
        r.url = "https://api.benzinga.com/api/v2/news/quantified"
        return r

    def test_returns_list(self):
        items = [
            {"headline": "AAPL", "volume": 1000000, "day_open": 150.0},
            {"headline": "NVDA", "volume": 2000000, "day_open": 500.0},
        ]
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(items)

            result = fetch_benzinga_quantified_news("test_key")
            assert len(result) == 2

    def test_date_params(self):
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response([])

            fetch_benzinga_quantified_news(
                "test_key",
                date_from="2025-01-01",
                date_to="2025-01-31",
                page_size=25,
            )
            call_args = MockClient.return_value.get.call_args
            assert call_args[1]["params"]["dateFrom"] == "2025-01-01"
            assert call_args[1]["params"]["dateTo"] == "2025-01-31"
            assert call_args[1]["params"]["pageSize"] == "25"

    def test_returns_empty_on_error(self):
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.side_effect = httpx.ConnectError("fail")

            result = fetch_benzinga_quantified_news("test_key")
            assert result == []

    def test_dict_with_results_key(self):
        data = {"results": [{"headline": "test"}]}
        with patch("newsstack_fmp.ingest_benzinga.httpx.Client") as MockClient:
            MockClient.return_value.__enter__ = MagicMock(return_value=MockClient.return_value)
            MockClient.return_value.__exit__ = MagicMock(return_value=False)
            MockClient.return_value.get.return_value = self._mock_response(data)

            result = fetch_benzinga_quantified_news("test_key")
            assert len(result) == 1
