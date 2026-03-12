from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
from pathlib import Path
import warnings

import numpy as np
import pandas as pd

from scripts.load_databento_export_bundle import build_bundle_summary, load_export_bundle, resolve_manifest_path
from scripts.databento_production_export import (
    _build_batl_debug_payload,
    _build_daily_symbol_features_full_universe_export,
    _collect_quality_window_source_frames,
    _compute_quality_window_signal,
    _enrich_universe_with_quality_window_status,
    _filter_premarket_rows,
    _load_fundamental_reference,
    _select_top_candidates_per_day,
    _format_optional_time,
    _build_premarket_features_full_universe_export,
    _prepare_full_universe_second_detail_export,
)

from databento_volatility_screener import (
    _build_tradingview_watchlist_text,
    _collapse_duplicate_symbol_seconds,
    _deduplicate_daily_symbol_rows,
    _format_reclaim_status_series,
    _numeric_series_or_nan,
    _download_nasdaq_trader_text,
    _clamp_request_end,
    _coerce_timestamp_frame,
    _daily_request_end_exclusive,
    _extract_unresolved_symbols_from_warning_messages,
    _iter_symbol_batches,
    _normalize_symbol_day_scope,
    _parse_nasdaq_trader_directory,
    _prepare_frame_for_excel,
    _probe_symbol_support,
    _read_symbol_support_cache,
    _symbols_requiring_support_check,
    _symbol_scope_token,
    _update_state_from_chunk,
    _write_symbol_support_cache,
    build_daily_features_full_universe,
    collect_detail_tables_for_summary,
    estimate_databento_costs,
    export_run_artifacts,
    fetch_symbol_day_detail,
    fetch_us_equity_universe,
    list_recent_trading_days,
    load_daily_bars,
    normalize_symbol_for_databento,
    run_intraday_screen,
    SYMBOL_SUPPORT_CACHE_TTL_SECONDS,
    SymbolDayState,
    WindowDefinition,
    build_cache_path,
    build_entry_checklist_table,
    build_data_status_result,
    build_window_definition,
    build_summary_table,
    choose_default_dataset,
    DataStatusResult,
    rank_top_fraction_per_day,
    resolve_watchlist_display_table,
    resolve_selected_detail_tables,
    summarize_symbol_day,
)
from scripts.generate_databento_watchlist import LongDipConfig, generate_watchlist_result


def test_build_window_definition_berlin_local_to_utc() -> None:
    window = build_window_definition(
        date(2025, 1, 6),
        display_timezone="Europe/Berlin",
        window_start=time(15, 20),
        window_end=time(16, 0),
        premarket_anchor_et=time(8, 0),
    )
    assert window.fetch_start_utc == pd.Timestamp("2025-01-06T13:00:00Z").to_pydatetime()
    assert window.fetch_end_utc == pd.Timestamp("2025-01-06T15:00:00Z").to_pydatetime()
    assert window.regular_open_utc == pd.Timestamp("2025-01-06T14:30:00Z").to_pydatetime()


def test_build_window_definition_handles_us_dst_start_transition() -> None:
    window = build_window_definition(
        date(2026, 3, 9),
        display_timezone="Europe/Berlin",
        window_start=time(14, 20),
        window_end=time(15, 0),
        premarket_anchor_et=time(8, 0),
    )

    assert window.fetch_start_utc == pd.Timestamp("2026-03-09T12:00:00Z").to_pydatetime()
    assert window.fetch_end_utc == pd.Timestamp("2026-03-09T14:00:00Z").to_pydatetime()
    assert window.regular_open_utc == pd.Timestamp("2026-03-09T13:30:00Z").to_pydatetime()


def test_summarize_symbol_day_computes_requested_percentages() -> None:
    state = SymbolDayState(
        symbol="AAPL",
        trade_date=date(2025, 1, 6),
        first_window_open=102.0,
        last_window_close=108.0,
        window_high=109.0,
        window_low=101.0,
        window_volume=120000.0,
        second_count=2400,
        premarket_price=101.0,
        market_open_price=103.0,
        realized_var=0.0009,
    )
    row = summarize_symbol_day(state, previous_close=100.0)
    assert round(float(row["window_return_pct"]), 4) == round(((108.0 / 102.0) - 1.0) * 100.0, 4)
    assert round(float(row["window_range_pct"]), 4) == round(((109.0 - 101.0) / 102.0) * 100.0, 4)
    assert round(float(row["prev_close_to_premarket_abs"]), 4) == 1.0
    assert round(float(row["prev_close_to_premarket_pct"]), 4) == 1.0
    assert round(float(row["premarket_to_open_abs"]), 4) == 2.0
    assert round(float(row["premarket_to_open_pct"]), 4) == round(((103.0 / 101.0) - 1.0) * 100.0, 4)
    assert round(float(row["open_to_current_abs"]), 4) == 5.0
    assert round(float(row["open_to_current_pct"]), 4) == round(((108.0 / 103.0) - 1.0) * 100.0, 4)
    assert round(float(row["realized_vol_pct"]), 4) == 3.0
    assert row["has_premarket_data"] is True


def test_build_summary_table_adds_absolute_and_percentage_transition_columns() -> None:
    ranked = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "rank": [1],
            "symbol": ["AAPL"],
            "previous_close": [100.0],
            "premarket_price": [101.5],
            "market_open_price": [103.0],
            "current_price": [106.0],
        }
    )
    universe = pd.DataFrame({"symbol": ["AAPL"], "name": ["Apple"]})

    summary = build_summary_table(ranked, universe)

    row = summary.iloc[0]
    assert round(float(row["prev_close_to_premarket_abs"]), 4) == 1.5
    assert round(float(row["prev_close_to_premarket_pct"]), 4) == 1.5
    assert round(float(row["premarket_to_open_abs"]), 4) == 1.5
    assert round(float(row["open_to_current_abs"]), 4) == 3.0
    assert round(float(row["open_to_current_pct"]), 4) == round(((106.0 / 103.0) - 1.0) * 100.0, 4)


def test_rank_top_fraction_per_day_keeps_top_decile_minimum_one() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2025, 1, 6)] * 5 + [date(2025, 1, 7)] * 3,
            "symbol": ["A", "B", "C", "D", "E", "F", "G", "H"],
            "window_range_pct": [1.0, 5.0, 3.0, 2.0, 4.0, 0.5, 7.0, 6.0],
        }
    )
    ranked = rank_top_fraction_per_day(frame, ranking_metric="window_range_pct", top_fraction=0.10)
    assert ranked.shape[0] == 2
    assert ranked.iloc[0]["symbol"] == "B"
    assert ranked.iloc[1]["symbol"] == "G"


def test_build_cache_path_is_stable_and_namespaced(tmp_path) -> None:
    first = build_cache_path(tmp_path, "intraday_summary", dataset="DBEQ.BASIC", parts=["2025-01-06", "Europe/Berlin", "152000"])
    second = build_cache_path(tmp_path, "intraday_summary", dataset="DBEQ.BASIC", parts=["2025-01-06", "Europe/Berlin", "152000"])
    third = build_cache_path(tmp_path, "intraday_summary", dataset="DBEQ.BASIC", parts=["2025-01-07", "Europe/Berlin", "152000"])
    assert first == second
    assert first != third
    assert "intraday_summary" in str(first)
    assert "DBEQ_BASIC" in str(first)


def test_daily_bar_cache_path_uses_separate_version_namespace(tmp_path) -> None:
    daily = build_cache_path(tmp_path, "daily_bars", dataset="DBEQ.BASIC", parts=["2025-01-01", "2025-01-31", "10_deadbeef"])
    intraday = build_cache_path(tmp_path, "intraday_summary", dataset="DBEQ.BASIC", parts=["2025-01-01", "Europe/Berlin", "152000"])
    assert daily != intraday


def test_choose_default_dataset_prefers_requested_then_priority_order() -> None:
    available = ["DBEQ.BASIC", "XNAS.BASIC", "XNAS.ITCH"]
    assert choose_default_dataset(available, requested_dataset="XNAS.BASIC") == "XNAS.BASIC"
    assert choose_default_dataset(available, requested_dataset="EQUS.ALL") == "XNAS.ITCH"
    assert choose_default_dataset(["XNAS.ITCH", "XNYS.PILLAR"], requested_dataset=None) == "XNAS.ITCH"


def test_import_databento_closes_new_idle_event_loops(monkeypatch) -> None:
    import asyncio
    import sys
    import types

    import databento_volatility_screener as dvs

    loop = asyncio.new_event_loop()
    fake_module = types.SimpleNamespace(Historical=object)
    original_import = __import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "databento":
            sys.modules[name] = fake_module
            return fake_module
        return original_import(name, globals, locals, fromlist, level)

    snapshots = [[], [loop]]

    def fake_get_objects():
        if snapshots:
            return snapshots.pop(0)
        return [loop]

    monkeypatch.setattr("builtins.__import__", fake_import)
    monkeypatch.delitem(sys.modules, "databento", raising=False)
    monkeypatch.setattr(dvs.gc, "get_objects", fake_get_objects)

    result = dvs._import_databento()

    assert result is fake_module
    assert loop.is_closed()


def test_clamp_request_end_caps_to_available_end() -> None:
    requested = pd.Timestamp("2026-03-07T00:00:00Z")
    available = pd.Timestamp("2026-03-06T00:00:00Z")
    assert _clamp_request_end(requested, available) == available
    assert _clamp_request_end(requested, None) == requested


def test_daily_request_end_exclusive_includes_last_trading_day() -> None:
    assert _daily_request_end_exclusive(date(2026, 3, 5), None) == date(2026, 3, 6)
    assert _daily_request_end_exclusive(
        date(2026, 3, 5),
        pd.Timestamp("2026-03-06T00:00:00Z"),
    ) == date(2026, 3, 6)
    # Midnight available_end means data through previous day only
    assert _daily_request_end_exclusive(
        date(2026, 3, 5),
        pd.Timestamp("2026-03-05T00:00:00Z"),
    ) == date(2026, 3, 5)
    # Intra-day available_end: data within that day should still be included
    assert _daily_request_end_exclusive(
        date(2026, 3, 5),
        pd.Timestamp("2026-03-05T20:00:00Z"),
    ) == date(2026, 3, 6)


def test_symbol_scope_token_and_batches_are_stable() -> None:
    symbols = {"MSFT", "AAPL", "NVDA"}
    assert _symbol_scope_token(symbols) == _symbol_scope_token(["NVDA", "AAPL", "MSFT"])
    assert _iter_symbol_batches(symbols, batch_size=2) == [["AAPL", "MSFT"], ["NVDA"]]


def test_normalize_symbol_for_databento_maps_berkshire_share_classes() -> None:
    assert normalize_symbol_for_databento("brk-b") == "BRK.B"
    assert normalize_symbol_for_databento("BRK-A") == "BRK.A"
    assert normalize_symbol_for_databento("BRK/B") == "BRK.B"
    assert normalize_symbol_for_databento("BRK/A") == "BRK.A"
    assert normalize_symbol_for_databento("MSFT") == "MSFT"


