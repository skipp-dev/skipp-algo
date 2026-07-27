"""Producer quote-reference coverage test for the full open_prep production
universe.

Task 0.2 (Databento signal migration). The A0-Fast bootstrap reference
(``services/a0_fast_detector/bootstrap/a0-reference.json``) is scoped to a
micro-cap symbol population and is deliberately Databento-source-pure (see
``services/a0_fast_detector/README.md``). This test instead proves the
STANDALONE producer reference in ``open_prep/quote_reference.py`` builds
``previous_close`` + ``average_daily_volume`` for the full liquid open_prep
candidate universe the realtime producer monitors (``DEFAULT_TOP_N=0`` =
ALL, ~900 symbols) -- the interface Task 1.3's ``DatabentoQuoteSource`` will
consume.

2026-07-25 decoupling decision: this module is fully independent of
``services/a0_fast_detector`` -- it does not import ``StreamReference``,
``open_prep.a0_reference``, or ``open_prep.a0_stream_state``, and it writes
its own artifact at its own path (``artifacts/open_prep/latest/
quote_reference.json``), never ``A0_FAST_REFERENCE_FILE``. prev_close/ADV
are sourced from FMP's adjusted EOD history (``FMPClient.
get_historical_price_eod_full`` -> ``/stable/historical-price-eod/full``) --
daily values, not latency-critical, and FMP delivers split/dividend-adjusted
prices unlike a raw Databento ``ohlcv-1d`` bar. Only the live intraday bars
stay Databento. Fixtures below use the real ``historical-price-eod/full``
response shape (both the bare-list and the ``{"historical": [...]}``-wrapped
variant this repo's other call sites already handle) -- no live network
access, no real API keys.
"""

from __future__ import annotations

import json

import pytest

from open_prep.quote_reference import (
    DEFAULT_OUTPUT_PATH,
    QuoteReference,
    QuoteReferenceRow,
    build_quote_reference_for_universe,
    extract_candidate_symbols_from_open_prep_run,
    fmp_eod_response_to_bars,
    write_quote_reference_file,
)

# Liquid, large-cap production-universe names -- deliberately NOT the
# micro-cap-only symbols the A0-Fast bootstrap file's process targets.
_PRODUCER_UNIVERSE_SYMBOLS = ["AAPL", "NVDA", "SPY", "TSLA", "MSFT"]

_LOOKBACK_SESSIONS = 15
_AS_OF_SESSION = "2026-07-24"


def _fixture_fmp_eod_response(symbol: str, symbol_index: int) -> list[dict[str, object]]:
    """Recorded-shape ``/stable/historical-price-eod/full`` response rows for
    one symbol: 16 prior sessions (>= lookback_sessions + 1), all < as_of,
    with monotonically increasing adjusted close/volume. Field shape mirrors
    the real FMP stable EOD response (date, open, high, low, close, volume,
    change, changePercent, vwap) as already consumed elsewhere in this repo
    (``open_prep/run_open_prep.py::_fetch_symbol_atr``,
    ``open_prep/market_microstructure.py::_fetch_eod_closes``)."""
    session_dates = [f"2026-07-{day:02d}" for day in range(1, 17)]  # 16 sessions, all < as_of_session
    base_price = 50.0 + symbol_index * 25.0
    base_volume = 1_000_000 + symbol_index * 500_000
    rows = []
    for day_index, session_date in enumerate(session_dates):
        close = base_price + day_index * 0.2
        rows.append(
            {
                "symbol": symbol,
                "date": session_date,
                "open": base_price + day_index * 0.1,
                "high": base_price + day_index * 0.1 + 1.0,
                "low": base_price + day_index * 0.1 - 1.0,
                "close": close,
                "volume": base_volume + day_index * 1_000,
                "change": 0.2,
                "changePercent": 0.4,
                "vwap": close,
            }
        )
    return rows


def _fixture_bars_by_symbol() -> dict[str, list]:
    bars_by_symbol: dict[str, list] = {}
    for symbol_index, symbol in enumerate(_PRODUCER_UNIVERSE_SYMBOLS):
        # Alternate response shape per symbol to prove both the bare-list AND
        # the {"historical": [...]}-wrapped variant are parsed identically --
        # FMPClient.get_historical_price_eod_full can return either.
        rows = _fixture_fmp_eod_response(symbol, symbol_index)
        response: list | dict = {"historical": rows} if symbol_index % 2 == 0 else rows
        bars_by_symbol[symbol] = fmp_eod_response_to_bars(symbol, response)
    return bars_by_symbol


def test_reference_covers_producer_universe() -> None:
    """Given the candidate list + an FMP adjusted-EOD fixture, the built
    reference yields previous_close>0 and average_daily_volume>0 for every
    symbol in the full liquid producer universe (brief Step 1)."""
    bars_by_symbol = _fixture_bars_by_symbol()

    rows_by_symbol, skipped = build_quote_reference_for_universe(
        _PRODUCER_UNIVERSE_SYMBOLS,
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
    )

    assert skipped == []
    assert set(rows_by_symbol.keys()) == set(_PRODUCER_UNIVERSE_SYMBOLS)
    for row in rows_by_symbol.values():
        assert row.previous_close > 0
        assert row.average_daily_volume > 0
        assert row.source == "fmp:adjusted-eod"
        assert row.as_of_session  # non-empty ISO date string


def test_reference_skips_symbols_with_insufficient_history() -> None:
    """A candidate symbol with no fetched EOD bars is omitted (not
    fabricated) rather than emitted with a zero/garbage row."""
    bars_by_symbol = _fixture_bars_by_symbol()

    rows_by_symbol, skipped = build_quote_reference_for_universe(
        [*_PRODUCER_UNIVERSE_SYMBOLS, "NODATA"],
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
    )

    assert skipped == ["NODATA"]
    assert set(rows_by_symbol.keys()) == set(_PRODUCER_UNIVERSE_SYMBOLS)


