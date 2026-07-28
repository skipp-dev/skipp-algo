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

import json

import pytest

from open_prep.databento_quote_feed import BarState
from open_prep.quote_reference import DATABENTO_ADV_SOURCE, QuoteReference, QuoteReferenceRow
from open_prep.quote_source import (
    _DEFAULT_MAX_BAR_AGE_SECS,
    DatabentoQuoteSource,
    _resolve_max_bar_age_secs,
)


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
    source: str = f"fmp:adjusted-eod+adv={DATABENTO_ADV_SOURCE}",
) -> QuoteReferenceRow:
    return QuoteReferenceRow(
        previous_close=previous_close,
        average_daily_volume=average_daily_volume,
        as_of_session=as_of_session,
        source=source,
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
    rows = source.fetch(["AAPL"], "regular", now=1_784_642_405.0)  # 4.75s after ts_recv -- fresh

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
    rows = source.fetch(["aapl"], "regular", now=1_784_642_405.0)  # fresh

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
    rows = source.fetch(["AAPL"], "regular", now=1_784_642_405.0)  # fresh -- omission is reference-driven, not staleness-driven

    assert rows == []


def test_databento_source_omits_reference_with_consolidated_adv(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """EQUS.MINI cumulative volume must never be divided by an FMP
    consolidated ADV. A mismatched row is omitted while a venue-consistent
    sibling in the same fetch remains available."""
    feed = _FakeDatabentoQuoteFeed()
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL"), cumulative_volume=96_300,
        session_high=102.0, session_low=99.0,
    )
    feed.set_symbol(
        "MSFT", bar=_bar("MSFT"), cumulative_volume=110_000,
        session_high=102.0, session_low=99.0,
    )
    reference = _reference({
        "AAPL": _reference_row(
            average_daily_volume=2_750_000.0,
            source="fmp:adjusted-eod",
        ),
        "MSFT": _reference_row(average_daily_volume=110_000.0),
    })

    source = DatabentoQuoteSource(feed, reference)
    rows = source.fetch(["AAPL", "MSFT"], "regular", now=1_784_642_405.0)
    source.fetch(["AAPL", "MSFT"], "regular", now=1_784_642_406.0)

    assert [row["symbol"] for row in rows] == ["MSFT"]
    assert caplog.text.count("rejected incompatible ADV provenance") == 1
    assert "fmp:adjusted-eod" in caplog.text


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
    rows = source.fetch(["AAPL", "TSLA", "MSFT"], "regular", now=1_784_642_405.0)  # fresh

    assert [row["symbol"] for row in rows] == ["AAPL"]


def test_databento_source_no_symbols_returns_empty_list() -> None:
    feed = _FakeDatabentoQuoteFeed()
    reference = _reference({})
    source = DatabentoQuoteSource(feed, reference)

    assert source.fetch([], "regular") == []


# ---------------------------------------------------------------------------
# Bounded-age staleness guard (final-review Finding 3): a dead feed keeps
# `latest_bar`/`cumulative_volume` returning the LAST CACHED entry forever
# (nothing purges the cache on a circuit-breaker trip -- see
# ``DatabentoQuoteFeed._run_feed_loop``), so without this guard `fetch()`
# would keep emitting a frozen price/volume row with no signal reaching the
# producer's `data_stale` clock. The guard omits any symbol whose bar has
# aged past ``max_bar_age_secs``, exactly like the existing no-bar/no-
# reference fail-closed omissions above.
# ---------------------------------------------------------------------------


def test_databento_source_omits_stale_symbol_but_keeps_fresh_one_in_same_call() -> None:
    """(a) A symbol whose latest bar ``ts_recv`` is older than
    ``max_bar_age_secs`` is OMITTED; a fresh symbol in the SAME ``fetch()``
    call is still included."""
    feed = _FakeDatabentoQuoteFeed()
    stale_ts_recv = 1_784_642_400.25
    fresh_ts_recv = 1_784_642_400.25 + 195.0  # arrives 195s after the stale bar
    feed.set_symbol(
        "AAPL",
        bar=_bar("AAPL", ts_event=stale_ts_recv - 0.25, ts_recv=stale_ts_recv),
        cumulative_volume=1_000,
        session_high=102.0,
        session_low=99.0,
    )
    feed.set_symbol(
        "MSFT",
        bar=_bar("MSFT", ts_event=fresh_ts_recv - 0.25, ts_recv=fresh_ts_recv),
        cumulative_volume=2_000,
        session_high=210.0,
        session_low=205.0,
    )
    reference = _reference({"AAPL": _reference_row(), "MSFT": _reference_row()})

    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=60.0)
    now = fresh_ts_recv + 5.0  # AAPL age = 200s (> 60s, stale); MSFT age = 5s (fresh)
    rows = source.fetch(["AAPL", "MSFT"], "regular", now=now)

    assert [row["symbol"] for row in rows] == ["MSFT"]


