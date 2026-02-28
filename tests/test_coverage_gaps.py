"""Tests targeting coverage gaps in terminal_poller, terminal_export,
newsstack_fmp/ingest_benzinga, newsstack_fmp/store_sqlite, and
newsstack_fmp/pipeline.

Convention: unittest.TestCase style, unittest.mock for isolation,
tempfile.TemporaryDirectory for file-based tests, imports at test level.
"""

from __future__ import annotations

import json
import os
import queue
import tempfile
import time
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

import httpx

# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════

def _make_newsitem(**overrides: Any) -> Any:
    """Build a NewsItem with sensible defaults."""
    from newsstack_fmp.common_types import NewsItem

    defaults: dict[str, Any] = {
        "provider": "benzinga_rest",
        "item_id": "test_item_1",
        "published_ts": time.time() - 60,
        "updated_ts": time.time() - 30,
        "headline": "AAPL beats Q4 earnings estimates",
        "snippet": "Apple reported strong earnings.",
        "tickers": ["AAPL"],
        "url": "https://example.com/news/1",
        "source": "Benzinga",
        "raw": {},
    }
    defaults.update(overrides)
    return NewsItem(**defaults)


def _make_classified_item(**overrides: Any) -> Any:
    """Build a ClassifiedItem with sensible defaults."""
    from terminal_poller import ClassifiedItem

    defaults: dict[str, Any] = dict(
        item_id="ci1",
        ticker="AAPL",
        tickers_all=["AAPL"],
        headline="AAPL beats estimates",
        snippet="Details here",
        url="https://example.com/1",
        source="Benzinga",
        published_ts=time.time(),
        updated_ts=time.time(),
        provider="benzinga_rest",
        category="earnings",
        impact=0.80,
        clarity=0.70,
        polarity=0.5,
        news_score=0.85,
        cluster_hash="abc123",
        novelty_count=1,
        relevance=0.60,
        entity_count=1,
        sentiment_label="bullish",
        sentiment_score=0.6,
        event_class="SCHEDULED",
        event_label="earnings",
        materiality="MEDIUM",
        recency_bucket="FRESH",
        age_minutes=5.0,
        is_actionable=True,
        source_tier="TIER_2",
        source_rank=2,
        channels=["Earnings"],
        tags=["AI"],
        is_wiim=False,
    )
    defaults.update(overrides)
    return ClassifiedItem(**defaults)


# ═════════════════════════════════════════════════════════════════
# terminal_poller: poll_and_classify_multi
# ═════════════════════════════════════════════════════════════════


class TestPollAndClassifyMulti(unittest.TestCase):
    """Tests for terminal_poller.poll_and_classify_multi (lines 376-441)."""

    def setUp(self) -> None:
        from newsstack_fmp.store_sqlite import SqliteStore

        self._tmpdir = tempfile.TemporaryDirectory()
        self.db = SqliteStore(os.path.join(self._tmpdir.name, "test.db"))

    def tearDown(self) -> None:
        self.db.close()
        self._tmpdir.cleanup()

    def test_benzinga_only_returns_classified(self) -> None:
        """With only benzinga adapter, items are classified."""
        from terminal_poller import poll_and_classify_multi

        item = _make_newsitem(item_id="bz1")
        bz = MagicMock()
        bz.fetch_news.return_value = [item]

        items, cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=None, store=self.db,
            cursor=None, page_size=50,
        )
        self.assertGreaterEqual(len(items), 1)
        self.assertTrue(cursor)

    def test_fmp_only_returns_classified(self) -> None:
        """With only FMP adapter, items are classified."""
        from terminal_poller import poll_and_classify_multi

        item = _make_newsitem(item_id="fmp1", provider="fmp_stock_latest")
        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = [item]
        fmp.fetch_press_latest.return_value = []

        items, _cursor = poll_and_classify_multi(
            benzinga_adapter=None, fmp_adapter=fmp, store=self.db,
            cursor=None, page_size=50,
        )
        self.assertGreaterEqual(len(items), 1)

    def test_both_adapters_combined(self) -> None:
        """Items from both sources are deduplicated and returned."""
        from terminal_poller import poll_and_classify_multi

        bz_item = _make_newsitem(item_id="bz_dual", headline="BZ news about TSLA", tickers=["TSLA"])
        fmp_item = _make_newsitem(item_id="fmp_dual", provider="fmp_stock_latest",
                                  headline="FMP news about GOOG", tickers=["GOOG"])

        bz = MagicMock()
        bz.fetch_news.return_value = [bz_item]
        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = [fmp_item]
        fmp.fetch_press_latest.return_value = []

        items, _cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=fmp, store=self.db,
            cursor=None, page_size=50,
        )
        tickers = {i.ticker for i in items}
        self.assertTrue(tickers.intersection({"TSLA", "GOOG"}))

    def test_benzinga_adapter_failure_surfaces_when_all_fail(self) -> None:
        """When all configured sources fail, RuntimeError is raised."""
        from terminal_poller import poll_and_classify_multi

        bz = MagicMock()
        bz.fetch_news.side_effect = ConnectionError("network down")

        with self.assertRaises(RuntimeError):
            poll_and_classify_multi(
                benzinga_adapter=bz, fmp_adapter=None, store=self.db,
                cursor=None, page_size=50,
            )

    def test_partial_failure_returns_good_items(self) -> None:
        """When one source fails but other succeeds, items are returned."""
        from terminal_poller import poll_and_classify_multi

        bz = MagicMock()
        bz.fetch_news.side_effect = ConnectionError("down")
        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = [
            _make_newsitem(item_id="fmp_partial", provider="fmp_stock_latest",
                           headline="FMP partial test", tickers=["XYZ"]),
        ]
        fmp.fetch_press_latest.return_value = []

        items, _cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=fmp, store=self.db,
            cursor=None, page_size=50,
        )
        self.assertGreaterEqual(len(items), 1)

    def test_empty_poll_both_adapters(self) -> None:
        """Both adapters returning empty → empty list, cursor unchanged."""
        from terminal_poller import poll_and_classify_multi

        bz = MagicMock()
        bz.fetch_news.return_value = []
        fmp = MagicMock()
        fmp.fetch_stock_latest.return_value = []
        fmp.fetch_press_latest.return_value = []

        items, cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=fmp, store=self.db,
            cursor="123", page_size=50,
        )
        self.assertEqual(items, [])
        # Cursor should remain as passed (no advancement)
        self.assertEqual(cursor, "123")

    def test_cursor_advances_to_max_ts(self) -> None:
        """Cursor should advance to the max updated_ts across all items."""
        from terminal_poller import poll_and_classify_multi

        now = time.time()
        item1 = _make_newsitem(item_id="c1", updated_ts=now - 10, published_ts=now - 20)
        item2 = _make_newsitem(item_id="c2", updated_ts=now - 5, published_ts=now - 15,
                               headline="Second item here", tickers=["MSFT"])

        bz = MagicMock()
        bz.fetch_news.return_value = [item1, item2]

        _items, cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=None, store=self.db,
            cursor=None, page_size=50,
        )
        self.assertGreater(float(cursor), 0)

    def test_invalid_cursor_handled(self) -> None:
        """A non-numeric cursor string should not crash."""
        from terminal_poller import poll_and_classify_multi

        bz = MagicMock()
        bz.fetch_news.return_value = []

        items, _cursor = poll_and_classify_multi(
            benzinga_adapter=bz, fmp_adapter=None, store=self.db,
            cursor="not-a-number", page_size=50,
        )
        self.assertEqual(items, [])

    def test_sanitize_exc_strips_apikey(self) -> None:
        """API keys/tokens in exception messages should be sanitised."""
        from terminal_poller import poll_and_classify_multi

        bz = MagicMock()
        bz.fetch_news.side_effect = RuntimeError(
            "HTTP 401 from https://api.benzinga.com?token=SECRETKEY123"
        )

        # With only one source, all-fail raises RuntimeError
        with self.assertRaises(RuntimeError) as ctx:
            poll_and_classify_multi(
                benzinga_adapter=bz, fmp_adapter=None, store=self.db,
                cursor=None, page_size=50,
            )
        self.assertNotIn("SECRETKEY123", str(ctx.exception))
        self.assertIn("token=***", str(ctx.exception))


