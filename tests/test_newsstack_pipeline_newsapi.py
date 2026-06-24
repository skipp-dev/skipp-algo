from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.pipeline import _next_newsapi_feed_uri
from newsstack_fmp.shared_fetch import CachedNewsBatch


def _newsapi_item(fetch_mode: str, uri: str) -> NewsItem:
    return NewsItem(
        provider="newsapi_ai",
        item_id=uri,
        published_ts=1_750_000_000.0,
        updated_ts=1_750_000_000.0,
        headline="AAPL headline",
        snippet="snippet",
        tickers=["AAPL"],
        url=None,
        source="Reuters",
        raw={
            "uri": uri,
            "newsapi_fetch_mode": fetch_mode,
        },
    )


def test_next_newsapi_feed_uri_prefers_feed_cursor() -> None:
    next_uri = _next_newsapi_feed_uri(
        "uri-feed-1",
        [_newsapi_item("feed_articles", "uri-feed-2")],
        cursor_advanced=True,
    )

    assert next_uri == "uri-feed-2"


def test_next_newsapi_feed_uri_clears_stale_uri_after_search_advance() -> None:
    next_uri = _next_newsapi_feed_uri(
        "uri-feed-1",
        [_newsapi_item("search_articles", "uri-search-1")],
        cursor_advanced=True,
    )

    assert next_uri == ""


def test_next_newsapi_feed_uri_keeps_existing_state_without_advance() -> None:
    next_uri = _next_newsapi_feed_uri("uri-feed-1", [], cursor_advanced=False)

    assert next_uri == "uri-feed-1"


def test_poll_once_exports_newsapi_no_recent_matches_status() -> None:
    from newsstack_fmp import pipeline
    from newsstack_fmp.config import Config
    from newsstack_fmp.store_sqlite import SqliteStore

    store = SqliteStore(":memory:")
    store.set_kv("newsapi_ai.last_seen_epoch", "1750000050.0")
    store.set_kv("newsapi_ai.last_seen_news_uri", "uri-feed-1")
    raw_item = _newsapi_item("search_events", "event-1")

    old_best = pipeline._best_by_ticker.copy()
    pipeline._best_by_ticker.clear()
    try:
        with (
            patch.object(pipeline, "_get_store", return_value=store),
            patch.object(pipeline, "_get_enricher", return_value=MagicMock()),
            patch.object(
                pipeline,
                "_fetch_newsapi_provider_items",
                return_value=CachedNewsBatch(
                    provider="newsapi_ai",
                    scope={"symbols": ["AAPL"]},
                    items=[],
                    raw_items=[raw_item],
                    raw_count=1,
                    cursor=1_750_000_050.0,
                    fetched_at=1_750_000_100.0,
                    from_cache=False,
                ),
            ),
            patch.object(pipeline, "export_open_prep") as mock_export,
            patch.dict(
                os.environ,
                {
                    "ENABLE_FMP": "0",
                    "ENABLE_FMP_ARTICLES": "0",
                    "ENABLE_BENZINGA_REST": "0",
                    "ENABLE_BENZINGA_WS": "0",
                    "ENABLE_TRADINGVIEW_NEWS": "0",
                    "ENABLE_NEWSAPI_AI": "1",
                    "NEWSAPI_KEY": "news-key",
                    "FILTER_TO_UNIVERSE": "0",
                },
                clear=False,
            ),
        ):
            cfg = Config()
            pipeline.poll_once(cfg, universe={"AAPL"})

        meta = mock_export.call_args[0][2]
        provider = meta["providers"]["newsapi_ai"]
        assert provider["provider_status"] == "ok_no_recent_matches"
        assert provider["status_detail"] == "Event Registry reachable, but no new symbol-matching NewsAPI.ai items were newer than the current cursor."
        assert meta["cursor"]["newsapi_ai_last_seen_news_uri"] == "uri-feed-1"
    finally:
        pipeline._best_by_ticker.clear()
        pipeline._best_by_ticker.update(old_best)
        store.close()


def test_poll_once_exports_newsapi_semantic_error_status() -> None:
    from newsstack_fmp import pipeline
    from newsstack_fmp.config import Config
    from newsstack_fmp.store_sqlite import SqliteStore

    class DummyNewsApiError(RuntimeError):
        def __init__(self, provider_status: str, detail: str) -> None:
            super().__init__(f"{provider_status}: {detail}")
            self.provider_status = provider_status
            self.detail = detail

    store = SqliteStore(":memory:")

    old_best = pipeline._best_by_ticker.copy()
    pipeline._best_by_ticker.clear()
    try:
        with (
            patch.object(pipeline, "_get_store", return_value=store),
            patch.object(pipeline, "_get_enricher", return_value=MagicMock()),
            patch.object(
                pipeline,
                "_fetch_newsapi_provider_items",
                side_effect=DummyNewsApiError("quota_exhausted", "Event Registry quota exhausted for this key."),
            ),
            patch.object(pipeline, "export_open_prep") as mock_export,
            patch.dict(
                os.environ,
                {
                    "ENABLE_FMP": "0",
                    "ENABLE_FMP_ARTICLES": "0",
                    "ENABLE_BENZINGA_REST": "0",
                    "ENABLE_BENZINGA_WS": "0",
                    "ENABLE_TRADINGVIEW_NEWS": "0",
                    "ENABLE_NEWSAPI_AI": "1",
                    "NEWSAPI_KEY": "news-key",
                    "FILTER_TO_UNIVERSE": "0",
                },
                clear=False,
            ),
        ):
            cfg = Config()
            pipeline.poll_once(cfg, universe={"AAPL"})

        meta = mock_export.call_args[0][2]
        provider = meta["providers"]["newsapi_ai"]
        assert provider["provider_status"] == "quota_exhausted"
        assert provider["status_detail"] == "Event Registry quota exhausted for this key."
        assert any("newsapi_ai:" in warning for warning in meta["warnings"])
    finally:
        pipeline._best_by_ticker.clear()
        pipeline._best_by_ticker.update(old_best)
        store.close()