def test_normalize_symbol_for_databento_maps_additional_share_classes_and_skips_unsupported() -> None:
    assert normalize_symbol_for_databento("BF-B") == "BF.B"
    assert normalize_symbol_for_databento("mkc-v") == "MKC.V"
    assert normalize_symbol_for_databento("MOG-A") == "MOG.A"
    assert normalize_symbol_for_databento("CTA-PA") == ""


def test_normalize_symbol_for_databento_filters_non_common_issue_patterns() -> None:
    assert normalize_symbol_for_databento("ACP$A") == ""
    assert normalize_symbol_for_databento("ACHR.W") == ""
    assert normalize_symbol_for_databento("SOUL.U") == ""
    assert normalize_symbol_for_databento("SOUL.R") == ""
    assert normalize_symbol_for_databento("TSI.RT") == ""


def test_symbols_requiring_support_check_returns_normalized_symbol_universe() -> None:
    assert _symbols_requiring_support_check(["AAPL", "BRK.B", "BF-B", "MSFT", "CTA-PA", "   "]) == ["AAPL", "BF.B", "BRK.B", "MSFT"]


def test_load_fundamental_reference_caches_empty_results(monkeypatch, tmp_path) -> None:
    call_count = {"n": 0}

    class FakeFMPClient:
        def __init__(self, api_key):
            self.api_key = api_key

        def get_profile_bulk(self):
            call_count["n"] += 1
            return []

    monkeypatch.setattr("scripts.databento_production_export.FMPClient", FakeFMPClient)

    first = _load_fundamental_reference(
        "key",
        cache_dir=tmp_path,
        use_file_cache=True,
        force_refresh=False,
    )
    second = _load_fundamental_reference(
        "key",
        cache_dir=tmp_path,
        use_file_cache=True,
        force_refresh=False,
    )

    assert first.empty
    assert second.empty
    assert call_count["n"] == 1


def test_probe_symbol_support_only_marks_explicit_unresolved_symbols_unsupported(monkeypatch) -> None:
    class FakeStore:
        def to_df(self, count=None):
            return pd.DataFrame(columns=["symbol", "ts"])

    class FakeMetadata:
        def get_dataset_condition(self, **kwargs):
            return [{"date": "2026-03-05", "condition": "available"}]

    class FakeTimeseries:
        def get_range(self, **kwargs):
            warnings.warn("Symbols did not resolve: BAD")
            return FakeStore()

    class FakeClient:
        metadata = FakeMetadata()
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    support = _probe_symbol_support("test-key", dataset="DBEQ.BASIC", symbols=["AAPL", "BAD"])

    assert support == {"BAD": False}


def test_list_recent_trading_days_uses_market_day_cutoff(monkeypatch) -> None:
    class FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            frozen = cls(2026, 3, 6, 0, 30, tzinfo=UTC)
            return frozen if tz is None else frozen.astimezone(tz)

    class FakeMetadata:
        def get_dataset_condition(self, **kwargs):
            return [
                {"date": "2026-03-04", "condition": "available"},
                {"date": "2026-03-05", "condition": "available"},
            ]

    class FakeClient:
        metadata = FakeMetadata()

    monkeypatch.setattr("databento_volatility_screener.datetime", FakeDateTime)
    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    days = list_recent_trading_days("test-key", dataset="DBEQ.BASIC", lookback_days=5)

    assert days == [date(2026, 3, 4)]


def test_parse_nasdaq_trader_directory_filters_etfs_test_rows_and_footer() -> None:
    text = """Symbol|Security Name|Listing Exchange|ETF|Test Issue\nBATL|Battalion Oil Corporation Common Stock|A|N|N\nSPY|SPDR S&P 500 ETF Trust|A|Y|N\nTEST|Example Test Symbol|Q|N|Y\nFile Creation Time: 0306202621:33||||\n"""

    frame = _parse_nasdaq_trader_directory(
        text,
        symbol_column="Symbol",
        security_name_column="Security Name",
        exchange_column="Listing Exchange",
        allowed_exchange_codes={"A", "Q"},
    )

    assert frame[["symbol", "company_name", "exchange", "sector", "industry"]].to_dict(orient="records") == [
        {
            "symbol": "BATL",
            "company_name": "Battalion Oil Corporation Common Stock",
            "exchange": "AMEX",
            "sector": "",
            "industry": "",
        }
    ]
    assert pd.isna(frame.iloc[0]["market_cap"])


def test_build_daily_symbol_features_full_universe_export_ranks_and_selects_top_fraction() -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "BATL"],
            "company_name": ["AAA Corp", "BBB Corp", "Battalion Oil"],
            "exchange": ["NASDAQ", "NYSE", "AMEX"],
            "sector": ["Tech", "Energy", "Energy"],
            "industry": ["Software", "Oil", "Oil"],
            "market_cap": [100.0, 200.0, np.nan],
            "asset_type": ["listed_equity_issue", "listed_equity_issue", "listed_equity_issue"],
            "has_reference_data": [True, True, True],
            "has_fundamentals": [True, True, False],
            "has_market_cap": [True, True, False],
        }
    )
    supported_universe = raw_universe[raw_universe["symbol"].isin(["AAA", "BBB"])]
    daily_bars = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "open": [10.0, 20.0],
            "high": [12.0, 25.0],
            "low": [9.0, 19.0],
            "close": [11.0, 24.0],
            "volume": [1000.0, 2000.0],
            "previous_close": [9.5, 19.5],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "previous_close": [9.5, 19.5],
            "premarket_price": [9.8, 19.8],
            "has_premarket_data": [True, True],
            "market_open_price": [10.0, 20.0],
            "window_start_price": [10.0, 20.0],
            "current_price": [10.8, 24.5],
            "window_high": [11.0, 25.0],
            "window_low": [9.9, 19.0],
            "window_volume": [500.0, 800.0],
            "seconds_in_window": [420, 420],
            "window_return_pct": [8.0, 22.5],
            "window_range_pct": [11.0, 30.0],
            "realized_vol_pct": [2.0, 4.0],
            "prev_close_to_premarket_abs": [0.3, 0.3],
            "prev_close_to_premarket_pct": [3.1579, 1.5385],
            "premarket_to_open_abs": [0.2, 0.2],
            "premarket_to_open_pct": [2.0408, 1.0101],
            "open_to_current_abs": [0.8, 4.5],
            "open_to_current_pct": [8.0, 22.5],
        }
    )
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "timestamp": [pd.Timestamp("2026-03-06T14:30:00Z"), pd.Timestamp("2026-03-06T14:30:00Z")],
            "session": ["regular", "regular"],
            "open": [10.0, 20.0],
            "high": [10.2, 20.3],
            "low": [9.9, 19.8],
            "close": [10.1, 20.1],
            "volume": [100.0, 120.0],
            "second_delta_pct": [np.nan, np.nan],
            "from_previous_close_pct": [6.3158, 3.0769],
        }
    )

    features, diagnostics = _build_daily_symbol_features_full_universe_export(
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail,
        display_timezone="Europe/Berlin",
        premarket_anchor_et=time(8, 0),
        ranking_metric="window_range_pct",
        top_fraction=0.20,
    )

    aaa = features.loc[features["symbol"] == "AAA"].iloc[0]
    bbb = features.loc[features["symbol"] == "BBB"].iloc[0]
    batl = features.loc[features["symbol"] == "BATL"].iloc[0]
    assert bool(aaa["is_eligible"]) is True
    assert bool(bbb["is_eligible"]) is True
    assert bool(bbb["selected_top20pct"]) is True
    assert "selected_top20pct_0400" in features.columns
    assert int(features["selected_top20pct_0400"].fillna(False).astype(bool).sum()) <= 1
    assert bool(batl["selected_top20pct_0400"]) is False
    assert int(bbb["rank_within_trade_date"]) == 1
    assert int(aaa["rank_within_trade_date"]) == 2
    assert int(aaa["eligible_count_for_trade_date"]) == 2
    assert int(aaa["take_n_for_trade_date"]) == 1
    assert bool(aaa["selected_top20pct"]) is False
    assert bool(batl["is_eligible"]) is False
    assert batl["eligibility_reason"] == "unsupported_by_databento"

    batl_diag = diagnostics.loc[diagnostics["symbol"] == "BATL"].iloc[0]
    assert batl_diag["excluded_step"] == "databento_support_filter"
    assert batl_diag["excluded_reason"] == "unsupported_by_databento"


def test_prepare_second_detail_and_premarket_feature_exports() -> None:
    trade_day = date(2026, 3, 6)
    daily_features = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "previous_close": [10.0, 20.0],
            "market_open_price": [10.5, 20.5],
        }
    )
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "AAA", "AAA"],
            "timestamp": [
                pd.Timestamp("2026-03-06T13:00:00Z"),
                pd.Timestamp("2026-03-06T14:29:59Z"),
                pd.Timestamp("2026-03-06T14:30:00Z"),
            ],
            "session": ["premarket", "premarket", "regular"],
            "open": [10.1, 10.3, 10.5],
            "high": [10.2, 10.4, 10.7],
            "low": [10.0, 10.2, 10.4],
            "close": [10.15, 10.35, 10.6],
            "volume": [100.0, 200.0, 300.0],
            "second_delta_pct": [np.nan, 1.9704, 2.4155],
            "from_previous_close_pct": [1.5, 3.5, 6.0],
        }
    )

    prepared = _prepare_full_universe_second_detail_export(second_detail, daily_features)
    aaa_last = prepared.loc[prepared["symbol"] == "AAA"].sort_values("timestamp").iloc[-1]
    assert round(float(aaa_last["from_open_pct"]), 4) == round(((10.6 / 10.5) - 1.0) * 100.0, 4)
    assert "trade_count" in prepared.columns

    premarket = _build_premarket_features_full_universe_export(prepared, daily_features)
    aaa = premarket.loc[premarket["symbol"] == "AAA"].iloc[0]
    bbb = premarket.loc[premarket["symbol"] == "BBB"].iloc[0]
    assert bool(aaa["has_premarket_data"]) is True
    assert round(float(aaa["premarket_last"]), 4) == 10.35
    assert round(float(aaa["premarket_volume"]), 4) == 300.0
    assert int(aaa["premarket_seconds"]) == 2
    assert round(float(aaa["prev_close_to_premarket_pct"]), 4) == round(((10.35 / 10.0) - 1.0) * 100.0, 4)
    assert round(float(aaa["premarket_to_open_pct"]), 4) == round(((10.5 / 10.35) - 1.0) * 100.0, 4)
    assert bool(bbb["has_premarket_data"]) is False