class TestClassifiedItemDataclass(unittest.TestCase):
    """Tests for ClassifiedItem dataclass creation and to_dict."""

    def test_field_types_after_construction(self) -> None:
        ci = _make_classified_item()
        self.assertIsInstance(ci.ticker, str)
        self.assertIsInstance(ci.tickers_all, list)
        self.assertIsInstance(ci.news_score, float)
        self.assertIsInstance(ci.channels, list)
        self.assertIsInstance(ci.tags, list)

    def test_to_dict_contains_all_keys(self) -> None:
        ci = _make_classified_item()
        d = ci.to_dict()
        expected_keys = {
            "item_id", "ticker", "tickers_all", "headline", "snippet",
            "url", "source", "published_ts", "updated_ts", "provider",
            "category", "impact", "clarity", "polarity", "news_score",
            "cluster_hash", "novelty_count", "relevance", "entity_count",
            "sentiment_label", "sentiment_score", "event_class",
            "event_label", "materiality", "recency_bucket", "age_minutes",
            "is_actionable", "source_tier", "source_rank", "channels", "tags",
            "is_wiim",
        }
        self.assertEqual(set(d.keys()), expected_keys)

    def test_to_dict_rounds_floats(self) -> None:
        ci = _make_classified_item(impact=0.123456789, clarity=0.987654321,
                                    news_score=0.555566667, relevance=0.111122223)
        d = ci.to_dict()
        # impact/clarity rounded to 3 decimals, news_score/relevance to 4
        self.assertEqual(d["impact"], round(0.123456789, 3))
        self.assertEqual(d["clarity"], round(0.987654321, 3))
        self.assertEqual(d["news_score"], round(0.555566667, 4))
        self.assertEqual(d["relevance"], round(0.111122223, 4))

    def test_to_dict_serialisable(self) -> None:
        """to_dict() output must be JSON-serialisable."""
        ci = _make_classified_item()
        d = ci.to_dict()
        serialised = json.dumps(d, default=str)
        self.assertIsInstance(json.loads(serialised), dict)


# ═════════════════════════════════════════════════════════════════
# terminal_poller: fetch_economic_calendar, fetch_sector_performance
# ═════════════════════════════════════════════════════════════════


