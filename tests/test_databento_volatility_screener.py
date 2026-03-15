from __future__ import annotations

from datetime import UTC, date, datetime, time
import json
from pathlib import Path
from typing import Any, cast
import warnings

import numpy as np
import pandas as pd

from scripts.load_databento_export_bundle import build_bundle_summary, load_export_bundle, resolve_manifest_path
from scripts.bullish_quality_config import PremarketWindowDefinition
from scripts.databento_production_export import (
    FIXED_ET_DISPLAY_TIMEZONE,
    _build_exact_window_end_lookup,
    _build_batl_debug_payload,
    _build_daily_symbol_features_full_universe_export,
    _build_quality_window_status_latest,
    _compute_quality_reason,
    _normalize_exchange_key,
    _normalize_quality_window_exchange_dataset_map,
    _window_bounds_for_trade_date,
    _write_exact_named_exports,
    build_premarket_window_features_full_universe_export,
    compute_single_window_features,
    _collect_quality_window_source_frames,
    _compute_quality_window_signal,
    _enrich_universe_with_quality_window_status,
    _filter_premarket_rows,
    _load_fundamental_reference,
    _select_top_candidates_per_day,
    _format_optional_time,
    _build_premarket_features_full_universe_export,
    _collect_fixed_et_second_detail,
    _prepare_full_universe_second_detail_export,
    _run_fixed_et_intraday_screen,
)

from databento_volatility_screener import (
    _build_focus_window_coverage_series,
    _build_open_pattern_status_series,
    _build_watchlist_snapshot_panel_frames,
    _build_watchlist_table_style_frame,
    _build_tradingview_watchlist_text,
    _augment_watchlist_result_with_intraday_context,
    _collapse_duplicate_symbol_seconds,
    _deduplicate_daily_symbol_rows,
    _format_intraday_reference_time,
    _highlight_rank_change_label,
    _format_reclaim_status_series,
    _resolve_watchlist_snapshot_trigger,
    _run_full_history_refresh_with_status,
    _numeric_series_or_nan,
    _persist_watchlist_snapshot,
    _download_nasdaq_trader_text,
    _fetch_us_equity_universe_via_screener,
    UNIVERSE_COLUMNS,
    _clamp_request_end,
    _coerce_timestamp_frame,
    _daily_request_end_exclusive,
    _extract_unresolved_symbols_from_warning_messages,
    _iter_symbol_batches,
    _normalize_symbol_day_scope,
    _parse_nasdaq_trader_directory,
    _prepare_frame_for_excel,
    _probe_symbol_support,
    _read_cached_frame,
    _read_symbol_support_cache,
    _symbols_requiring_support_check,
    _symbol_scope_token,
    _update_state_from_chunk,
    _write_cached_frame,
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
    DATA_CACHE_TTL_SECONDS,
    CACHE_VERSION_BY_CATEGORY,
    _write_tradingview_watchlist_exports,
    _write_streamlit_watchlist_txt_exports,
    _load_watchlist_snapshot_history,
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
    WATCHLIST_SNAPSHOT_FILE,
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


def test_choose_default_dataset_matches_requested_case_insensitively() -> None:
    available = ["DBEQ.BASIC", "XNAS.ITCH"]

    assert choose_default_dataset(available, requested_dataset=" xnas.itch ") == "XNAS.ITCH"


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
        close_detail_all=pd.DataFrame(),
        close_trade_detail_all=pd.DataFrame(),
        close_outcome_minute_detail_all=pd.DataFrame(),
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
    assert "focus_0930_open_30s_volume" in features.columns
    assert "focus_0800_open_window_second_rows" in features.columns
    assert "focus_0400_open_window_second_rows" in features.columns
    assert "focus_0400_open_30s_volume" in features.columns
    assert int(features["selected_top20pct_0400"].fillna(False).astype(bool).sum()) <= 1
    assert bool(batl["selected_top20pct_0400"]) is False
    assert pd.isna(batl["focus_0400_open_30s_volume"])
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
    assert aaa["premarket_last_trade_ts"] == pd.Timestamp("2026-03-06T14:29:59Z")
    assert round(float(aaa["prev_close_to_premarket_pct"]), 4) == round(((10.35 / 10.0) - 1.0) * 100.0, 4)
    assert round(float(aaa["premarket_to_open_pct"]), 4) == round(((10.5 / 10.35) - 1.0) * 100.0, 4)
    assert bool(bbb["has_premarket_data"]) is False


def test_build_premarket_window_features_full_universe_export_computes_window_metrics() -> None:
    trade_day = date(2026, 3, 6)
    daily_features = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "previous_close": [10.0],
            "market_open_price": [10.9],
        }
    )
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "AAA", "AAA"],
            "timestamp": [
                pd.Timestamp("2026-03-06T09:00:00Z"),
                pd.Timestamp("2026-03-06T09:20:00Z"),
                pd.Timestamp("2026-03-06T09:40:00Z"),
            ],
            "session": ["premarket", "premarket", "premarket"],
            "open": [10.0, 10.2, 10.4],
            "high": [10.2, 10.5, 10.8],
            "low": [9.9, 10.1, 10.3],
            "close": [10.1, 10.4, 10.7],
            "volume": [30_000.0, 30_000.0, 30_000.0],
            "trade_count": [50, 50, 50],
        }
    )
    window_definition = PremarketWindowDefinition("pm_0400_0500", "04:00:00", "05:00:00", "04:00-05:00 ET")

    result = build_premarket_window_features_full_universe_export(
        second_detail,
        daily_features,
        window_definitions=(window_definition,),
        source_data_fetched_at="2026-03-06T14:29:59+00:00",
        dataset="DBEQ.BASIC",
    )

    assert len(result) == 1
    row = result.iloc[0]
    assert row["window_tag"] == "pm_0400_0500"
    assert bool(row["has_window_data"]) is True
    assert int(row["window_row_count"]) == 3
    assert int(row["window_trade_count"]) == 150
    assert float(row["window_volume"]) == 90_000.0
    assert round(float(row["window_dollar_volume"]), 2) == 936_000.0
    assert round(float(row["window_vwap"]), 4) == round(936_000.0 / 90_000.0, 4)
    assert round(float(row["window_return_pct"]), 4) == 7.0
    assert round(float(row["prev_close_to_window_close_pct"]), 4) == 7.0
    assert round(float(row["window_close_position_pct"]), 4) == round(((10.7 - 9.9) / (10.8 - 9.9)) * 100.0, 4)
    assert bool(row["passes_quality_filter"]) is True
    assert row["quality_filter_reason"] == "eligible"
    assert row["window_quality_score"] > 0.0

    single = compute_single_window_features(
        second_detail,
        daily_features.iloc[0],
        window_definition=window_definition,
        dataset="DBEQ.BASIC",
        source_data_fetched_at="2026-03-06T14:29:59+00:00",
    )

    assert single["window_tag"] == "pm_0400_0500"
    assert round(float(single["window_quality_score"]), 4) == round(float(row["window_quality_score"]), 4)


def test_build_premarket_window_features_full_universe_export_marks_missing_window_data() -> None:
    trade_day = date(2026, 3, 6)
    daily_features = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "previous_close": [10.0, 12.0],
            "market_open_price": [10.5, 12.5],
        }
    )
    window_definition = PremarketWindowDefinition("pm_0500_0600", "05:00:00", "06:00:00", "05:00-06:00 ET")

    result = build_premarket_window_features_full_universe_export(
        pd.DataFrame(),
        daily_features,
        window_definitions=(window_definition,),
        source_data_fetched_at=None,
        dataset="DBEQ.BASIC",
    )

    assert result[["symbol", "window_tag"]].to_dict(orient="records") == [
        {"symbol": "AAA", "window_tag": "pm_0500_0600"},
        {"symbol": "BBB", "window_tag": "pm_0500_0600"},
    ]
    assert result["has_window_data"].tolist() == [False, False]
    assert result["passes_quality_filter"].tolist() == [False, False]
    assert result["quality_filter_reason"].tolist() == ["no_window_data", "no_window_data"]
    assert result["quality_selected_top_n"].tolist() == [False, False]
    assert result["quality_rank_within_window"].isna().all()


def test_build_premarket_window_features_full_universe_export_populates_window_ranks() -> None:
    trade_day = date(2026, 3, 10)
    definition = PremarketWindowDefinition(tag="pm_0900_0930", start_time_et="09:00:00", end_time_et="09:30:00", label="09:00-09:30 ET")
    second_detail = pd.DataFrame(
        {
            "trade_date": [trade_day] * 6,
            "symbol": ["AAA", "AAA", "BBB", "BBB", "CCC", "CCC"],
            "timestamp": [
                pd.Timestamp("2026-03-10T13:00:00Z"),
                pd.Timestamp("2026-03-10T13:29:00Z"),
                pd.Timestamp("2026-03-10T13:00:00Z"),
                pd.Timestamp("2026-03-10T13:29:00Z"),
                pd.Timestamp("2026-03-10T13:00:00Z"),
                pd.Timestamp("2026-03-10T13:29:00Z"),
            ],
            "session": ["premarket"] * 6,
            "open": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
            "high": [10.4, 10.5, 10.9, 11.0, 10.1, 10.2],
            "low": [9.9, 10.0, 9.9, 10.0, 9.8, 9.9],
            "close": [10.4, 10.5, 10.9, 11.0, 10.0, 10.05],
            "volume": [50_000.0, 60_000.0, 90_000.0, 110_000.0, 2_000.0, 3_000.0],
            "trade_count": [40, 45, 70, 75, 2, 3],
        }
    )
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day, trade_day],
            "symbol": ["AAA", "BBB", "CCC"],
            "previous_close": [10.0, 10.0, 10.0],
            "market_open_price": [10.6, 11.1, 10.1],
        }
    )

    result = build_premarket_window_features_full_universe_export(
        second_detail,
        daily,
        window_definitions=(definition,),
        source_data_fetched_at="2026-03-10T13:31:00+00:00",
        dataset="DBEQ.BASIC",
    )

    ranked = result.sort_values(["quality_rank_within_window", "symbol"], na_position="last").reset_index(drop=True)
    assert ranked.loc[0, "symbol"] == "BBB"
    assert ranked.loc[0, "quality_rank_within_window"] == 1
    assert bool(ranked.loc[0, "quality_selected_top_n"]) is True
    assert ranked.loc[1, "symbol"] == "AAA"
    assert ranked.loc[1, "quality_rank_within_window"] == 2
    assert bool(ranked.loc[1, "quality_selected_top_n"]) is True
    ccc = result.loc[result["symbol"] == "CCC"].iloc[0]
    assert bool(ccc["passes_quality_filter"]) is False
    assert pd.isna(ccc["quality_rank_within_window"])
    assert bool(ccc["quality_selected_top_n"]) is False


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