def test_enrich_universe_with_quality_window_status_marks_latest_trade_date_windows() -> None:
    trade_day = date(2026, 3, 6)
    universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "company_name": ["AAA Corp", "BBB Corp", "CCC Corp"],
        }
    )
    daily_features = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "BBB", "CCC"],
            "previous_close": [10.0, 12.0, 1.0],
        }
    )
    premarket_features = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "BBB", "CCC"],
            "prev_close_to_premarket_pct": [1.2, 0.8, 2.0],
            "premarket_to_open_pct": [0.4, 0.2, -1.0],
        }
    )
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day] * 8,
            "symbol": ["AAA", "AAA", "BBB", "BBB", "BBB", "BBB", "CCC", "CCC"],
            "timestamp": [
                pd.Timestamp("2026-03-06T09:00:00Z"),
                pd.Timestamp("2026-03-06T09:29:00Z"),
                pd.Timestamp("2026-03-06T14:00:00Z"),
                pd.Timestamp("2026-03-06T14:29:00Z"),
                pd.Timestamp("2026-03-06T09:00:00Z"),
                pd.Timestamp("2026-03-06T09:29:00Z"),
                pd.Timestamp("2026-03-06T09:00:00Z"),
                pd.Timestamp("2026-03-06T09:29:00Z"),
            ],
            "close": [10.2, 10.5, 12.1, 12.3, 12.0, 12.2, 3.1, 3.2],
            "high": [10.2, 10.55, 12.2, 12.35, 12.05, 12.25, 3.15, 3.2],
            "open": [10.1, 10.2, 12.0, 12.1, 11.95, 12.0, 3.0, 3.1],
            "low": [10.1, 10.2, 12.0, 12.1, 11.95, 12.0, 3.0, 3.1],
            "volume": [30_000.0, 30_000.0, 30_000.0, 30_000.0, 25_000.0, 25_000.0, 30_000.0, 30_000.0],
        }
    )

    status, candidate_exports = _compute_quality_window_signal(
        second_detail,
        daily_features,
        premarket_features,
        display_timezone="Europe/Berlin",
        latest_trade_date=trade_day,
    )

    enriched = _enrich_universe_with_quality_window_status(
        universe,
        daily_features,
        premarket_features,
        second_detail,
        display_timezone="Europe/Berlin",
    )

    statuses = dict(zip(enriched["symbol"], enriched["quality_open_drive_window_latest_berlin"], strict=False))
    coverage = dict(zip(enriched["symbol"], enriched["quality_open_drive_window_coverage_latest_berlin"], strict=False))
    scores = dict(zip(enriched["symbol"], enriched["quality_open_drive_window_score_latest_berlin"], strict=False))
    assert statuses["AAA"] == "10:00-10:30"
    assert statuses["BBB"] == "10:00-10:30+15:00-15:30"
    assert statuses["CCC"] == "none"
    assert coverage["AAA"] == "10:00-10:30"
    assert coverage["BBB"] == "10:00-10:30+15:00-15:30"
    assert coverage["CCC"] == "10:00-10:30"
    assert round(float(scores["AAA"]), 4) == 11.5
    assert round(float(scores["BBB"]), 4) == 11.5
    assert pd.isna(scores["CCC"])
    assert set(enriched["quality_open_drive_window_trade_date"].astype(str)) == {"2026-03-06"}
    assert set(status["symbol"]) == {"AAA", "BBB", "CCC"}

    early_candidates = candidate_exports["quality_candidates_0400_0430_et_all"]
    late_candidates = candidate_exports["quality_candidates_0900_0930_et_all"]
    assert list(early_candidates["symbol"]) == ["AAA", "BBB"]
    assert list(late_candidates["symbol"]) == ["BBB"]
    assert set(early_candidates.columns) >= {
        "trade_date",
        "symbol",
        "previous_close",
        "prev_close_to_premarket_pct",
        "premarket_to_open_pct",
        "window_return_pct",
        "window_range_pct",
        "window_close_vs_high_pct",
        "window_dollar_volume",
        "quality_score",
    }
    assert list(candidate_exports["quality_candidates_0400_0430_et_top20_per_day"]["symbol"]) == ["AAA", "BBB"]
    assert list(candidate_exports["quality_candidates_0900_0930_et_top50_per_day"]["symbol"]) == ["BBB"]


def test_collect_quality_window_source_frames_prefers_exchange_specific_early_and_premarket_sources(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC"],
            "exchange": ["NASDAQ", "NYSE", "AMEX"],
        }
    )
    supported_universe = raw_universe.copy()
    daily_bars = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "BBB", "CCC"],
            "previous_close": [10.0, 20.0, 30.0],
        }
    )

    def _frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day] * len(rows),
                "symbol": [symbol for symbol, _, _ in rows],
                "timestamp": [pd.Timestamp(ts) for _, ts, _ in rows],
                "session": ["premarket" if pd.Timestamp(ts) < pd.Timestamp("2026-03-06T14:30:00Z") else "regular" for _, ts, _ in rows],
                "open": [value for _, _, value in rows],
                "high": [value for _, _, value in rows],
                "low": [value for _, _, value in rows],
                "close": [value for _, _, value in rows],
                "volume": [100.0] * len(rows),
                "second_delta_pct": [np.nan] * len(rows),
                "from_previous_close_pct": [np.nan] * len(rows),
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(
            [
                ("AAA", "2026-03-06T09:00:00Z", 10.0),
                ("AAA", "2026-03-06T14:00:00Z", 11.0),
                ("AAA", "2026-03-06T14:29:59Z", 12.0),
                ("AAA", "2026-03-06T14:30:10Z", 13.0),
                ("BBB", "2026-03-06T09:00:00Z", 20.0),
                ("BBB", "2026-03-06T14:00:00Z", 21.0),
                ("BBB", "2026-03-06T14:29:59Z", 22.0),
                ("BBB", "2026-03-06T14:30:10Z", 23.0),
                ("CCC", "2026-03-06T09:00:00Z", 30.0),
                ("CCC", "2026-03-06T14:00:00Z", 31.0),
                ("CCC", "2026-03-06T14:29:59Z", 32.0),
                ("CCC", "2026-03-06T14:30:10Z", 33.0),
            ]
        ),
        "XNAS.BASIC": _frame(
            [
                ("AAA", "2026-03-06T09:00:00Z", 100.0),
                ("AAA", "2026-03-06T14:00:00Z", 110.0),
                ("AAA", "2026-03-06T14:29:59Z", 120.0),
                ("AAA", "2026-03-06T14:30:10Z", 130.0),
            ]
        ),
        "XNYS.PILLAR": _frame(
            [
                ("BBB", "2026-03-06T09:00:00Z", 200.0),
                ("BBB", "2026-03-06T14:00:00Z", 210.0),
                ("BBB", "2026-03-06T14:29:59Z", 220.0),
                ("BBB", "2026-03-06T14:30:10Z", 230.0),
            ]
        ),
        "XASE.PILLAR": _frame(
            [
                ("CCC", "2026-03-06T09:00:00Z", 300.0),
                ("CCC", "2026-03-06T14:00:00Z", 310.0),
                ("CCC", "2026-03-06T14:29:59Z", 320.0),
                ("CCC", "2026-03-06T14:30:10Z", 330.0),
            ]
        ),
    }

    def fake_collect(*args, dataset: str, universe_symbols: set[str], **kwargs):
        frame = frames[dataset].copy()
        return frame.loc[frame["symbol"].isin(universe_symbols)].reset_index(drop=True)

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    quality_detail, premarket_detail, metadata = _collect_quality_window_source_frames(
        databento_api_key="test-key",
        base_dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        symbol_day_scope=None,
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=False,
        early_exchange_datasets={"NASDAQ": "XNAS.BASIC", "NYSE": "XNYS.PILLAR", "AMEX": "XASE.PILLAR"},
    )

    aaa_quality = quality_detail.loc[quality_detail["symbol"] == "AAA"].sort_values("timestamp")
    bbb_quality = quality_detail.loc[quality_detail["symbol"] == "BBB"].sort_values("timestamp")
    ccc_quality = quality_detail.loc[quality_detail["symbol"] == "CCC"].sort_values("timestamp")
    aaa_premarket = premarket_detail.loc[premarket_detail["symbol"] == "AAA"].sort_values("timestamp")
    bbb_premarket = premarket_detail.loc[premarket_detail["symbol"] == "BBB"].sort_values("timestamp")
    ccc_premarket = premarket_detail.loc[premarket_detail["symbol"] == "CCC"].sort_values("timestamp")

    assert list(aaa_quality["close"]) == [100.0, 11.0, 12.0, 130.0]
    assert list(bbb_quality["close"]) == [200.0, 21.0, 22.0, 230.0]
    assert list(ccc_quality["close"]) == [300.0, 31.0, 32.0, 330.0]
    assert list(aaa_premarket["close"]) == [100.0, 110.0, 120.0]
    assert list(bbb_premarket["close"]) == [200.0, 210.0, 220.0]
    assert list(ccc_premarket["close"]) == [300.0, 310.0, 320.0]
    assert metadata["applied_early_exchange_datasets"] == {"NASDAQ": "XNAS.BASIC", "NYSE": "XNYS.PILLAR", "AMEX": "XASE.PILLAR"}
    assert metadata["early_exchange_symbol_counts"] == {"NASDAQ": 1, "NYSE": 1, "AMEX": 1}


def test_collect_quality_window_source_frames_uses_alternate_on_timestamp_collisions(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame({"symbol": ["AAA"], "exchange": ["NASDAQ"]})
    supported_universe = raw_universe.copy()
    daily_bars = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"], "previous_close": [10.0]})

    def _frame(close_value: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day],
                "symbol": ["AAA"],
                "timestamp": [pd.Timestamp("2026-03-06T09:00:00Z")],
                "session": ["premarket"],
                "open": [close_value],
                "high": [close_value],
                "low": [close_value],
                "close": [close_value],
                "volume": [100.0],
                "second_delta_pct": [np.nan],
                "from_previous_close_pct": [np.nan],
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(10.0),
        "XNAS.BASIC": _frame(100.0),
    }

    def fake_collect(*args, dataset: str, universe_symbols: set[str], **kwargs):
        frame = frames[dataset].copy()
        return frame.loc[frame["symbol"].isin(universe_symbols)].reset_index(drop=True)

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    quality_detail, premarket_detail, _ = _collect_quality_window_source_frames(
        databento_api_key="test-key",
        base_dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        symbol_day_scope=None,
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=False,
        early_exchange_datasets={"NASDAQ": "XNAS.BASIC"},
    )

    assert len(quality_detail) == 1
    assert len(premarket_detail) == 1
    assert float(quality_detail.iloc[0]["close"]) == 100.0
    assert float(premarket_detail.iloc[0]["close"]) == 100.0


def test_collect_quality_window_source_frames_keeps_base_for_exchange_symbols_missing_in_alternate(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame({"symbol": ["AAA", "AAB"], "exchange": ["NASDAQ", "NASDAQ"]})
    supported_universe = raw_universe.copy()
    daily_bars = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "AAB"],
            "previous_close": [10.0, 11.0],
        }
    )

    def _frame(rows: list[tuple[str, str, float]]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day] * len(rows),
                "symbol": [symbol for symbol, _, _ in rows],
                "timestamp": [pd.Timestamp(ts) for _, ts, _ in rows],
                "session": ["premarket"] * len(rows),
                "open": [value for _, _, value in rows],
                "high": [value for _, _, value in rows],
                "low": [value for _, _, value in rows],
                "close": [value for _, _, value in rows],
                "volume": [100.0] * len(rows),
                "second_delta_pct": [np.nan] * len(rows),
                "from_previous_close_pct": [np.nan] * len(rows),
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(
            [
                ("AAA", "2026-03-06T09:00:00Z", 10.0),
                ("AAB", "2026-03-06T09:00:00Z", 20.0),
            ]
        ),
        "XNAS.BASIC": _frame(
            [
                ("AAA", "2026-03-06T09:00:00Z", 100.0),
            ]
        ),
    }

    def fake_collect(*args, dataset: str, universe_symbols: set[str], **kwargs):
        frame = frames[dataset].copy()
        return frame.loc[frame["symbol"].isin(universe_symbols)].reset_index(drop=True)

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    quality_detail, premarket_detail, _ = _collect_quality_window_source_frames(
        databento_api_key="test-key",
        base_dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        symbol_day_scope=None,
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=False,
        early_exchange_datasets={"NASDAQ": "XNAS.BASIC"},
    )

    aaa_pm = premarket_detail.loc[premarket_detail["symbol"] == "AAA", "close"].tolist()
    aab_pm = premarket_detail.loc[premarket_detail["symbol"] == "AAB", "close"].tolist()
    assert aaa_pm == [100.0]
    assert aab_pm == [20.0]
    assert set(quality_detail["symbol"].tolist()) == {"AAA", "AAB"}