class TestFetchEconomicCalendar(unittest.TestCase):
    """Tests for terminal_poller.fetch_economic_calendar (lines 468-494)."""

    @patch("terminal_poller._get_fmp_client")
    def test_returns_list_on_success(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_economic_calendar

        mock_resp = MagicMock()
        mock_resp.json.return_value = [
            {"date": "2026-02-26", "event": "GDP", "country": "US", "actual": "3.2"},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        result = fetch_economic_calendar("fake_key", "2026-02-26", "2026-02-27")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["event"], "GDP")

    @patch("terminal_poller._get_fmp_client")
    def test_returns_empty_on_non_list(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_economic_calendar

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"error": "bad request"}
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        result = fetch_economic_calendar("fake_key", "2026-02-26", "2026-02-27")
        self.assertEqual(result, [])

    @patch("terminal_poller._get_fmp_client")
    def test_returns_empty_on_network_error(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_economic_calendar

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("timeout")
        mock_get_client.return_value = mock_client

        result = fetch_economic_calendar("fake_key", "2026-02-26", "2026-02-27")
        self.assertEqual(result, [])

    @patch("terminal_poller._get_fmp_client")
    def test_sanitizes_api_key_in_error(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_economic_calendar

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError(
            "https://api.com?apikey=MY_SECRET_KEY failed"
        )
        mock_get_client.return_value = mock_client

        # Should not raise; returns empty list
        with self.assertLogs("newsstack_fmp._bz_http", level="WARNING") as cm:
            result = fetch_economic_calendar("MY_SECRET_KEY", "2026-02-26", "2026-02-27")
        self.assertEqual(result, [])
        # Ensure API key is sanitised in log
        combined = " ".join(cm.output)
        self.assertNotIn("MY_SECRET_KEY", combined)


class TestFetchSectorPerformance(unittest.TestCase):
    """Tests for terminal_poller.fetch_sector_performance (lines 497-508)."""

    @patch("terminal_poller._get_fmp_client")
    def test_returns_list_on_success(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_sector_performance

        mock_resp = MagicMock()
        # Stable API returns per (sector, exchange) with averageChange
        mock_resp.json.return_value = [
            {"date": "2026-02-26", "sector": "Technology", "exchange": "NASDAQ", "averageChange": 1.5},
            {"date": "2026-02-26", "sector": "Technology", "exchange": "NYSE", "averageChange": 0.5},
        ]
        mock_resp.raise_for_status = MagicMock()
        mock_client = MagicMock()
        mock_client.get.return_value = mock_resp
        mock_get_client.return_value = mock_client

        result = fetch_sector_performance("fake_key")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sector"], "Technology")
        # Mean of 1.5 and 0.5
        self.assertAlmostEqual(result[0]["changesPercentage"], 1.0, places=4)

    @patch("terminal_poller._get_fmp_client")
    def test_returns_empty_on_failure(self, mock_get_client: MagicMock) -> None:
        from terminal_poller import fetch_sector_performance

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ReadTimeout("timeout")
        mock_get_client.return_value = mock_client

        result = fetch_sector_performance("fake_key")
        self.assertEqual(result, [])


# ═════════════════════════════════════════════════════════════════
# terminal_export: CSV / webhook / JSONL edge cases
# ═════════════════════════════════════════════════════════════════


class TestLoadJsonlFeed(unittest.TestCase):
    """Tests for terminal_export.load_jsonl_feed (lines 80-96)."""

    def test_file_not_found_returns_empty(self) -> None:
        from terminal_export import load_jsonl_feed

        result = load_jsonl_feed("/nonexistent/path.jsonl")
        self.assertEqual(result, [])

    def test_reads_and_reverses(self) -> None:
        from terminal_export import load_jsonl_feed

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "feed.jsonl")
            with open(path, "w") as f:
                for i in range(5):
                    f.write(json.dumps({"idx": i, "published_ts": 1000 + i}) + "\n")

            result = load_jsonl_feed(path)
            self.assertEqual(len(result), 5)
            # Newest first (sorted by published_ts descending)
            self.assertEqual(result[0]["idx"], 4)
            self.assertEqual(result[-1]["idx"], 0)

    def test_skips_blank_and_malformed_lines(self) -> None:
        from terminal_export import load_jsonl_feed

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "mixed.jsonl")
            with open(path, "w") as f:
                f.write('{"a": 1}\n')
                f.write("\n")
                f.write("NOT JSON\n")
                f.write('{"b": 2}\n')

            result = load_jsonl_feed(path)
            self.assertEqual(len(result), 2)

    def test_max_items_limit(self) -> None:
        from terminal_export import load_jsonl_feed

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "big.jsonl")
            with open(path, "w") as f:
                for i in range(100):
                    f.write(json.dumps({"i": i, "published_ts": 1000 + i}) + "\n")

            result = load_jsonl_feed(path, max_items=10)
            self.assertEqual(len(result), 10)
            # Newest first (sorted by published_ts descending)
            self.assertEqual(result[0]["i"], 99)


class TestFireWebhookExtended(unittest.TestCase):
    """Extended tests for terminal_export.fire_webhook (lines 244-349)."""

    def test_reuse_external_client(self) -> None:
        """When _client is provided, it is NOT closed by fire_webhook."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"accepted": True}
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(news_score=0.90)
        result = fire_webhook(ci, url="https://hook.example.com", _client=mock_client)

        self.assertEqual(result, {"accepted": True})
        mock_client.close.assert_not_called()

    def test_signature_header_present_when_secret_set(self) -> None:
        """X-Signature-256 header should be present when secret is set."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(news_score=0.90)
        fire_webhook(ci, url="https://hook.example.com", secret="mysecret", _client=mock_client)

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers", {})
        self.assertIn("X-Signature-256", headers)
        self.assertTrue(headers["X-Signature-256"].startswith("sha256="))

    def test_no_signature_header_when_no_secret(self) -> None:
        """X-Signature-256 header should NOT be present when secret is empty."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(news_score=0.90)
        fire_webhook(ci, url="https://hook.example.com", secret="", _client=mock_client)

        call_kwargs = mock_client.post.call_args
        headers = call_kwargs[1].get("headers") or call_kwargs.kwargs.get("headers", {})
        self.assertNotIn("X-Signature-256", headers)

    def test_bearish_high_score_action_sell(self) -> None:
        """Bearish sentiment + high score → action=sell."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(
            news_score=0.90, sentiment_label="bearish", sentiment_score=-0.7,
        )
        fire_webhook(ci, url="https://hook.example.com", _client=mock_client)

        body = json.loads(mock_client.post.call_args[1]["content"])
        self.assertEqual(body["action"], "sell")

    def test_neutral_action_watch(self) -> None:
        """Neutral sentiment → action=watch regardless of score."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True}
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(
            news_score=0.95, sentiment_label="neutral", sentiment_score=0.0,
        )
        fire_webhook(ci, url="https://hook.example.com", _client=mock_client)

        body = json.loads(mock_client.post.call_args[1]["content"])
        self.assertEqual(body["action"], "watch")

    def test_http_error_returns_none(self) -> None:
        """HTTP errors should return None, not raise."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.ConnectError("down")

        ci = _make_classified_item(news_score=0.90)
        result = fire_webhook(ci, url="https://hook.example.com", _client=mock_client)
        self.assertIsNone(result)

    def test_response_json_parse_failure_fallback(self) -> None:
        """When response.json() fails, returns {status, text}."""
        from terminal_export import fire_webhook

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = ValueError("not json")
        mock_resp.text = "OK"
        mock_client.post.return_value = mock_resp

        ci = _make_classified_item(news_score=0.90)
        result = fire_webhook(ci, url="https://hook.example.com", _client=mock_client)
        self.assertIsNotNone(result)
        assert result is not None  # for mypy
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["text"], "OK")