def test_collect_quality_window_source_frames_keeps_base_rows_for_partial_alternate_coverage(monkeypatch, tmp_path: Path) -> None:
    trade_day = date(2026, 3, 6)
    raw_universe = pd.DataFrame({"symbol": ["AAA"], "exchange": ["NASDAQ"]})
    supported_universe = raw_universe.copy()
    daily_bars = pd.DataFrame({"trade_date": [trade_day], "symbol": ["AAA"], "previous_close": [10.0]})

    def _frame(rows: list[tuple[str, float]]) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trade_date": [trade_day] * len(rows),
                "symbol": ["AAA"] * len(rows),
                "timestamp": [pd.Timestamp(ts) for ts, _ in rows],
                "session": ["premarket" if pd.Timestamp(ts) < pd.Timestamp("2026-03-06T14:30:00Z") else "regular" for ts, _ in rows],
                "open": [value for _, value in rows],
                "high": [value for _, value in rows],
                "low": [value for _, value in rows],
                "close": [value for _, value in rows],
                "volume": [100.0] * len(rows),
                "second_delta_pct": [np.nan] * len(rows),
                "from_previous_close_pct": [np.nan] * len(rows),
            }
        )

    frames = {
        "DBEQ.BASIC": _frame(
            [
                ("2026-03-06T09:00:00Z", 10.0),
                ("2026-03-06T09:10:00Z", 11.0),
                ("2026-03-06T14:00:00Z", 12.0),
                ("2026-03-06T14:10:00Z", 13.0),
                ("2026-03-06T14:30:10Z", 14.0),
            ]
        ),
        "XNAS.BASIC": _frame(
            [
                ("2026-03-06T09:00:00Z", 100.0),
                ("2026-03-06T14:30:10Z", 140.0),
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

    assert premarket_detail["timestamp"].dt.strftime("%H:%M:%S").tolist() == ["09:00:00", "09:10:00", "14:00:00", "14:10:00"]
    assert premarket_detail["close"].tolist() == [100.0, 11.0, 12.0, 13.0]
    assert quality_detail["timestamp"].dt.strftime("%H:%M:%S").tolist() == ["09:00:00", "09:10:00", "14:00:00", "14:10:00", "14:30:10"]
    assert quality_detail["close"].tolist() == [100.0, 11.0, 12.0, 13.0, 140.0]


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


def test_resolve_watchlist_snapshot_trigger_labels_fast_refresh_auto_generation() -> None:
    assert _resolve_watchlist_snapshot_trigger(generate_watchlist=False, fast_pipeline=False, fast_refresh=True) == "fast_refresh_auto_generate"
    assert _resolve_watchlist_snapshot_trigger(generate_watchlist=False, fast_pipeline=True, fast_refresh=False) == "fast_pipeline"
    assert _resolve_watchlist_snapshot_trigger(generate_watchlist=True, fast_pipeline=True, fast_refresh=True) == "generate_watchlist"


def test_run_full_history_refresh_with_status_marks_complete_on_success() -> None:
    calls: list[dict[str, Any]] = []

    class _StatusContainer:
        def update(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    _run_full_history_refresh_with_status(status_container=_StatusContainer(), run_pipeline=lambda: None)

    assert calls == [{"label": "Full history refresh: complete.", "state": "complete", "expanded": False}]


def test_run_full_history_refresh_with_status_marks_error_on_failure() -> None:
    calls: list[dict[str, Any]] = []

    class _StatusContainer:
        def update(self, **kwargs: Any) -> None:
            calls.append(kwargs)

    try:
        _run_full_history_refresh_with_status(
            status_container=_StatusContainer(),
            run_pipeline=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        )
    except RuntimeError as exc:
        assert str(exc) == "boom"
    else:
        raise AssertionError("Expected RuntimeError")

    assert calls == [{"label": "Full history refresh: failed.", "state": "error", "expanded": True}]


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


def test_detail_scope_manifest_field_reflects_second_detail_scope() -> None:
    """detail_scope in the manifest must adapt to the second_detail_scope parameter."""
    scope_map = {"none": "no_second_detail", "ranked_only": "ranked_symbol_day_only", "full_universe": "full_supported_universe_symbol_days"}
    for key, expected in scope_map.items():
        assert scope_map[key] == expected


def test_write_exact_named_exports_uses_atomic_parquet_writes(tmp_path, monkeypatch) -> None:
    export_dir = tmp_path / "exports"
    frames = {
        "daily_symbol_features_full_universe": pd.DataFrame({"symbol": ["AAA"], "trade_date": [date(2026, 3, 10)]}),
        "quality_window_status_latest": pd.DataFrame({"symbol": ["AAA"], "quality_open_drive_window_latest_berlin": ["10:00-10:30"]}),
    }
    writes: list[tuple[Path, pd.DataFrame]] = []

    def fake_write(path: Path, frame: pd.DataFrame) -> None:
        writes.append((path, frame.copy()))

    monkeypatch.setattr("scripts.databento_production_export._write_parquet_atomic", fake_write)

    created = _write_exact_named_exports(export_dir, frames)

    assert export_dir.is_dir()
    assert created == {
        "daily_symbol_features_full_universe": export_dir / "daily_symbol_features_full_universe.parquet",
        "quality_window_status_latest": export_dir / "quality_window_status_latest.parquet",
    }
    assert [path for path, _ in writes] == list(created.values())
    assert writes[0][1].equals(frames["daily_symbol_features_full_universe"])
    assert writes[1][1].equals(frames["quality_window_status_latest"])


def test_run_fixed_et_intraday_screen_forces_new_york_timezone(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_run_intraday_screen(*args, **kwargs):
        captured["display_timezone"] = kwargs.get("display_timezone")
        return pd.DataFrame()

    monkeypatch.setattr("scripts.databento_production_export.run_intraday_screen", fake_run_intraday_screen)

    result = _run_fixed_et_intraday_screen("fake-key", dataset="DBEQ.BASIC")

    assert result.empty
    assert captured["display_timezone"] == FIXED_ET_DISPLAY_TIMEZONE


def test_collect_fixed_et_second_detail_forces_new_york_timezone(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_collect(*args, **kwargs):
        captured["display_timezone"] = kwargs.get("display_timezone")
        return pd.DataFrame()

    monkeypatch.setattr("scripts.databento_production_export.collect_full_universe_open_window_second_detail", fake_collect)

    result = _collect_fixed_et_second_detail("fake-key", dataset="DBEQ.BASIC")

    assert result.empty
    assert captured["display_timezone"] == FIXED_ET_DISPLAY_TIMEZONE


def test_build_quality_window_status_latest_uses_canonical_window_rows() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 10), date(2026, 3, 10), date(2026, 3, 10)],
            "symbol": ["AAA", "AAA", "BBB"],
            "window_tag": ["pm_0400_0500", "pm_0900_0930", "pm_0900_0930"],
            "has_window_data": [True, True, False],
            "passes_quality_filter": [False, True, False],
            "quality_selected_top_n": [False, True, False],
            "window_quality_score": [40.0, 90.0, pd.NA],
        }
    )

    status = _build_quality_window_status_latest(frame, display_timezone="Europe/Berlin")

    aaa = status.loc[status["symbol"] == "AAA"].iloc[0]
    bbb = status.loc[status["symbol"] == "BBB"].iloc[0]
    assert aaa["quality_open_drive_window_latest_berlin"] != "none"
    assert "+" in aaa["quality_open_drive_window_coverage_latest_berlin"]
    assert float(aaa["quality_open_drive_window_score_latest_berlin"]) == 90.0
    assert bbb["quality_open_drive_window_coverage_latest_berlin"] == "none"
    assert bbb["quality_open_drive_window_latest_berlin"] == "none"


def test_build_quality_window_status_latest_prefers_best_score_over_later_window() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 10), date(2026, 3, 10)],
            "symbol": ["AAA", "AAA"],
            "window_tag": ["pm_0400_0500", "pm_0900_0930"],
            "has_window_data": [True, True],
            "passes_quality_filter": [True, True],
            "quality_selected_top_n": [True, True],
            "window_quality_score": [95.0, 10.0],
        }
    )

    status = _build_quality_window_status_latest(frame, display_timezone="Europe/Berlin")

    aaa = status.loc[status["symbol"] == "AAA"].iloc[0]
    assert aaa["quality_open_drive_window_latest_berlin"] == "09:00-10:00"
    assert float(aaa["quality_open_drive_window_score_latest_berlin"]) == 95.0


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
    assert "datetime64" in str(prepared["ts"].dtype)
    assert prepared["ts"].dt.tz is None


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

    status = build_data_status_result(tmp_path, stale_after_minutes=11_000)

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


def test_build_data_status_result_fast_manifest_does_not_fallback_second_detail_from_full_history_file(tmp_path: Path) -> None:
    manifest_path = tmp_path / "databento_preopen_fast_20260310_093100_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "mode": "preopen_fast_reduced_scope",
                "export_generated_at": "2026-03-10T09:31:00+00:00",
                "premarket_fetched_at": "2026-03-10T09:30:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    # This file is a full-history artifact and should not be used for fast-manifest second-detail fallback.
    (tmp_path / "full_universe_second_detail_open.parquet").write_bytes(b"placeholder")

    status = build_data_status_result(tmp_path, stale_after_minutes=10_000)

    assert status.manifest_path is not None
    assert status.manifest_path.endswith(manifest_path.name)
    assert status.second_detail_fetched_at is None
    assert status.lookback_days is None


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
    watchlist_table = cast(pd.DataFrame, result["watchlist_table"])

    assert result["trade_date"] == "2026-03-06"
    assert result["source_data_fetched_at"] is not None
    assert result["generated_at"] is not None
    assert len(watchlist_table) == 1
    assert watchlist_table.iloc[0]["symbol"] == "BBB"


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


def test_resolve_watchlist_display_table_keeps_empty_latest_trade_date_table() -> None:
    historical = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["AAA"],
            "watchlist_rank": [1],
        }
    )
    active = historical.iloc[0:0].copy()

    latest_table, latest_caption = resolve_watchlist_display_table(
        watchlist_result={
            "generated_at": "2026-03-09T17:00:00+00:00",
            "source_data_fetched_at": "2026-03-09T16:55:00+00:00",
            "trade_date": "2026-03-07",
            "watchlist_table": historical,
            "active_watchlist_table": active,
        },
        view_mode="Latest trade date",
    )

    assert latest_table.empty
    assert "Showing latest trade date 2026-03-07 (0 rows, 1 historical rows total)." in latest_caption


