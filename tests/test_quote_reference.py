"""Reference-file coverage test for the full open_prep production universe.

Task 0.2 (Databento signal migration): the A0-Fast bootstrap reference today
(``services/a0_fast_detector/bootstrap/a0-reference.json``) covers only the
~58-symbol micro-cap shadow list (``A0_FAST_SYMBOLS``). This test proves the
parametrized generator in ``scripts/build_a0_reference.py`` instead builds
``previous_close`` + ``average_daily_volume`` for the full liquid open_prep
candidate universe the realtime producer monitors
(``DEFAULT_TOP_N=0`` = ALL, ~900 symbols), using a recorded-shape Databento
daily-bars fixture -- no live network access, no real API keys.
"""

from __future__ import annotations

import pandas as pd

from scripts.build_a0_reference import (
    build_reference_for_universe,
    daily_bars_frame_to_bars_by_symbol,
    extract_candidate_symbols_from_open_prep_run,
)

# Liquid, large-cap production-universe names -- deliberately NOT the
# micro-cap shadow symbols (FUSE/YSXT/FTFT/...) that the existing bootstrap
# file is scoped to today.
_PRODUCER_UNIVERSE_SYMBOLS = ["AAPL", "NVDA", "SPY", "TSLA", "MSFT"]

_LOOKBACK_SESSIONS = 15
_AS_OF_SESSION = "2026-07-24"


def _fixture_daily_bars_frame() -> pd.DataFrame:
    """Recorded-shape Databento daily-bar fixture.

    16 prior sessions per symbol (>= lookback_sessions + 1) with
    monotonically increasing close/volume, in the exact column shape
    ``databento_volatility_screener.load_daily_bars`` returns
    (trade_date, symbol, open, high, low, close, volume).
    """
    rows: list[dict[str, object]] = []
    session_dates = [f"2026-07-{day:02d}" for day in range(1, 17)]  # 16 sessions, all < as_of_session
    for symbol_index, symbol in enumerate(_PRODUCER_UNIVERSE_SYMBOLS):
        base_price = 50.0 + symbol_index * 25.0
        base_volume = 1_000_000 + symbol_index * 500_000
        for day_index, session_date in enumerate(session_dates):
            rows.append(
                {
                    "trade_date": pd.Timestamp(session_date).date(),
                    "symbol": symbol,
                    "open": base_price + day_index * 0.1,
                    "high": base_price + day_index * 0.1 + 1.0,
                    "low": base_price + day_index * 0.1 - 1.0,
                    "close": base_price + day_index * 0.2,
                    "volume": base_volume + day_index * 1_000,
                }
            )
    return pd.DataFrame(rows)


def test_reference_covers_producer_universe() -> None:
    """Given the candidate list + a Databento daily fixture, the built
    reference yields previous_close>0 and average_daily_volume>0 for every
    symbol in the full liquid producer universe (brief Step 1)."""
    frame = _fixture_daily_bars_frame()
    bars_by_symbol = daily_bars_frame_to_bars_by_symbol(frame)

    references, skipped = build_reference_for_universe(
        _PRODUCER_UNIVERSE_SYMBOLS,
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
        reference_version="databento-bootstrap-test",
    )

    assert skipped == []
    assert {reference.symbol for reference in references} == set(_PRODUCER_UNIVERSE_SYMBOLS)
    for reference in references:
        assert reference.previous_close > 0
        assert reference.average_daily_volume > 0
        assert reference.source == "databento:daily"
        assert reference.corporate_action_version == "databento-adjusted-ohlcv-1d-v1"
        assert reference.lookback_sessions == _LOOKBACK_SESSIONS


def test_reference_skips_symbols_with_insufficient_history() -> None:
    """A candidate symbol with no fetched daily bars is omitted (not
    fabricated) rather than emitted with a zero/garbage reference -- the
    worker's StreamReference.is_valid_for() requires previous_close>0."""
    frame = _fixture_daily_bars_frame()
    bars_by_symbol = daily_bars_frame_to_bars_by_symbol(frame)

    references, skipped = build_reference_for_universe(
        [*_PRODUCER_UNIVERSE_SYMBOLS, "NODATA"],
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
        reference_version="databento-bootstrap-test",
    )

    assert skipped == ["NODATA"]
    assert {reference.symbol for reference in references} == set(_PRODUCER_UNIVERSE_SYMBOLS)


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