class TestSignPayload(unittest.TestCase):
    """Tests for terminal_export._sign_payload."""

    def test_hmac_deterministic(self) -> None:
        from terminal_export import _sign_payload

        sig1 = _sign_payload(b'{"a":1}', "secret")
        sig2 = _sign_payload(b'{"a":1}', "secret")
        self.assertEqual(sig1, sig2)
        self.assertEqual(len(sig1), 64)  # SHA-256 hex

    def test_different_secrets_different_sigs(self) -> None:
        from terminal_export import _sign_payload

        sig1 = _sign_payload(b"data", "secret1")
        sig2 = _sign_payload(b"data", "secret2")
        self.assertNotEqual(sig1, sig2)


class TestBuildVdSnapshotEdgeCases(unittest.TestCase):
    """Edge-case tests for build_vd_snapshot (lines 150-210)."""

    def test_empty_feed(self) -> None:
        from terminal_export import build_vd_snapshot

        rows = build_vd_snapshot([])
        self.assertEqual(rows, [])

    def test_provider_field_propagated(self) -> None:
        from terminal_export import build_vd_snapshot

        feed = [{"ticker": "A", "news_score": 0.5, "provider": "fmp_stock_latest"}]
        rows = build_vd_snapshot(feed, max_age_s=0)
        self.assertEqual(rows[0]["provider"], "fmp_stock_latest")

    def test_missing_fields_use_defaults(self) -> None:
        from terminal_export import build_vd_snapshot

        feed = [{"ticker": "X", "news_score": 0.3}]
        rows = build_vd_snapshot(feed, max_age_s=0)
        self.assertEqual(rows[0]["category"], "")
        self.assertEqual(rows[0]["event"], "")
        self.assertEqual(rows[0]["polarity"], 0)
        self.assertEqual(rows[0]["age_min"], 0.0)


# ═════════════════════════════════════════════════════════════════
# newsstack_fmp/ingest_benzinga: Retry logic
# ═════════════════════════════════════════════════════════════════


