"""Unit tests for Task 2.1 of the Databento signal-migration plan: wiring
``RT_QUOTE_SOURCE`` behind ``RealtimeEngine._default_quote_source()``.

Task 1.1 introduced the ``_quote_source`` seam but left the self-heal in
``_fetch_realtime_quotes`` always rebuilding ``FMPQuoteSource`` regardless of
``RT_QUOTE_SOURCE`` -- an inert flag. This suite proves the fix with a FAKE
``DatabentoQuoteFeed`` factory and a stub ``QuoteReference.load`` (no real
network, no real ``DATABENTO_API_KEY``):

(a) ``RT_QUOTE_SOURCE=databento`` makes ``_fetch_realtime_quotes`` pull rows
    from the Databento source, not FMP.
(b) The self-heal (``_quote_source is None``) now respects the flag: it
    rebuilds a ``DatabentoQuoteSource`` under the flag instead of always
    falling back to FMP.
(c) Databento is the default when the flag is unset; FMP is only selected
    explicitly or as an observable construction-time fallback.

A fifth test proves the feed lifecycle: ``start_quote_source()`` /
``stop_quote_source()`` start/stop the constructed feed exactly once each,
and are a no-op under explicit/fallback FMP mode.
"""

from __future__ import annotations

import time
import types
from typing import Any

import pytest

import open_prep.quote_reference as quote_reference_module
import open_prep.realtime_signals as rs
from open_prep.databento_quote_feed import BarState
from open_prep.quote_reference import QuoteReference, QuoteReferenceRow
from open_prep.quote_source import DatabentoQuoteSource, FMPQuoteSource


class _FakeDatabentoQuoteFeed:
    """Duck-typed stand-in for ``DatabentoQuoteFeed`` (same shape as
    ``tests/test_databento_quote_source.py``'s fixture): canned bar/volume/
    hi-lo state plus start/stop call counters, no real thread, no network."""

    def __init__(self) -> None:
        self._bars: dict[str, BarState] = {}
        self._cumulative_volume: dict[str, int] = {}
        self._session_high_low: dict[str, tuple[float | None, float | None]] = {}
        self.start_calls = 0
        self.stop_calls = 0

    def set_symbol(
        self,
        symbol: str,
        *,
        bar: BarState,
        cumulative_volume: int,
        session_high: float,
        session_low: float,
    ) -> None:
        self._bars[symbol] = bar
        self._cumulative_volume[symbol] = cumulative_volume
        self._session_high_low[symbol] = (session_high, session_low)

    def latest_bar(self, symbol: str) -> BarState | None:
        return self._bars.get(symbol.strip().upper())

    def cumulative_volume(self, symbol: str) -> int:
        return self._cumulative_volume.get(symbol.strip().upper(), 0)

    def session_high_low(self, symbol: str) -> tuple[float | None, float | None]:
        return self._session_high_low.get(symbol.strip().upper(), (None, None))

    def start(self) -> None:
        self.start_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1


class _FakeDatabentoQuoteFeedFactory:
    """Stand-in for the ``DatabentoQuoteFeed`` class itself: records the
    constructor args ``_build_databento_quote_source`` passes (proving the
    watchlist symbols + a lazy client factory were used, never invoked) and
    returns a preloaded ``_FakeDatabentoQuoteFeed`` instead of opening a real
    ``db.Live()`` connection."""

    def __init__(self, feed: _FakeDatabentoQuoteFeed) -> None:
        self.feed = feed
        self.calls: list[dict[str, Any]] = []

    def __call__(self, symbols, client_or_factory, *, replay_start, **kwargs):
        self.calls.append({
            "symbols": list(symbols),
            "client_or_factory": client_or_factory,
            "replay_start": replay_start,
        })
        return self.feed


class _PoisonFMPClient:
    """Any FMP call site touched under RT_QUOTE_SOURCE=databento is a bug."""

    def get_stable_batch_quotes(self, symbols):
        raise AssertionError(f"FMP must not be called under RT_QUOTE_SOURCE=databento (symbols={symbols})")

    def get_batch_quotes(self, symbols):
        raise AssertionError(f"FMP must not be called under RT_QUOTE_SOURCE=databento (symbols={symbols})")


def _fake_reference(symbol: str = "AAPL") -> QuoteReference:
    return QuoteReference({
        symbol: QuoteReferenceRow(
            previous_close=95.0,
            average_daily_volume=1_000_000.0,
            as_of_session="2026-07-23",
            source="fmp:adjusted-eod+adv=databento:equs-mini-ohlcv-1d",
        ),
    })