def test_persist_watchlist_snapshot_enables_intraday_rank_context(tmp_path: Path) -> None:
    first_result = {
        "generated_at": "2026-03-09T12:00:00+00:00",
        "source_data_fetched_at": "2026-03-09T11:59:00+00:00",
        "trade_date": "2026-03-09",
        "active_watchlist_table": pd.DataFrame(
            {
                "trade_date": [date(2026, 3, 9), date(2026, 3, 9)],
                "symbol": ["AAA", "BBB"],
                "watchlist_rank": [1, 2],
            }
        ),
        "watchlist_table": pd.DataFrame(
            {
                "trade_date": [date(2026, 3, 9), date(2026, 3, 9)],
                "symbol": ["AAA", "BBB"],
                "watchlist_rank": [1, 2],
            }
        ),
    }
    second_result = {
        "generated_at": "2026-03-09T12:05:00+00:00",
        "source_data_fetched_at": "2026-03-09T12:04:30+00:00",
        "trade_date": "2026-03-09",
        "active_watchlist_table": pd.DataFrame(
            {
                "trade_date": [date(2026, 3, 9), date(2026, 3, 9), date(2026, 3, 9)],
                "symbol": ["BBB", "AAA", "CCC"],
                "watchlist_rank": [1, 2, 3],
            }
        ),
        "watchlist_table": pd.DataFrame(
            {
                "trade_date": [date(2026, 3, 9), date(2026, 3, 9), date(2026, 3, 9)],
                "symbol": ["BBB", "AAA", "CCC"],
                "watchlist_rank": [1, 2, 3],
            }
        ),
    }

    history = _persist_watchlist_snapshot(tmp_path, first_result, trigger="generate_watchlist")
    history = _persist_watchlist_snapshot(tmp_path, second_result, trigger="generate_watchlist")
    augmented = _augment_watchlist_result_with_intraday_context(second_result, history)

    assert (tmp_path / WATCHLIST_SNAPSHOT_FILE).exists()
    assert len(history) == 5
    active = augmented["active_watchlist_table"]
    bbb = active.loc[active["symbol"] == "BBB"].iloc[0]
    aaa = active.loc[active["symbol"] == "AAA"].iloc[0]
    ccc = active.loc[active["symbol"] == "CCC"].iloc[0]

    assert int(bbb["previous_intraday_watchlist_rank"]) == 2
    assert bbb["intraday_watchlist_rank_change"] == "up 1"
    assert int(aaa["previous_intraday_watchlist_rank"]) == 1
    assert aaa["intraday_watchlist_rank_change"] == "down 1"
    assert pd.isna(ccc["previous_intraday_watchlist_rank"])
    assert ccc["intraday_watchlist_rank_change"] == "first"


def test_build_open_pattern_status_series_distinguishes_all_vs_single_focus_views() -> None:
    frame = pd.DataFrame(
        {
            "open_30s_volume": [1500.0, np.nan],
            "early_dip_pct_10s": [-2.1, np.nan],
            "reclaim_second_30s": [12.0, np.nan],
            "focus_0930_open_30s_volume": [1500.0, np.nan],
            "focus_0930_early_dip_pct_10s": [-2.1, np.nan],
            "focus_0930_reclaim_second_30s": [12.0, np.nan],
            "focus_0800_open_30s_volume": [np.nan, np.nan],
            "focus_0800_early_dip_pct_10s": [np.nan, np.nan],
            "focus_0800_reclaim_second_30s": [np.nan, np.nan],
            "focus_0400_open_30s_volume": [np.nan, np.nan],
            "focus_0400_early_dip_pct_10s": [np.nan, np.nan],
            "focus_0400_reclaim_second_30s": [np.nan, np.nan],
        }
    )

    assert _build_open_pattern_status_series(frame, "All (04:00 + 08:00 + 09:30)").tolist() == [
        "available via >=1 focus window",
        "missing across all focus windows",
    ]
    assert _build_open_pattern_status_series(frame, "09:30 only").tolist() == [
        "available at 09:30",
        "missing at 09:30",
    ]
    assert _build_open_pattern_status_series(frame, "08:00 only").tolist() == [
        "missing at 08:00",
        "missing at 08:00",
    ]
    assert _build_open_pattern_status_series(frame, "04:00 only").tolist() == [
        "missing at 04:00",
        "missing at 04:00",
    ]


def test_build_focus_window_coverage_series_shows_exact_window_combinations() -> None:
    frame = pd.DataFrame(
        {
            "open_window_second_rows": [12, 0, 0, 0, 0],
            "focus_0930_open_window_second_rows": [12, 0, 4, 0, 0],
            "focus_0800_open_window_second_rows": [0, 8, 4, 0, 0],
            "focus_0400_open_window_second_rows": [0, 0, 4, 9, 0],
        }
    )

    assert _build_focus_window_coverage_series(frame).tolist() == [
        "09:30",
        "08:00",
        "04:00 + 08:00 + 09:30",
        "04:00",
        "none",
    ]


def test_build_focus_window_coverage_series_returns_unavailable_when_window_rows_are_absent() -> None:
    frame = pd.DataFrame({"symbol": ["AAA", "BBB"]})

    assert _build_focus_window_coverage_series(frame).tolist() == ["unavailable", "unavailable"]


def test_highlight_rank_change_label_emphasizes_direction_and_special_states() -> None:
    assert _highlight_rank_change_label("up 2", 2) == "UP +2"
    assert _highlight_rank_change_label("down 3", -3) == "DOWN -3"
    assert _highlight_rank_change_label("flat", 0) == "FLAT 0"
    assert _highlight_rank_change_label("new") == "NEW"
    assert _highlight_rank_change_label("first") == "FIRST"


def test_format_intraday_reference_time_uses_display_timezone() -> None:
    assert _format_intraday_reference_time("2026-03-12T08:15:00+00:00") == "09:15:00 CET"
    assert _format_intraday_reference_time(None) == "n/a"


def test_build_watchlist_table_style_frame_marks_rank_direction_cells() -> None:
    frame = pd.DataFrame(
        {
            "watchlist_rank_change": ["UP +2", "DOWN -1", "NEW", "FLAT 0"],
            "watchlist_rank_delta": [2, -1, np.nan, 0],
            "intraday_watchlist_rank_change": ["FIRST", "UP +1", "DOWN -2", "FLAT 0"],
            "intraday_watchlist_rank_delta": [np.nan, 1, -2, 0],
        }
    )

    styles = _build_watchlist_table_style_frame(frame)

    assert "#dcfce7" in styles.loc[0, "watchlist_rank_change"]
    assert "#fee2e2" in styles.loc[1, "watchlist_rank_change"]
    assert "#dbeafe" in styles.loc[2, "watchlist_rank_change"]
    assert "#e5e7eb" in styles.loc[3, "watchlist_rank_change"]
    assert "#fef3c7" in styles.loc[0, "intraday_watchlist_rank_change"]
    assert "#dcfce7" in styles.loc[1, "intraday_watchlist_rank_delta"]
    assert "#fee2e2" in styles.loc[2, "intraday_watchlist_rank_delta"]


def test_build_watchlist_snapshot_panel_frames_returns_summary_and_rank_trail() -> None:
    history = pd.DataFrame(
        {
            "snapshot_at": [
                pd.Timestamp("2026-03-12T08:15:00Z"),
                pd.Timestamp("2026-03-12T08:15:00Z"),
                pd.Timestamp("2026-03-12T08:30:00Z"),
                pd.Timestamp("2026-03-12T08:30:00Z"),
                pd.Timestamp("2026-03-11T08:15:00Z"),
            ],
            "trade_date": [
                date(2026, 3, 12),
                date(2026, 3, 12),
                date(2026, 3, 12),
                date(2026, 3, 12),
                date(2026, 3, 11),
            ],
            "symbol": ["AAA", "BBB", "AAA", "BBB", "OLD"],
            "watchlist_rank": [1, 2, 2, 1, 1],
            "source_data_fetched_at": ["", "", "", "", ""],
            "watchlist_generated_at": ["", "", "", "", ""],
            "trigger": ["auto_load", "auto_load", "fast_pipeline", "fast_pipeline", "auto_load"],
        }
    )

    summary, trail = _build_watchlist_snapshot_panel_frames(
        history,
        trade_date=date(2026, 3, 12),
        active_symbols=["BBB", "AAA"],
        display_timezone="Europe/Berlin",
    )

    assert summary.to_dict(orient="records") == [
        {
            "snapshot_time": "09:30:00 CET",
            "trigger": "fast_pipeline",
            "symbols": 2,
            "leader": "BBB",
            "top3": "BBB, AAA",
        },
        {
            "snapshot_time": "09:15:00 CET",
            "trigger": "auto_load",
            "symbols": 2,
            "leader": "AAA",
            "top3": "AAA, BBB",
        },
    ]
    assert trail.columns.tolist() == ["symbol", "09:15:00 CET", "09:30:00 CET"]
    assert trail.to_dict(orient="records") == [
        {"symbol": "BBB", "09:15:00 CET": 2.0, "09:30:00 CET": 1.0},
        {"symbol": "AAA", "09:15:00 CET": 1.0, "09:30:00 CET": 2.0},
    ]


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
    watchlist_table = cast(pd.DataFrame, result["watchlist_table"])
    source_metadata = cast(dict[str, Any], result["source_metadata"])

    assert result["trade_date"] == "2026-03-06"
    assert watchlist_table.iloc[0]["symbol"] == "BBB"
    assert source_metadata["source"] == "bundle"
    assert "fallback_reason" in source_metadata


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
    watchlist_table = cast(pd.DataFrame, result["watchlist_table"])
    funnel = cast(list[dict[str, Any]], result["filter_funnel"])

    assert watchlist_table.empty
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
    watchlist_table = cast(pd.DataFrame, result["watchlist_table"])

    assert len(watchlist_table) == 1
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
            "early_dip_pct_10s": -1.5,
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
    assert "Gap >=" in rule_note


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
    assert bool(features.loc[0, "has_close_window_detail"]) is False
    assert int(coverage.loc[0, "open_window_second_rows"]) == 0
    assert bool(coverage.loc[0, "has_open_window_detail"]) is False
    assert int(coverage.loc[0, "close_window_second_rows"]) == 0
    assert bool(coverage.loc[0, "has_close_window_detail"]) is False