class TestBenzingaRestRetry(unittest.TestCase):
    """Tests for BenzingaRestAdapter.fetch_news retry logic (lines 88-109)."""

    def _make_adapter(self) -> Any:
        from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter

        adapter = BenzingaRestAdapter.__new__(BenzingaRestAdapter)
        adapter.api_key = "test_key"
        adapter.client = MagicMock(spec=httpx.Client)
        return adapter

    def test_success_on_first_attempt(self) -> None:
        adapter = self._make_adapter()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [
            {"id": 1, "title": "Test", "created": "Thu, 20 Feb 2026 10:00:00 -0500",
             "updated": "Thu, 20 Feb 2026 10:00:00 -0500", "url": "https://example.com",
             "stocks": [{"name": "AAPL"}], "teaser": "snip"},
        ]
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.raise_for_status = MagicMock()
        adapter.client.get.return_value = mock_resp

        items = adapter.fetch_news()
        self.assertEqual(len(items), 1)
        adapter.client.get.assert_called_once()

    @patch("newsstack_fmp.ingest_benzinga.time.sleep")
    def test_retries_on_429(self, mock_sleep: MagicMock) -> None:
        """429 should trigger a retry, then succeed."""
        adapter = self._make_adapter()

        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.headers = {"content-type": "application/json"}

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = []
        resp_ok.headers = {"content-type": "application/json"}
        resp_ok.raise_for_status = MagicMock()

        adapter.client.get.side_effect = [resp_429, resp_ok]
        items = adapter.fetch_news()
        self.assertEqual(items, [])
        self.assertEqual(adapter.client.get.call_count, 2)
        mock_sleep.assert_called()

    @patch("newsstack_fmp.ingest_benzinga.time.sleep")
    def test_retries_on_503(self, mock_sleep: MagicMock) -> None:
        """503 should trigger retry."""
        adapter = self._make_adapter()

        resp_503 = MagicMock()
        resp_503.status_code = 503
        resp_503.headers = {"content-type": "application/json"}

        resp_ok = MagicMock()
        resp_ok.status_code = 200
        resp_ok.json.return_value = []
        resp_ok.headers = {"content-type": "application/json"}
        resp_ok.raise_for_status = MagicMock()

        adapter.client.get.side_effect = [resp_503, resp_ok]
        items = adapter.fetch_news()
        self.assertEqual(items, [])
        self.assertEqual(adapter.client.get.call_count, 2)

    @patch("newsstack_fmp.ingest_benzinga.time.sleep")
    def test_retries_on_connect_error(self, mock_sleep: MagicMock) -> None:
        """ConnectError should retry up to MAX_ATTEMPTS, then raise."""
        adapter = self._make_adapter()
        adapter.client.get.side_effect = httpx.ConnectError("refused")

        with self.assertRaises(httpx.ConnectError):
            adapter.fetch_news()
        self.assertEqual(adapter.client.get.call_count, 3)

    @patch("newsstack_fmp.ingest_benzinga.time.sleep")
    def test_retries_on_read_timeout(self, mock_sleep: MagicMock) -> None:
        """ReadTimeout should retry."""
        adapter = self._make_adapter()
        adapter.client.get.side_effect = httpx.ReadTimeout("timed out")

        with self.assertRaises(httpx.ReadTimeout):
            adapter.fetch_news()
        self.assertEqual(adapter.client.get.call_count, 3)

    def test_non_retryable_status_raises_immediately(self) -> None:
        """A 401 should raise HTTPStatusError without retry."""
        adapter = self._make_adapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.url = "https://api.benzinga.com/api/v2/news?token=***"
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="401 Unauthorized",
            request=MagicMock(),
            response=mock_resp,
        )
        adapter.client.get.return_value = mock_resp

        with self.assertRaises(httpx.HTTPStatusError):
            adapter.fetch_news()
        # Only one attempt (no retry)
        self.assertEqual(adapter.client.get.call_count, 1)

    def test_non_json_response_raises_valueerror(self) -> None:
        """Non-JSON body should raise ValueError."""
        adapter = self._make_adapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.side_effect = Exception("decode error")
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.url = "https://api.benzinga.com/api/v2/news"
        mock_resp.raise_for_status = MagicMock()
        adapter.client.get.return_value = mock_resp

        with self.assertRaises(ValueError):
            adapter.fetch_news()

    @patch("newsstack_fmp.ingest_benzinga.time.sleep")
    def test_all_retries_exhausted_on_retryable(self, mock_sleep: MagicMock) -> None:
        """When all 3 attempts fail with 500, no response is available → RuntimeError."""
        adapter = self._make_adapter()

        resp_500 = MagicMock()
        resp_500.status_code = 500
        resp_500.headers = {"content-type": "application/json"}
        resp_500.url = "https://api.benzinga.com/api/v2/news"
        resp_500.raise_for_status.side_effect = httpx.HTTPStatusError(
            message="500", request=MagicMock(), response=resp_500,
        )
        adapter.client.get.return_value = resp_500

        with self.assertRaises(httpx.HTTPStatusError):
            adapter.fetch_news()
        self.assertEqual(adapter.client.get.call_count, 3)

    def test_response_dict_with_articles_key(self) -> None:
        """Response dict with 'articles' key should extract items."""
        adapter = self._make_adapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "articles": [
                {"id": 1, "title": "Article", "created": "Thu, 20 Feb 2026 10:00:00 -0500",
                 "updated": "Thu, 20 Feb 2026 10:00:00 -0500", "url": "https://example.com",
                 "stocks": [{"name": "GOOG"}], "teaser": "snippet"},
            ],
        }
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.raise_for_status = MagicMock()
        adapter.client.get.return_value = mock_resp

        items = adapter.fetch_news()
        self.assertEqual(len(items), 1)

    def test_response_dict_unknown_keys_logs_warning(self) -> None:
        """Response dict with no recognized keys should log a warning."""
        adapter = self._make_adapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"unexpected": "payload"}
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.raise_for_status = MagicMock()
        adapter.client.get.return_value = mock_resp

        with self.assertLogs("newsstack_fmp.ingest_benzinga", level="WARNING"):
            items = adapter.fetch_news()
        self.assertEqual(items, [])

    def test_response_non_list_non_dict_returns_empty(self) -> None:
        """Unexpected top-level type (e.g. string) → empty list."""
        adapter = self._make_adapter()

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = "just a string"
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.raise_for_status = MagicMock()
        adapter.client.get.return_value = mock_resp

        with self.assertLogs("newsstack_fmp.ingest_benzinga", level="WARNING"):
            items = adapter.fetch_news()
        self.assertEqual(items, [])


# ═════════════════════════════════════════════════════════════════
# newsstack_fmp/ingest_benzinga: WebSocket adapter
# ═════════════════════════════════════════════════════════════════