def test_collect_quality_window_source_frames_normalizes_symbol_aliases_for_exchange_routing(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame({"symbol": ["BRK/B"], "exchange": ["NYSE"]})
    supported_universe = pd.DataFrame({"symbol": ["BRK.B"], "exchange": ["NYSE"]})
    daily_bars = pd.DataFrame({"trade_date": [trade_day], "symbol": ["BRK.B"], "previous_close": [10.0]})

    def _frame(close_value: float, session: str = "premarket") -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day],
                "symbol": ["BRK.B"],
                "timestamp": [pd.Timestamp("2026-03-06T09:00:00Z")],
                "session": [session],
                "open": [close_value],
                "high": [close_value],
                "low": [close_value],
                "close": [close_value],
                "volume": [100.0],
                "second_delta_pct": [np.nan],
                "from_previous_close_pct": [np.nan],
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(10.0),
        "XNYS.PILLAR": _frame(100.0),
    }

    def fake_collect(*args, dataset: str, universe_symbols: set[str], **kwargs):
        frame = frames[dataset].copy()
        return frame.loc[frame["symbol"].isin(universe_symbols)].reset_index(drop=True)

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    quality_detail, premarket_detail, metadata = _collect_quality_window_source_frames(
        databento_api_key="test-key",
        base_dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        symbol_day_scope=None,
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=False,
        early_exchange_datasets={"NYSE": "XNYS.PILLAR"},
    )

    assert len(quality_detail) == 1
    assert len(premarket_detail) == 1
    assert float(quality_detail.iloc[0]["close"]) == 100.0
    assert float(premarket_detail.iloc[0]["close"]) == 100.0
    assert metadata["applied_early_exchange_datasets"] == {"NYSE": "XNYS.PILLAR"}


def test_collect_quality_window_source_frames_normalizes_exchange_aliases_for_amex(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame({"symbol": ["EQX"], "exchange": ["NYSE American"]})
    supported_universe = pd.DataFrame({"symbol": ["EQX"], "exchange": ["NYSE American"]})
    daily_bars = pd.DataFrame({"trade_date": [trade_day], "symbol": ["EQX"], "previous_close": [5.0]})

    def _frame(close_value: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day],
                "symbol": ["EQX"],
                "timestamp": [pd.Timestamp("2026-03-06T09:00:00Z")],
                "session": ["premarket"],
                "open": [close_value],
                "high": [close_value],
                "low": [close_value],
                "close": [close_value],
                "volume": [100.0],
                "second_delta_pct": [np.nan],
                "from_previous_close_pct": [np.nan],
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(10.0),
        "XASE.PILLAR": _frame(100.0),
    }

    def fake_collect(*args, dataset: str, universe_symbols: set[str], **kwargs):
        frame = frames[dataset].copy()
        return frame.loc[frame["symbol"].isin(universe_symbols)].reset_index(drop=True)

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    quality_detail, premarket_detail, metadata = _collect_quality_window_source_frames(
        databento_api_key="test-key",
        base_dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        symbol_day_scope=None,
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=False,
        early_exchange_datasets={"AMEX": "XASE.PILLAR"},
    )

    assert len(quality_detail) == 1
    assert len(premarket_detail) == 1
    assert float(quality_detail.iloc[0]["close"]) == 100.0
    assert float(premarket_detail.iloc[0]["close"]) == 100.0
    assert metadata["applied_early_exchange_datasets"] == {"AMEX": "XASE.PILLAR"}


def test_filter_premarket_rows_strips_session_whitespace() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "session": [" Premarket ", "regular"],
            "timestamp": [pd.Timestamp("2026-03-06T09:00:00Z"), pd.Timestamp("2026-03-06T14:30:00Z")],
        }
    )

    filtered = _filter_premarket_rows(frame)

    assert len(filtered) == 1
    assert str(filtered.iloc[0]["session"]).strip().lower() == "premarket"


def test_select_top_candidates_per_day_returns_empty_for_non_positive_top_n() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6), date(2026, 3, 6)],
            "symbol": ["AAA", "BBB"],
            "quality_score": [5.0, 4.0],
            "window_dollar_volume": [1000.0, 900.0],
            "window_return_pct": [1.0, 0.8],
        }
    )

    result_zero = _select_top_candidates_per_day(frame, 0)
    result_negative = _select_top_candidates_per_day(frame, -1)

    assert result_zero.empty
    assert result_negative.empty


def test_build_tradingview_watchlist_text_uses_exchange_prefixed_symbols() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["EQX", "GBR", "EQX", "SPY", "", None],
            "exchange": ["AMEX", "AMEX", "AMEX", "NYSE ARCA", "AMEX", "NASDAQ"],
        }
    )

    assert _build_tradingview_watchlist_text(frame) == "AMEX:EQX,AMEX:GBR,AMEX:SPY,"


def test_numeric_series_or_nan_returns_nan_series_for_missing_columns() -> None:
    frame = pd.DataFrame({"symbol": ["AAA", "BBB"]})
    series = _numeric_series_or_nan(frame, "open_30s_volume")

    assert len(series) == len(frame)
    assert series.isna().all()


def test_format_reclaim_status_series_handles_missing_and_boolean_values() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "reclaimed_start_price_within_30s": [True, False, np.nan, pd.NA],
        }
    )

    formatted = _format_reclaim_status_series(frame)

    assert formatted.tolist() == ["yes", "no", "n/a", "n/a"]


def test_format_reclaim_status_series_returns_na_for_missing_column() -> None:
    frame = pd.DataFrame({"symbol": ["AAA", "BBB"]})

    formatted = _format_reclaim_status_series(frame)

    assert formatted.tolist() == ["n/a", "n/a"]


def test_prepare_full_universe_second_detail_export_deduplicates_daily_feature_lookup() -> None:
    trade_day = date(2026, 3, 6)
    daily_features = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "AAA"],
            "previous_close": [10.0, 10.0],
            "market_open_price": [10.5, 10.5],
        }
    )
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "timestamp": [pd.Timestamp("2026-03-06T14:30:00Z")],
            "session": ["regular"],
            "open": [10.5],
            "high": [10.7],
            "low": [10.4],
            "close": [10.6],
            "volume": [300.0],
            "second_delta_pct": [2.4155],
            "from_previous_close_pct": [6.0],
        }
    )

    prepared = _prepare_full_universe_second_detail_export(second_detail, daily_features)

    assert len(prepared) == 1
    assert prepared.iloc[0]["symbol"] == "AAA"


def test_format_optional_time_handles_none() -> None:
    assert _format_optional_time(None) == "market_relative_default"
    assert _format_optional_time(time(15, 30, 20)) == "15:30:20"


def test_build_batl_debug_payload_prefers_feature_row_and_falls_back_to_diagnostics() -> None:
    features = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["BATL"],
            "is_eligible": [False],
            "eligibility_reason": ["unsupported_by_databento"],
            "rank_within_trade_date": [pd.NA],
            "selected_top20pct": [False],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["BATL"],
            "selected_top20pct": [False],
            "excluded_step": ["databento_support_filter"],
            "excluded_reason": ["unsupported_by_databento"],
        }
    )

    payload = _build_batl_debug_payload(features, diagnostics)

    assert payload["present_in_daily_symbol_features_full_universe"] is True
    assert payload["eligibility_reason"] == "unsupported_by_databento"


def test_fetch_us_equity_universe_prefers_official_listing_source(monkeypatch) -> None:
    official = pd.DataFrame(
        {
            "symbol": ["BATL", "AAPL"],
            "company_name": ["Battalion Oil Corporation Common Stock", "Apple Inc. Common Stock"],
            "exchange": ["AMEX", "NASDAQ"],
            "sector": ["", ""],
            "industry": ["", ""],
            "market_cap": [pd.NA, pd.NA],
        }
    )

    monkeypatch.setattr("databento_volatility_screener._fetch_us_equity_universe_via_nasdaq_trader", lambda **_: official)
    monkeypatch.setattr(
        "databento_volatility_screener._fetch_us_equity_universe_via_screener",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("legacy screener should not be used for full universe")),
    )

    result = fetch_us_equity_universe("fake-key")

    assert result.equals(official)


def test_fetch_us_equity_universe_uses_screener_for_market_cap_filtered_calls(monkeypatch) -> None:
    screener = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "company_name": ["Apple Inc."],
            "exchange": ["NASDAQ"],
            "sector": ["Technology"],
            "industry": ["Consumer Electronics"],
            "market_cap": [1.0],
        }
    )

    monkeypatch.setattr(
        "databento_volatility_screener._fetch_us_equity_universe_via_nasdaq_trader",
        lambda **_: (_ for _ in ()).throw(AssertionError("official directory should be bypassed when min_market_cap is set")),
    )
    monkeypatch.setattr("databento_volatility_screener._fetch_us_equity_universe_via_screener", lambda *args, **kwargs: screener)

    result = fetch_us_equity_universe("fake-key", min_market_cap=1000.0)

    assert result.equals(screener)


def test_extract_unresolved_symbols_from_warning_messages_normalizes_aliases() -> None:
    messages = [
        "The streaming request had one or more symbols which did not resolve: BF-B, CTA-PA, MKC-V...",
        "No data found for the request you submitted.",
    ]
    assert _extract_unresolved_symbols_from_warning_messages(messages) == {"BF.B", "MKC.V"}


def test_extract_unresolved_symbols_from_warning_messages_strips_trailing_punctuation() -> None:
    messages = [
        "The streaming request had one or more symbols which did not resolve: BMGL, BUI.V, DMAAR.",
    ]
    assert _extract_unresolved_symbols_from_warning_messages(messages) == {"BMGL", "BUI.V", "DMAAR"}


def test_normalize_symbol_day_scope_drops_invalid_symbols_and_deduplicates() -> None:
    scope = pd.DataFrame(
        {
            "trade_date": ["2026-03-07", "2026-03-07", "2026-03-07", "bad-date"],
            "symbol": ["SOUL.R", "BRK-B", "BRK-B", "AAPL"],
        }
    )

    normalized = _normalize_symbol_day_scope(scope)

    assert normalized.to_dict(orient="records") == [
        {"trade_date": date(2026, 3, 7), "symbol": "BRK.B"},
    ]


