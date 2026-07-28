"""Tests for the opt-in near-A0 fast-lane re-poller (open_prep.realtime_signals).

The re-poller re-polls the A1/A2 warm set faster than the full cycle and pushes a
fresh A0 early. These tests pin the safety-critical behaviour with fakes (no real
FMP / Databento / threads): warm-set = A1/A2 only, only A0 is pushed, off-hours /
empty warm set skip the fetch entirely, delivery flows through rt_notify's dedup --
and (Finding 2 of the final whole-branch review) the re-poller fetches through the
ENGINE's shared ``QuoteSource`` seam rather than a FMP client of its own, so the
fast lane and the main poll loop always read off the SAME data source.
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from typing import Any

import pytest

import open_prep.quote_reference as quote_reference_module
from open_prep import realtime_signals as rs
from open_prep.databento_quote_feed import BarState
from open_prep.quote_reference import QuoteReference, QuoteReferenceRow
from open_prep.quote_source import DatabentoQuoteSource, FMPQuoteSource
from open_prep.realtime_signals import NearA0Repoller


def _sig(symbol: str, level: str, direction: str = "LONG") -> Any:
    return SimpleNamespace(
        symbol=symbol, level=level, direction=direction, price=100.0,
        volume_ratio=3.5, change_pct=2.1, news_score=0.0, news_category="",
        news_headline="",
    )


class _FakeRegime:
    def adjusted_thresholds(self) -> dict[str, float]:
        return {"volume_ratio_min": 3.0}


class _FakeQuoteSource:
    """Minimal ``QuoteSource`` stand-in: records ``(symbols, session)`` calls
    and returns canned rows, mirroring the real
    ``fetch(symbols, session) -> list[dict]`` contract (FMPQuoteSource /
    DatabentoQuoteSource) that the re-poller must now go through instead of
    a FMP client of its own."""

    def __init__(self, rows_by_symbol: dict[str, dict[str, Any]] | None = None) -> None:
        self._rows_by_symbol = rows_by_symbol or {}
        self.calls: list[tuple[list[str], str]] = []

    def fetch(self, symbols: list[str], session: str) -> list[dict[str, Any]]:
        self.calls.append((list(symbols), session))
        return [
            {"symbol": s, **self._rows_by_symbol.get(s, {"price": 101.0, "previousClose": 99.0})}
            for s in symbols
        ]


class _FakeEngine:
    """Minimal engine surface the re-poller reads. ``quote_source`` stands in
    for ``RealtimeEngine._quote_source`` -- the seam the re-poller must fetch
    through."""

    def __init__(
        self, active: list[Any], detect_map: dict[str, Any],
        *, quote_source: Any = None,
    ) -> None:
        self._active = active
        self._detect_map = detect_map
        self._watchlist = [{"symbol": s} for s in ("AAPL", "NVDA", "PLTR", "AMZN")]
        self._volume_regime = _FakeRegime()
        self._async_newsstack: Any = None
        self._quote_source = quote_source if quote_source is not None else _FakeQuoteSource()

    def get_active_signals(self) -> list[Any]:
        return list(self._active)

    def _detect_signal(self, symbol: str, quote: dict[str, Any], wl_entry: dict[str, Any],
                       *, regime_thresholds: Any = None,
                       expected_volume_fraction: Any = None) -> Any:
        return self._detect_map.get(symbol)


@pytest.fixture(autouse=True)
def _open_market(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: True)


def _repoller(engine: _FakeEngine) -> NearA0Repoller:
    return NearA0Repoller(engine, interval=5.0)


def test_warm_set_is_a1_a2_only() -> None:
    active = [_sig("AAPL", "A0"), _sig("NVDA", "A1"), _sig("PLTR", "A2"), _sig("AMZN", "A1")]
    r = _repoller(_FakeEngine(active, {}))
    assert sorted(r._warm_set()) == ["AMZN", "NVDA", "PLTR"]  # A0 excluded


def test_only_fresh_a0_is_pushed(monkeypatch: pytest.MonkeyPatch) -> None:
    pushed: list[list[Any]] = []
    monkeypatch.setattr(
        "open_prep.rt_notify.notify_fresh_signals",
        lambda sigs, **kw: (pushed.append(list(sigs)), [f"{s.symbol} {s.direction} {s.level}" for s in sigs])[1],
    )
    active = [_sig("NVDA", "A1"), _sig("PLTR", "A2"), _sig("AMZN", "A1")]
    # NVDA escalates to A0; PLTR stays A1 (not pushed); AMZN no signal.
    detect_map = {"NVDA": _sig("NVDA", "A0"), "PLTR": _sig("PLTR", "A1"), "AMZN": None}
    quote_source = _FakeQuoteSource()
    r = _repoller(_FakeEngine(active, detect_map, quote_source=quote_source))
    r._tick()
    # Fetched exactly the warm set, through the engine's quote source, "regular" session.
    assert quote_source.calls == [(["NVDA", "PLTR", "AMZN"], "regular")]
    assert len(pushed) == 1 and [s.symbol for s in pushed[0]] == ["NVDA"]
    assert r.metrics()["a0_pushed"] == 1


def test_market_closed_skips_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(rs, "_is_within_market_hours", lambda: False)
    quote_source = _FakeQuoteSource()
    r = _repoller(_FakeEngine([_sig("NVDA", "A1")], {"NVDA": _sig("NVDA", "A0")}, quote_source=quote_source))
    r._tick()
    assert quote_source.calls == []  # no fetch off-hours


def test_empty_warm_set_skips_fetch() -> None:
    quote_source = _FakeQuoteSource()
    r = _repoller(_FakeEngine([_sig("AAPL", "A0")], {}, quote_source=quote_source))  # only A0 active -> warm set empty
    r._tick()
    assert quote_source.calls == []


def test_news_enrichment_on_early_push() -> None:
    engine = _FakeEngine([_sig("NVDA", "A1")], {"NVDA": _sig("NVDA", "A0")})
    engine._async_newsstack = SimpleNamespace(
        latest=lambda: {"NVDA": {"news_score": 0.9, "category": "M&A", "headline": "deal"}}
    )
    fresh = _repoller(engine)._detect_fresh_a0(
        {"NVDA": {"symbol": "NVDA", "price": 101.0}}
    )
    assert len(fresh) == 1 and fresh[0].news_score == 0.9 and fresh[0].news_category == "M&A"


def test_loop_is_fail_soft_on_quote_source_error() -> None:
    class _BoomQuoteSource:
        def fetch(self, symbols: list[str], session: str) -> list[dict[str, Any]]:
            raise RuntimeError("quote source down")

    r = NearA0Repoller(
        _FakeEngine([_sig("NVDA", "A1")], {}, quote_source=_BoomQuoteSource()), interval=0.01,
    )
    # Run the loop body exactly once: the end-of-iteration wait flips stop so the
    # while-guard exits, and the quote-source error must be swallowed + counted, not raised.
    r._stop.wait = lambda _t: r._stop.set()  # type: ignore[assignment]
    r._loop()
    assert r.metrics()["poll_errors"] >= 1


# ---------------------------------------------------------------------------
# Finding 2 (final whole-branch review): the re-poller used to fetch through
# its OWN FMPClient, bypassing the QuoteSource seam entirely -- meaning that
# under RT_QUOTE_SOURCE=databento the fast lane could escalate/push A0
# signals off 15-min-delayed FMP prices while the main loop ran on realtime
# Databento data. These two tests are the fix's proof.
# ---------------------------------------------------------------------------


def test_repoller_never_constructs_its_own_fmp_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a, part 1) Regardless of RT_QUOTE_SOURCE, the re-poller must never
    build its own FMPClient -- it only ever reads the engine's shared
    quote source. Poisoning FMPClient.from_env proves the old
    self._client_or_init() -> FMPClient.from_env() call site is gone."""
    monkeypatch.setattr("open_prep.rt_notify.notify_fresh_signals", lambda sigs, **kw: [])

    def _poison_from_env(cls: Any) -> Any:
        raise AssertionError("NearA0Repoller must not construct its own FMPClient")

    monkeypatch.setattr(rs.FMPClient, "from_env", classmethod(_poison_from_env))

    quote_source = _FakeQuoteSource()
    engine = _FakeEngine(
        [_sig("NVDA", "A1")], {"NVDA": _sig("NVDA", "A0")}, quote_source=quote_source,
    )
    r = _repoller(engine)
    r._tick()  # would raise AssertionError if FMPClient.from_env were still called

    assert quote_source.calls == [(["NVDA"], "regular")]


