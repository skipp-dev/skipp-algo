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


# ---------------------------------------------------------------------------
# Databento-native ADV (venue-consistent volume denominator)
#
# Live-verified 2026-07-28: EQUS.MINI delivers only 5-12% of FMP's
# consolidated session volume (same-moment comparison, e.g. T 1.94M vs
# 21.9M = 8.9%). An FMP-consolidated ADV denominator therefore depresses
# every databento-path volume_ratio ~10x -- the volume regime reads >=80%
# thin (HOLIDAY_SUSPECT, all signals suspended) and the A0/A1/A2 pace gates
# never fire. Fix: source average_daily_volume from EQUS.MINI ohlcv-1d
# history so ratio = subset/subset. previous_close stays FMP-adjusted.
# ---------------------------------------------------------------------------


def _fixture_databento_volume_rows(symbol: str, *, base_volume: int, sessions: int = 16) -> list[dict]:
    session_dates = [f"2026-07-{day:02d}" for day in range(1, sessions + 1)]
    return [
        {"symbol": symbol, "session_date": session_date, "volume": base_volume + index * 100}
        for index, session_date in enumerate(session_dates)
    ]


def test_compute_databento_adv_windows_strictly_before_as_of() -> None:
    """ADV = mean EQUS.MINI daily volume over the trailing lookback sessions
    STRICTLY before as_of -- same windowing contract as the FMP builder, so
    the two ADV sources are drop-in interchangeable."""
    from open_prep.quote_reference import compute_databento_adv

    rows = _fixture_databento_volume_rows("AAPL", base_volume=500_000)
    # A session ON as_of must be excluded from the window.
    rows.append({"symbol": "AAPL", "session_date": _AS_OF_SESSION, "volume": 99_999_999})

    adv_by_symbol = compute_databento_adv(
        rows, as_of_session=_AS_OF_SESSION, lookback_sessions=_LOOKBACK_SESSIONS
    )

    # trailing 15 of the 16 prior sessions: indices 1..15 -> volumes 500_100..501_500
    expected = sum(500_000 + i * 100 for i in range(1, 16)) / 15
    assert adv_by_symbol == {"AAPL": expected}


def test_compute_databento_adv_omits_insufficient_history_and_dust() -> None:
    """Symbols with fewer than lookback sessions, or a subset-ADV below the
    1000-share usability floor (_volume_semantics zeroes ratios under that
    average), are OMITTED -- the reference builder then drops them
    fail-closed instead of emitting an unusable row."""
    from open_prep.quote_reference import compute_databento_adv

    rows = [
        *_fixture_databento_volume_rows("LIQUID", base_volume=500_000),
        # only 3 prior sessions -- insufficient
        *_fixture_databento_volume_rows("SPARSE", base_volume=500_000, sessions=3),
        # enough sessions, but trailing-15 subset ADV = 900 shares -> under
        # the 1000-share usability floor
        *_fixture_databento_volume_rows("DUST", base_volume=100),
    ]

    adv_by_symbol = compute_databento_adv(
        rows, as_of_session=_AS_OF_SESSION, lookback_sessions=_LOOKBACK_SESSIONS
    )

    assert set(adv_by_symbol.keys()) == {"LIQUID"}


def test_apply_databento_adv_overrides_volume_and_documents_provenance() -> None:
    """The FMP-built rows keep previous_close/as_of_session untouched;
    average_daily_volume is replaced by the databento subset ADV and the
    row's source records BOTH provenances. Symbols without a databento ADV
    are dropped fail-closed (never left with the consolidated-ADV row, which
    would silently re-break the volume gates)."""
    from open_prep.quote_reference import DATABENTO_ADV_SOURCE, apply_databento_adv

    bars_by_symbol = _fixture_bars_by_symbol()
    fmp_rows, _ = build_quote_reference_for_universe(
        _PRODUCER_UNIVERSE_SYMBOLS,
        bars_by_symbol,
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
    )
    adv_by_symbol = {symbol: 123_456.0 for symbol in _PRODUCER_UNIVERSE_SYMBOLS if symbol != "TSLA"}

    merged, skipped = apply_databento_adv(fmp_rows, adv_by_symbol)

    assert skipped == ["TSLA"]
    assert set(merged.keys()) == set(_PRODUCER_UNIVERSE_SYMBOLS) - {"TSLA"}
    for symbol, row in merged.items():
        assert row.average_daily_volume == 123_456.0
        assert row.previous_close == fmp_rows[symbol].previous_close
        assert row.as_of_session == fmp_rows[symbol].as_of_session
        assert row.source == f"fmp:adjusted-eod+adv={DATABENTO_ADV_SOURCE}"


def test_databento_daily_df_to_volume_rows_parses_get_range_frame() -> None:
    """Converter for ``Historical.timeseries.get_range(...).to_df()`` output.
    Layout verified live 2026-07-28: ts_event index = 00:00:00 UTC of the
    session date itself, ``symbol``/``volume`` columns present, volume raw
    (unscaled). NaN/negative-volume rows are dropped."""
    pandas = pytest.importorskip("pandas")
    from open_prep.quote_reference import databento_daily_df_to_volume_rows

    frame = pandas.DataFrame(
        {
            "symbol": ["T", "MSFT", "T", "BAD"],
            "volume": [3_993_401, 1_366_730, 4_453_711, -5],
        },
        index=pandas.to_datetime(
            ["2026-07-20", "2026-07-20", "2026-07-21", "2026-07-21"], utc=True
        ),
    )

    rows = databento_daily_df_to_volume_rows(frame)

    assert rows == [
        {"symbol": "T", "session_date": "2026-07-20", "volume": 3_993_401},
        {"symbol": "MSFT", "session_date": "2026-07-20", "volume": 1_366_730},
        {"symbol": "T", "session_date": "2026-07-21", "volume": 4_453_711},
    ]


def test_fetch_databento_daily_volume_rows_queries_equs_mini_1d() -> None:
    """The fetch helper must query EQUS.MINI / ohlcv-1d / raw_symbol over a
    calendar window generous enough for the lookback, via an injectable
    client factory (no live network in tests)."""
    pandas = pytest.importorskip("pandas")
    from open_prep.quote_reference import fetch_databento_daily_volume_rows

    captured: dict = {}

    class _FakeStore:
        def to_df(self):
            return pandas.DataFrame(
                {"symbol": ["T"], "volume": [3_993_401]},
                index=pandas.to_datetime(["2026-07-20"], utc=True),
            )

    class _FakeTimeseries:
        def get_range(self, **kwargs):
            captured.update(kwargs)
            return _FakeStore()

    class _FakeHistorical:
        timeseries = _FakeTimeseries()

    rows = fetch_databento_daily_volume_rows(
        ["T", "MSFT"],
        as_of_session=_AS_OF_SESSION,
        lookback_sessions=_LOOKBACK_SESSIONS,
        client=_FakeHistorical(),
    )

    assert captured["dataset"] == "EQUS.MINI"
    assert captured["schema"] == "ohlcv-1d"
    assert captured["stype_in"] == "raw_symbol"
    assert captured["symbols"] == ["T", "MSFT"]
    assert captured["end"] == _AS_OF_SESSION
    # >= lookback*4 calendar days back (weekend/holiday buffer, mirrors the
    # FMP fetch's date_from arithmetic in main()).
    from datetime import date, timedelta
    start = date.fromisoformat(captured["start"])
    assert date.fromisoformat(_AS_OF_SESSION) - start >= timedelta(days=_LOOKBACK_SESSIONS * 4)
    assert rows == [{"symbol": "T", "session_date": "2026-07-20", "volume": 3_993_401}]