def test_prepare_frame_for_excel_removes_timezone_information() -> None:
    frame = pd.DataFrame(
        {
            "ts": [pd.Timestamp("2026-03-05T15:40:00Z")],
            "value": [1],
        }
    )
    prepared = _prepare_frame_for_excel(frame)
    assert str(prepared["ts"].dtype) == "datetime64[ns]"


def test_build_data_status_result_uses_manifest_timestamps(tmp_path: Path) -> None:
    manifest_path = tmp_path / "databento_volatility_production_20260308_152400_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "DBEQ.BASIC",
                "lookback_days": 30,
                "export_generated_at": "2026-03-08T14:24:19+00:00",
                "daily_bars_fetched_at": "2026-03-08T14:23:41+00:00",
                "intraday_fetched_at": "2026-03-08T14:24:02+00:00",
                "premarket_fetched_at": "2026-03-08T14:24:10+00:00",
                "second_detail_fetched_at": "2026-03-08T14:24:10+00:00",
                "trade_dates_covered": ["2026-03-05", "2026-03-06"],
            }
        ),
        encoding="utf-8",
    )

    status = build_data_status_result(tmp_path, stale_after_minutes=10_000)

    assert status.dataset == "DBEQ.BASIC"
    assert status.export_generated_at == "2026-03-08T14:24:19+00:00"
    assert status.premarket_fetched_at == "2026-03-08T14:24:10+00:00"
    assert status.trade_dates_covered == ("2026-03-05", "2026-03-06")
    assert status.is_stale is False


def test_build_data_status_result_marks_invalid_manifest_timestamp_as_stale(tmp_path: Path) -> None:
    manifest_path = tmp_path / "databento_volatility_production_20260308_152400_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset": "DBEQ.BASIC",
                "lookback_days": "30",
                "export_generated_at": "not-a-timestamp",
                "trade_dates_covered": ["2026-03-05", "2026-03-06"],
            }
        ),
        encoding="utf-8",
    )

    status = build_data_status_result(tmp_path)

    assert status.is_stale is True
    assert status.staleness_reason == "Invalid export timestamp in manifest."
    assert status.lookback_days == 30


def test_resolve_manifest_path_accepts_directory_and_basename(tmp_path: Path) -> None:
    manifest_path = tmp_path / "bundle_20260307_120000_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")

    assert resolve_manifest_path(tmp_path) == manifest_path
    assert resolve_manifest_path(tmp_path / "bundle_20260307_120000") == manifest_path


def test_generate_watchlist_result_returns_generated_and_source_timestamps(tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "previous_close": [10.0],
            "window_range_pct": [2.0],
            "window_return_pct": [1.0],
            "realized_vol_pct": [1.0],
            "selected_top20pct": [True],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "has_premarket_data": [True],
            "premarket_last": [11.0],
            "premarket_volume": [300_000],
            "premarket_trade_count": [800],
            "prev_close_to_premarket_pct": [10.0],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "present_in_eligible": [True],
            "excluded_reason": [""],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)
    diagnostics.to_parquet(tmp_path / "symbol_day_diagnostics.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["trade_date"] == "2026-03-06"
    assert result["source_data_fetched_at"] is not None
    assert result["generated_at"] is not None
    assert len(result["watchlist_table"]) == 1
    assert result["watchlist_table"].iloc[0]["symbol"] == "BBB"


def test_resolve_watchlist_display_table_switches_between_latest_and_full_history() -> None:
    historical = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6), date(2026, 3, 7), date(2026, 3, 7)],
            "symbol": ["AAA", "BBB", "CCC"],
            "watchlist_rank": [1, 1, 2],
        }
    )
    active = historical.loc[historical["trade_date"] == date(2026, 3, 7)].reset_index(drop=True)
    watchlist_result = {
        "generated_at": "2026-03-09T17:00:00+00:00",
        "source_data_fetched_at": "2026-03-09T16:55:00+00:00",
        "trade_date": "2026-03-07",
        "watchlist_table": historical,
        "active_watchlist_table": active,
    }

    latest_table, latest_caption = resolve_watchlist_display_table(
        watchlist_result=watchlist_result,
        view_mode="Latest trade date",
    )
    full_table, full_caption = resolve_watchlist_display_table(
        watchlist_result=watchlist_result,
        view_mode="Full history",
    )

    assert latest_table[["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": date(2026, 3, 7), "symbol": "BBB"},
        {"trade_date": date(2026, 3, 7), "symbol": "CCC"},
    ]
    assert "Showing latest trade date 2026-03-07 (2 rows, 3 historical rows total)." in latest_caption
    assert full_table[["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": date(2026, 3, 6), "symbol": "AAA"},
        {"trade_date": date(2026, 3, 7), "symbol": "BBB"},
        {"trade_date": date(2026, 3, 7), "symbol": "CCC"},
    ]
    assert "Showing full history (3 rows across 2 trade dates). Latest trade date is 2026-03-07." in full_caption


def test_generate_watchlist_result_falls_back_to_latest_bundle_when_exact_named_exports_are_corrupt(tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    (tmp_path / "daily_symbol_features_full_universe.parquet").write_text("corrupt", encoding="utf-8")
    (tmp_path / "premarket_features_full_universe.parquet").write_text("corrupt", encoding="utf-8")

    manifest = {
        "export_generated_at": "2026-03-06T08:15:00+00:00",
        "source_data_fetched_at": "2026-03-06T08:10:00+00:00",
    }
    (tmp_path / "databento_volatility_production_20260306_081500_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )

    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "previous_close": [10.0],
            "window_range_pct": [2.0],
            "window_return_pct": [1.0],
            "realized_vol_pct": [1.0],
            "selected_top20pct": [True],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "has_premarket_data": [True],
            "premarket_last": [11.0],
            "premarket_volume": [300_000],
            "premarket_trade_count": [800],
            "prev_close_to_premarket_pct": [10.0],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "present_in_eligible": [True],
            "excluded_reason": [""],
        }
    )
    daily.to_parquet(tmp_path / "databento_volatility_production_20260306_081500__daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "databento_volatility_production_20260306_081500__premarket_features_full_universe.parquet", index=False)
    diagnostics.to_parquet(tmp_path / "databento_volatility_production_20260306_081500__symbol_day_diagnostics.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["trade_date"] == "2026-03-06"
    assert result["watchlist_table"].iloc[0]["symbol"] == "BBB"
    assert result["source_metadata"]["source"] == "bundle"
    assert "fallback_reason" in result["source_metadata"]


def test_filter_funnel_returned_when_watchlist_empty(tmp_path: Path) -> None:
    """Filter funnel diagnostic is included when no candidates pass the filters."""
    trade_day = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "exchange": ["NYSE", "NYSE"],
            "asset_type": ["listed_equity_issue", "listed_equity_issue"],
            "previous_close": [10.0, 1.50],
            "window_range_pct": [2.0, 1.0],
            "window_return_pct": [1.0, 0.5],
            "realized_vol_pct": [1.0, 0.5],
            "selected_top20pct": [True, True],
            "is_eligible": [True, True],
            "eligibility_reason": ["eligible", "eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "has_premarket_data": [True, True],
            "premarket_last": [11.0, 1.60],
            "premarket_volume": [500, 200],
            "premarket_trade_count": [5, 2],
            "prev_close_to_premarket_pct": [10.0, 6.67],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(
        export_dir=tmp_path,
        cfg=LongDipConfig(
            top_n=5,
            min_premarket_dollar_volume=5_000.0,
            min_premarket_volume=1_000,
            min_premarket_trade_count=0,
        ),
    )

    assert result["watchlist_table"].empty
    funnel = result["filter_funnel"]
    assert len(funnel) >= 5
    assert funnel[0]["filter"] == "Total symbols"
    assert funnel[0]["remaining"] == 2
    # premarket_dollar_volume >= 5,000 leaves AAA alive, and the stricter share-volume cut then eliminates it.
    pmdv_step = next(s for s in funnel if s["filter"] == "premarket_dollar_volume")
    assert pmdv_step["remaining"] == 1
    vol_step = next(s for s in funnel if s["filter"] == "premarket_volume")
    assert vol_step["remaining"] == 0


def test_filter_funnel_not_returned_when_watchlist_has_results(tmp_path: Path) -> None:
    """Filter funnel is empty when watchlist has candidates (no diagnostic needed)."""
    trade_day = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "previous_close": [10.0],
            "window_range_pct": [2.0],
            "window_return_pct": [1.0],
            "realized_vol_pct": [1.0],
            "selected_top20pct": [True],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "has_premarket_data": [True],
            "premarket_last": [11.0],
            "premarket_volume": [300_000],
            "premarket_trade_count": [800],
            "prev_close_to_premarket_pct": [10.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=5))

    assert len(result["watchlist_table"]) == 1
    assert result["filter_funnel"] == []


def test_load_export_bundle_reads_manifest_and_parquet_frames(tmp_path: Path) -> None:
    manifest_path = tmp_path / "bundle_20260307_120000_manifest.json"
    manifest = {"dataset": "DBEQ.BASIC", "summary_rows": 2}
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    summary_frame = pd.DataFrame({"symbol": ["AAPL", "MSFT"], "value": [1, 2]})
    detail_frame = pd.DataFrame({"symbol": ["AAPL"], "trade_date": ["2026-03-05"]})
    summary_frame.to_parquet(tmp_path / "bundle_20260307_120000__summary.parquet", index=False)
    detail_frame.to_parquet(tmp_path / "bundle_20260307_120000__minute_detail.parquet", index=False)

    payload = load_export_bundle(tmp_path)

    assert payload["manifest_path"] == manifest_path
    assert payload["manifest"] == manifest
    assert set(payload["frames"].keys()) == {"summary", "minute_detail"}
    assert payload["frames"]["summary"].equals(summary_frame)

    summary = build_bundle_summary(payload)
    assert summary["table"].tolist() == ["minute_detail", "summary"]
    assert summary.loc[summary["table"] == "summary", "rows"].iloc[0] == 2


def test_collect_detail_tables_for_summary_combines_unique_symbol_days(monkeypatch) -> None:
    summary = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL", "MSFT"],
            "previous_close": [100.0, 100.0, 200.0],
        }
    )

    calls: list[tuple[str, date, float | None]] = []

    def fake_fetch_symbol_day_detail(*args, **kwargs):
        calls.append((kwargs["symbol"], kwargs["trade_date"], kwargs.get("previous_close")))
        second_detail = pd.DataFrame(
            {
                "timestamp": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")],
                "session": ["regular"],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.05],
                "volume": [10],
                "second_delta_pct": [0.5],
                "from_previous_close_pct": [1.0],
            }
        )
        minute_detail = pd.DataFrame(
            {
                "minute": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")],
                "open": [1.0],
                "high": [1.1],
                "low": [0.9],
                "close": [1.05],
                "volume": [10],
                "seconds": [1],
                "minute_delta_pct": [0.5],
                "cumulative_pct": [0.5],
            }
        )
        return second_detail, minute_detail

    monkeypatch.setattr("databento_volatility_screener.fetch_symbol_day_detail", fake_fetch_symbol_day_detail)

    second_detail_all, minute_detail_all = collect_detail_tables_for_summary(
        "test-key",
        dataset="DBEQ.BASIC",
        summary=summary,
        use_file_cache=True,
        force_refresh=False,
    )

    assert calls == [
        ("AAPL", date(2026, 3, 5), 100.0),
        ("MSFT", date(2026, 3, 6), 200.0),
    ]
    assert second_detail_all[["trade_date", "symbol"]].drop_duplicates().shape[0] == 2
    assert minute_detail_all[["trade_date", "symbol"]].drop_duplicates().shape[0] == 2


