from __future__ import annotations

from unittest.mock import patch

from newsstack_fmp.common_types import NewsItem
from newsstack_fmp.shared_fetch import fetch_cached_batch, resolved_shared_cache_ttl_seconds


def _item(*, item_id: str, ts: float) -> NewsItem:
    return NewsItem(
        provider="fmp_stock_latest",
        item_id=item_id,
        published_ts=ts,
        updated_ts=ts,
        headline=f"Headline {item_id}",
        snippet="",
        tickers=["AAPL"],
        url=f"https://example.test/{item_id}",
        source="FMP",
    )


def test_fetch_cached_batch_reuses_recent_payload(tmp_path) -> None:
    calls = {"count": 0}

    def _fetcher():
        calls["count"] += 1
        return [_item(item_id="first", ts=100.0)]

    first = fetch_cached_batch(
        provider="fmp_stock_latest",
        scope={"page": 0, "limit": 100},
        ttl_seconds=120.0,
        min_cursor=0.0,
        fetcher=_fetcher,
        cache_dir=tmp_path,
    )
    second = fetch_cached_batch(
        provider="fmp_stock_latest",
        scope={"page": 0, "limit": 100},
        ttl_seconds=120.0,
        min_cursor=0.0,
        fetcher=_fetcher,
        cache_dir=tmp_path,
    )

    assert first.from_cache is False
    assert second.from_cache is True
    assert calls["count"] == 1
    assert [item.item_id for item in second.items] == ["first"]
    assert [item.item_id for item in second.raw_items] == ["first"]


def test_fetch_cached_batch_filters_cached_items_by_cursor(tmp_path) -> None:
    calls = {"count": 0}

    def _fetcher():
        calls["count"] += 1
        return [_item(item_id="older", ts=100.0), _item(item_id="newer", ts=200.0)]

    fetch_cached_batch(
        provider="fmp_stock_latest",
        scope={"page": 0, "limit": 100},
        ttl_seconds=120.0,
        min_cursor=0.0,
        fetcher=_fetcher,
        cache_dir=tmp_path,
    )
    filtered = fetch_cached_batch(
        provider="fmp_stock_latest",
        scope={"page": 0, "limit": 100},
        ttl_seconds=120.0,
        min_cursor=150.0,
        fetcher=_fetcher,
        cache_dir=tmp_path,
    )

    assert filtered.from_cache is True
    assert calls["count"] == 1
    assert [item.item_id for item in filtered.items] == ["newer"]
    assert [item.item_id for item in filtered.raw_items] == ["older", "newer"]


def test_resolved_shared_cache_ttl_seconds_prefers_newsapi_override() -> None:
    with patch.dict("os.environ", {"NEWSAPI_AI_SHARED_CACHE_TTL_SECONDS": "25"}, clear=False):
        assert resolved_shared_cache_ttl_seconds("newsapi_ai", 90.0) == 25.0
        assert resolved_shared_cache_ttl_seconds("fmp_stock_latest", 90.0) == 90.0


def test_resolved_shared_cache_ttl_seconds_ignores_invalid_override() -> None:
    with patch.dict("os.environ", {"NEWSAPI_AI_SHARED_CACHE_TTL_SECONDS": "invalid"}, clear=False):
        assert resolved_shared_cache_ttl_seconds("newsapi_ai", 90.0) == 90.0