def test_poll_once_exposes_last_meta_for_downstream_consumers() -> None:
    from newsstack_fmp import pipeline
    from newsstack_fmp.config import Config
    from newsstack_fmp.store_sqlite import SqliteStore

    store = SqliteStore(":memory:")
    store.set_kv("newsapi_ai.last_seen_epoch", "1750000050.0")

    old_best = pipeline._best_by_ticker.copy()
    old_meta = pipeline._last_meta
    pipeline._best_by_ticker.clear()
    try:
        with (
            patch.object(pipeline, "_get_store", return_value=store),
            patch.object(pipeline, "_get_enricher", return_value=MagicMock()),
            patch.object(
                pipeline,
                "_fetch_newsapi_provider_items",
                return_value=CachedNewsBatch(
                    provider="newsapi_ai",
                    scope={"symbols": ["AAPL"]},
                    items=[],
                    raw_items=[_newsapi_item("search_events", "event-2")],
                    raw_count=1,
                    cursor=1_750_000_050.0,
                    fetched_at=1_750_000_100.0,
                    from_cache=False,
                ),
            ),
            patch.object(pipeline, "export_open_prep"),
            patch.dict(
                os.environ,
                {
                    "ENABLE_FMP": "0",
                    "ENABLE_FMP_ARTICLES": "0",
                    "ENABLE_BENZINGA_REST": "0",
                    "ENABLE_BENZINGA_WS": "0",
                    "ENABLE_TRADINGVIEW_NEWS": "0",
                    "ENABLE_NEWSAPI_AI": "1",
                    "NEWSAPI_KEY": "news-key",
                    "FILTER_TO_UNIVERSE": "0",
                },
                clear=False,
            ),
        ):
            cfg = Config()
            pipeline.poll_once(cfg, universe={"AAPL"})

        meta = pipeline.get_last_meta()
        provider = meta["providers"]["newsapi_ai"]
        assert provider["provider_status"] == "ok_no_recent_matches"
        provider["provider_status"] = "mutated"
        assert pipeline.get_last_meta()["providers"]["newsapi_ai"]["provider_status"] == "ok_no_recent_matches"
    finally:
        pipeline._best_by_ticker.clear()
        pipeline._best_by_ticker.update(old_best)
        pipeline._last_meta = old_meta
        store.close()


def test_poll_once_exports_benzinga_rss_provider_state() -> None:
    from newsstack_fmp import pipeline
    from newsstack_fmp.config import Config
    from newsstack_fmp.store_sqlite import SqliteStore

    class _DummyRssAdapter:
        def __init__(self, *, fetch_total: int, fetch_errors: int, last_fetch_errors: int) -> None:
            self.fetch_total = fetch_total
            self.fetch_errors = fetch_errors
            self.last_fetch_errors = last_fetch_errors
            self.items_parsed = 7
            self.items_deduped = 2
            self.bozo_total = 1
            self.last_fetch_duration = 0.456

        def fetch_news(self, *, min_epoch: float = 0.0):
            _ = min_epoch
            return []

    store = SqliteStore(":memory:")

    old_best = pipeline._best_by_ticker.copy()
    old_meta = pipeline._last_meta
    old_adapter = pipeline._bz_rss_adapter
    pipeline._best_by_ticker.clear()
    try:
        with (
            patch.object(pipeline, "_get_store", return_value=store),
            patch.object(pipeline, "_get_enricher", return_value=MagicMock()),
            patch.object(pipeline, "_fetch_newsapi_provider_items", return_value=None),
            patch.object(pipeline, "export_open_prep") as mock_export,
            patch.dict(
                os.environ,
                {
                    "ENABLE_FMP": "0",
                    "ENABLE_FMP_ARTICLES": "0",
                    "ENABLE_BENZINGA_REST": "0",
                    "ENABLE_BENZINGA_WS": "0",
                    "ENABLE_BENZINGA_RSS": "1",
                    "ENABLE_TRADINGVIEW_NEWS": "0",
                    "ENABLE_NEWSAPI_AI": "0",
                    "FILTER_TO_UNIVERSE": "0",
                },
                clear=False,
            ),
        ):
            pipeline._bz_rss_adapter = _DummyRssAdapter(
                fetch_total=1,
                fetch_errors=1,
                last_fetch_errors=1,
            )
            cfg = Config()
            pipeline.poll_once(cfg, universe={"AAPL"})

        meta = mock_export.call_args[0][2]
        provider = meta["providers"]["benzinga_rss"]
        assert provider["ok"] is False
        assert provider["fetch_total"] == 1
        assert provider["fetch_errors"] == 1
        assert provider["last_fetch_errors"] == 1
        assert provider["items_parsed"] == 7
        assert provider["items_deduped"] == 2
        assert provider["bozo_total"] == 1
        assert provider["last_fetch_duration_s"] == 0.456
    finally:
        pipeline._best_by_ticker.clear()
        pipeline._best_by_ticker.update(old_best)
        pipeline._last_meta = old_meta
        pipeline._bz_rss_adapter = old_adapter
        store.close()