def test_resolve_selected_detail_tables_skips_fallback_without_explicit_opt_in() -> None:
    second_detail_all = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "timestamp": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")],
        }
    )
    minute_detail_all = pd.DataFrame()

    fallback_calls: list[str] = []

    def fallback_loader() -> tuple[pd.DataFrame, pd.DataFrame]:
        fallback_calls.append("called")
        return pd.DataFrame({"x": [1]}), pd.DataFrame({"y": [2]})

    second_detail, minute_detail, used_fallback = resolve_selected_detail_tables(
        second_detail_all,
        minute_detail_all,
        selected_date="2026-03-05",
        selected_symbol="AAPL",
        fallback_loader=fallback_loader,
        allow_explicit_refetch=False,
    )

    assert used_fallback is False
    assert fallback_calls == []
    assert len(second_detail) == 1
    assert minute_detail.empty


def test_resolve_selected_detail_tables_uses_fallback_with_explicit_opt_in() -> None:
    second_detail_all = pd.DataFrame()
    minute_detail_all = pd.DataFrame()

    fallback_calls: list[str] = []

    def fallback_loader() -> tuple[pd.DataFrame, pd.DataFrame]:
        fallback_calls.append("called")
        return (
            pd.DataFrame({"timestamp": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")]}),
            pd.DataFrame({"minute": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")]}),
        )

    second_detail, minute_detail, used_fallback = resolve_selected_detail_tables(
        second_detail_all,
        minute_detail_all,
        selected_date="2026-03-05",
        selected_symbol="AAPL",
        fallback_loader=fallback_loader,
        allow_explicit_refetch=True,
    )

    assert used_fallback is True
    assert fallback_calls == ["called"]
    assert len(second_detail) == 1
    assert len(minute_detail) == 1


def test_resolve_selected_detail_tables_does_not_match_unsupported_symbols() -> None:
    second_detail_all = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["CTA-PA"],
            "timestamp": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")],
        }
    )
    minute_detail_all = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["CTA-PA"],
            "minute": [pd.Timestamp("2026-03-05T15:20:00", tz="Europe/Berlin")],
        }
    )

    second_detail, minute_detail, used_fallback = resolve_selected_detail_tables(
        second_detail_all,
        minute_detail_all,
        selected_date="2026-03-05",
        selected_symbol="CTA-PA",
        fallback_loader=None,
        allow_explicit_refetch=False,
    )

    assert used_fallback is False
    assert second_detail.empty
    assert minute_detail.empty


def test_load_daily_bars_accepts_iterator_payload_from_databento(monkeypatch) -> None:
    trading_days = [date(2026, 3, 5)]
    universe_symbols = {"AAPL"}

    class FakeStore:
        def to_df(self, count=None):
            frame = pd.DataFrame(
                {
                    "ts_event": [pd.Timestamp("2026-03-05T00:00:00Z")],
                    "symbol": ["AAPL"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "volume": [1000.0],
                }
            )
            return iter([frame])

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeMetadata:
        def get_dataset_range(self, **kwargs):
            return {"schema": {"ohlcv-1d": {"end": "2026-03-06T00:00:00Z"}}}

    class FakeClient:
        timeseries = FakeTimeseries()
        metadata = FakeMetadata()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    frame = load_daily_bars(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        use_file_cache=False,
    )

    assert len(frame) == 1
    assert frame.iloc[0]["symbol"] == "AAPL"
    assert frame.iloc[0]["trade_date"] == date(2026, 3, 5)


def test_download_nasdaq_trader_text_retries_then_succeeds(monkeypatch) -> None:
    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"Symbol|Security Name|Listing Exchange\n"

    def fake_urlopen(request, timeout, context):
        calls["count"] += 1
        if calls["count"] < 3:
            raise TimeoutError("temporary network issue")
        return FakeResponse()

    monkeypatch.setattr("databento_volatility_screener.urlopen", fake_urlopen)
    monkeypatch.setattr("databento_volatility_screener.time_module.sleep", lambda _: None)

    payload = _download_nasdaq_trader_text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt")

    assert "Symbol|Security Name|Listing Exchange" in payload
    assert calls["count"] == 3


def test_download_nasdaq_trader_text_retries_on_http_429_then_succeeds(monkeypatch) -> None:
    from urllib.error import HTTPError

    calls = {"count": 0}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"Symbol|Security Name|Listing Exchange\n"

    def fake_urlopen(request, timeout, context):
        calls["count"] += 1
        if calls["count"] < 3:
            raise HTTPError(request.full_url, 429, "too many requests", hdrs=None, fp=None)
        return FakeResponse()

    monkeypatch.setattr("databento_volatility_screener.urlopen", fake_urlopen)
    monkeypatch.setattr("databento_volatility_screener.time_module.sleep", lambda _: None)

    payload = _download_nasdaq_trader_text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt")

    assert "Symbol|Security Name|Listing Exchange" in payload
    assert calls["count"] == 3


def test_download_nasdaq_trader_text_raises_after_retries_for_http_error_statuses(monkeypatch) -> None:
    from urllib.error import HTTPError

    status_codes = [401, 403, 500]
    for status_code in status_codes:
        calls = {"count": 0}

        def fake_urlopen(request, timeout, context, *, _status_code=status_code):
            calls["count"] += 1
            raise HTTPError(request.full_url, _status_code, "failure", hdrs=None, fp=None)

        monkeypatch.setattr("databento_volatility_screener.urlopen", fake_urlopen)
        monkeypatch.setattr("databento_volatility_screener.time_module.sleep", lambda _: None)

        try:
            _download_nasdaq_trader_text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt")
        except HTTPError as exc:
            assert exc.code == status_code
        else:
            raise AssertionError(f"Expected HTTPError for status code {status_code}")
        assert calls["count"] == 3


def test_build_daily_features_full_universe_materializes_expected_symbol_days() -> None:
    trading_days = [date(2026, 3, 5), date(2026, 3, 6)]
    universe = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT"],
            "company_name": ["Apple", "Microsoft"],
            "market_cap": [1.0, 2.0],
        }
    )
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6), date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL", "MSFT", "MSFT"],
            "open": [100.0, 102.0, 200.0, 198.0],
            "high": [103.0, 105.0, 202.0, 201.0],
            "low": [99.0, 101.0, 195.0, 197.0],
            "close": [101.0, 104.0, 198.0, 199.0],
            "volume": [1000.0, 1200.0, 800.0, 900.0],
            "previous_close": [99.0, 101.0, 201.0, 198.0],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "MSFT"],
            "previous_close": [99.0, 198.0],
            "premarket_price": [100.0, None],
            "has_premarket_data": [True, False],
            "market_open_price": [101.0, 199.0],
            "window_start_price": [100.5, 199.0],
            "current_price": [102.0, 198.5],
            "window_high": [102.0, 200.0],
            "window_low": [100.0, 198.0],
            "window_volume": [150.0, 75.0],
            "seconds_in_window": [4, 2],
            "window_return_pct": [1.5, -0.2],
            "window_range_pct": [2.0, 1.0],
            "realized_vol_pct": [1.0, 0.5],
            "prev_close_to_premarket_abs": [1.0, None],
            "prev_close_to_premarket_pct": [1.0101, None],
            "premarket_to_open_abs": [1.0, None],
            "premarket_to_open_pct": [1.0, None],
            "open_to_current_abs": [1.0, -0.5],
            "open_to_current_pct": [0.9901, -0.2513],
        }
    )
    second_detail_all = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL", "MSFT"],
            "timestamp": [
                pd.Timestamp("2026-03-05T15:30:00", tz="Europe/Berlin"),
                pd.Timestamp("2026-03-05T15:30:30", tz="Europe/Berlin"),
                pd.Timestamp("2026-03-06T15:30:10", tz="Europe/Berlin"),
            ],
            "session": ["regular", "regular", "regular"],
            "open": [101.0, 101.2, 199.0],
            "high": [101.2, 101.5, 199.2],
            "low": [100.9, 101.1, 198.9],
            "close": [101.1, 101.4, 199.1],
            "volume": [10.0, 20.0, 30.0],
            "second_delta_pct": [None, 0.2967, None],
            "from_previous_close_pct": [2.1212, 2.4242, 0.5556],
        }
    )

    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail_all,
        display_timezone="Europe/Berlin",
        premarket_anchor_et=time(8, 0),
    )

    assert features[["trade_date", "symbol"]].drop_duplicates().shape[0] == 4
    assert coverage[["trade_date", "symbol"]].drop_duplicates().shape[0] == 4
    aapl_day = features[(features["trade_date"] == date(2026, 3, 5)) & (features["symbol"] == "AAPL")].iloc[0]
    assert bool(aapl_day["has_premarket_data"]) is True
    assert float(aapl_day["open_1m_volume"]) == 30.0
    assert float(aapl_day["open_30s_volume"]) == 10.0
    assert float(aapl_day["regular_open_reference_price"]) == 101.0
    assert round(float(aapl_day["early_dip_pct_10s"]), 4) == -0.0990
    assert float(aapl_day["early_dip_second"]) == 0.0
    assert bool(aapl_day["reclaimed_start_price_within_30s"]) is False
    assert pd.isna(aapl_day["reclaim_second_30s"])
    assert aapl_day["premarket_price_source"] == "last_ohlcv_1s_close_between_anchor_and_regular_open"
    missing_row = coverage[(coverage["trade_date"] == date(2026, 3, 6)) & (coverage["symbol"] == "AAPL")].iloc[0]
    assert bool(missing_row["has_daily_bar"]) is True
    assert bool(missing_row["has_open_window_detail"]) is False
    assert missing_row["exclusion_reason"] == "missing_intraday_summary"


def test_build_entry_checklist_table_applies_exact_long_setup_rules() -> None:
    status = DataStatusResult(
        export_generated_at=datetime.now(UTC).isoformat(),
        daily_bars_fetched_at=None,
        intraday_fetched_at=None,
        premarket_fetched_at=None,
        second_detail_fetched_at=None,
        dataset="XNAS.BASIC",
        lookback_days=5,
        trade_dates_covered=("2026-03-05",),
        is_stale=False,
        staleness_reason="",
        manifest_path=None,
    )
    selected_row = pd.Series(
        {
            "prev_close_to_premarket_pct": 6.2,
            "premarket_dollar_volume": 750_000.0,
            "early_dip_pct_10s": -0.7,
            "early_dip_second": 4.0,
            "open_30s_volume": 12_000.0,
            "reclaimed_start_price_within_30s": True,
            "reclaim_second_30s": 14.0,
        }
    )

    checklist, rule_note, score = build_entry_checklist_table(
        status=status,
        selected_row=selected_row,
        watchlist_table=pd.DataFrame(),
        watchlist_config=None,
    )

    assert score == 5
    assert checklist["erfuellt"].tolist() == [True, True, True, True, True]
    assert "Gap >= 5.0%" in rule_note