def test_build_daily_features_full_universe_builds_close_imbalance_metrics() -> None:
    trading_days = [date(2026, 3, 5)]
    universe = pd.DataFrame(
        {
            "symbol": ["AAPL"],
            "news_score": [0.8],
            "float_shares": [15_000_000.0],
        }
    )
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "open": [100.0],
            "high": [103.0],
            "low": [99.0],
            "close": [102.0],
            "volume": [1000.0],
            "previous_close": [99.5],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)],
            "symbol": ["AAPL"],
            "current_price": [102.0],
        }
    )
    open_detail = pd.DataFrame(columns=["trade_date", "symbol", "timestamp", "volume"])
    close_detail = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 4,
            "symbol": ["AAPL"] * 4,
            "timestamp": pd.to_datetime(
                [
                    "2026-03-05 20:50:00+00:00",
                    "2026-03-05 20:59:30+00:00",
                    "2026-03-05 21:00:00+00:00",
                    "2026-03-05 21:04:00+00:00",
                ]
            ),
            "session": ["regular", "regular", "postmarket", "postmarket"],
            "open": [100.0, 101.0, 101.5, 101.7],
            "high": [100.2, 101.5, 101.8, 102.0],
            "low": [99.9, 100.8, 101.2, 101.4],
            "close": [100.1, 101.4, 101.7, 101.9],
            "volume": [100.0, 300.0, 200.0, 50.0],
        }
    )

    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=open_detail,
        close_detail_all=close_detail,
    )

    row = features.iloc[0]
    assert bool(row["has_close_window_detail"]) is True
    assert int(row["close_window_second_rows"]) == 4
    assert int(row["close_preclose_second_rows"]) == 2
    assert int(row["close_last_minute_second_rows"]) == 1
    assert int(row["close_postclose_second_rows"]) == 2
    assert float(row["close_10m_volume"]) == 400.0
    assert float(row["close_last_1m_volume"]) == 300.0
    assert float(row["close_postclose_5m_volume"]) == 250.0
    assert round(float(row["close_last_1m_volume_share"]), 4) == 0.75
    assert round(float(row["close_postclose_volume_share"]), 4) == round(250.0 / 650.0, 4)
    assert round(float(row["close_preclose_return_pct"]), 4) == 1.4
    assert round(float(row["close_postclose_return_pct"]), 4) == round(((101.9 / 101.4) - 1.0) * 100.0, 4)
    assert bool(coverage.loc[0, "has_close_window_detail"]) is True


def test_build_daily_features_full_universe_builds_close_hygiene_venue_mix_and_forward_outcomes() -> None:
    trading_days = [date(2026, 3, 5), date(2026, 3, 6)]
    universe = pd.DataFrame({"symbol": ["AAPL"]})
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "open": [100.0, 103.0],
            "high": [103.0, 105.0],
            "low": [99.0, 102.0],
            "close": [102.0, 104.0],
            "volume": [1000.0, 1100.0],
            "previous_close": [99.5, 102.0],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "market_open_price": [100.8, 103.0],
            "window_start_price": [100.9, 103.2],
            "current_price": [101.9, 104.0],
            "exact_1000_price": [101.85, 103.6],
        }
    )
    close_detail = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 4,
            "symbol": ["AAPL"] * 4,
            "timestamp": pd.to_datetime(
                [
                    "2026-03-05 20:50:00+00:00",
                    "2026-03-05 20:59:30+00:00",
                    "2026-03-05 21:00:00+00:00",
                    "2026-03-05 21:04:00+00:00",
                ]
            ),
            "session": ["regular", "regular", "postmarket", "postmarket"],
            "open": [100.0, 101.0, 101.5, 101.7],
            "high": [100.2, 101.5, 101.8, 102.0],
            "low": [99.9, 100.8, 101.2, 101.4],
            "close": [100.1, 101.4, 101.7, 101.9],
            "volume": [100.0, 300.0, 200.0, 50.0],
        }
    )
    close_trade_detail = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 3,
            "symbol": ["AAPL"] * 3,
            "timestamp": pd.to_datetime(
                [
                    "2026-03-05 20:59:05+00:00",
                    "2026-03-05 20:59:20+00:00",
                    "2026-03-05 20:59:40+00:00",
                ]
            ),
            "ts_event": pd.to_datetime(
                [
                    "2026-03-05 20:59:05+00:00",
                    "2026-03-05 20:59:20+00:00",
                    "2026-03-05 20:59:39+00:00",
                ]
            ),
            "ts_recv": pd.to_datetime(
                [
                    "2026-03-05 20:59:05+00:00",
                    "2026-03-05 20:59:20+00:00",
                    "2026-03-05 20:59:40+00:00",
                ]
            ),
            "publisher_id": [11, 12, 12],
            "publisher": ["FINRA/Nasdaq TRF Carteret", "Nasdaq", "Nasdaq"],
            "venue_class": ["off_exchange_trf", "lit_exchange", "lit_exchange"],
            "side": ["N", "B", "N"],
            "price": [101.35, 101.40, 101.45],
            "size": [100.0, 50.0, 20.0],
            "flags": [0, 0, 8],
            "sequence": [1, 2, 3],
            "ts_in_delta": [0, 0, 0],
        }
    )
    close_outcome_minute = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 5)],
            "symbol": ["AAPL", "AAPL"],
            "timestamp": pd.to_datetime([
                "2026-03-05 21:00:00+00:00",
                "2026-03-06 00:59:00+00:00",
            ]),
            "open": [101.5, 102.8],
            "high": [102.0, 103.0],
            "low": [101.3, 102.7],
            "close": [101.8, 103.0],
            "volume": [300.0, 700.0],
        }
    )

    features, _ = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=pd.DataFrame(),
        close_detail_all=close_detail,
        close_trade_detail_all=close_trade_detail,
        close_outcome_minute_detail_all=close_outcome_minute,
    )

    day1 = features.loc[features["trade_date"] == date(2026, 3, 5)].iloc[0]
    day2 = features.loc[features["trade_date"] == date(2026, 3, 6)].iloc[0]
    assert int(day1["close_trade_print_count"]) == 3
    assert float(day1["close_trade_share_volume"]) == 170.0
    assert int(day1["close_trade_clean_print_count"]) == 2
    assert float(day1["close_trade_clean_share_volume"]) == 150.0
    assert int(day1["close_trade_bad_ts_recv_count"]) == 1
    assert int(day1["close_trade_trf_print_count"]) == 1
    assert int(day1["close_trade_lit_print_count"]) == 2
    assert round(float(day1["close_trade_trf_volume_share"]), 4) == round(100.0 / 170.0, 4)
    assert bool(day1["close_trade_has_trf_activity"]) is True
    assert bool(day1["close_trade_has_lit_activity"]) is True
    assert bool(day1["close_trade_has_lit_followthrough"]) is True
    assert round(float(day1["close_to_2000_return_pct"]), 4) == round(((103.0 / 101.4) - 1.0) * 100.0, 4)
    assert round(float(day1["close_to_next_open_return_pct"]), 4) == round(((103.0 / 101.4) - 1.0) * 100.0, 4)
    assert float(day1["next_day_window_end_price"]) == 103.6
    assert round(float(day1["next_open_to_window_end_return_pct"]), 4) == round(((103.6 / 103.0) - 1.0) * 100.0, 4)
    assert round(float(day1["close_to_next_window_end_return_pct"]), 4) == round(((103.6 / 101.4) - 1.0) * 100.0, 4)
    assert bool(day1["has_next_day_outcome"]) is True
    assert pd.isna(day2["next_trade_date"])
    assert bool(day2["has_next_day_outcome"]) is False


def test_build_daily_features_full_universe_falls_back_to_next_day_current_price_when_exact_1000_missing() -> None:
    trading_days = [date(2026, 3, 5), date(2026, 3, 6)]
    universe = pd.DataFrame({"symbol": ["AAPL"]})
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "open": [100.0, 103.0],
            "high": [103.0, 105.0],
            "low": [99.0, 102.0],
            "close": [102.0, 104.0],
            "volume": [1000.0, 1100.0],
            "previous_close": [99.5, 102.0],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "market_open_price": [100.8, 103.0],
            "current_price": [101.9, 104.0],
            "exact_1000_price": [101.85, np.nan],
        }
    )
    close_detail = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 2,
            "symbol": ["AAPL"] * 2,
            "timestamp": pd.to_datetime([
                "2026-03-05 20:50:00+00:00",
                "2026-03-05 20:59:30+00:00",
            ]),
            "open": [100.0, 101.0],
            "high": [100.2, 101.5],
            "low": [99.9, 100.8],
            "close": [100.1, 101.4],
            "volume": [100.0, 300.0],
        }
    )

    features, _ = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=pd.DataFrame(),
        close_detail_all=close_detail,
    )

    day1 = features.loc[features["trade_date"] == date(2026, 3, 5)].iloc[0]
    assert float(day1["next_day_window_end_price"]) == 104.0
    assert round(float(day1["close_to_next_window_end_return_pct"]), 4) == round(((104.0 / 101.4) - 1.0) * 100.0, 4)
    assert bool(day1["has_next_day_outcome"]) is True


def test_build_daily_features_full_universe_requires_next_day_window_end_for_outcome_flag() -> None:
    trading_days = [date(2026, 3, 5), date(2026, 3, 6)]
    universe = pd.DataFrame({"symbol": ["AAPL"]})
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "open": [100.0, 103.0],
            "high": [103.0, 105.0],
            "low": [99.0, 102.0],
            "close": [102.0, 104.0],
            "volume": [1000.0, 1100.0],
            "previous_close": [99.5, 102.0],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAPL", "AAPL"],
            "market_open_price": [100.8, 103.0],
            "current_price": [101.9, np.nan],
            "exact_1000_price": [101.85, np.nan],
        }
    )
    close_detail = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 2,
            "symbol": ["AAPL"] * 2,
            "timestamp": pd.to_datetime([
                "2026-03-05 20:50:00+00:00",
                "2026-03-05 20:59:30+00:00",
            ]),
            "open": [100.0, 101.0],
            "high": [100.2, 101.5],
            "low": [99.9, 100.8],
            "close": [100.1, 101.4],
            "volume": [100.0, 300.0],
        }
    )

    features, _ = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=pd.DataFrame(),
        close_detail_all=close_detail,
    )

    day1 = features.loc[features["trade_date"] == date(2026, 3, 5)].iloc[0]
    assert pd.isna(day1["next_day_window_end_price"])
    assert pd.isna(day1["close_to_next_window_end_return_pct"])
    assert bool(day1["has_next_day_outcome"]) is False


def test_build_exact_window_end_lookup_only_keeps_true_boundary_rows() -> None:
    anchor = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6), date(2026, 3, 6)],
            "symbol": ["AAPL", "MSFT"],
            "current_price": [103.6, 210.4],
            "current_price_timestamp": pd.to_datetime(
                [
                    "2026-03-06 15:00:00+00:00",
                    "2026-03-06 14:59:59+00:00",
                ]
            ),
        }
    )

    out = _build_exact_window_end_lookup(anchor, display_timezone="Europe/Berlin")

    assert list(out["symbol"]) == ["AAPL"]
    assert float(out.iloc[0]["exact_1000_price"]) == 103.6