def _install_fake_databento_plumbing(monkeypatch, feed: _FakeDatabentoQuoteFeed) -> _FakeDatabentoQuoteFeedFactory:
    factory = _FakeDatabentoQuoteFeedFactory(feed)
    # Patched at the source module: _build_databento_quote_source does a
    # local `from .databento_quote_feed import DatabentoQuoteFeed`, which
    # resolves this attribute at CALL time (late binding), so patching here
    # takes effect without touching realtime_signals.py's import list.
    monkeypatch.setattr("open_prep.databento_quote_feed.DatabentoQuoteFeed", factory)
    monkeypatch.setattr(
        quote_reference_module.QuoteReference, "load",
        classmethod(lambda cls, path=quote_reference_module.DEFAULT_OUTPUT_PATH: _fake_reference()),
    )
    return factory


def _bar(symbol: str = "AAPL") -> BarState:
    # ts_event/ts_recv anchored to real wall-clock time (not a fixed
    # historical epoch): these tests exercise the real, un-clocked
    # `engine._fetch_realtime_quotes()` -> `DatabentoQuoteSource.fetch()`
    # path, which defaults its bounded-age staleness guard (see
    # quote_source.py) to `time.time()`, not an injectable test clock.
    now = time.time()
    return BarState(
        symbol=symbol, open=99.0, high=101.0, low=98.5, close=100.5,
        volume=12_345, ts_event=now - 1.0, ts_recv=now - 0.5,
    )


# ---------------------------------------------------------------------------
# (a) RT_QUOTE_SOURCE=databento -- the poll cycle pulls from Databento, not FMP
# ---------------------------------------------------------------------------


