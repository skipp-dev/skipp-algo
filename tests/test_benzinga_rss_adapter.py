"""Unit tests for BenzingaRssAdapter (newsstack_fmp/ingest_benzinga.py).

All network calls are mocked — no real HTTP in CI.
"""
from __future__ import annotations

import sys
import threading
from types import ModuleType, SimpleNamespace

import pytest

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
        updated_parsed=None,
        summary=summary,
        author=author,
        tags=resolved_tags,
    )


def _mock_feedparser(parse_fn):
    """Context-manager: inject a fake feedparser into sys.modules.

    Also stubs the module's ``_rss_http_get`` so ``_fetch_single_feed`` never
    hits the network — feedparser now parses bytes we fetch ourselves (the
    real ``feedparser.parse`` has no ``timeout`` kwarg), so tests must supply
    the HTTP boundary too.
    """
    import contextlib

    import newsstack_fmp.ingest_benzinga as _bz

    @contextlib.contextmanager
    def _ctx():
        mock_fp = ModuleType("feedparser")
        mock_fp.parse = parse_fn
        old = sys.modules.get("feedparser")
        sys.modules["feedparser"] = mock_fp
        old_get = _bz._rss_http_get
        # Return per-URL bytes so fake ``parse`` fns that key off their input
        # (guid=f"guid-{content}") still differentiate feeds now that parse
        # receives fetched content instead of the feed URL.
        _bz._rss_http_get = lambda feed_url, *, timeout: feed_url.encode()
        try:
            yield mock_fp
        finally:
            _bz._rss_http_get = old_get
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


def test_entry_to_news_item_updated_ts_from_updated_parsed():
    entry = _make_entry(
        published_parsed=(2024, 6, 1, 10, 0, 0, 5, 153, 0),
    )
    entry.updated_parsed = (2024, 6, 1, 11, 30, 0, 5, 153, 0)
    item = _entry_to_news_item(entry, source_url="x")
    assert item is not None
    assert item.updated_ts > item.published_ts


def test_entry_to_news_item_updated_ts_falls_back_to_published():
    entry = _make_entry(
        published_parsed=(2024, 6, 1, 10, 0, 0, 5, 153, 0),
    )
    entry.updated_parsed = None
    item = _entry_to_news_item(entry, source_url="x")
    assert item is not None
    assert item.updated_ts == item.published_ts


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


@pytest.mark.parametrize("min_epoch", [float("nan"), float("inf"), float("-inf")])
def test_fetch_news_non_finite_min_epoch_returns_no_items(min_epoch: float):
    parse_calls = 0

    def _parse(url, **_kw):
        nonlocal parse_calls
        parse_calls += 1
        return {"entries": [_make_entry(guid=f"guid-{url}")], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news(min_epoch=min_epoch)

    assert items == []
    assert parse_calls == 0


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


def test_fetch_news_no_feedparser(monkeypatch: pytest.MonkeyPatch):
    """If feedparser is not installed, returns empty list (no exception)."""
    import builtins

    old = sys.modules.pop("feedparser", None)
    real_import = builtins.__import__

    def _raise_for_feedparser(name, *args, **kwargs):
        if name == "feedparser":
            raise ImportError("blocked feedparser")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raise_for_feedparser)
    try:
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
        assert items == []
    finally:
        if old is not None:
            sys.modules["feedparser"] = old