def test_fmp_eod_response_to_bars_handles_list_and_historical_wrapped_shapes() -> None:
    """FMPClient.get_historical_price_eod_full can return either a bare list
    or {"historical": [...]} (both observed at existing call sites in this
    repo) -- both must parse identically, reading ``close``/``volume``/``date``
    (NOT ``adjClose`` -- see module docstring "FMP field verification")."""
    rows = _fixture_fmp_eod_response("AAPL", 0)

    from_list = fmp_eod_response_to_bars("AAPL", rows)
    from_dict = fmp_eod_response_to_bars("AAPL", {"historical": rows})

    assert len(from_list) == len(rows) == len(from_dict)
    assert all(bar.source == "fmp:adjusted-eod" for bar in from_list)
    assert [bar.close for bar in from_list] == [bar.close for bar in from_dict]
    assert [bar.volume for bar in from_list] == [bar.volume for bar in from_dict]
    assert from_list[-1].close == rows[-1]["close"]
    assert from_list[-1].session_date == rows[-1]["date"]


def test_extract_candidate_symbols_merges_ranked_overflow_and_quotes() -> None:
    """Mirrors open_prep.realtime_signals._load_watchlist's DEFAULT_TOP_N=0
    (ALL) merge: ranked_v2 + filtered_out_v2 rows scoped only by
    below_top_n_cutoff + any symbol seen in enriched_quotes -- the full
    ~900-symbol production universe, not the ranked-only top slice."""
    payload = {
        "ranked_v2": [{"symbol": "AAPL"}, {"symbol": "nvda"}],
        "filtered_out_v2": [
            {"symbol": "MSFT", "filter_reasons": ["below_top_n_cutoff"]},
            {"symbol": "PENNY", "filter_reasons": ["price_floor"]},
        ],
        "enriched_quotes": [{"symbol": "spy"}, {"symbol": "AAPL"}],
    }
    symbols = extract_candidate_symbols_from_open_prep_run(payload)
    assert symbols == ["AAPL", "NVDA", "MSFT", "SPY"]


def test_quote_reference_loader_round_trips_artifact(tmp_path) -> None:
    """The QuoteReference loader -- the interface Task 1.3's
    DatabentoQuoteSource consumes -- round-trips write_quote_reference_file's
    artifact and serves previous_close()/average_daily_volume() per symbol,
    with no Databento-purity gate and no dependency on a0_fast machinery."""
    bars_by_symbol = _fixture_bars_by_symbol()
    rows_by_symbol, _skipped = build_quote_reference_for_universe(
        _PRODUCER_UNIVERSE_SYMBOLS,
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
    )
    artifact_path = tmp_path / "quote_reference.json"
    write_quote_reference_file(rows_by_symbol, artifact_path)

    reference = QuoteReference.load(artifact_path)

    assert len(reference) == len(_PRODUCER_UNIVERSE_SYMBOLS)
    for symbol in _PRODUCER_UNIVERSE_SYMBOLS:
        assert symbol in reference
        assert reference.previous_close(symbol) == rows_by_symbol[symbol].previous_close
        assert reference.average_daily_volume(symbol) == rows_by_symbol[symbol].average_daily_volume
    # Missing symbol: served as None, not a fabricated/zero row and not a KeyError.
    assert "DOESNOTEXIST" not in reference
    assert reference.previous_close("DOESNOTEXIST") is None
    assert reference.average_daily_volume("DOESNOTEXIST") is None


def test_default_output_path_is_producer_owned_not_a0_fast() -> None:
    """The artifact path must be its own, distinct from
    services/a0_fast_detector/bootstrap/a0-reference.json, so the A0-Fast
    worker's _load_references() never loads it."""
    assert "a0_fast_detector" not in str(DEFAULT_OUTPUT_PATH)
    assert "a0-reference.json" not in str(DEFAULT_OUTPUT_PATH)
    assert str(DEFAULT_OUTPUT_PATH) == "artifacts/open_prep/latest/quote_reference.json"


def test_reload_rereads_artifact_from_the_load_path(tmp_path) -> None:
    """``reload()`` re-reads the same path ``load()`` used, so a new session's
    out-of-band rewrite is picked up without knowing the path at the call
    site."""
    path = tmp_path / "quote_reference.json"
    path.write_text(
        json.dumps({"AAPL": {"previous_close": 100.0, "average_daily_volume": 2_000_000.0,
                             "as_of_session": "2026-07-24", "source": "fmp:adjusted-eod"}}),
        encoding="utf-8",
    )
    reference = QuoteReference.load(path)
    assert reference.previous_close("AAPL") == 100.0

    path.write_text(
        json.dumps({"AAPL": {"previous_close": 105.0, "average_daily_volume": 2_500_000.0,
                             "as_of_session": "2026-07-25", "source": "fmp:adjusted-eod"}}),
        encoding="utf-8",
    )
    reloaded = reference.reload()
    assert reloaded.previous_close("AAPL") == 105.0
    assert reloaded.average_daily_volume("AAPL") == 2_500_000.0
    # reload() returns a fresh instance; the original is left untouched.
    assert reference.previous_close("AAPL") == 100.0


def test_reload_without_source_path_raises() -> None:
    """A directly-constructed reference (no ``load()``) has no path to reload
    from -- raise rather than silently return an empty/garbage reference."""
    reference = QuoteReference({"AAPL": QuoteReferenceRow(
        previous_close=100.0, average_daily_volume=2_000_000.0,
        as_of_session="2026-07-24", source="fmp:adjusted-eod",
    )})
    with pytest.raises(ValueError):
        reference.reload()