def test_engine_uses_databento_source_when_flagged(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    fake_feed.set_symbol("AAPL", bar=_bar(), cumulative_volume=500_000, session_high=101.0, session_low=98.0)
    factory = _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _PoisonFMPClient()
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None
    engine._quote_source = None  # forces the self-heal to build one

    quotes = engine._fetch_realtime_quotes()

    assert isinstance(engine._quote_source, DatabentoQuoteSource)
    assert quotes["AAPL"]["source"] == "databento"
    assert quotes["AAPL"]["price"] == 100.5
    assert quotes["AAPL"]["previousClose"] == 95.0
    assert quotes["AAPL"]["avgVolume"] == 1_000_000.0
    assert len(factory.calls) == 1
    assert factory.calls[0]["symbols"] == ["AAPL"]
    assert callable(factory.calls[0]["client_or_factory"])
    # The self-heal must start the freshly-rebuilt feed itself (orphaned-feed
    # fix) -- main() only calls start_quote_source() once, before the poll
    # loop begins, so a self-healed feed left unstarted would never fill its
    # cache. This does NOT itself touch db.Live(): the fake feed's start()
    # just increments a counter, mirroring how the real feed's start() only
    # spawns its reconnect thread -- the client_or_factory lambda is invoked
    # later, by that thread, not by start() itself.
    assert fake_feed.start_calls == 1


def test_databento_source_requires_api_key_at_build_time(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._watchlist = [{"symbol": "AAPL"}]

    with pytest.raises(RuntimeError, match="DATABENTO_API_KEY is required"):
        engine._build_databento_quote_source()


def test_disabled_fmp_client_does_not_block_databento_fetch(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    fake_feed.set_symbol(
        "AAPL",
        bar=_bar(),
        cumulative_volume=500_000,
        session_high=101.0,
        session_low=98.0,
    )
    _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = None
    engine._client_disabled_reason = "RuntimeError"
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None
    engine._quote_source = None

    quotes = engine._fetch_realtime_quotes()

    assert quotes["AAPL"]["source"] == "databento"
    assert isinstance(engine._quote_source, DatabentoQuoteSource)


# ---------------------------------------------------------------------------
# (b) Self-heal respects the flag: None _quote_source rebuilds Databento
# ---------------------------------------------------------------------------


def test_self_heal_rebuilds_databento_source_not_fmp_when_flagged(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    fake_feed.set_symbol("MSFT", bar=_bar("MSFT"), cumulative_volume=10_000, session_high=101.0, session_low=98.0)
    _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _PoisonFMPClient()
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "MSFT"}]
    engine._databento_feed = None
    engine._quote_source = None

    # Pre-Task-2.1 this self-heal always rebuilt FMPQuoteSource here,
    # silently ignoring RT_QUOTE_SOURCE -- this is the exact regression
    # this test pins closed.
    rebuilt = engine._default_quote_source()

    assert isinstance(rebuilt, DatabentoQuoteSource)
    assert not isinstance(rebuilt, FMPQuoteSource)


def test_self_healed_feed_is_started_not_orphaned(monkeypatch) -> None:
    """Covering test for the orphaned-feed bug: main() calls
    start_quote_source() exactly once, before the poll loop begins -- so a
    feed rebuilt later by the self-heal (e.g. cold start with an empty
    watchlist, watchlist fills in on a later poll) must be started by the
    self-heal itself, or its threads never run, the cache stays empty, and
    DatabentoQuoteSource.fetch() fail-closed omits every symbol forever."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    fake_feed.set_symbol("AAPL", bar=_bar(), cumulative_volume=500_000, session_high=101.0, session_low=98.0)
    _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _PoisonFMPClient()
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None
    engine._quote_source = None  # forces the self-heal path in _fetch_realtime_quotes

    engine._fetch_realtime_quotes()

    assert engine._databento_feed is fake_feed
    assert fake_feed.start_calls == 1, (
        "self-healed feed was constructed but never started -- orphaned, "
        "cache never fills, every symbol is fail-closed omitted forever"
    )


# ---------------------------------------------------------------------------
# (c) Databento default + explicit/automatic FMP fallback
# ---------------------------------------------------------------------------


def test_default_quote_source_is_databento_when_flag_unset(monkeypatch) -> None:
    monkeypatch.delenv("RT_QUOTE_SOURCE", raising=False)
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None

    source = engine._default_quote_source()

    assert isinstance(source, DatabentoQuoteSource)
    assert engine._quote_source_fallback_reason == ""


def test_explicit_fmp_end_to_end_fetch_unchanged(monkeypatch) -> None:
    """Explicit rollback preserves the same end-to-end shape as the pre-existing
    test_fmp_quote_source_matches_current_engine_fetch_realtime_quotes in
    test_quote_source_parity.py."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "fmp")

    class _Client:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def get_stable_batch_quotes(self, symbols):
            self.calls.append(symbols)
            return [{"symbol": symbol, "price": 1.0} for symbol in symbols]

    client = _Client()
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = client
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]
    engine._databento_feed = None
    engine._quote_source = None

    quotes = engine._fetch_realtime_quotes()

    assert client.calls == [["AAPL", "MSFT"]]
    assert sorted(quotes) == ["AAPL", "MSFT"]
    assert isinstance(engine._quote_source, FMPQuoteSource)


def test_databento_construction_failure_falls_back_to_fmp(monkeypatch) -> None:
    monkeypatch.delenv("RT_QUOTE_SOURCE", raising=False)
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = "sentinel-client"
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None

    source = engine._default_quote_source()

    assert isinstance(source, FMPQuoteSource)
    assert source._resolve_client() == "sentinel-client"
    assert engine._quote_source_fallback_reason == "RuntimeError"


def test_empty_databento_reference_falls_back_to_fmp(monkeypatch) -> None:
    monkeypatch.delenv("RT_QUOTE_SOURCE", raising=False)
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    _install_fake_databento_plumbing(monkeypatch, fake_feed)
    monkeypatch.setattr(
        quote_reference_module.QuoteReference,
        "load",
        classmethod(
            lambda cls, path=quote_reference_module.DEFAULT_OUTPUT_PATH: QuoteReference({})
        ),
    )

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = "sentinel-client"
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None

    source = engine._default_quote_source()

    assert isinstance(source, FMPQuoteSource)
    assert engine._databento_feed is None
    assert engine._quote_source_fallback_reason == "RuntimeError"


# ---------------------------------------------------------------------------
# Feed lifecycle: start_quote_source() / stop_quote_source()
# ---------------------------------------------------------------------------


def test_start_stop_quote_source_drive_the_databento_feed(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")

    fake_feed = _FakeDatabentoQuoteFeed()
    _install_fake_databento_plumbing(monkeypatch, fake_feed)

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _PoisonFMPClient()
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}]
    engine._databento_feed = None
    engine._quote_source = engine._default_quote_source()  # builds + stashes _databento_feed

    assert engine._databento_feed is fake_feed
    assert fake_feed.start_calls == 0

    engine.start_quote_source()
    assert fake_feed.start_calls == 1
    assert fake_feed.stop_calls == 0

    engine.stop_quote_source()
    assert fake_feed.start_calls == 1
    assert fake_feed.stop_calls == 1


