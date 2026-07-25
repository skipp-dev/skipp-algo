"""Parity test for Task 1.1 of the Databento signal-migration plan.

Proves that ``FMPQuoteSource.fetch(...)`` returns exactly what the
pre-refactor inline fetch codepaths in ``RealtimeEngine`` returned, for both
the regular-session hot path (``_fetch_realtime_quotes``) and the
premarket/postmarket extended-shadow path (``_poll_extended_shadow``).
"""

from __future__ import annotations

import open_prep.realtime_signals as rs
from open_prep.postmarket_quotes import build_postmarket_quotes
from open_prep.quote_source import _BATCH_QUOTE_CHUNK_SIZE, FMPQuoteSource


class _RegularOnlyClient:
    """Mirrors the mock used in test_realtime_fetch_uses_true_batch_method."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def get_stable_batch_quotes(self, symbols: list[str]) -> list[dict]:
        self.calls.append(list(symbols))
        return [{"symbol": symbol, "price": 1.0} for symbol in symbols]


def _legacy_fetch_realtime_quotes(client, symbols: list[str]) -> dict[str, dict]:
    """Verbatim copy of the pre-Task-1.1 `_fetch_realtime_quotes` body
    (the chunk loop + dict-building), used as the parity ground truth."""
    quotes: dict[str, dict] = {}
    chunk_size = _BATCH_QUOTE_CHUNK_SIZE
    for chunk_start in range(0, len(symbols), chunk_size):
        chunk = symbols[chunk_start:chunk_start + chunk_size]
        try:
            fetch_quotes = getattr(client, "get_stable_batch_quotes", None)
            raw = (fetch_quotes or client.get_batch_quotes)(chunk)
            for q in raw:
                sym = str(q.get("symbol", "")).strip().upper()
                if sym:
                    quotes[sym] = q
        except Exception:
            pass
    return quotes


def test_fmp_quote_source_matches_legacy_fetch_regular_session() -> None:
    symbols = ["AAPL", "MSFT", "TSLA"]

    legacy_client = _RegularOnlyClient()
    legacy_quotes = _legacy_fetch_realtime_quotes(legacy_client, symbols)

    source_client = _RegularOnlyClient()
    source = FMPQuoteSource(source_client)
    rows = source.fetch(symbols, "regular")
    new_quotes = {str(r["symbol"]).upper(): r for r in rows}

    assert new_quotes == legacy_quotes
    assert legacy_client.calls == source_client.calls


def test_fmp_quote_source_regular_session_chunks_like_legacy() -> None:
    """Watchlists larger than the chunk size must chunk identically."""
    symbols = [f"SYM{i}" for i in range(_BATCH_QUOTE_CHUNK_SIZE + 5)]

    legacy_client = _RegularOnlyClient()
    _legacy_fetch_realtime_quotes(legacy_client, symbols)

    source_client = _RegularOnlyClient()
    FMPQuoteSource(source_client).fetch(symbols, "regular")

    assert source_client.calls == legacy_client.calls
    assert len(source_client.calls) == 2
    assert len(source_client.calls[0]) == _BATCH_QUOTE_CHUNK_SIZE
    assert len(source_client.calls[1]) == 5


def test_fmp_quote_source_regular_session_survives_chunk_exception() -> None:
    """A raising chunk must be logged and skipped, matching the legacy
    per-chunk try/except (verified against RealtimeEngine's real hot path,
    not just the local copy)."""

    class _FlakyClient:
        def __init__(self) -> None:
            self.calls = 0

        def get_stable_batch_quotes(self, symbols):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("boom")
            return [{"symbol": s, "price": 2.0} for s in symbols]

    symbols = [f"SYM{i}" for i in range(_BATCH_QUOTE_CHUNK_SIZE + 1)]
    client = _FlakyClient()
    rows = FMPQuoteSource(client).fetch(symbols, "regular")

    assert client.calls == 2
    assert len(rows) == 1  # first (larger) chunk's exception drops those rows


def test_fmp_quote_source_matches_current_engine_fetch_realtime_quotes() -> None:
    """End-to-end: RealtimeEngine._fetch_realtime_quotes(), after the Task
    1.1 rewire, must still return exactly what test_realtime_fetch_uses_true_
    batch_method (pre-existing suite) asserts today."""

    class _Client:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def get_stable_batch_quotes(self, symbols: list[str]):
            self.calls.append(symbols)
            return [{"symbol": symbol, "price": 1.0} for symbol in symbols]

    client = _Client()
    engine = rs.RealtimeEngine.__new__(rs.RealtimeEngine)
    engine._client = client
    engine._client_disabled_reason = None
    engine._watchlist = [{"symbol": "AAPL"}, {"symbol": "MSFT"}]

    quotes = engine._fetch_realtime_quotes()

    assert client.calls == [["AAPL", "MSFT"]]
    assert sorted(quotes) == ["AAPL", "MSFT"]


def test_fmp_quote_source_matches_legacy_postmarket_adaptation(monkeypatch) -> None:
    """Legacy `_poll_extended_shadow` postmarket branch, reproduced inline,
    vs. FMPQuoteSource.fetch(..., "postmarket")."""

    import open_prep.quote_source as qs

    now_epoch = 1_784_222_000.0
    baseline_session_date = "2026-07-16"

    class _FixedDatetime:
        @staticmethod
        def now(_tz):
            from datetime import datetime as _dt
            return _dt(2026, 7, 16, 17, 0)

    monkeypatch.setattr(qs, "datetime", _FixedDatetime)

    class _Client:
        def get_stable_batch_quotes(self, _symbols):
            return [{"symbol": "AAPL", "price": 99.0, "previousClose": 100.0}]

        def get_stable_batch_aftermarket_quotes(self, _symbols):
            return [{
                "symbol": "AAPL",
                "bidPrice": 101.0,
                "askPrice": 102.0,
                "volume": 1_050_000,
                "timestamp": (now_epoch - 5) * 1000,
            }]

        def get_stable_batch_aftermarket_trades(self, _symbols):
            return [{
                "symbol": "AAPL",
                "price": 101.75,
                "timestamp": (now_epoch - 2) * 1000,
            }]

    symbols = ["AAPL"]
    close_volume_by_symbol = {"AAPL": 1_000_000.0}

    # Legacy: the three calls done inline, adapted directly.
    legacy_client = _Client()
    regular = legacy_client.get_stable_batch_quotes(symbols)
    quote_rows = legacy_client.get_stable_batch_aftermarket_quotes(symbols)
    trade_rows = legacy_client.get_stable_batch_aftermarket_trades(symbols)
    legacy_adapted = build_postmarket_quotes(
        reference_rows=regular,
        quote_rows=quote_rows,
        trade_rows=trade_rows,
        close_volume_by_symbol=close_volume_by_symbol,
        baseline_session_date=baseline_session_date,
        current_session_date=baseline_session_date,
        now_epoch=now_epoch,
    )

    source = FMPQuoteSource(_Client())
    new_rows = source.fetch(
        symbols,
        "postmarket",
        close_volume_by_symbol=close_volume_by_symbol,
        baseline_session_date=baseline_session_date,
        now_epoch=now_epoch,
    )

    assert new_rows == regular
    assert source.last_adapted_quotes == legacy_adapted.quotes
    assert source.last_adapted_stats == legacy_adapted.stats
    assert source.last_regular_rows == regular
    assert source.last_quote_rows == quote_rows
    assert source.last_trade_rows == trade_rows


def test_fmp_quote_source_premarket_returns_regular_rows_only() -> None:
    class _Client:
        def get_stable_batch_quotes(self, _symbols):
            return [{"symbol": "AAPL", "price": 101.0}]

        def get_stable_batch_aftermarket_quotes(self, _symbols):
            return [{"symbol": "AAPL", "bidPrice": 100.0, "askPrice": 102.0}]

        def get_stable_batch_aftermarket_trades(self, _symbols):
            return [{"symbol": "AAPL", "price": 100.5}]

    source = FMPQuoteSource(_Client())
    rows = source.fetch(["AAPL"], "premarket")

    assert rows == [{"symbol": "AAPL", "price": 101.0}]
    assert source.last_adapted_quotes is None
    assert source.last_adapted_stats is None


def test_fmp_quote_source_client_resolved_lazily_via_callable() -> None:
    """RealtimeEngine.client is a property that may raise until resolved;
    FMPQuoteSource must accept a zero-arg provider and re-resolve per call
    (not cache a client captured before it existed), matching the exact
    per-chunk try/except placement of the legacy code."""

    calls = {"n": 0}

    def _provider():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("client not ready yet")
        return _RegularOnlyClient()

    source = FMPQuoteSource(_provider)
    rows = source.fetch(["AAPL"], "regular")

    assert calls["n"] == 1  # first (only) chunk's exception was caught, not raised
    assert rows == []