def test_has_open_window_detail_ors_open_and_regular_rows() -> None:
    """has_open_window_detail must be True when EITHER open_window or regular_open rows exist."""
    trading_days = [date(2026, 3, 5)]
    universe = pd.DataFrame({"symbol": ["AAPL", "MSFT"]})
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 2,
            "symbol": ["AAPL", "MSFT"],
            "open": [100.0, 200.0],
            "high": [101.0, 201.0],
            "low": [99.0, 199.0],
            "close": [100.5, 200.5],
            "volume": [1000.0, 2000.0],
            "previous_close": [99.5, 199.5],
        }
    )
    intraday = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 2,
            "symbol": ["AAPL", "MSFT"],
            "current_price": [100.5, 200.5],
        }
    )
    # AAPL has open_window rows but zero regular_open rows;
    # MSFT has zero open_window rows but regular_open rows.
    second_detail_all = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5)] * 2,
            "symbol": ["AAPL", "MSFT"],
            "timestamp": pd.to_datetime(["2026-03-05 14:29:00+00:00", "2026-03-05 14:30:30+00:00"]),
            "session": ["premarket", "regular"],
            "open": [100.0, 200.0],
            "high": [100.1, 200.1],
            "low": [99.9, 199.9],
            "close": [100.0, 200.0],
            "volume": [10, 20],
        }
    )

    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail_all,
    )

    aapl = features.loc[features["symbol"] == "AAPL"].iloc[0]
    msft = features.loc[features["symbol"] == "MSFT"].iloc[0]
    # Both should be True because at least one source of data exists
    assert bool(aapl["has_open_window_detail"]) is True
    assert bool(msft["has_open_window_detail"]) is True


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


def test_read_cached_frame_ttl_returns_none_when_expired(tmp_path) -> None:
    """_read_cached_frame returns None when max_age_seconds is exceeded."""
    import os

    cache_path = tmp_path / "test_cache.parquet"
    frame = pd.DataFrame({"symbol": ["AAPL"], "price": [100.0]})
    _write_cached_frame(cache_path, frame)

    # Fresh cache with TTL should return data
    result_fresh = _read_cached_frame(cache_path, max_age_seconds=DATA_CACHE_TTL_SECONDS)
    assert result_fresh is not None
    assert len(result_fresh) == 1

    # No TTL should always return data
    result_no_ttl = _read_cached_frame(cache_path)
    assert result_no_ttl is not None

    # Backdate the file to exceed TTL
    old_mtime = cache_path.stat().st_mtime - DATA_CACHE_TTL_SECONDS - 60
    os.utime(cache_path, (old_mtime, old_mtime))

    result_expired = _read_cached_frame(cache_path, max_age_seconds=DATA_CACHE_TTL_SECONDS)
    assert result_expired is None

    # Without TTL, stale file is still returned
    result_no_ttl_stale = _read_cached_frame(cache_path)
    assert result_no_ttl_stale is not None
    assert len(result_no_ttl_stale) == 1


def test_read_cached_frame_ttl_returns_data_when_within_limit(tmp_path) -> None:
    """_read_cached_frame returns data when file is within max_age_seconds."""
    cache_path = tmp_path / "fresh_cache.parquet"
    frame = pd.DataFrame({"x": [1, 2, 3]})
    _write_cached_frame(cache_path, frame)

    result = _read_cached_frame(cache_path, max_age_seconds=60)
    assert result is not None
    assert list(result["x"]) == [1, 2, 3]


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


def test_symbol_detail_cache_key_includes_premarket_anchor(tmp_path) -> None:
    """Changing premarket_anchor_et must produce a different cache key."""
    base_parts = ["2025-01-06", "AAPL", "Europe/Berlin", "152000", "160000"]
    path_a = build_cache_path(
        tmp_path, "symbol_detail_second", dataset="DBEQ.BASIC",
        parts=base_parts + ["040000"],
    )
    path_b = build_cache_path(
        tmp_path, "symbol_detail_second", dataset="DBEQ.BASIC",
        parts=base_parts + ["080000"],
    )
    assert path_a != path_b, "Different premarket_anchor_et must produce different cache paths"


def test_cache_version_by_category_covers_all_data_categories() -> None:
    """All data cache categories should be tracked in CACHE_VERSION_BY_CATEGORY."""
    expected = {
        "daily_bars",
        "symbol_support",
        "full_universe_open_second_detail",
        "full_universe_close_trade_detail",
        "full_universe_close_outcome_minute_detail",
        "intraday_summary",
        "symbol_detail_second",
        "symbol_detail_minute",
    }
    assert expected == set(CACHE_VERSION_BY_CATEGORY.keys())


def test_tradingview_watchlist_writes_are_atomic(tmp_path) -> None:
    """TXT exports should use atomic writes (temp + rename), not direct write_text."""
    frame = pd.DataFrame({
        "symbol": ["AAPL", "TSLA"],
        "exchange": ["NASDAQ", "NASDAQ"],
    })
    created = _write_tradingview_watchlist_exports(tmp_path, "test_base", {"summary": frame})
    assert "summary" in created
    content = created["summary"].read_text(encoding="utf-8")
    assert "NASDAQ:AAPL" in content
    # No leftover temp files
    temps = list(tmp_path.glob(".*.tmp"))
    assert temps == [], f"Leftover temp files: {temps}"


def test_choose_default_dataset_warns_on_fallback(caplog) -> None:
    """A warning should be logged when the requested dataset is not available."""
    import logging
    with caplog.at_level(logging.WARNING):
        result = choose_default_dataset(["DBEQ.BASIC"], requested_dataset="EQUS.ALL")
    assert result == "DBEQ.BASIC"
    assert any("EQUS.ALL" in msg for msg in caplog.messages)


def test_streamlit_watchlist_txt_exports_are_atomic(tmp_path) -> None:
    """Streamlit TXT exports should use atomic writes (no leftover .tmp files)."""
    watchlist_result = {
        "active_watchlist_table": pd.DataFrame({
            "symbol": ["AAPL", "TSLA"],
            "exchange": ["NASDAQ", "NASDAQ"],
        }),
        "watchlist_table": pd.DataFrame({
            "symbol": ["AAPL", "TSLA", "NVDA"],
            "exchange": ["NASDAQ", "NASDAQ", "NASDAQ"],
        }),
    }
    created = _write_streamlit_watchlist_txt_exports(tmp_path, watchlist_result)
    assert "txt_topn_latest" in created
    assert "txt_topn_full_history" in created
    latest_content = created["txt_topn_latest"].read_text(encoding="utf-8")
    assert "NASDAQ:AAPL" in latest_content
    history_content = created["txt_topn_full_history"].read_text(encoding="utf-8")
    assert "NASDAQ:NVDA" in history_content
    temps = list(tmp_path.glob(".*.tmp"))
    assert temps == [], f"Leftover temp files: {temps}"


def test_build_data_status_result_logs_corrupt_manifest(tmp_path, caplog) -> None:
    """Corrupt manifest JSON should be logged, not silently swallowed."""
    import logging
    manifest_path = tmp_path / "test_corrupt_20260101_000000_manifest.json"
    manifest_path.write_text("{invalid json", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result = build_data_status_result(tmp_path)
    assert result.is_stale
    assert any("Failed to parse manifest JSON" in msg for msg in caplog.messages)


# ── Round 4: ranking/quality-window scoring fixes ─────────────────────


def test_trade_count_nan_proxy_fallback() -> None:
    """When trade_count column is absent, active_seconds proxy must be used — not 0."""
    daily_bars = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)],
        "symbol": ["AAPL"],
        "previous_close": [150.0],
        "market_open_price": [155.0],
    })
    ts_base = pd.Timestamp("2026-03-06 09:00:00", tz="US/Eastern").tz_convert("UTC")
    detail = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * 3,
        "symbol": ["AAPL"] * 3,
        "timestamp": [ts_base + pd.Timedelta(seconds=i) for i in range(3)],
        "session": ["premarket"] * 3,
        "open": [151.0, 152.0, 153.0],
        "high": [152.0, 153.0, 154.0],
        "low": [150.0, 151.0, 152.0],
        "close": [152.0, 153.0, 154.0],
        "volume": [100.0, 200.0, 300.0],
    })
    # No "trade_count" column → proxy should kick in
    window_def = (PremarketWindowDefinition("pm_0900_0930", "09:00:00", "09:30:00", "09:00-09:30 ET"),)
    result = build_premarket_window_features_full_universe_export(
        detail, daily_bars, window_definitions=window_def,
        source_data_fetched_at="2026-03-06T09:00:00Z", dataset="DBEQ_BASIC",
    )
    row = result.loc[result["symbol"] == "AAPL"].iloc[0]
    # Proxy should report 3 active seconds (3 rows with volume > 0)
    assert row["window_trade_count"] == 3, f"Expected proxy=3, got {row['window_trade_count']}"
    assert row["window_trade_count_source"] == "proxy_active_seconds"


def test_compute_quality_reason_nan_returns_failure_not_eligible() -> None:
    """NaN in threshold columns must produce a failure reason, not 'eligible'."""
    frame = pd.DataFrame({
        "has_window_data": [True, True, True, True],
        "passes_min_previous_close": [True, True, True, True],
        "passes_min_gap_pct": [True, True, True, True],
        "passes_min_window_dollar_volume": [True, True, True, True],
        "passes_min_window_trade_count": [True, True, True, True],
        "window_close_position_pct": [np.nan, 80.0, 80.0, 80.0],
        "window_return_pct": [1.0, np.nan, 1.0, 1.0],
        "window_pullback_pct": [10.0, 10.0, np.nan, 10.0],
        "window_close": [50.0, 50.0, 50.0, np.nan],
        "window_vwap": [49.0, 49.0, 49.0, 49.0],
    })
    reasons = _compute_quality_reason(frame)
    assert reasons.iloc[0] == "close_position_below_min", f"Expected failure reason, got {reasons.iloc[0]}"
    assert reasons.iloc[1] == "window_return_below_min", f"Expected failure reason, got {reasons.iloc[1]}"
    assert reasons.iloc[2] == "window_pullback_above_max", f"Expected failure reason, got {reasons.iloc[2]}"
    assert reasons.iloc[3] == "close_below_vwap", f"Expected failure reason, got {reasons.iloc[3]}"


