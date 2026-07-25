"""Reference-file coverage test for the full open_prep production universe.

Task 0.2 (Databento signal migration). The A0-Fast bootstrap reference today
(``services/a0_fast_detector/bootstrap/a0-reference.json``) is scoped to a
micro-cap symbol population, not the full open_prep production candidate
universe. This test proves the parametrized generator in
``scripts/build_a0_reference.py`` instead builds ``previous_close`` +
``average_daily_volume`` for the full liquid open_prep candidate universe the
realtime producer monitors (``DEFAULT_TOP_N=0`` = ALL, ~900 symbols).

2026-07-25 fix (Option A): prev_close/ADV are sourced from FMP's adjusted EOD
history (``FMPClient.get_historical_price_eod_full`` ->
``/stable/historical-price-eod/full``), NOT Databento daily bars -- a
Databento ``ohlcv-1d`` bar on EQUS.MINI is raw/unadjusted for corporate
actions, so the prior Databento-sourced implementation's
``corporate_action_adjusted=True`` label was factually wrong. Only the live
intraday bars remain Databento. Fixtures below use the real
``historical-price-eod/full`` response shape (both the bare-list and the
``{"historical": [...]}``-wrapped variant this repo's other call sites
already handle) -- no live network access, no real API keys.
"""

from __future__ import annotations

from scripts.build_a0_reference import (
    build_reference_for_universe,
    extract_candidate_symbols_from_open_prep_run,
    fmp_eod_response_to_bars,
)

# Liquid, large-cap production-universe names -- deliberately NOT the
# micro-cap-only symbols the existing bootstrap file's process targets.
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

    references, skipped = build_reference_for_universe(
        _PRODUCER_UNIVERSE_SYMBOLS,
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
        reference_version="fmp-bootstrap-test",
    )

    assert skipped == []
    assert {reference.symbol for reference in references} == set(_PRODUCER_UNIVERSE_SYMBOLS)
    for reference in references:
        assert reference.previous_close > 0
        assert reference.average_daily_volume > 0
        assert reference.source == "fmp:adjusted-eod"
        assert reference.corporate_action_version == "fmp-adjusted-eod-v1"
        assert reference.lookback_sessions == _LOOKBACK_SESSIONS


def test_reference_skips_symbols_with_insufficient_history() -> None:
    """A candidate symbol with no fetched EOD bars is omitted (not
    fabricated) rather than emitted with a zero/garbage reference -- the
    worker's StreamReference.is_valid_for() requires previous_close>0."""
    bars_by_symbol = _fixture_bars_by_symbol()

    references, skipped = build_reference_for_universe(
        [*_PRODUCER_UNIVERSE_SYMBOLS, "NODATA"],
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
        reference_version="fmp-bootstrap-test",
    )

    assert skipped == ["NODATA"]
    assert {reference.symbol for reference in references} == set(_PRODUCER_UNIVERSE_SYMBOLS)


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
    ~900-symbol production universe, not the ranked-only top slice.
    (Unchanged by the 2026-07-25 FMP source fix.)"""
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