def test_databento_source_dead_feed_returns_empty_fetch() -> None:
    """(b) Dead-feed scenario: the circuit breaker tripped and every cached
    bar has aged well past ``max_bar_age_secs`` (nothing refreshes the
    cache), so ``fetch()`` returns an EMPTY list for the whole universe --
    this is precisely what stops the producer's ``_last_data_epoch`` from
    advancing (``realtime_signals.py`` only stamps it on a non-empty fetch)
    and lets the ``data_stale`` gauge fire after ``DATA_STALL_SECONDS``."""
    feed = _FakeDatabentoQuoteFeed()
    stale_ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=stale_ts_recv),
        cumulative_volume=1_000, session_high=102.0, session_low=99.0,
    )
    feed.set_symbol(
        "MSFT", bar=_bar("MSFT", ts_recv=stale_ts_recv),
        cumulative_volume=2_000, session_high=210.0, session_low=205.0,
    )
    reference = _reference({"AAPL": _reference_row(), "MSFT": _reference_row()})

    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=90.0)
    now = stale_ts_recv + 600.0  # feed has been dead for 10 minutes
    rows = source.fetch(["AAPL", "MSFT"], "regular", now=now)

    assert rows == []


def test_databento_source_emits_bar_within_max_age() -> None:
    """(c) A bar within ``max_bar_age_secs`` is still emitted normally."""
    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=ts_recv),
        cumulative_volume=1_000, session_high=102.0, session_low=99.0,
    )
    reference = _reference({"AAPL": _reference_row()})

    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=90.0)
    now = ts_recv + 30.0  # well within the 90s budget
    rows = source.fetch(["AAPL"], "regular", now=now)

    assert [row["symbol"] for row in rows] == ["AAPL"]


def test_databento_source_max_bar_age_defaults_when_unset(monkeypatch) -> None:
    """No explicit ``max_bar_age_secs`` and no env override -> the built-in
    default (90s) applies: a bar 89s old survives, one at 91s does not."""
    monkeypatch.delenv("DATABENTO_QUOTE_MAX_BAR_AGE_SECS", raising=False)
    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=ts_recv),
        cumulative_volume=1_000, session_high=102.0, session_low=99.0,
    )
    reference = _reference({"AAPL": _reference_row()})
    source = DatabentoQuoteSource(feed, reference)

    assert source.fetch(["AAPL"], "regular", now=ts_recv + 89.0) != []
    assert source.fetch(["AAPL"], "regular", now=ts_recv + 91.0) == []


def test_databento_source_max_bar_age_env_override(monkeypatch) -> None:
    """``DATABENTO_QUOTE_MAX_BAR_AGE_SECS`` overrides the built-in default
    when the constructor isn't given an explicit value."""
    monkeypatch.setenv("DATABENTO_QUOTE_MAX_BAR_AGE_SECS", "30")
    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=ts_recv),
        cumulative_volume=1_000, session_high=102.0, session_low=99.0,
    )
    reference = _reference({"AAPL": _reference_row()})
    source = DatabentoQuoteSource(feed, reference)

    assert source.fetch(["AAPL"], "regular", now=ts_recv + 20.0) != []
    assert source.fetch(["AAPL"], "regular", now=ts_recv + 40.0) == []  # would pass the 90s default, fails the 30s override


# ---------------------------------------------------------------------------
# Hardening: reject an invalid max-bar-age env override (a non-positive value
# would age EVERY bar out on arrival -> fail-close the whole feed; a NaN/inf
# would disable the staleness guard entirely -> frozen prices served forever).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["-5", "0", "-0.1", "abc", "nan", "inf", "-inf", ""])
def test_resolve_max_bar_age_rejects_invalid_env(monkeypatch, bad) -> None:
    monkeypatch.setenv("DATABENTO_QUOTE_MAX_BAR_AGE_SECS", bad)
    assert _resolve_max_bar_age_secs(None) == _DEFAULT_MAX_BAR_AGE_SECS