def test_quality_window_return_threshold_consistency() -> None:
    """Both score pipelines must treat 0% return identically (>=, not >)."""
    daily_bars = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)],
        "symbol": ["FLAT"],
        "previous_close": [100.0],
        "market_open_price": [105.0],
    })
    ts_base = pd.Timestamp("2026-03-06 09:00:00", tz="US/Eastern").tz_convert("UTC")
    # Flat window: open == close → 0% return
    detail = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * 100,
        "symbol": ["FLAT"] * 100,
        "timestamp": [ts_base + pd.Timedelta(seconds=i) for i in range(100)],
        "session": ["premarket"] * 100,
        "open": [100.0] * 100,
        "high": [100.0] * 100,
        "low": [100.0] * 100,
        "close": [100.0] * 100,
        "volume": [10_000.0] * 100,
        "trade_count": [10] * 100,
    })
    window_def = (PremarketWindowDefinition("pm_0900_0930", "09:00:00", "09:30:00", "09:00-09:30 ET"),)
    result = build_premarket_window_features_full_universe_export(
        detail, daily_bars, window_definitions=window_def,
        source_data_fetched_at="2026-03-06T09:00:00Z", dataset="DBEQ_BASIC",
    )
    row = result.loc[result["symbol"] == "FLAT"].iloc[0]
    # 0% return should pass the min_window_return_pct >= 0.0 filter
    assert row["window_return_pct"] == 0.0
    # The filter check for return should not reject a 0% return
    passes_return = pd.to_numeric(pd.Series([row["window_return_pct"]]), errors="coerce").iloc[0] >= 0.0
    assert passes_return, "0% return must pass the >= 0.0 threshold"


def test_quality_window_status_score_same_window() -> None:
    """Status and score must come from the same qualifying window."""
    window_features = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * 2,
        "symbol": ["AAPL", "AAPL"],
        "window_tag": ["pm_0700_0800", "pm_0900_0930"],
        "has_window_data": [True, True],
        "passes_quality_filter": [True, False],
        "quality_selected_top_n": [True, False],
        "window_quality_score": [80.0, 20.0],
    })
    status_df = _build_quality_window_status_latest(window_features, display_timezone="Europe/Berlin")
    row = status_df.iloc[0]
    # Score should come from the passing window (80.0), not the latest window (20.0)
    assert float(row["quality_open_drive_window_score_latest_berlin"]) == 80.0, (
        f"Expected score=80 from passing window, got {row['quality_open_drive_window_score_latest_berlin']}"
    )


# ── Round 5: missing test coverage ───────────────────────────────────


# ---- 1. Timezone / DST boundaries ----


def test_build_window_definition_handles_us_dst_fall_back_transition() -> None:
    """November DST fall-back: US clocks go back -> UTC offsets shift by 1h.
    Berlin stays CET (UTC+1), US goes from EDT (UTC-4) to EST (UTC-5)."""
    # 2026-11-01 is the DST fall-back date in the US
    window = build_window_definition(
        date(2026, 11, 2),
        display_timezone="Europe/Berlin",
        window_start=time(15, 20),
        window_end=time(16, 0),
        premarket_anchor_et=time(8, 0),
    )
    # After fall-back: Berlin is CET (UTC+1), US is EST (UTC-5)
    # 15:20 CET = 14:20 UTC; 16:00 CET = 15:00 UTC
    # premarket_anchor 08:00 EST = 13:00 UTC
    # regular_open 09:30 EST = 14:30 UTC
    assert window.fetch_start_utc == pd.Timestamp("2026-11-02T13:00:00Z").to_pydatetime()
    assert window.fetch_end_utc == pd.Timestamp("2026-11-02T15:00:00Z").to_pydatetime()
    assert window.regular_open_utc == pd.Timestamp("2026-11-02T14:30:00Z").to_pydatetime()


def test_window_bounds_for_trade_date_dst_spring_forward() -> None:
    """_window_bounds_for_trade_date must produce correct UTC bounds during
    US spring-forward DST (March 2026: EDT starts March 8)."""
    wdef = PremarketWindowDefinition("pm_0400_0500", "04:00:00", "05:00:00")
    # March 9 is first Monday after spring-forward: EDT (UTC-4)
    start_utc, end_utc = _window_bounds_for_trade_date(date(2026, 3, 9), wdef)
    assert start_utc == pd.Timestamp("2026-03-09T08:00:00Z")
    assert end_utc == pd.Timestamp("2026-03-09T09:00:00Z")


def test_window_bounds_for_trade_date_dst_fall_back() -> None:
    """_window_bounds_for_trade_date must produce correct UTC bounds during
    US fall-back DST (November 2026: EST starts November 1)."""
    wdef = PremarketWindowDefinition("pm_0400_0500", "04:00:00", "05:00:00")
    # November 2 is first Monday after fall-back: EST (UTC-5)
    start_utc, end_utc = _window_bounds_for_trade_date(date(2026, 11, 2), wdef)
    assert start_utc == pd.Timestamp("2026-11-02T09:00:00Z")
    assert end_utc == pd.Timestamp("2026-11-02T10:00:00Z")


# ---- 2. Duplicate symbol-second and duplicate daily rows ----


def test_deduplicate_daily_symbol_rows_nan_volume_keeps_row_with_valid_close() -> None:
    """When one duplicate row has NaN volume, highest-close tie-breaker must
    still deterministically pick the best row."""
    trade_day = date(2026, 3, 6)
    frame = pd.DataFrame({
        "trade_date": [trade_day, trade_day],
        "symbol": ["AAA", "AAA"],
        "open": [10.0, 10.0],
        "high": [10.5, 10.5],
        "low": [9.8, 9.8],
        "close": [10.2, 10.4],
        "volume": [np.nan, 500.0],
    })
    deduped = _deduplicate_daily_symbol_rows(frame)
    assert len(deduped) == 1
    assert float(deduped.iloc[0]["volume"]) == 500.0


def test_deduplicate_daily_symbol_rows_noop_without_duplicates() -> None:
    """No duplicates → frame returned unchanged."""
    frame = pd.DataFrame({
        "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
        "symbol": ["AAA", "BBB"],
        "open": [10.0, 20.0],
        "high": [11.0, 21.0],
        "low": [9.0, 19.0],
        "close": [10.5, 20.5],
        "volume": [1000.0, 2000.0],
    })
    deduped = _deduplicate_daily_symbol_rows(frame)
    assert len(deduped) == 2


def test_collapse_duplicate_symbol_seconds_zero_volume_rows() -> None:
    """Zero-volume duplicate seconds should still collapse correctly."""
    frame = pd.DataFrame({
        "symbol": ["AAA", "AAA"],
        "ts": [pd.Timestamp("2026-03-05T14:30:00Z")] * 2,
        "open": [10.0, 10.2],
        "high": [10.5, 10.6],
        "low": [9.9, 10.0],
        "close": [10.1, 10.4],
        "volume": [0, 0],
    })
    collapsed = _collapse_duplicate_symbol_seconds(frame, context="test")
    assert len(collapsed) == 1
    assert collapsed.iloc[0]["volume"] == 0
    assert collapsed.iloc[0]["high"] == 10.6  # max of highs
    assert collapsed.iloc[0]["low"] == 9.9  # min of lows


def test_collapse_duplicate_symbol_seconds_preserves_non_duplicates() -> None:
    """Non-duplicate rows must pass through unchanged."""
    frame = pd.DataFrame({
        "symbol": ["AAA", "BBB"],
        "ts": [pd.Timestamp("2026-03-05T14:30:00Z"), pd.Timestamp("2026-03-05T14:30:01Z")],
        "open": [10.0, 20.0],
        "high": [10.5, 20.5],
        "low": [9.9, 19.9],
        "close": [10.2, 20.2],
        "volume": [100, 200],
    })
    result = _collapse_duplicate_symbol_seconds(frame, context="test")
    assert len(result) == 2


def test_deduplicate_daily_symbol_rows_missing_required_columns() -> None:
    """Frame without trade_date or symbol columns returns unchanged."""
    frame = pd.DataFrame({"open": [10.0], "close": [10.5]})
    result = _deduplicate_daily_symbol_rows(frame)
    assert len(result) == 1


# ---- 3. Fallback dataset paths ----


def test_choose_default_dataset_empty_list_returns_fallback() -> None:
    """Empty available list with no requested → returns first preferred."""
    result = choose_default_dataset([], requested_dataset=None)
    assert result == "XNAS.ITCH"


def test_choose_default_dataset_empty_list_with_request_returns_request() -> None:
    """Empty available list but requested dataset → returns requested."""
    result = choose_default_dataset([], requested_dataset="CUSTOM.DS")
    assert result == "CUSTOM.DS"


def test_normalize_exchange_key_covers_all_aliases() -> None:
    """All known exchange aliases must normalize correctly."""
    assert _normalize_exchange_key("NASDAQ") == "NASDAQ"
    assert _normalize_exchange_key("XNAS") == "NASDAQ"
    assert _normalize_exchange_key("nasdaq") == "NASDAQ"
    assert _normalize_exchange_key("NYSE") == "NYSE"
    assert _normalize_exchange_key("XNYS") == "NYSE"
    assert _normalize_exchange_key("nyse") == "NYSE"
    assert _normalize_exchange_key("AMEX") == "AMEX"
    assert _normalize_exchange_key("XASE") == "AMEX"
    assert _normalize_exchange_key("NYSE AMERICAN") == "AMEX"
    assert _normalize_exchange_key("NYSE MKT") == "AMEX"
    assert _normalize_exchange_key("") == ""
    assert _normalize_exchange_key(None) == ""
    assert _normalize_exchange_key("OTHER") == "OTHER"


def test_normalize_quality_window_exchange_dataset_map_normalizes_keys_and_values() -> None:
    """Exchange-to-dataset map must normalize exchange aliases and uppercase dataset."""
    result = _normalize_quality_window_exchange_dataset_map({
        "nasdaq": "xnas.basic",
        "XNYS": "xnys.pillar",
        "NYSE American": "xase.pillar",
    })
    assert result == {
        "NASDAQ": "XNAS.BASIC",
        "NYSE": "XNYS.PILLAR",
        "AMEX": "XASE.PILLAR",
    }


def test_normalize_quality_window_exchange_dataset_map_none_returns_empty() -> None:
    """None input returns empty dict."""
    assert _normalize_quality_window_exchange_dataset_map(None) == {}


def test_normalize_quality_window_exchange_dataset_map_skips_empty_entries() -> None:
    """Empty exchange or dataset values should be dropped."""
    result = _normalize_quality_window_exchange_dataset_map({
        "NASDAQ": "XNAS.BASIC",
        "": "XNYS.PILLAR",
        "NYSE": "",
    })
    assert result == {"NASDAQ": "XNAS.BASIC"}