def test_fetch_news_enforces_timeout_on_http_not_feedparser(monkeypatch):
    """RSS-1: the network timeout is enforced on the HTTP fetch, and
    ``feedparser.parse`` is called with content only (NO ``timeout`` kwarg —
    feedparser 6.x raises TypeError on it, which previously killed every fetch).
    """
    import newsstack_fmp.ingest_benzinga as _bz

    captured_timeouts: list[int] = []
    captured_parse_args: list[tuple] = []
    captured_parse_kwargs: list[dict] = []

    def _fake_get(feed_url, *, timeout):
        captured_timeouts.append(timeout)
        return b"<rss></rss>"

    def _parse(*args, **kw):
        captured_parse_args.append(args)
        captured_parse_kwargs.append(kw)
        return {"entries": [], "bozo": False}

    mock_fp = ModuleType("feedparser")
    mock_fp.parse = _parse
    monkeypatch.setitem(sys.modules, "feedparser", mock_fp)
    monkeypatch.setattr(_bz, "_rss_http_get", _fake_get)

    adapter = BenzingaRssAdapter(timeout=7)
    adapter.fetch_news()

    assert captured_timeouts, "HTTP fetch must run"
    assert all(t == 7 for t in captured_timeouts), "timeout must reach the HTTP layer"
    assert captured_parse_args, "feedparser.parse must be called with content"
    assert captured_parse_args[0][0] == b"<rss></rss>", "parse receives fetched bytes"
    assert all("timeout" not in kw for kw in captured_parse_kwargs), (
        "feedparser.parse must NOT receive a timeout kwarg (unsupported in 6.x)"
    )


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


def test_fetch_news_empty_feeds_counts_error() -> None:
    """Empty feed configuration should be surfaced as a fetch error."""
    with _mock_feedparser(lambda _url, **_kw: {"entries": [], "bozo": False}):
        adapter = BenzingaRssAdapter(feeds=())
        items = adapter.fetch_news()

    assert items == []
    assert adapter.fetch_total == 1
    assert adapter.fetch_errors == 1
    assert adapter.last_fetch_errors == 1


def test_fetch_news_retries_transient_failure_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
):
    """A feed that fails once then succeeds should still yield items."""
    attempts: list[str] = []
    seen_fail: set[str] = set()
    lock = threading.Lock()
    monkeypatch.setattr("newsstack_fmp.ingest_benzinga.time.sleep", lambda _s: None)

    def _parse(url, **_kw):
        with lock:
            attempts.append(url)
            first_for_url = url not in seen_fail
            if first_for_url:
                seen_fail.add(url)
        if first_for_url:
            raise Exception("transient")
        entry = _make_entry(guid=f"guid-{url}", title="Recovered")
        return {"entries": [entry], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    # Two feeds configured by default; each URL fails once, then succeeds.
    assert len(items) == 2
    assert adapter.fetch_errors == 0  # transient retries don't count as final errors


def test_fetch_news_gives_up_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
):
    """A feed that always fails should be skipped after max attempts."""
    monkeypatch.setattr("newsstack_fmp.ingest_benzinga.time.sleep", lambda _s: None)
    def _parse(url, **_kw):
        raise Exception("persistent")

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter()
        items = adapter.fetch_news()
    assert len(items) == 0
    assert adapter.fetch_errors == 2  # one per default feed


def test_fetch_news_parallel_fetches_all_feeds():
    """Multiple feeds are fetched and aggregated even when they return different items."""
    feeds = (
        "https://benzinga.com/feed/a",
        "https://benzinga.com/feed/b",
        "https://benzinga.com/feed/c",
    )

    def _parse(content, **_kw):
        # parse now receives fetched bytes; the mock http layer returns the
        # feed URL encoded, so decode back to keep the per-feed assertion.
        url = content.decode() if isinstance(content, bytes) else content
        return {"entries": [_make_entry(guid=f"guid-{url}", title=f"From {url}")], "bozo": False}

    with _mock_feedparser(_parse):
        adapter = BenzingaRssAdapter(feeds=feeds)
        items = adapter.fetch_news()
    assert len(items) == 3
    assert {i.headline for i in items} == {f"From {u}" for u in feeds}


def test_entry_to_news_item_published_ts_falls_back_to_updated_parsed():
    """When published_parsed is missing but updated_parsed exists, use it."""
    entry = _make_entry(guid="g", title="t")
    entry.published_parsed = None
    entry.updated_parsed = (2024, 6, 1, 11, 30, 0, 5, 153, 0)
    item = _entry_to_news_item(entry, source_url="x")
    assert item is not None
    assert item.published_ts > 0.0
    assert item.published_ts == item.updated_ts