def test_build_daily_features_full_universe_handles_missing_open_window_rows_column() -> None:
    trading_days = [date(2026, 3, 5)]
    universe = pd.DataFrame({"symbol": ["AAPL"]})
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [1000.0],
            "previous_close": [99.5],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "current_price": [100.5],
        }
    )
    second_detail_all = pd.DataFrame(columns=["trade_date", "symbol", "timestamp", "volume"])

    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail_all,
    )

    assert bool(features.loc[0, "has_open_window_detail"]) is False
    assert int(coverage.loc[0, "open_window_second_rows"]) == 0
    assert bool(coverage.loc[0, "has_open_window_detail"]) is False


def test_fetch_symbol_day_detail_uses_exclusive_intraday_end(monkeypatch) -> None:
    captured: dict[str, str] = {}

    class FakeStore:
        def to_df(self):
            return pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "open": [100.0],
                    "high": [101.0],
                    "low": [99.0],
                    "close": [100.5],
                    "volume": [10],
                },
                index=pd.DatetimeIndex([pd.Timestamp("2026-03-05T14:30:00Z")], name="ts_event"),
            )

    class FakeTimeseries:
        def get_range(self, **kwargs):
            captured.update(kwargs)
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    fetch_symbol_day_detail("test-key", dataset="DBEQ.BASIC", symbol="AAPL", trade_date=date(2026, 3, 5))

    assert captured["end"] == "2026-03-05T15:00:01+00:00"


def test_fetch_symbol_day_detail_collapses_duplicate_symbol_seconds(monkeypatch) -> None:
    duplicate_ts = pd.Timestamp("2026-03-05T14:30:00Z")
    next_ts = pd.Timestamp("2026-03-05T14:30:01Z")

    class FakeStore:
        def to_df(self):
            return pd.DataFrame(
                {
                    "symbol": ["AAPL", "AAPL", "AAPL"],
                    "open": [10.0, 10.2, 12.5],
                    "high": [11.0, 13.0, 12.7],
                    "low": [9.5, 10.1, 12.4],
                    "close": [10.5, 12.5, 12.6],
                    "volume": [100, 250, 50],
                },
                index=pd.DatetimeIndex([duplicate_ts, duplicate_ts, next_ts], name="ts_event"),
            )

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    second_detail, minute_detail = fetch_symbol_day_detail(
        "test-key",
        dataset="DBEQ.BASIC",
        symbol="AAPL",
        trade_date=date(2026, 3, 5),
        previous_close=10.0,
    )

    assert len(second_detail) == 2
    first = second_detail.sort_values("timestamp").iloc[0]
    assert first["open"] == 10.0
    assert first["high"] == 13.0
    assert first["low"] == 9.5
    assert first["close"] == 12.5
    assert first["volume"] == 350
    assert len(minute_detail) == 1
    assert minute_detail.iloc[0]["volume"] == 400


def test_collapse_duplicate_symbol_seconds_sums_trade_count_alias_columns() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["AAA", "AAA"],
            "ts": [pd.Timestamp("2026-03-05T14:30:00Z"), pd.Timestamp("2026-03-05T14:30:00Z")],
            "open": [10.0, 10.2],
            "high": [10.5, 10.6],
            "low": [9.9, 10.1],
            "close": [10.1, 10.4],
            "volume": [100, 200],
            "trade_count": [3, 7],
            "n_trades": [11, 13],
        }
    )

    collapsed = _collapse_duplicate_symbol_seconds(frame, context="unit-test")

    assert len(collapsed) == 1
    assert int(collapsed.iloc[0]["trade_count"]) == 10
    assert int(collapsed.iloc[0]["n_trades"]) == 24


def test_deduplicate_daily_symbol_rows_uses_close_as_tie_breaker_when_volume_matches() -> None:
    trade_day = date(2026, 3, 6)
    frame = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "AAA"],
            "open": [10.0, 10.0],
            "high": [10.4, 10.5],
            "low": [9.8, 9.9],
            "close": [10.2, 10.3],
            "volume": [1_000.0, 1_000.0],
        }
    )

    deduped = _deduplicate_daily_symbol_rows(frame)

    assert len(deduped) == 1
    assert float(deduped.iloc[0]["close"]) == 10.3


def test_estimate_databento_costs_uses_exclusive_daily_and_intraday_ends(monkeypatch) -> None:
    cost_calls: list[dict[str, str]] = []
    size_calls: list[dict[str, str]] = []

    class FakeMetadata:
        def get_cost(self, **kwargs):
            cost_calls.append(kwargs)
            return 1.0

        def get_billable_size(self, **kwargs):
            size_calls.append(kwargs)
            return 100

    class FakeClient:
        metadata = FakeMetadata()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())
    monkeypatch.setattr(
        "databento_volatility_screener._get_schema_available_end",
        lambda client, dataset, schema: pd.Timestamp("2026-03-06T00:00:00Z") if schema == "ohlcv-1d" else None,
    )

    estimate_databento_costs("test-key", dataset="DBEQ.BASIC", trading_days=[date(2026, 3, 5)])

    assert cost_calls[0]["schema"] == "ohlcv-1d"
    assert cost_calls[0]["end"] == "2026-03-06"
    assert size_calls[0]["end"] == "2026-03-06"
    assert cost_calls[1]["schema"] == "ohlcv-1s"
    assert cost_calls[1]["end"] == "2026-03-05T15:00:01+00:00"
    assert size_calls[1]["end"] == "2026-03-05T15:00:01+00:00"


def test_export_run_artifacts_defaults_exported_at_to_utc(tmp_path) -> None:
    created = export_run_artifacts(
        export_dir=tmp_path,
        basename="bundle_20260308_120000",
        summary=pd.DataFrame({"symbol": ["AAPL"]}),
        universe=pd.DataFrame({"symbol": ["AAPL"]}),
        daily_bars=pd.DataFrame({"symbol": ["AAPL"]}),
        intraday=pd.DataFrame({"symbol": ["AAPL"]}),
        ranked=pd.DataFrame({"symbol": ["AAPL"]}),
    )

    manifest = json.loads(created["manifest"].read_text(encoding="utf-8"))

    assert manifest["exported_at"].endswith("+00:00")


def test_export_run_artifacts_writes_tradingview_txt_for_exchange_symbol_frames(tmp_path) -> None:
    created = export_run_artifacts(
        export_dir=tmp_path,
        basename="bundle_20260308_120000",
        summary=pd.DataFrame({"symbol": ["AAPL"], "exchange": ["NASDAQ"]}),
        universe=pd.DataFrame({"symbol": ["AAPL"], "exchange": ["NASDAQ"]}),
        daily_bars=pd.DataFrame({"symbol": ["AAPL"]}),
        intraday=pd.DataFrame({"symbol": ["AAPL"]}),
        ranked=pd.DataFrame({"symbol": ["MSFT"], "exchange": ["NASDAQ"]}),
        additional_parquet_targets={
            "watch_candidates": pd.DataFrame(
                {
                    "symbol": ["EQX", "GBR"],
                    "exchange": ["AMEX", "AMEX"],
                }
            )
        },
    )

    assert created["txt_summary"].name == "bundle_20260308_120000__summary.txt"
    assert created["txt_universe"].name == "bundle_20260308_120000__universe.txt"
    assert created["txt_ranked"].name == "bundle_20260308_120000__ranked.txt"
    assert created["txt_watch_candidates"].name == "bundle_20260308_120000__watch_candidates.txt"
    assert created["txt_summary"].read_text(encoding="utf-8") == "NASDAQ:AAPL,"
    assert created["txt_universe"].read_text(encoding="utf-8") == "NASDAQ:AAPL,"
    assert created["txt_ranked"].read_text(encoding="utf-8") == "NASDAQ:MSFT,"
    assert created["txt_watch_candidates"].read_text(encoding="utf-8") == "AMEX:EQX,AMEX:GBR,"


def test_export_run_artifacts_skips_tradingview_txt_when_symbol_or_exchange_missing(tmp_path) -> None:
    created = export_run_artifacts(
        export_dir=tmp_path,
        basename="bundle_20260308_120001",
        summary=pd.DataFrame({"value": [1]}),
        universe=pd.DataFrame({"symbol": ["AAPL"]}),
        daily_bars=pd.DataFrame({"symbol": ["AAPL"]}),
        intraday=pd.DataFrame({"symbol": ["AAPL"]}),
        ranked=pd.DataFrame({"exchange": ["NASDAQ"]}),
    )

    assert "txt_summary" not in created
    assert "txt_universe" not in created
    assert "txt_ranked" not in created


# ── P2: Mocked tests for previously untested critical functions ──────────


def test_update_state_from_chunk_accumulates_premarket_and_regular_session() -> None:
    """_update_state_from_chunk correctly separates premarket vs regular data."""
    window = build_window_definition(
        date(2026, 3, 5),
        display_timezone="Europe/Berlin",
        window_start=time(15, 20),
        window_end=time(16, 0),
        premarket_anchor_et=time(8, 0),
    )
    # Create a chunk spanning premarket and regular session
    premarket_ts = pd.Timestamp("2026-03-05T13:30:00Z")  # 8:30 ET – premarket
    regular_ts = pd.Timestamp("2026-03-05T14:30:00Z")    # 9:30 ET – regular open
    window_ts = pd.Timestamp("2026-03-05T14:35:00Z")     # inside 15:35 Berlin window

    chunk = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "open": [150.0, 151.0, 151.5],
            "high": [150.5, 151.5, 152.0],
            "low": [149.5, 150.8, 151.0],
            "close": [150.2, 151.2, 151.8],
            "volume": [100, 200, 300],
        },
        index=pd.DatetimeIndex([premarket_ts, regular_ts, window_ts], name="ts_event"),
    )

    states: dict[str, SymbolDayState] = {}
    _update_state_from_chunk(chunk, window=window, universe_symbols={"AAPL"}, states=states)

    assert "AAPL" in states
    state = states["AAPL"]
    assert state.premarket_price == 150.2  # premarket close
    assert state.market_open_price == 151.0  # first regular open


def test_update_state_from_chunk_handles_empty_chunk() -> None:
    """_update_state_from_chunk is a no-op on empty DataFrames."""
    window = build_window_definition(
        date(2026, 3, 5),
        display_timezone="Europe/Berlin",
        window_start=time(15, 20),
        window_end=time(16, 0),
        premarket_anchor_et=time(8, 0),
    )
    states: dict[str, SymbolDayState] = {}
    _update_state_from_chunk(pd.DataFrame(), window=window, universe_symbols=None, states=states)
    assert states == {}