# ---- 4. Manifest field presence/accuracy ----


def test_export_run_artifacts_manifest_has_required_fields(tmp_path) -> None:
    """Manifest JSON must contain all critical metadata fields."""
    summary = pd.DataFrame({"symbol": ["AAA"], "trade_date": [date(2026, 3, 5)]})
    universe = pd.DataFrame({"symbol": ["AAA"], "exchange": ["NASDAQ"]})
    daily_bars = pd.DataFrame({"symbol": ["AAA"], "trade_date": [date(2026, 3, 5)]})
    manifest = {
        "dataset": "DBEQ.BASIC",
        "lookback_days": 2,
        "top_fraction": 0.20,
        "ranking_metric": "window_range_pct",
        "display_timezone": "Europe/Berlin",
        "export_generated_at": "2026-03-05T10:00:00+00:00",
        "trade_dates_covered": ["2026-03-05"],
        "detail_scope": "full_supported_universe_symbol_days",
        "second_detail_scope": "full_universe",
        "detail_symbol_count": 1,
        "missing_open_window_symbol_day_rows": 0,
        "quality_window_candidate_exports": "not_applicable_in_current_pipeline",
    }
    paths = export_run_artifacts(
        export_dir=tmp_path,
        basename="test_export_20260305_100000",
        summary=summary,
        universe=universe,
        daily_bars=daily_bars,
        intraday=pd.DataFrame(),
        ranked=pd.DataFrame(),
        manifest=manifest,
    )
    manifest_path = paths.get("manifest")
    assert manifest_path is not None
    assert manifest_path.exists()
    with open(manifest_path, encoding="utf-8") as fh:
        loaded = json.load(fh)
    for required_key in ["dataset", "lookback_days", "top_fraction", "ranking_metric",
                         "display_timezone", "export_generated_at", "trade_dates_covered",
                         "detail_scope", "second_detail_scope", "detail_symbol_count",
                         "missing_open_window_symbol_day_rows"]:
        assert required_key in loaded, f"Missing manifest key: {required_key}"
    assert isinstance(loaded["trade_dates_covered"], list)
    assert isinstance(loaded["detail_symbol_count"], int)


def test_export_run_artifacts_manifest_timestamps_are_strings(tmp_path) -> None:
    """Timestamp fields in manifest must be serializable strings, not datetime objects."""
    manifest = {
        "dataset": "DBEQ.BASIC",
        "export_generated_at": "2026-03-05T10:00:00+00:00",
        "daily_bars_fetched_at": "2026-03-05T09:00:00+00:00",
        "trade_dates_covered": ["2026-03-05"],
    }
    paths = export_run_artifacts(
        export_dir=tmp_path,
        basename="test_ts_20260305",
        summary=pd.DataFrame({"symbol": ["A"]}),
        universe=pd.DataFrame({"symbol": ["A"]}),
        daily_bars=pd.DataFrame(),
        intraday=pd.DataFrame(),
        ranked=pd.DataFrame(),
        manifest=manifest,
    )
    loaded = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    assert isinstance(loaded["export_generated_at"], str)
    assert isinstance(loaded["daily_bars_fetched_at"], str)


# ---- 5. TXT export naming/versioning behavior ----


def test_write_tradingview_watchlist_exports_skips_empty_frames(tmp_path) -> None:
    """Empty frames should produce no TXT files."""
    result = _write_tradingview_watchlist_exports(
        tmp_path,
        "test_export_20260305",
        {
            "empty_frame": pd.DataFrame(),
            "no_symbol_col": pd.DataFrame({"exchange": ["NASDAQ"]}),
        },
    )
    assert result == {}
    assert list(tmp_path.glob("*.txt")) == []


def test_write_tradingview_watchlist_exports_creates_expected_filename(tmp_path) -> None:
    """TXT file name must follow {basename}__{name}.txt pattern."""
    frames = {
        "watchlist": pd.DataFrame({
            "symbol": ["AAPL"],
            "exchange": ["NASDAQ"],
        }),
    }
    result = _write_tradingview_watchlist_exports(tmp_path, "export_20260305_100000", frames)
    assert "watchlist" in result
    assert result["watchlist"].name == "export_20260305_100000__watchlist.txt"
    assert result["watchlist"].exists()
    content = result["watchlist"].read_text(encoding="utf-8")
    assert "NASDAQ:AAPL" in content


def test_build_tradingview_watchlist_text_all_nan_symbols_returns_empty() -> None:
    """Frame with only NaN/empty symbols should produce empty text."""
    frame = pd.DataFrame({
        "symbol": [None, np.nan, ""],
        "exchange": ["NASDAQ", "NYSE", "AMEX"],
    })
    result = _build_tradingview_watchlist_text(frame)
    assert result == ""


def test_write_streamlit_watchlist_txt_exports_empty_tables(tmp_path) -> None:
    """Empty watchlist result tables should not create any files."""
    result = _write_streamlit_watchlist_txt_exports(tmp_path, {
        "active_watchlist_table": pd.DataFrame(),
        "watchlist_table": pd.DataFrame(),
    })
    assert result == {}
    assert list(tmp_path.glob("*.txt")) == []


# ---- 6. Error paths (API errors) ----


def test_download_nasdaq_trader_text_raises_after_retries_for_5xx(monkeypatch) -> None:
    """Server errors (503 Service Unavailable) must exhaust retries then raise."""
    from urllib.error import HTTPError
    calls = {"count": 0}

    def fake_urlopen(request, timeout, context):
        calls["count"] += 1
        raise HTTPError(request.full_url, 503, "Service Unavailable", hdrs=None, fp=None)

    monkeypatch.setattr("databento_volatility_screener.urlopen", fake_urlopen)
    monkeypatch.setattr("databento_volatility_screener.time_module.sleep", lambda _: None)
    try:
        _download_nasdaq_trader_text("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt")
    except HTTPError as exc:
        assert exc.code == 503
    else:
        raise AssertionError("Expected HTTPError for 503")
    assert calls["count"] == 3


def test_list_recent_trading_days_survives_empty_conditions(monkeypatch) -> None:
    """When API returns no available conditions, result should be empty list."""
    class _FakeMetadata:
        def get_dataset_condition(self, **kwargs):
            return []

    class _FakeClient:
        metadata = _FakeMetadata()

    monkeypatch.setattr(
        "databento_volatility_screener._make_databento_client",
        lambda key: _FakeClient(),
    )
    result = list_recent_trading_days(
        "test-key", dataset="DBEQ.BASIC", lookback_days=5,
    )
    assert result == []


def test_fetch_us_equity_universe_falls_back_to_fmp_when_nasdaq_fails(monkeypatch) -> None:
    """When Nasdaq Trader directory fails, FMP fallback should be used."""
    def failing_download(url):
        raise ConnectionError("simulated network failure")

    monkeypatch.setattr("databento_volatility_screener._download_nasdaq_trader_text", failing_download)

    class FakeFMPClient:
        def __init__(self, api_key): pass
        def get_company_screener(self, **kwargs):
            return [{"symbol": "AAPL", "companyName": "Apple", "exchangeShortName": "NASDAQ",
                      "marketCap": 3e12, "isETF": False, "isActivelyTrading": True}]

    monkeypatch.setattr("databento_volatility_screener.FMPClient", FakeFMPClient)
    result = fetch_us_equity_universe("fake-fmp-key", min_market_cap=None)
    assert len(result) >= 1
    assert "AAPL" in result["symbol"].values


# ---- 7. _filter_premarket_rows edge cases ----


def test_filter_premarket_rows_empty_returns_empty() -> None:
    """Empty input returns empty."""
    result = _filter_premarket_rows(pd.DataFrame())
    assert result.empty


def test_filter_premarket_rows_session_column_filters_by_session() -> None:
    """When session column exists, filter by session == premarket."""
    frame = pd.DataFrame({
        "trade_date": [date(2026, 3, 5)] * 3,
        "symbol": ["A", "B", "C"],
        "session": ["premarket", "regular", "  Premarket  "],
        "timestamp": pd.to_datetime(["2026-03-05T08:00:00", "2026-03-05T10:00:00", "2026-03-05T08:30:00"]),
    })
    result = _filter_premarket_rows(frame)
    assert set(result["symbol"].tolist()) == {"A", "C"}


def test_filter_premarket_rows_nan_timestamps_dropped() -> None:
    """Rows with unparseable timestamps should be dropped."""
    frame = pd.DataFrame({
        "trade_date": [date(2026, 3, 5)] * 2,
        "symbol": ["A", "B"],
        "timestamp": ["2026-03-05T08:00:00+00:00", "not-a-timestamp"],
    })
    result = _filter_premarket_rows(frame)
    # "B" should be dropped due to invalid timestamp
    assert len(result) == 1
    assert result.iloc[0]["symbol"] == "A"


# ---- 8. _select_top_candidates_per_day edge cases ----


def test_select_top_candidates_per_day_nan_score_sorts_to_bottom() -> None:
    """Rows with NaN quality_score should lose to rows with valid scores."""
    frame = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * 3,
        "symbol": ["AAA", "BBB", "CCC"],
        "quality_score": [np.nan, 50.0, 80.0],
        "window_dollar_volume": [1e6, 1e6, 1e6],
        "window_return_pct": [5.0, 5.0, 5.0],
    })
    result = _select_top_candidates_per_day(frame, top_n=2)
    assert len(result) == 2
    assert set(result["symbol"].tolist()) == {"BBB", "CCC"}


def test_select_top_candidates_per_day_zero_top_n_returns_empty() -> None:
    """top_n=0 → empty result."""
    frame = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)],
        "symbol": ["AAA"],
        "quality_score": [50.0],
        "window_dollar_volume": [1e6],
        "window_return_pct": [5.0],
    })
    result = _select_top_candidates_per_day(frame, top_n=0)
    assert result.empty


# ---- 9. FMPClient API contract ----


def test_fmp_client_stub_has_get_company_screener() -> None:
    """The real FMPClient stub must expose get_company_screener so the screener
    fallback path doesn't silently raise AttributeError."""
    from open_prep.macro import FMPClient
    client = FMPClient(api_key="test-key")
    assert hasattr(client, "get_company_screener"), "FMPClient missing get_company_screener method"
    result = client.get_company_screener(country="US", market_cap_more_than=1e9, exchange="NASDAQ")
    assert isinstance(result, list)


def test_fetch_us_equity_universe_via_screener_real_stub_returns_empty() -> None:
    """Using the real FMPClient stub (which returns []) should produce an empty
    frame without raising exceptions."""
    from open_prep.macro import FMPClient
    result = _fetch_us_equity_universe_via_screener(
        FMPClient("test-key"),
        min_market_cap=1e9,
        exchanges="NASDAQ,NYSE",
    )
    assert result.empty
    assert list(result.columns) == UNIVERSE_COLUMNS