class TestBenzingaWsAdapter(unittest.TestCase):
    """Tests for BenzingaWsAdapter (lines 190-302)."""

    def test_init_sets_fields(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        ws = BenzingaWsAdapter("key123", "wss://custom.url/stream")
        self.assertEqual(ws.api_key, "key123")
        self.assertEqual(ws.ws_url, "wss://custom.url/stream")
        self.assertIsInstance(ws.queue, queue.Queue)
        self.assertFalse(ws._stop_event.is_set())

    def test_drain_empty_queue(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        ws = BenzingaWsAdapter("key", "wss://ws.example.com")
        items = ws.drain()
        self.assertEqual(items, [])

    def test_drain_returns_enqueued_items(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        ws = BenzingaWsAdapter("key", "wss://ws.example.com")
        item1 = _make_newsitem(item_id="ws1", provider="benzinga_ws")
        item2 = _make_newsitem(item_id="ws2", provider="benzinga_ws")
        ws.queue.put(item1)
        ws.queue.put(item2)

        drained = ws.drain()
        self.assertEqual(len(drained), 2)
        # Queue should be empty now
        self.assertEqual(ws.drain(), [])

    def test_stop_sets_event(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        ws = BenzingaWsAdapter("key", "wss://ws.example.com")
        ws.stop()
        self.assertTrue(ws._stop_event.is_set())

    def test_start_idempotent_while_alive(self) -> None:
        """Calling start() twice while thread is alive should not spawn a second thread."""
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        ws = BenzingaWsAdapter("key", "wss://ws.example.com")
        # Replace _run_loop with a function that blocks until stop is signalled
        def _blocking_loop() -> None:
            ws._stop_event.wait()

        with patch.object(ws, "_run_loop", side_effect=_blocking_loop):
            ws.start()
            first_thread = ws._thread
            self.assertIsNotNone(first_thread)
            self.assertTrue(first_thread.is_alive())  # type: ignore[union-attr]
            ws.start()  # second call — should be a no-op
            self.assertIs(ws._thread, first_thread)
            ws.stop()

    def test_extract_payloads_data_list(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads(
            {"data": [{"id": 1}, {"id": 2}]}
        )
        self.assertEqual(len(result), 2)

    def test_extract_payloads_data_dict(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads({"data": {"id": 1}})
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], 1)

    def test_extract_payloads_data_non_dict(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads({"data": "string_value"})
        self.assertEqual(result, [])

    def test_extract_payloads_list(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads([{"a": 1}, "not_dict", {"b": 2}])
        self.assertEqual(len(result), 2)

    def test_extract_payloads_bare_dict(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads({"title": "News"})
        self.assertEqual(len(result), 1)

    def test_extract_payloads_non_container(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads("plain string")
        self.assertEqual(result, [])

    def test_extract_payloads_none(self) -> None:
        from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter

        result = BenzingaWsAdapter._extract_payloads(None)
        self.assertEqual(result, [])


# ═════════════════════════════════════════════════════════════════
# newsstack_fmp/store_sqlite: prune_seen, prune_clusters
# ═════════════════════════════════════════════════════════════════


class TestSqliteStorePrune(unittest.TestCase):
    """Tests for SqliteStore.prune_seen and prune_clusters (lines 107-128)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        from newsstack_fmp.store_sqlite import SqliteStore

        self.store = SqliteStore(os.path.join(self._tmpdir.name, "prune.db"))

    def tearDown(self) -> None:
        self.store.close()
        self._tmpdir.cleanup()

    def test_prune_seen_removes_old_entries(self) -> None:
        now = time.time()
        # Insert old entries
        self.store.mark_seen("prov", "old1", now - 7200)
        self.store.mark_seen("prov", "old2", now - 3700)
        # Insert fresh entry
        self.store.mark_seen("prov", "fresh", now - 100)

        self.store.prune_seen(keep_seconds=3600)

        # old1 and old2 should be pruned
        # fresh should still be present
        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM seen WHERE item_id='fresh'"
        ).fetchone()
        self.assertEqual(row[0], 1)

        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM seen WHERE item_id='old1'"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_prune_seen_on_empty_db(self) -> None:
        """Pruning an empty table should not fail."""
        self.store.prune_seen(3600)
        count = self.store.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        self.assertEqual(count, 0)

    def test_prune_clusters_removes_old_entries(self) -> None:
        now = time.time()
        self.store.cluster_touch("hash_old", now - 7200)
        self.store.cluster_touch("hash_fresh", now - 100)

        self.store.prune_clusters(keep_seconds=3600)

        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE hash='hash_fresh'"
        ).fetchone()
        self.assertEqual(row[0], 1)

        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE hash='hash_old'"
        ).fetchone()
        self.assertEqual(row[0], 0)

    def test_prune_clusters_on_empty_db(self) -> None:
        """Pruning an empty clusters table should not fail."""
        self.store.prune_clusters(3600)
        count = self.store.conn.execute("SELECT COUNT(*) FROM clusters").fetchone()[0]
        self.assertEqual(count, 0)

    def test_prune_seen_keeps_recent(self) -> None:
        """Items newer than keep_seconds should survive prune."""
        now = time.time()
        for i in range(10):
            self.store.mark_seen("p", f"item_{i}", now - i * 10)

        self.store.prune_seen(keep_seconds=50)  # keep last 50s
        count = self.store.conn.execute("SELECT COUNT(*) FROM seen").fetchone()[0]
        self.assertEqual(count, 5)  # items 0-4 (0s, 10s, 20s, 30s, 40s ago)

    def test_prune_clusters_uses_last_ts(self) -> None:
        """Clusters should be pruned by last_ts, not first_ts."""
        now = time.time()
        # Cluster first seen a long time ago but last touched recently
        self.store.cluster_touch("hash_multi", now - 5000)
        self.store.cluster_touch("hash_multi", now - 100)

        self.store.prune_clusters(keep_seconds=3600)

        # Should still exist because last_ts is recent
        row = self.store.conn.execute(
            "SELECT COUNT(*) FROM clusters WHERE hash='hash_multi'"
        ).fetchone()
        self.assertEqual(row[0], 1)


class TestSqliteStoreClusterTouch(unittest.TestCase):
    """Additional tests for cluster_touch edge cases."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        from newsstack_fmp.store_sqlite import SqliteStore

        self.store = SqliteStore(os.path.join(self._tmpdir.name, "cluster.db"))

    def tearDown(self) -> None:
        self.store.close()
        self._tmpdir.cleanup()

    def test_first_touch_returns_count_one(self) -> None:
        count, first_ts = self.store.cluster_touch("new_hash", 1000.0)
        self.assertEqual(count, 1)
        self.assertEqual(first_ts, 1000.0)

    def test_second_touch_increments_count(self) -> None:
        self.store.cluster_touch("h", 1000.0)
        count, first_ts = self.store.cluster_touch("h", 2000.0)
        self.assertEqual(count, 2)
        self.assertEqual(first_ts, 1000.0)  # first_ts should not change


# ═════════════════════════════════════════════════════════════════
# newsstack_fmp/pipeline: singleton cleanup, _effective_ts
# ═════════════════════════════════════════════════════════════════


class TestCleanupSingletons(unittest.TestCase):
    """Tests for pipeline._cleanup_singletons (lines 466-487)."""

    def test_cleanup_noop_when_all_none(self) -> None:
        """Cleanup should not fail when all singletons are None."""
        from newsstack_fmp import pipeline

        # Save original state
        orig = (
            pipeline._store, pipeline._fmp_adapter,
            pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
            pipeline._enricher,
        )
        try:
            pipeline._store = None
            pipeline._fmp_adapter = None
            pipeline._bz_rest_adapter = None
            pipeline._bz_ws_adapter = None
            pipeline._enricher = None
            # Should not raise
            pipeline._cleanup_singletons()
        finally:
            (
                pipeline._store, pipeline._fmp_adapter,
                pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
                pipeline._enricher,
            ) = orig

    def test_cleanup_calls_close_on_adapters(self) -> None:
        """Cleanup should call close() on FMP adapter, BZ REST, enricher."""
        from newsstack_fmp import pipeline

        orig = (
            pipeline._store, pipeline._fmp_adapter,
            pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
            pipeline._enricher,
        )
        try:
            mock_fmp = MagicMock()
            mock_bz = MagicMock()
            mock_enricher = MagicMock()
            mock_store = MagicMock()

            pipeline._fmp_adapter = mock_fmp
            pipeline._bz_rest_adapter = mock_bz
            pipeline._enricher = mock_enricher
            pipeline._store = mock_store
            pipeline._bz_ws_adapter = None

            pipeline._cleanup_singletons()

            mock_fmp.close.assert_called_once()
            mock_bz.close.assert_called_once()
            mock_enricher.close.assert_called_once()
            mock_store.close.assert_called_once()

            # All should be reset to None
            self.assertIsNone(pipeline._store)
            self.assertIsNone(pipeline._fmp_adapter)
            self.assertIsNone(pipeline._bz_rest_adapter)
            self.assertIsNone(pipeline._enricher)
        finally:
            (
                pipeline._store, pipeline._fmp_adapter,
                pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
                pipeline._enricher,
            ) = orig

    def test_cleanup_calls_stop_on_ws_adapter(self) -> None:
        """Cleanup should call stop() on BenzingaWsAdapter."""
        from newsstack_fmp import pipeline

        orig = (
            pipeline._store, pipeline._fmp_adapter,
            pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
            pipeline._enricher,
        )
        try:
            mock_ws = MagicMock()
            pipeline._bz_ws_adapter = mock_ws
            pipeline._fmp_adapter = None
            pipeline._bz_rest_adapter = None
            pipeline._enricher = None
            pipeline._store = None

            pipeline._cleanup_singletons()

            mock_ws.stop.assert_called_once()
            self.assertIsNone(pipeline._bz_ws_adapter)
        finally:
            (
                pipeline._store, pipeline._fmp_adapter,
                pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
                pipeline._enricher,
            ) = orig

    def test_cleanup_tolerates_close_exceptions(self) -> None:
        """Cleanup should swallow exceptions from close()/stop()."""
        from newsstack_fmp import pipeline

        orig = (
            pipeline._store, pipeline._fmp_adapter,
            pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
            pipeline._enricher,
        )
        try:
            mock_fmp = MagicMock()
            mock_fmp.close.side_effect = RuntimeError("boom")
            mock_store = MagicMock()
            mock_store.close.side_effect = RuntimeError("crash")

            pipeline._fmp_adapter = mock_fmp
            pipeline._store = mock_store
            pipeline._bz_rest_adapter = None
            pipeline._bz_ws_adapter = None
            pipeline._enricher = None

            # Should NOT raise
            pipeline._cleanup_singletons()
            self.assertIsNone(pipeline._fmp_adapter)
            self.assertIsNone(pipeline._store)
        finally:
            (
                pipeline._store, pipeline._fmp_adapter,
                pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
                pipeline._enricher,
            ) = orig

    def test_cleanup_clears_best_by_ticker(self) -> None:
        """Cleanup should clear _best_by_ticker dict."""
        from newsstack_fmp import pipeline

        orig_bbt = pipeline._best_by_ticker.copy()
        orig = (
            pipeline._store, pipeline._fmp_adapter,
            pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
            pipeline._enricher,
        )
        try:
            pipeline._best_by_ticker["TEST"] = {"ticker": "TEST", "news_score": 0.5}
            pipeline._store = None
            pipeline._fmp_adapter = None
            pipeline._bz_rest_adapter = None
            pipeline._bz_ws_adapter = None
            pipeline._enricher = None

            pipeline._cleanup_singletons()
            self.assertEqual(len(pipeline._best_by_ticker), 0)
        finally:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(orig_bbt)
            (
                pipeline._store, pipeline._fmp_adapter,
                pipeline._bz_rest_adapter, pipeline._bz_ws_adapter,
                pipeline._enricher,
            ) = orig


class TestEffectiveTs(unittest.TestCase):
    """Tests for pipeline._effective_ts."""

    def test_prefers_updated_ts(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 1000.0, "published_ts": 900.0, "_seen_ts": 800.0}
        self.assertEqual(_effective_ts(cand), 1000.0)

    def test_falls_back_to_published_ts(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 900.0, "_seen_ts": 800.0}
        self.assertEqual(_effective_ts(cand), 900.0)

    def test_falls_back_to_seen_ts(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 0.0, "_seen_ts": 800.0}
        self.assertEqual(_effective_ts(cand), 800.0)

    def test_all_zero_returns_zero(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": 0.0, "published_ts": 0.0, "_seen_ts": 0.0}
        self.assertEqual(_effective_ts(cand), 0.0)

    def test_missing_keys_returns_zero(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        self.assertEqual(_effective_ts({}), 0.0)

    def test_none_updated_ts_uses_published(self) -> None:
        from newsstack_fmp.pipeline import _effective_ts

        cand = {"updated_ts": None, "published_ts": 500.0}
        self.assertEqual(_effective_ts(cand), 500.0)


class TestSingletonGetters(unittest.TestCase):
    """Tests for pipeline singleton getters (lines 44-78)."""

    def test_get_store_creates_on_first_call(self) -> None:
        from newsstack_fmp import pipeline
        from newsstack_fmp.config import Config

        orig_store = pipeline._store
        try:
            pipeline._store = None
            with tempfile.TemporaryDirectory() as tmpdir, patch.dict(os.environ, {
                    "NEWSSTACK_SQLITE_PATH": os.path.join(tmpdir, "test.db"),
                }):
                    cfg_mock = MagicMock(spec=Config)
                    cfg_mock.sqlite_path = os.path.join(tmpdir, "test.db")

                    store = pipeline._get_store(cfg_mock)
                    self.assertIsNotNone(store)
                    # Second call returns same instance
                    store2 = pipeline._get_store(cfg_mock)
                    self.assertIs(store, store2)
                    store.close()
        finally:
            pipeline._store = orig_store

    def test_get_enricher_singleton(self) -> None:
        from newsstack_fmp import pipeline

        orig = pipeline._enricher
        try:
            pipeline._enricher = None
            e1 = pipeline._get_enricher()
            e2 = pipeline._get_enricher()
            self.assertIs(e1, e2)
        finally:
            pipeline._enricher = orig

    def test_get_fmp_adapter_singleton(self) -> None:
        from newsstack_fmp import pipeline

        orig = pipeline._fmp_adapter
        try:
            pipeline._fmp_adapter = None
            cfg_mock = MagicMock()
            cfg_mock.fmp_api_key = "test_key"

            adapter = pipeline._get_fmp_adapter(cfg_mock)
            self.assertIsNotNone(adapter)
            adapter2 = pipeline._get_fmp_adapter(cfg_mock)
            self.assertIs(adapter, adapter2)
        finally:
            pipeline._fmp_adapter = orig

    def test_get_bz_rest_adapter_singleton(self) -> None:
        from newsstack_fmp import pipeline

        orig = pipeline._bz_rest_adapter
        try:
            pipeline._bz_rest_adapter = None
            cfg_mock = MagicMock()
            cfg_mock.benzinga_api_key = "bz_test_key"

            adapter = pipeline._get_bz_rest_adapter(cfg_mock)
            self.assertIsNotNone(adapter)
            adapter2 = pipeline._get_bz_rest_adapter(cfg_mock)
            self.assertIs(adapter, adapter2)
            adapter.close()
        finally:
            pipeline._bz_rest_adapter = orig


class TestPruneBestByTicker(unittest.TestCase):
    """Tests for pipeline._prune_best_by_ticker."""

    def test_prunes_stale_entries(self) -> None:
        from newsstack_fmp import pipeline

        orig = pipeline._best_by_ticker.copy()
        try:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker["OLD"] = {
                "ticker": "OLD", "updated_ts": time.time() - 7200,
                "news_score": 0.5,
            }
            pipeline._best_by_ticker["NEW"] = {
                "ticker": "NEW", "updated_ts": time.time(),
                "news_score": 0.8,
            }

            pipeline._prune_best_by_ticker(3600)

            self.assertNotIn("OLD", pipeline._best_by_ticker)
            self.assertIn("NEW", pipeline._best_by_ticker)
        finally:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(orig)

    def test_keeps_entries_with_seen_ts_fallback(self) -> None:
        """Entries with 0 updated_ts but fresh _seen_ts should survive."""
        from newsstack_fmp import pipeline

        orig = pipeline._best_by_ticker.copy()
        try:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker["ZERO_TS"] = {
                "ticker": "ZERO_TS", "updated_ts": 0.0,
                "published_ts": 0.0, "_seen_ts": time.time(),
                "news_score": 0.5,
            }

            pipeline._prune_best_by_ticker(3600)
            self.assertIn("ZERO_TS", pipeline._best_by_ticker)
        finally:
            pipeline._best_by_ticker.clear()
            pipeline._best_by_ticker.update(orig)


# ═════════════════════════════════════════════════════════════════
# terminal_export: rotate_jsonl edge cases
# ═════════════════════════════════════════════════════════════════


class TestRotateJsonlEdgeCases(unittest.TestCase):
    """Edge-case tests for rotate_jsonl."""

    def test_rotate_nonexistent_file_noop(self) -> None:
        from terminal_export import rotate_jsonl

        # Should not raise
        rotate_jsonl("/nonexistent/path/feed.jsonl", max_lines=10)

    def test_rotate_preserves_newest_lines(self) -> None:
        from terminal_export import rotate_jsonl

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "feed.jsonl")
            now = time.time()
            with open(path, "w") as f:
                for i in range(100):
                    f.write(json.dumps({"i": i, "published_ts": now}) + "\n")

            rotate_jsonl(path, max_lines=20)

            with open(path) as f:
                lines = f.readlines()
            self.assertEqual(len(lines), 20)
            first = json.loads(lines[0])
            last = json.loads(lines[-1])
            self.assertEqual(first["i"], 80)
            self.assertEqual(last["i"], 99)


# ═════════════════════════════════════════════════════════════════
# newsstack_fmp/ingest_benzinga: _sanitize_url
# ═════════════════════════════════════════════════════════════════


class TestSanitizeUrl(unittest.TestCase):
    """Tests for _sanitize_url helper."""

    def test_strips_token(self) -> None:
        from newsstack_fmp.ingest_benzinga import _sanitize_url

        result = _sanitize_url("https://api.benzinga.com/news?token=ABCDEF&page=1")
        self.assertNotIn("ABCDEF", result)
        self.assertIn("token=***", result)
        self.assertIn("page=1", result)

    def test_strips_apikey(self) -> None:
        from newsstack_fmp.ingest_benzinga import _sanitize_url

        result = _sanitize_url("https://api.fmp.com?apikey=SECRET123")
        self.assertNotIn("SECRET123", result)
        self.assertIn("apikey=***", result)

    def test_no_key_unchanged(self) -> None:
        from newsstack_fmp.ingest_benzinga import _sanitize_url

        url = "https://example.com/api/news?page=1"
        self.assertEqual(_sanitize_url(url), url)


if __name__ == "__main__":
    unittest.main()
