"""Unit tests for BenzingaRssAdapter (newsstack_fmp/ingest_benzinga.py).

All network calls are mocked — no real HTTP in CI.
"""
from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from newsstack_fmp.ingest_benzinga import BenzingaRssAdapter, _entry_to_news_item, _parse_rss_tickers

# ── helpers ──────────────────────────────────────────────────────────


def _make_entry(
    *,
    guid: str = "https://benzinga.com/article/1",
    title: str = "AAPL beats earnings",
    link: str = "https://benzinga.com/article/1",
    published_parsed: tuple | None = (2024, 6, 1, 10, 0, 0, 5, 153, 0),
    summary: str = "Apple Inc reported better than expected earnings.",
    author: str = "Jane Doe",
    tags: list | None = None,
) -> SimpleNamespace:
    resolved_tags = (
        [SimpleNamespace(scheme="stock-symbol", term="AAPL", label="AAPL")]
        if tags is None
        else tags
    )
    return SimpleNamespace(
        id=guid,
        title=title,
        link=link,
        published_parsed=published_parsed,
        summary=summary,
        author=author,
        tags=resolved_tags,
    )


def _mock_feedparser(parse_fn):
    """Context-manager: inject a fake feedparser into sys.modules."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        mock_fp = ModuleType("feedparser")
        mock_fp.parse = parse_fn
        old = sys.modules.get("feedparser")
        sys.modules["feedparser"] = mock_fp
        try:
            yield mock_fp
        finally:
            if old is None:
                sys.modules.pop("feedparser", None)
            else:
                sys.modules["feedparser"] = old

    return _ctx()


# ── _parse_rss_tickers ────────────────────────────────────────────────


def test_parse_rss_tickers_stock_symbol():
    entry = _make_entry(
        tags=[
            SimpleNamespace(scheme="stock-symbol", term="NVDA", label="NVDA"),
            SimpleNamespace(scheme="sector", term="Technology", label="Technology"),
        ]
    )
    tickers = _parse_rss_tickers(entry)
    assert tickers == ["NVDA"]


def test_parse_rss_tickers_multiple():
    entry = _make_entry(
        tags=[
            SimpleNamespace(scheme="stock-symbol", term="MSFT", label=None),
            SimpleNamespace(scheme="stock-symbol", term="GOOG", label=None),
        ]
    )
    assert set(_parse_rss_tickers(entry)) == {"MSFT", "GOOG"}


def test_parse_rss_tickers_no_tags():
    entry = _make_entry(tags=[])
    assert _parse_rss_tickers(entry) == []


def test_parse_rss_tickers_skips_long_term():
    entry = _make_entry(
        tags=[SimpleNamespace(scheme="stock-symbol", term="TOOLONG1", label=None)]
    )
    # 8 chars > 6 limit → filtered out
    assert _parse_rss_tickers(entry) == []


# ── _entry_to_news_item ───────────────────────────────────────────────


def test_entry_to_news_item_basic():
    entry = _make_entry()
    item = _entry_to_news_item(entry, source_url="https://benzinga.com/markets/feed")
    assert item is not None
    assert item.provider == "benzinga_rss"
    assert item.headline == "AAPL beats earnings"
    assert "AAPL" in item.tickers
    assert item.published_ts > 0
    assert item.url == "https://benzinga.com/article/1"
    assert item.source == "Jane Doe"


def test_entry_to_news_item_missing_title_returns_none():
    entry = _make_entry(title="")
    assert _entry_to_news_item(entry, source_url="x") is None


def test_entry_to_news_item_missing_guid_returns_none():
    entry = _make_entry(guid="")
    # fallback to link; if link also empty → None
    entry.link = ""
    assert _entry_to_news_item(entry, source_url="x") is None


def test_entry_to_news_item_no_timestamp():
    entry = _make_entry(published_parsed=None)
    item = _entry_to_news_item(entry, source_url="x")
    assert item is not None
    assert item.published_ts == 0.0


# ── BenzingaRssAdapter.fetch_news ────────────────────────────────────


def test_fetch_news_returns_items():
    def _parse(url, **_kw):
        entry = _make_entry(
            guid=f"guid-{url}",
            title="Test headline",
            published_parsed=(2024, 6, 1, 12, 0, 0, 5, 153, 0),
        )
        return {"entries": [entry], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    # Two feeds → 2 items (different guids)
    assert len(items) == 2
    assert all(i.provider == "benzinga_rss" for i in items)


def test_fetch_news_deduplicates_same_guid():
    """Same guid from both feeds - only one item returned."""
    def _parse(url, **_kw):
        return {"entries": [_make_entry(guid="shared-guid")], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    assert len(items) == 1


def test_fetch_news_min_epoch_filters_old():
    import calendar

    future_ts = float(calendar.timegm((2099, 1, 1, 0, 0, 0, 0, 1, 0)))

    def _parse(url, **_kw):
        return {"entries": [_make_entry()], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news(min_epoch=future_ts)
    assert items == []


def test_fetch_news_tolerates_bozo_with_no_entries():
    def _parse(url, **_kw):
        return {"entries": [], "bozo": True, "bozo_exception": Exception("parse error")}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    assert items == []


def test_fetch_news_tolerates_network_error():
    def _parse(url, **_kw):
        raise OSError("connection refused")

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    assert items == []


def test_fetch_news_no_feedparser():
    """If feedparser is not installed, returns empty list (no exception)."""
    old = sys.modules.pop("feedparser", None)
    try:
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
        assert items == []
    finally:
        if old is not None:
            sys.modules["feedparser"] = old


def test_fetch_news_passes_timeout_to_feedparser():
    """RSS-1: timeout kwarg must be forwarded to feedparser.parse()."""
    captured_kwargs: list[dict] = []

    def _parse(url, **kw):
        captured_kwargs.append(kw)
        return {"entries": [], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter(timeout=7)
        adapter.fetch_news()

    assert captured_kwargs
    assert all(kw.get("timeout") == 7 for kw in captured_kwargs)


def test_seen_guids_bounded():
    """RSS-2: _seen_guids must not grow beyond _RSS_MAX_SEEN_GUIDS."""
    from newsstack_fmp.ingest_benzinga import _RSS_MAX_SEEN_GUIDS

    adapter = BenzingaRssAdapter()
    # Simulate many unique GUIDs
    for i in range(_RSS_MAX_SEEN_GUIDS + 100):
        adapter._seen_guids.append(f"guid-{i}")
    assert len(adapter._seen_guids) <= _RSS_MAX_SEEN_GUIDS


def test_fetch_news_bozo_with_entries_still_processes():
    """RSS-5: bozo=True with entries should log warning but still yield items."""
    def _parse(url, **_kw):
        return {
            "bozo": True,
            "bozo_exception": "CharacterEncodingOverride",
            "entries": [_make_entry()],
        }

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    assert len(items) == 1


def test_metrics_counters_populated_after_fetch():
    """RSS adapter counters are incremented correctly after a successful fetch."""
    def _parse(url, **_kw):
        return {"bozo": False, "entries": [_make_entry(guid=f"g-{url}")]}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        adapter.fetch_news()

    assert adapter.fetch_total == 1
    assert adapter.fetch_errors == 0
    assert adapter.last_fetch_errors == 0
    assert adapter.items_parsed == 2  # 2 feeds × 1 entry
    assert adapter.items_deduped == 0
    assert adapter.bozo_total == 0
    assert adapter.last_fetch_duration > 0


def test_metrics_dedup_counter():
    """Dedup counter increments when same GUID seen twice."""
    def _parse(url, **_kw):
        return {"bozo": False, "entries": [_make_entry(guid="same-guid")]}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        adapter.fetch_news()
        adapter.fetch_news()

    assert adapter.items_deduped == 3  # 1st call: feed2 dups feed1; 2nd call: both feeds dup
    assert adapter.fetch_total == 2


def test_last_fetch_errors_resets_per_fetch_call():
    """last_fetch_errors reflects only the most recent fetch invocation."""
    state = {"fail": True}

    def _parse(_url, **_kw):
        if state["fail"]:
            raise RuntimeError("transient rss failure")
        return {"bozo": False, "entries": []}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        adapter.fetch_news()
        assert adapter.last_fetch_errors == 2  # two RSS feed URLs

        state["fail"] = False
        adapter.fetch_news()

    assert adapter.last_fetch_errors == 0