def test_start_stop_quote_source_are_noop_under_explicit_fmp_rollback(monkeypatch) -> None:
    monkeypatch.setenv("RT_QUOTE_SOURCE", "fmp")

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = "sentinel-client"
    engine._databento_feed = None
    engine._quote_source = engine._default_quote_source()

    assert isinstance(engine._quote_source, FMPQuoteSource)
    assert engine._databento_feed is None

    # Must not raise even though there is no feed to start/stop.
    engine.start_quote_source()
    engine.stop_quote_source()


# ---------------------------------------------------------------------------
# Hardening: SIGTERM stop path + watchlist-rotation feed lifecycle (Phase 2.2
# follow-up). SIGTERM must flow through the same graceful shutdown SIGINT does;
# a watchlist reload must resubscribe the feed + reload the daily reference,
# and stay a safe no-op under explicit FMP rollback.
# ---------------------------------------------------------------------------


def test_sigterm_handler_raises_keyboard_interrupt() -> None:
    """The SIGTERM handler translates the signal into the KeyboardInterrupt
    that ``main()``'s existing graceful-shutdown block already catches (which
    stops the Databento feed's db.Live socket + threads)."""
    with pytest.raises(KeyboardInterrupt):
        rs._raise_keyboard_interrupt_on_sigterm(15, None)


def _minimal_engine_for_reload(monkeypatch, watchlist, *, feed, quote_source):
    """A ``RealtimeEngine`` skeleton with just the attributes
    ``reload_watchlist`` touches, and ``_load_watchlist`` stubbed to a no-op
    (its file/network work is out of scope here)."""
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._watchlist = watchlist
    monkeypatch.setattr(engine, "_load_watchlist", lambda: None)
    engine._last_prices = {}
    engine._price_history = {}
    engine._quote_hashes = {}
    engine._vd_last_change_epoch = {}
    engine._avg_vol_cache = {}
    engine._delta_tracker = types.SimpleNamespace(_prev={}, _streaks={})
    engine._hysteresis = types.SimpleNamespace(_state={})
    engine._dynamic_cooldown = types.SimpleNamespace(prune_stale=lambda keep: None)
    engine._technical_scorer = types.SimpleNamespace(clear=lambda: None)
    engine._databento_feed = feed
    engine._quote_source = quote_source
    return engine


def test_reload_watchlist_resubscribes_feed_and_reloads_reference(monkeypatch) -> None:
    calls: dict[str, Any] = {}
    feed = types.SimpleNamespace(
        update_symbols=lambda syms: calls.__setitem__("symbols", syms),
    )
    quote_source = types.SimpleNamespace(
        reload_reference=lambda: calls.__setitem__("reloaded", True),
    )
    engine = _minimal_engine_for_reload(
        monkeypatch, [{"symbol": "AAPL"}, {"symbol": "msft"}],
        feed=feed, quote_source=quote_source,
    )

    engine.reload_watchlist()

    assert calls.get("symbols") == ["AAPL", "MSFT"]  # normalized + sorted
    assert calls.get("reloaded") is True


def test_reload_watchlist_is_noop_for_explicit_fmp_rollback(monkeypatch) -> None:
    """Explicit FMP rollback: no Databento feed, and an FMP source has no
    ``reload_reference`` -- the rotation must not raise."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "fmp")
    engine = _minimal_engine_for_reload(
        monkeypatch, [{"symbol": "AAPL"}],
        feed=None,
        quote_source=FMPQuoteSource(lambda: object()),
    )
    engine.reload_watchlist()  # must not raise


def test_reload_watchlist_retries_databento_after_runtime_fallback(monkeypatch) -> None:
    """An automatic FMP fallback is not sticky forever: the daily watchlist
    reload retries Databento and starts the recovered feed."""
    monkeypatch.delenv("RT_QUOTE_SOURCE", raising=False)
    recovered_feed = _FakeDatabentoQuoteFeed()
    recovered = DatabentoQuoteSource(recovered_feed, _fake_reference())
    engine = _minimal_engine_for_reload(
        monkeypatch,
        [{"symbol": "AAPL"}],
        feed=None,
        quote_source=FMPQuoteSource(lambda: object()),
    )
    monkeypatch.setattr(engine, "_default_quote_source", lambda: recovered)
    starts: list[bool] = []
    monkeypatch.setattr(engine, "start_quote_source", lambda: starts.append(True))

    engine.reload_watchlist()

    assert engine._quote_source is recovered
    assert starts == [True]