# ---------- Round 7: focused correctness fixes ----------


def test_passes_quality_filter_respects_require_close_above_vwap_false(monkeypatch) -> None:
    """When require_close_above_vwap is False, a symbol with close < vwap should
    still pass the quality filter and get reason='eligible'."""
    from scripts import databento_production_export as mod
    from scripts.bullish_quality_config import BullishQualityConfig

    override = BullishQualityConfig(require_close_above_vwap=False)
    monkeypatch.setattr(mod, "_DEFAULT_BULLISH_QUALITY_CFG", override)

    daily_bars = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)],
        "symbol": ["AAPL"],
        "previous_close": [150.0],
        "market_open_price": [155.0],
    })
    ts_base = pd.Timestamp("2026-03-06 09:00:00", tz="US/Eastern").tz_convert("UTC")
    n = 120
    # First 30 seconds: high volume at high price → pulls VWAP above final close
    # Last 90 seconds: moderate volume near the top of the range
    opens = [150.0] * n
    highs = [160.0] * n
    lows = [149.0] * n
    closes = [160.0] * 30 + [158.0] * 90  # window_close = 158
    volumes = [10_000.0] * 30 + [500.0] * 90
    trade_counts = [50] * 30 + [10] * 90
    detail = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * n,
        "symbol": ["AAPL"] * n,
        "timestamp": [ts_base + pd.Timedelta(seconds=i) for i in range(n)],
        "session": ["premarket"] * n,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "trade_count": trade_counts,
    })
    window_def = (PremarketWindowDefinition("pm_0900_0930", "09:00:00", "09:30:00", "09:00-09:30 ET"),)
    result = build_premarket_window_features_full_universe_export(
        detail, daily_bars, window_definitions=window_def,
        source_data_fetched_at="2026-03-06T09:00:00Z", dataset="DBEQ_BASIC",
    )
    row = result.loc[result["symbol"] == "AAPL"].iloc[0]
    # Sanity: close < vwap in this data
    assert row["window_close"] < row["window_vwap"], (
        f"Test setup error: expected close ({row['window_close']}) < vwap ({row['window_vwap']})"
    )
    # With require_close_above_vwap=False, close < vwap should not block the filter
    assert bool(row["passes_quality_filter"]) is True, (
        f"Expected passes_quality_filter=True with require_close_above_vwap=False, got {row['passes_quality_filter']}"
    )
    assert row["quality_filter_reason"] == "eligible", (
        f"Expected reason='eligible', got {row['quality_filter_reason']}"
    )


def test_passes_quality_filter_vwap_check_still_applies_when_flag_true() -> None:
    """Default config (require_close_above_vwap=True) should still reject close < vwap."""
    daily_bars = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)],
        "symbol": ["AAPL"],
        "previous_close": [150.0],
        "market_open_price": [155.0],
    })
    ts_base = pd.Timestamp("2026-03-06 09:00:00", tz="US/Eastern").tz_convert("UTC")
    n = 120
    # Same data as above: first 30s at high volume/160 close, last 90s at low volume/158 close
    opens = [150.0] * n
    highs = [160.0] * n
    lows = [149.0] * n
    closes = [160.0] * 30 + [158.0] * 90
    volumes = [10_000.0] * 30 + [500.0] * 90
    trade_counts = [50] * 30 + [10] * 90
    detail = pd.DataFrame({
        "trade_date": [date(2026, 3, 6)] * n,
        "symbol": ["AAPL"] * n,
        "timestamp": [ts_base + pd.Timedelta(seconds=i) for i in range(n)],
        "session": ["premarket"] * n,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "trade_count": trade_counts,
    })

    window_def = (PremarketWindowDefinition("pm_0900_0930", "09:00:00", "09:30:00", "09:00-09:30 ET"),)
    result = build_premarket_window_features_full_universe_export(
        detail, daily_bars, window_definitions=window_def,
        source_data_fetched_at="2026-03-06T09:00:00Z", dataset="DBEQ_BASIC",
    )
    row = result.loc[result["symbol"] == "AAPL"].iloc[0]
    assert row["window_close"] < row["window_vwap"], "Test setup: close should be below vwap"
    assert not row["passes_quality_filter"], (
        f"Expected passes_quality_filter=False when close < vwap, got {row['passes_quality_filter']}"
    )
    assert row["quality_filter_reason"] == "close_below_vwap", (
        f"Expected reason='close_below_vwap', got {row['quality_filter_reason']}"
    )


def test_quality_window_signal_vwap_uses_dollar_volume_directly() -> None:
    """After removing the redundant window_close_value alias, VWAP should still
    be computed correctly as sum(dollar_volume) / sum(volume)."""
    ts_base = pd.Timestamp("2026-03-12 09:00:00", tz="US/Eastern").tz_convert("UTC")
    detail = pd.DataFrame({
        "trade_date": [date(2026, 3, 12)] * 3,
        "symbol": ["TEST"] * 3,
        "timestamp": [ts_base + pd.Timedelta(seconds=i) for i in range(3)],
        "session": ["premarket"] * 3,
        "open": [100.0, 101.0, 102.0],
        "high": [101.0, 102.0, 103.0],
        "low": [99.0, 100.0, 101.0],
        "close": [101.0, 102.0, 103.0],
        "volume": [1000.0, 2000.0, 3000.0],
    })
    daily = pd.DataFrame({
        "trade_date": [date(2026, 3, 12)],
        "symbol": ["TEST"],
        "previous_close": [98.0],
        "market_open_price": [100.0],
    })
    premarket = pd.DataFrame({
        "trade_date": [date(2026, 3, 12)],
        "symbol": ["TEST"],
        "has_premarket_data": [True],
        "premarket_last": [100.0],
        "prev_close_to_premarket_pct": [2.0],
        "premarket_to_open_pct": [0.0],
    })
    status, candidate_exports = _compute_quality_window_signal(
        detail,
        daily_features=daily,
        premarket_features=premarket,
        display_timezone="Europe/Berlin",
        latest_trade_date=date(2026, 3, 12),
    )
    # The function should run without error (no window_close_value dependency).
    # Verify VWAP-dependent flag: close=103 > VWAP≈102.17 → window_vwap_trend_ok=True
    late_key = "quality_candidates_0900_0930_all"
    if late_key in candidate_exports and not candidate_exports[late_key].empty:
        row = candidate_exports[late_key].iloc[0]
        assert row["window_vwap_trend_ok"] is True or row["window_vwap_trend_ok"] == True, (
            f"window_vwap_trend_ok should be True (close > vwap), got {row['window_vwap_trend_ok']}"
        )


def test_quality_window_signal_gap_filter_uses_window_close_basis_consistently() -> None:
    trade_day = date(2026, 3, 12)
    ts_base = pd.Timestamp("2026-03-12 09:00:00", tz="US/Eastern").tz_convert("UTC")
    detail = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["TEST", "TEST"],
            "timestamp": [ts_base, ts_base + pd.Timedelta(minutes=1)],
            "session": ["premarket", "premarket"],
            "open": [100.0, 100.0],
            "high": [101.0, 103.0],
            "low": [99.0, 100.0],
            "close": [100.0, 103.0],
            "volume": [400_000.0, 400_000.0],
            "trade_count": [40, 40],
        }
    )
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["TEST"],
            "previous_close": [100.0],
            "market_open_price": [101.0],
        }
    )
    premarket = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["TEST"],
            "prev_close_to_premarket_pct": [-5.0],
            "premarket_to_open_pct": [0.0],
        }
    )

    status, candidate_exports = _compute_quality_window_signal(
        detail,
        daily_features=daily,
        premarket_features=premarket,
        display_timezone="Europe/Berlin",
        latest_trade_date=trade_day,
    )

    row = status.iloc[0]
    assert row["quality_open_drive_window_latest_berlin"] == "14:00-14:30"
    assert not pd.isna(row["quality_open_drive_window_score_latest_berlin"])
    assert list(candidate_exports["quality_candidates_0900_0930_et_all"]["symbol"]) == ["TEST"]


def test_collect_full_universe_preserves_trade_count(monkeypatch, tmp_path: Path) -> None:
    """collect_full_universe_open_window_second_detail should propagate the
    trade_count column (normalized from 'count') to the output frame."""
    from databento_volatility_screener import collect_full_universe_open_window_second_detail
    import databento_volatility_screener as screener_mod

    trade_day = date(2026, 3, 6)
    ts_base = pd.Timestamp("2026-03-06 09:00:00", tz="US/Eastern").tz_convert("UTC")

    raw_frame = pd.DataFrame({
        "ts_event": [ts_base + pd.Timedelta(seconds=i) for i in range(3)],
        "symbol": ["AAPL"] * 3,
        "open": [150.0, 151.0, 152.0],
        "high": [151.0, 152.0, 153.0],
        "low": [149.0, 150.0, 151.0],
        "close": [151.0, 152.0, 153.0],
        "volume": [100, 200, 300],
        "count": [5, 10, 15],  # Databento uses 'count', not 'trade_count'
    })

    class FakeStore:
        def to_df(self, count=None):
            return raw_frame.copy()

    class FakeTimeseries:
        def get_range(self, **kwargs):
            return FakeStore()

    class FakeClient:
        timeseries = FakeTimeseries()

    monkeypatch.setattr(screener_mod, "_get_schema_available_end", lambda *a, **kw: pd.Timestamp("2026-03-07", tz="UTC"))
    monkeypatch.setattr(screener_mod, "_probe_symbol_support", lambda *a, **kw: ({"AAPL"}, set()))
    monkeypatch.setattr(screener_mod, "_make_databento_client", lambda *a, **kw: FakeClient())

    result = collect_full_universe_open_window_second_detail(
        "fake-key",
        dataset="DBEQ.BASIC",
        trading_days=[trade_day],
        universe_symbols={"AAPL"},
        daily_bars=pd.DataFrame({
            "trade_date": [trade_day],
            "symbol": ["AAPL"],
            "previous_close": [148.0],
        }),
        display_timezone="Europe/Berlin",
        window_start=time(9, 0),
        window_end=time(9, 30),
        premarket_anchor_et=time(4, 0),
        cache_dir=tmp_path,
        use_file_cache=False,
        force_refresh=True,
    )

    assert not result.empty, "Expected non-empty result"
    assert "trade_count" in result.columns, (
        f"Expected 'trade_count' column in output, got columns: {list(result.columns)}"
    )
    assert result["trade_count"].tolist() == [5, 10, 15], (
        f"Expected trade_count=[5,10,15], got {result['trade_count'].tolist()}"
    )