class _FakeDatabentoQuoteFeed:
    """Duck-typed stand-in for ``DatabentoQuoteFeed`` (same shape as
    ``tests/test_realtime_signals_databento_wiring.py``'s fixture): canned
    bar/volume/hi-lo state plus a start() call counter, no real thread, no
    network."""

    def __init__(self) -> None:
        self._bars: dict[str, BarState] = {}
        self._cumulative_volume: dict[str, int] = {}
        self._session_high_low: dict[str, tuple[float | None, float | None]] = {}
        self.start_calls = 0

    def set_symbol(
        self, symbol: str, *, bar: BarState, cumulative_volume: int,
        session_high: float, session_low: float,
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
        pass


def test_repoller_fetches_via_engine_databento_source_under_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a, part 2) Under RT_QUOTE_SOURCE=databento, the re-poller resolves the
    REAL engine's Databento-backed QuoteSource (built by the same
    ``_default_quote_source()`` factory ``_fetch_realtime_quotes`` uses) and
    fetches the warm set through it -- not FMP. Uses the real
    ``RealtimeEngine`` (via ``__new__``, same technique as
    test_realtime_signals_databento_wiring.py) so this exercises the exact
    production self-heal / factory code, not a re-implementation of it."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "databento")
    monkeypatch.setenv("DATABENTO_API_KEY", "test-key-not-real")
    monkeypatch.setattr("open_prep.rt_notify.notify_fresh_signals", lambda sigs, **kw: list(sigs))

    # ts_event/ts_recv anchored to real wall-clock time (not a fixed
    # historical epoch): this exercises the real, un-clocked
    # DatabentoQuoteSource.fetch() path, whose bounded-age staleness guard
    # (see quote_source.py) defaults to `time.time()`, not a test clock.
    _now = time.time()
    fake_feed = _FakeDatabentoQuoteFeed()
    fake_feed.set_symbol("NVDA", bar=BarState(
        symbol="NVDA", open=249.0, high=251.0, low=248.5, close=250.5,
        volume=12_345, ts_event=_now - 1.0, ts_recv=_now - 0.5,
    ), cumulative_volume=500_000, session_high=251.0, session_low=248.0)

    class _FakeDatabentoQuoteFeedFactory:
        def __call__(self, symbols: Any, client_or_factory: Any, *, replay_start: Any, **kwargs: Any) -> Any:
            return fake_feed

    monkeypatch.setattr("open_prep.databento_quote_feed.DatabentoQuoteFeed", _FakeDatabentoQuoteFeedFactory())
    monkeypatch.setattr(
        quote_reference_module.QuoteReference, "load",
        classmethod(lambda cls, path=quote_reference_module.DEFAULT_OUTPUT_PATH: QuoteReference({
            "NVDA": QuoteReferenceRow(
                previous_close=240.0, average_daily_volume=2_000_000.0,
                as_of_session="2026-07-24",
                source="fmp:adjusted-eod+adv=databento:equs-mini-ohlcv-1d",
            ),
        })),
    )

    class _PoisonFMPClient:
        def get_stable_batch_quotes(self, symbols: Any) -> Any:
            raise AssertionError(f"FMP must not be called under RT_QUOTE_SOURCE=databento (symbols={symbols})")

    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = _PoisonFMPClient()
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "NVDA"}]
    engine._databento_feed = None
    engine._quote_source = None  # forces the same self-heal _fetch_realtime_quotes uses
    engine._volume_regime = _FakeRegime()
    engine._async_newsstack = None
    engine._active_signals = [_sig("NVDA", "A1")]
    engine._lock = threading.Lock()
    engine.get_active_signals = lambda: list(engine._active_signals)
    engine._detect_signal = lambda symbol, quote, wl_entry, **kw: (
        _sig(symbol, "A0") if symbol == "NVDA" else None
    )

    r = NearA0Repoller(engine, interval=5.0)
    r._tick()

    assert isinstance(engine._quote_source, DatabentoQuoteSource)
    assert not isinstance(engine._quote_source, FMPQuoteSource)
    assert fake_feed.start_calls == 1  # self-healed feed started, not orphaned
    assert r.metrics()["a0_pushed"] == 1  # NVDA's escalation still reached rt_notify


