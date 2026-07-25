"""Unit tests for ``DatabentoQuoteSource`` (Task 1.3 of the Databento
signal-migration plan).

Drives ``DatabentoQuoteSource`` with a fake ``DatabentoQuoteFeed`` (canned
``BarState``/cumulative-volume/session-hi-lo, no real feed, no network, no
threads) plus a fixture ``QuoteReference``, and proves the resulting rows
satisfy the Task 0.1 FMP quote-row contract (``docs/
databento_quote_row_contract.md``) including the ``avgVolume`` field FMP's
batch-quote endpoint omits. The FMP-vs-Databento signal-parity test lives in
``tests/test_quote_source_parity.py`` alongside the rest of Task 1.1's parity
coverage.
"""

from __future__ import annotations

from open_prep.databento_quote_feed import BarState
from open_prep.quote_reference import QuoteReference, QuoteReferenceRow
from open_prep.quote_source import DatabentoQuoteSource


class _FakeDatabentoQuoteFeed:
    """Duck-typed stand-in for ``DatabentoQuoteFeed``: same three read
    methods (``latest_bar``, ``cumulative_volume``, ``session_high_low``),
    backed by plain dicts instead of a live thread-safe cache."""

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
        session_high: float | None,
        session_low: float | None,
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


def _bar(
    symbol: str = "AAPL",
    *,
    close: float = 101.5,
    open_: float = 100.0,
    high: float = 102.0,
    low: float = 99.5,
    volume: int = 5_000,
    ts_event: float = 1_784_642_400.0,
    ts_recv: float = 1_784_642_400.25,
) -> BarState:
    return BarState(
        symbol=symbol,
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        ts_event=ts_event,
        ts_recv=ts_recv,
    )


def _reference(rows: dict[str, QuoteReferenceRow]) -> QuoteReference:
    return QuoteReference(rows)


def _reference_row(
    *,
    previous_close: float = 100.0,
    average_daily_volume: float = 2_000_000.0,
    as_of_session: str = "2026-07-24",
) -> QuoteReferenceRow:
    return QuoteReferenceRow(
        previous_close=previous_close,
        average_daily_volume=average_daily_volume,
        as_of_session=as_of_session,
        source="fmp:adjusted-eod",
    )


def test_databento_source_row_matches_contract() -> None:
    """Step 1/RED->GREEN: a cache hit + reference hit builds a full,
    contract-conformant row, including ``avgVolume`` (unlike FMP)."""
    feed = _FakeDatabentoQuoteFeed()
    feed.set_symbol(
        "AAPL",
        bar=_bar(close=101.5, ts_event=1_784_642_400.0, ts_recv=1_784_642_400.25),
        cumulative_volume=123_456,
        session_high=102.75,
        session_low=99.0,
    )
    reference = _reference({"AAPL": _reference_row(previous_close=100.0, average_daily_volume=2_000_000.0)})

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["AAPL"], "regular")

    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == "AAPL"
    assert row["price"] == 101.5
    assert row["lastPrice"] == 101.5
    assert row["previousClose"] == 100.0
    assert row["volume"] == 123_456
    assert row["avgVolume"] == 2_000_000.0  # present -- FMP batch-quote omits this
    assert row["timestamp"] == 1_784_642_400.0
    assert row["received_at"] == 1_784_642_400.25
    assert row["dayHigh"] == 102.75
    assert row["dayLow"] == 99.0
    assert row["source"] == "databento"
    assert row["changesPercentage"] == 1.5


def test_databento_source_normalizes_symbol_case() -> None:
    feed = _FakeDatabentoQuoteFeed()
    feed.set_symbol("AAPL", bar=_bar(), cumulative_volume=1_000, session_high=102.0, session_low=99.0)
    reference = _reference({"AAPL": _reference_row()})

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["aapl"], "regular")

    assert len(rows) == 1
    assert rows[0]["symbol"] == "AAPL"


def test_databento_source_omits_symbol_with_no_cached_bar() -> None:
    """Fail-closed: a symbol never seen by the feed (no bar yet) is omitted,
    never emitted with a fabricated/None price."""
    feed = _FakeDatabentoQuoteFeed()
    reference = _reference({"AAPL": _reference_row()})

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["AAPL"], "regular")

    assert rows == []


def test_databento_source_omits_symbol_with_no_reference_entry() -> None:
    """Fail-closed: a symbol with a live bar but no daily reference row
    (previousClose/avgVolume) is omitted, never emitted with a stale/zero
    previousClose."""
    feed = _FakeDatabentoQuoteFeed()
    feed.set_symbol("AAPL", bar=_bar(), cumulative_volume=1_000, session_high=102.0, session_low=99.0)
    reference = _reference({})  # no AAPL entry

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["AAPL"], "regular")

    assert rows == []


def test_databento_source_mixed_universe_only_emits_complete_rows() -> None:
    """One symbol has both bar+reference, one is missing a bar, one is
    missing a reference row -- only the complete one survives."""
    feed = _FakeDatabentoQuoteFeed()
    feed.set_symbol("AAPL", bar=_bar("AAPL"), cumulative_volume=1_000, session_high=102.0, session_low=99.0)
    feed.set_symbol("TSLA", bar=_bar("TSLA"), cumulative_volume=2_000, session_high=200.0, session_low=190.0)
    # MSFT: never fed a bar.
    reference = _reference({
        "AAPL": _reference_row(),
        # TSLA: no reference row.
        "MSFT": _reference_row(),
    })

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["AAPL", "TSLA", "MSFT"], "regular")

    assert [row["symbol"] for row in rows] == ["AAPL"]


def test_databento_source_no_symbols_returns_empty_list() -> None:
    feed = _FakeDatabentoQuoteFeed()
    reference = _reference({})
    source = DatabentoQuoteSource(feed, reference)

    assert source.fetch([], "regular") == []