def test_resolve_max_bar_age_accepts_positive_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABENTO_QUOTE_MAX_BAR_AGE_SECS", "45.5")
    assert _resolve_max_bar_age_secs(None) == 45.5


def test_resolve_max_bar_age_explicit_value_bypasses_env(monkeypatch) -> None:
    monkeypatch.setenv("DATABENTO_QUOTE_MAX_BAR_AGE_SECS", "45")
    assert _resolve_max_bar_age_secs(120.0) == 120.0


# ---------------------------------------------------------------------------
# Hardening: daily reference reload -- pick up a rewritten artifact (a new
# session's previous_close/ADV) without a producer restart, fail-soft.
# ---------------------------------------------------------------------------


def _write_reference_artifact(
    path,
    *,
    previous_close,
    average_daily_volume,
    as_of_session,
    source=f"fmp:adjusted-eod+adv={DATABENTO_ADV_SOURCE}",
) -> None:
    path.write_text(
        json.dumps(
            {
                "AAPL": {
                    "previous_close": previous_close,
                    "average_daily_volume": average_daily_volume,
                    "as_of_session": as_of_session,
                    "source": source,
                }
            }
        ),
        encoding="utf-8",
    )


def test_reload_reference_picks_up_rewritten_artifact(tmp_path) -> None:
    path = tmp_path / "quote_reference.json"
    _write_reference_artifact(path, previous_close=100.0, average_daily_volume=2_000_000.0, as_of_session="2026-07-24")
    reference = QuoteReference.load(path)

    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", close=110.0, ts_recv=ts_recv),
        cumulative_volume=1_000, session_high=111.0, session_low=99.0,
    )
    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=1e9)

    assert source.fetch(["AAPL"], "regular", now=ts_recv)[0]["previousClose"] == 100.0

    # Out-of-band daily rebuild rewrites the artifact with the new session's row.
    _write_reference_artifact(path, previous_close=105.0, average_daily_volume=2_500_000.0, as_of_session="2026-07-25")
    assert source.reload_reference() is True

    row = source.fetch(["AAPL"], "regular", now=ts_recv)[0]
    assert row["previousClose"] == 105.0
    assert row["avgVolume"] == 2_500_000.0


def test_reload_reference_failsoft_keeps_current_on_missing_artifact(tmp_path) -> None:
    path = tmp_path / "quote_reference.json"
    _write_reference_artifact(path, previous_close=100.0, average_daily_volume=2_000_000.0, as_of_session="2026-07-24")
    reference = QuoteReference.load(path)

    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=ts_recv),
        cumulative_volume=1_000, session_high=111.0, session_low=99.0,
    )
    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=1e9)

    path.unlink()  # artifact removed between rebuilds
    assert source.reload_reference() is False
    # Old reference kept, NOT cleared to empty (which would fail-close AAPL).
    assert source.fetch(["AAPL"], "regular", now=ts_recv)[0]["previousClose"] == 100.0


def test_reload_reference_failsoft_on_directly_constructed_reference() -> None:
    # _reference() builds QuoteReference(rows) directly -> no source path.
    source = DatabentoQuoteSource(_FakeDatabentoQuoteFeed(), _reference({"AAPL": _reference_row()}))
    assert source.reload_reference() is False


def test_reload_to_consolidated_adv_reference_fails_closed(tmp_path) -> None:
    path = tmp_path / "quote_reference.json"
    _write_reference_artifact(
        path,
        previous_close=100.0,
        average_daily_volume=100_000.0,
        as_of_session="2026-07-24",
    )
    reference = QuoteReference.load(path)
    feed = _FakeDatabentoQuoteFeed()
    ts_recv = 1_784_642_400.25
    feed.set_symbol(
        "AAPL", bar=_bar("AAPL", ts_recv=ts_recv),
        cumulative_volume=100_000, session_high=111.0, session_low=99.0,
    )
    source = DatabentoQuoteSource(feed, reference, max_bar_age_secs=1e9)
    assert source.fetch(["AAPL"], "regular", now=ts_recv)

    _write_reference_artifact(
        path,
        previous_close=101.0,
        average_daily_volume=2_750_000.0,
        as_of_session="2026-07-25",
        source="fmp:adjusted-eod",
    )
    assert source.reload_reference() is True
    assert source.fetch(["AAPL"], "regular", now=ts_recv) == []