def test_repoller_explicit_fmp_produces_same_row_shape_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b) Explicit FMP rollback: the re-poller's fetch still
    produces the exact same {symbol: row} shape the pre-fix
    self._client_or_init() -> client.get_stable_batch_quotes() -> per-row
    upper-case-keyed dict used to build -- because the engine's
    FMPQuoteSource._fetch_regular wraps the identical
    get_stable_batch_quotes call, verbatim (see quote_source.py's docstring:
    'a 1:1 extraction of the pre-Task-1.1 inline fetch logic')."""
    monkeypatch.setenv("RT_QUOTE_SOURCE", "fmp")

    class _Client:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def get_stable_batch_quotes(self, symbols: list[str]) -> list[dict[str, Any]]:
            self.calls.append(list(symbols))
            return [{"symbol": s, "price": 101.0, "previousClose": 99.0} for s in symbols]

    client = _Client()
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = client
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "NVDA"}, {"symbol": "PLTR"}, {"symbol": "AMZN"}]
    engine._databento_feed = None
    engine._quote_source = None
    engine._volume_regime = _FakeRegime()
    engine._async_newsstack = None
    active = [_sig("NVDA", "A1"), _sig("PLTR", "A2"), _sig("AMZN", "A1")]
    engine._active_signals = active
    engine._lock = threading.Lock()
    engine.get_active_signals = lambda: list(active)

    r = NearA0Repoller(engine, interval=5.0)
    warm = r._warm_set()
    quotes = r._fetch(warm)

    assert client.calls == [["NVDA", "PLTR", "AMZN"]]
    assert quotes == {
        "NVDA": {"symbol": "NVDA", "price": 101.0, "previousClose": 99.0},
        "PLTR": {"symbol": "PLTR", "price": 101.0, "previousClose": 99.0},
        "AMZN": {"symbol": "AMZN", "price": 101.0, "previousClose": 99.0},
    }
    assert isinstance(engine._quote_source, FMPQuoteSource)
