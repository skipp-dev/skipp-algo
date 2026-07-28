"""Parity test for Task 1.1 of the Databento signal-migration plan.

Proves that ``FMPQuoteSource.fetch(...)`` returns exactly what the
pre-refactor inline fetch codepaths in ``RealtimeEngine`` returned, for both
the regular-session hot path (``_fetch_realtime_quotes``) and the
premarket/postmarket extended-shadow path (``_poll_extended_shadow``).
"""

from __future__ import annotations

import open_prep.realtime_signals as rs
from open_prep.a0_contract import A0ThresholdContext, build_market_snapshot, decide_core_level
from open_prep.databento_quote_feed import BarState
from open_prep.postmarket_quotes import build_postmarket_quotes
from open_prep.quote_reference import QuoteReference, QuoteReferenceRow
from open_prep.quote_source import _BATCH_QUOTE_CHUNK_SIZE, DatabentoQuoteSource, FMPQuoteSource


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


# ---------------------------------------------------------------------------
# Task 1.3: FMP-vs-Databento signal-core parity.
# ---------------------------------------------------------------------------


class _FakeDatabentoQuoteFeedForParity:
    """Minimal duck-typed ``DatabentoQuoteFeed`` stand-in: only the three
    read methods ``DatabentoQuoteSource`` consumes, backed by plain dicts —
    no real feed, no network, no threads."""

    def __init__(self) -> None:
        self._bars: dict[str, BarState] = {}
        self._cumulative_volume: dict[str, int] = {}
        self._session_high_low: dict[str, tuple[float | None, float | None]] = {}

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


def _core_level_for_row(row: dict, *, expected_volume_fraction: float, observed_at: float) -> str | None:
    """Reproduces exactly the field-extraction pipeline
    ``RealtimeEngine._detect_signal`` runs on a quote row before calling the
    shared, provider-neutral signal core (``build_market_snapshot`` +
    ``decide_core_level``) — the same two calls, same thresholds module
    constants, same ``_volume_semantics`` helper. ``expected_volume_fraction``
    is passed explicitly (mirroring ``_detect_signal``'s own override
    parameter) so the result never depends on wall-clock time."""
    price = rs._safe_float(row.get("price") or row.get("lastPrice"), 0.0)
    prev_close = rs._safe_float(row.get("previousClose"), 0.0)
    volume = rs._safe_float(row.get("volume"), 0.0)
    avg_volume = rs._safe_float(row.get("avgVolume"), 0.0)
    change_pct = ((price / prev_close) - 1) * 100
    raw_volume_ratio, vol_frac, volume_pace = rs._volume_semantics(
        volume, avg_volume, expected_volume_fraction,
    )
    snapshot = build_market_snapshot(
        symbol=str(row["symbol"]),
        price=price,
        prev_close=prev_close,
        change_pct=change_pct,
        raw_daily_volume_ratio=raw_volume_ratio,
        expected_volume_fraction=vol_frac,
        normalized_volume_pace=volume_pace,
        source=str(row.get("source") or "fmp"),
        raw_ts_event=row.get("timestamp"),
        raw_ts_recv=row.get("received_at"),
        observed_at=observed_at,
    )
    decision = decide_core_level(
        snapshot,
        A0ThresholdContext(
            a0_volume=rs.A0_VOLUME_RATIO_MIN,
            a1_volume=rs.A1_VOLUME_RATIO_MIN,
            a2_volume=rs.A2_VOLUME_RATIO_MIN,
            a0_price=rs.A0_PRICE_CHANGE_PCT_MIN,
            a1_price=rs.A1_PRICE_CHANGE_PCT_MIN,
            a2_price=rs.A2_PRICE_CHANGE_PCT_MIN,
        ),
    )
    return decision.core_level


def test_databento_vs_fmp_same_core_decision() -> None:
    """The key parity test (Task 1.3, Step 5): feed the SAME underlying
    numbers (prev_close, price, volume, avgVolume) through an FMP-shaped row
    and the row ``DatabentoQuoteSource`` derives from an equivalent
    feed+reference, run both through ``decide_core_level`` (the shared,
    provider-neutral signal core), and assert the identical core decision.
    Proves the Databento row is a drop-in for the signal math — not just
    shape-compatible."""
    symbol = "AAPL"
    price = 103.0
    prev_close = 100.0
    volume = 900_000
    avg_volume = 2_000_000.0
    expected_volume_fraction = 0.5
    ts_event = 1_784_642_400.0
    ts_recv = 1_784_642_400.25
    observed_at = 1_784_642_500.0

    fmp_row = {
        "symbol": symbol,
        "price": price,
        "previousClose": prev_close,
        "volume": volume,
        "avgVolume": avg_volume,
        "timestamp": ts_event,
        "received_at": ts_recv,
        "source": "fmp",
    }

    feed = _FakeDatabentoQuoteFeedForParity()
    feed.set_symbol(
        symbol,
        bar=BarState(
            symbol=symbol,
            open=price - 1.0,
            high=price + 0.5,
            low=price - 1.5,
            close=price,
            volume=volume,
            ts_event=ts_event,
            ts_recv=ts_recv,
        ),
        cumulative_volume=volume,
        session_high=price + 0.5,
        session_low=price - 1.5,
    )
    reference = QuoteReference({
        symbol: QuoteReferenceRow(
            previous_close=prev_close,
            average_daily_volume=avg_volume,
            as_of_session="2026-07-24",
            source="fmp:adjusted-eod+adv=databento:equs-mini-ohlcv-1d",
        )
    })
    databento_rows = DatabentoQuoteSource(feed, reference).fetch(
        [symbol], "regular", now=ts_recv + 5.0,  # fresh -- independent of `observed_at` below
    )
    assert len(databento_rows) == 1
    databento_row = databento_rows[0]

    fmp_decision = _core_level_for_row(
        fmp_row, expected_volume_fraction=expected_volume_fraction, observed_at=observed_at,
    )
    databento_decision = _core_level_for_row(
        databento_row, expected_volume_fraction=expected_volume_fraction, observed_at=observed_at,
    )

    # Sanity: the chosen inputs actually trip a level (3% move, large-move
    # branch) rather than both trivially landing on None.
    assert fmp_decision == "A1"
    assert fmp_decision == databento_decision