def test_load_daily_bars_transforms_and_filters_correctly(monkeypatch) -> None:
    """load_daily_bars applies symbol filtering, trade_date filtering, and previous_close shift."""
    raw_df = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL", "MSFT", "MSFT", "MSFT"],
            "open": [100, 102, 104, 200, 198, 202],
            "high": [101, 103, 105, 201, 199, 203],
            "low": [99, 101, 103, 199, 197, 201],
            "close": [100.5, 102.5, 104.5, 200.5, 198.5, 202.5],
            "volume": [1000, 1100, 1200, 2000, 2100, 2200],
        },
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-02-25T00:00Z"),
                pd.Timestamp("2026-03-04T00:00Z"),
                pd.Timestamp("2026-03-05T00:00Z"),
                pd.Timestamp("2026-02-25T00:00Z"),
                pd.Timestamp("2026-03-04T00:00Z"),
                pd.Timestamp("2026-03-05T00:00Z"),
            ],
            name="ts_event",
        ),
    )

    class FakeStore:
        def to_df(self):
            return raw_df

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())
    monkeypatch.setattr(
        "databento_volatility_screener._get_schema_available_end",
        lambda client, dataset, schema: None,
    )

    trading_days = [date(2026, 3, 4), date(2026, 3, 5)]
    result = load_daily_bars(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=trading_days,
        universe_symbols={"AAPL"},  # only AAPL, exclude MSFT
    )

    # Should only have AAPL rows for the requested trading days
    assert set(result["symbol"].unique()) == {"AAPL"}
    assert sorted(result["trade_date"].unique()) == trading_days
    # previous_close for Mar 4 should be Feb 25's close
    mar4 = result[result["trade_date"] == date(2026, 3, 4)].iloc[0]
    assert mar4["previous_close"] == 100.5
    # previous_close for Mar 5 should be Mar 4's close
    mar5 = result[result["trade_date"] == date(2026, 3, 5)].iloc[0]
    assert mar5["previous_close"] == 102.5


def test_load_daily_bars_deduplicates_symbol_day_using_highest_volume(monkeypatch) -> None:
    raw_df = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL", "AAPL"],
            "open": [100, 102, 103, 104],
            "high": [101, 103, 104, 105],
            "low": [99, 101, 102, 103],
            "close": [100.5, 102.5, 103.5, 104.5],
            "volume": [1000, 1100, 5000, 1200],
        },
        index=pd.DatetimeIndex(
            [
                pd.Timestamp("2026-02-25T00:00Z"),
                pd.Timestamp("2026-03-04T00:00Z"),
                pd.Timestamp("2026-03-04T00:00Z"),
                pd.Timestamp("2026-03-05T00:00Z"),
            ],
            name="ts_event",
        ),
    )

    class FakeStore:
        def to_df(self):
            return raw_df

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())
    monkeypatch.setattr(
        "databento_volatility_screener._get_schema_available_end",
        lambda client, dataset, schema: None,
    )

    result = load_daily_bars(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 4), date(2026, 3, 5)],
        universe_symbols={"AAPL"},
    )

    assert len(result) == 2
    mar4 = result[result["trade_date"] == date(2026, 3, 4)].iloc[0]
    mar5 = result[result["trade_date"] == date(2026, 3, 5)].iloc[0]
    assert mar4["close"] == 103.5
    assert mar4["volume"] == 5000
    assert mar4["previous_close"] == 100.5
    assert mar5["previous_close"] == 103.5


def test_load_daily_bars_returns_empty_for_no_trading_days() -> None:
    """load_daily_bars with empty trading_days returns a correctly-shaped empty frame."""
    result = load_daily_bars("test-key", dataset="DBEQ.BASIC", trading_days=[], universe_symbols={"AAPL"})
    assert result.empty
    assert "previous_close" in result.columns


def test_run_intraday_screen_handles_empty_universe(monkeypatch) -> None:
    """run_intraday_screen with no universe symbols returns an empty frame."""
    class FakeClient:
        pass

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    result = run_intraday_screen(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 5)],
        universe_symbols=set(),
        daily_bars=pd.DataFrame(columns=["trade_date", "symbol", "previous_close"]),
    )
    assert result.empty


def test_run_intraday_screen_produces_intraday_summaries(monkeypatch) -> None:
    """run_intraday_screen creates per-symbol summaries from mocked 1s data."""
    regular_ts = pd.Timestamp("2026-03-05T14:30:00Z")
    window_ts1 = pd.Timestamp("2026-03-05T14:20:00Z")  # 15:20 Berlin (CET)
    window_ts2 = pd.Timestamp("2026-03-05T14:21:00Z")

    raw_df = pd.DataFrame(
        {
            "symbol": ["AAPL", "AAPL", "AAPL"],
            "open": [150.0, 151.0, 151.5],
            "high": [150.5, 151.5, 152.0],
            "low": [149.5, 150.8, 151.0],
            "close": [150.2, 151.2, 151.8],
            "volume": [100, 200, 300],
        },
        index=pd.DatetimeIndex([regular_ts, window_ts1, window_ts2], name="ts_event"),
    )

    class FakeStore:
        def to_df(self, count=None):
            return raw_df

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr("databento_volatility_screener._make_databento_client", lambda api_key: FakeClient())

    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "previous_close": [149.0],
        }
    )

    result = run_intraday_screen(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 5)],
        universe_symbols={"AAPL"},
        daily_bars=daily_bars,
    )

    assert len(result) >= 1
    assert "AAPL" in result["symbol"].values
    assert "window_volume" in result.columns


def test_coerce_timestamp_frame_handles_various_index_types() -> None:
    """_coerce_timestamp_frame normalizes DatetimeIndex, ts_event, and ts_recv columns."""
    # DatetimeIndex
    df1 = pd.DataFrame(
        {"close": [1.0]},
        index=pd.DatetimeIndex([pd.Timestamp("2026-03-05T14:30:00Z")]),
    )
    result1 = _coerce_timestamp_frame(df1)
    assert "ts" in result1.columns

    # ts_event column
    df2 = pd.DataFrame(
        {"ts_event": [pd.Timestamp("2026-03-05T14:30:00Z")], "close": [1.0]}
    )
    result2 = _coerce_timestamp_frame(df2)
    assert "ts" in result2.columns

    # ts_recv column
    df3 = pd.DataFrame(
        {"ts_recv": [pd.Timestamp("2026-03-05T14:30:00Z")], "close": [1.0]}
    )
    result3 = _coerce_timestamp_frame(df3)
    assert "ts" in result3.columns


def test_symbol_support_cache_ttl_expires_stale_entries(tmp_path) -> None:
    """_read_symbol_support_cache returns empty dict when the cache file is older than TTL."""
    import os

    cache_path = tmp_path / "support_cache.parquet"
    _write_symbol_support_cache(cache_path, {"AAPL": True, "BADX": False})
    # Fresh cache should return data
    result_fresh = _read_symbol_support_cache(cache_path)
    assert result_fresh == {"AAPL": True, "BADX": False}

    # Backdate the file to exceed TTL
    old_mtime = cache_path.stat().st_mtime - SYMBOL_SUPPORT_CACHE_TTL_SECONDS - 60
    os.utime(cache_path, (old_mtime, old_mtime))
    result_stale = _read_symbol_support_cache(cache_path)
    assert result_stale == {}


def test_run_intraday_screen_survives_api_error(monkeypatch) -> None:
    """run_intraday_screen logs and continues when a batch API call fails."""
    call_count = {"n": 0}

    class _FakeStore:
        def to_df(self, count=None):
            return pd.DataFrame()

    class _FakeTimeseries:
        def get_range(self, **kwargs):
            call_count["n"] += 1
            raise RuntimeError("simulated API failure")

    class _FakeClient:
        timeseries = _FakeTimeseries()

    monkeypatch.setattr(
        "databento_volatility_screener._make_databento_client",
        lambda key: _FakeClient(),
    )
    daily_bars = pd.DataFrame({
        "trade_date": [date(2026, 3, 5)],
        "symbol": ["AAPL"],
        "previous_close": [150.0],
    })
    result = run_intraday_screen(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 5)],
        universe_symbols={"AAPL"},
        daily_bars=daily_bars,
    )
    assert result.empty or isinstance(result, pd.DataFrame)
    assert call_count["n"] >= 1


def test_load_daily_bars_survives_batch_api_error(monkeypatch) -> None:
    """load_daily_bars logs and continues when a batch fails."""
    class _FakeTimeseries:
        def get_range(self, **kwargs):
            raise RuntimeError("simulated API failure")

    class _FakeMetadata:
        def get_dataset_range(self, dataset):
            return {"start": "2026-01-01", "end": "2026-03-06"}

    class _FakeClient:
        timeseries = _FakeTimeseries()
        metadata = _FakeMetadata()

    monkeypatch.setattr(
        "databento_volatility_screener._make_databento_client",
        lambda key: _FakeClient(),
    )
    result = load_daily_bars(
        "test-key",
        dataset="DBEQ.BASIC",
        trading_days=[date(2026, 3, 5)],
        universe_symbols={"AAPL"},
    )
    assert result.empty


def test_probe_symbol_support_survives_api_error(monkeypatch) -> None:
    """_probe_symbol_support treats batch failures as supported (safe default)."""
    class _FakeTimeseries:
        def get_range(self, **kwargs):
            raise RuntimeError("simulated API failure")

    class _FakeMetadata:
        def get_dataset_condition(self, **kwargs):
            return [{"date": "2026-03-04", "condition": "available"}]

    class _FakeClient:
        timeseries = _FakeTimeseries()
        metadata = _FakeMetadata()

    monkeypatch.setattr(
        "databento_volatility_screener._make_databento_client",
        lambda key: _FakeClient(),
    )
    result = _probe_symbol_support("test-key", dataset="DBEQ.BASIC", symbols=["AAPL", "MSFT"])
    # Symbols should default to supported on error
    assert result.get("AAPL") is True
    assert result.get("MSFT") is True


def test_fetch_symbol_day_detail_survives_api_error(monkeypatch) -> None:
    """fetch_symbol_day_detail returns empty DataFrames on API failure."""
    class _FakeTimeseries:
        def get_range(self, **kwargs):
            raise RuntimeError("simulated API failure")

    class _FakeClient:
        timeseries = _FakeTimeseries()

    monkeypatch.setattr(
        "databento_volatility_screener._make_databento_client",
        lambda key: _FakeClient(),
    )
    second, minute = fetch_symbol_day_detail(
        "test-key", dataset="DBEQ.BASIC", symbol="AAPL", trade_date=date(2026, 3, 5),
    )
    assert second.empty
    assert minute.empty

def test_build_summary_table_no_suffix_leak_on_overlapping_columns() -> None:
    """When ranked already contains columns from the universe (e.g. exchange,
    sector), the merge must NOT create _x/_y suffixed duplicates."""
    ranked = pd.DataFrame(
        {
            "trade_date": [date(2026, 4, 1)],
            "rank": [1],
            "symbol": ["TSLA"],
            "exchange": ["NASDAQ"],
            "sector": ["Tech"],
            "market_cap": [800e9],
            "previous_close": [200.0],
            "premarket_price": [202.0],
            "market_open_price": [204.0],
            "current_price": [210.0],
        }
    )
    universe = pd.DataFrame(
        {
            "symbol": ["TSLA"],
            "exchange": ["NASDAQ"],
            "sector": ["Tech"],
            "market_cap": [800e9],
            "company_name": ["Tesla Inc"],
        }
    )
    summary = build_summary_table(ranked, universe)
    suffix_cols = [c for c in summary.columns if c.endswith("_x") or c.endswith("_y")]
    assert suffix_cols == [], f"Unexpected suffix columns: {suffix_cols}"
    assert "company_name" in summary.columns, "Universe-only column should be merged in"
    assert summary.iloc[0]["exchange"] == "NASDAQ"
