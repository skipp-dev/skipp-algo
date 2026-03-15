from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from strategy_config import (
    LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_DEFAULTS,
    LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS,
)
from scripts.generate_databento_watchlist import (
    LongDipConfig,
    _merge_open_signal_metrics,
    build_filter_funnel,
    build_parser as build_watchlist_parser,
    build_daily_watchlists,
    build_preanchor_seed_candidates,
    build_preopen_long_candidates,
    compute_entry_ladder,
    generate_watchlist_result,
)
from scripts.execute_ibkr_watchlist import build_parser as build_execute_parser


def test_build_preopen_long_candidates_filters_and_ranks_with_preopen_data() -> None:
    trade_date = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_date] * 3,
            "symbol": ["AAA", "BBB", "CCC"],
            "exchange": ["NASDAQ", "NYSE", "AMEX"],
            "asset_type": ["listed_equity_issue"] * 3,
            "previous_close": [5.0, 10.0, 7.0],
            "window_range_pct": [4.0, 2.0, 3.0],
            "window_return_pct": [2.0, 1.0, 1.5],
            "realized_vol_pct": [1.0, 1.0, 1.0],
            "selected_top20pct": [False, True, False],
            "is_eligible": [True, True, True],
            "eligibility_reason": ["eligible", "eligible", "eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_date] * 3,
            "symbol": ["AAA", "BBB", "CCC"],
            "has_premarket_data": [True, True, True],
            "premarket_last": [5.4, 11.0, 7.5],
            "premarket_volume": [90_000, 300_000, 20_000],
            "premarket_trade_count": [350, 800, 300],
            "prev_close_to_premarket_pct": [8.0, 10.0, 7.0],
        }
    )
    diagnostics = pd.DataFrame(
        {
            "trade_date": [trade_date] * 3,
            "symbol": ["AAA", "BBB", "CCC"],
            "present_in_eligible": [True, True, True],
            "excluded_reason": ["", "", ""],
        }
    )

    cfg = LongDipConfig(min_premarket_dollar_volume=0.0, min_premarket_volume=50_000, min_premarket_trade_count=200, max_gap_pct=40.0)
    candidates = build_preopen_long_candidates(
        daily=daily,
        prem=prem,
        cfg=cfg,
        trade_date=trade_date,
        diagnostics=diagnostics,
    )

    assert candidates["symbol"].tolist() == ["BBB", "AAA"]
    assert candidates.iloc[0]["watchlist_rank"] == 1
    assert candidates.iloc[1]["watchlist_rank"] == 2


def test_compute_entry_ladder_builds_three_levels_with_tp_and_stops() -> None:
    cfg = LongDipConfig(position_budget_usd=10_000.0)
    levels = compute_entry_ladder(10.0, cfg)

    assert [level.tag for level in levels] == ["L1", "L2", "L3"]
    assert [level.limit_price for level in levels] == [9.95, 9.9, 9.85]
    assert [level.quantity for level in levels] == [251, 353, 406]
    assert levels[0].take_profit_price == 10.149
    assert levels[0].stop_loss_price == 9.7908
    assert levels[0].trailing_stop_anchor_price == 9.8505


def test_build_daily_watchlists_limits_output_to_top_n_per_day() -> None:
    day_one = date(2026, 3, 6)
    day_two = date(2026, 3, 7)
    daily = pd.DataFrame(
        {
            "trade_date": [day_one, day_one, day_two],
            "symbol": ["AAA", "BBB", "CCC"],
            "exchange": ["NASDAQ", "NYSE", "AMEX"],
            "asset_type": ["listed_equity_issue"] * 3,
            "previous_close": [5.0, 6.0, 7.0],
            "window_range_pct": [1.0, 2.0, 3.0],
            "window_return_pct": [1.0, 1.0, 1.0],
            "realized_vol_pct": [1.0, 1.0, 1.0],
            "selected_top20pct": [False, False, True],
            "is_eligible": [True, True, True],
            "eligibility_reason": ["eligible", "eligible", "eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [day_one, day_one, day_two],
            "symbol": ["AAA", "BBB", "CCC"],
            "has_premarket_data": [True, True, True],
            "premarket_last": [5.4, 6.8, 8.0],
            "premarket_volume": [90_000, 95_000, 100_000],
            "premarket_trade_count": [350, 320, 400],
            "prev_close_to_premarket_pct": [8.0, 12.0, 14.0],
        }
    )

    watchlists = build_daily_watchlists(
        daily=daily,
        prem=prem,
        diagnostics=None,
        cfg=LongDipConfig(top_n=1),
    )

    assert watchlists[["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": day_one, "symbol": "BBB"},
        {"trade_date": day_two, "symbol": "CCC"},
    ]


def test_generate_watchlist_result_exposes_latest_trade_date_subset(tmp_path) -> None:
    day_one = date(2026, 3, 6)
    day_two = date(2026, 3, 7)
    daily = pd.DataFrame(
        {
            "trade_date": [day_one, day_one, day_two],
            "symbol": ["AAA", "BBB", "CCC"],
            "exchange": ["NASDAQ", "NYSE", "AMEX"],
            "asset_type": ["listed_equity_issue"] * 3,
            "previous_close": [5.0, 6.0, 7.0],
            "window_range_pct": [1.0, 2.0, 3.0],
            "window_return_pct": [1.0, 1.0, 1.0],
            "realized_vol_pct": [1.0, 1.0, 1.0],
            "selected_top20pct": [False, False, True],
            "is_eligible": [True, True, True],
            "eligibility_reason": ["eligible", "eligible", "eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [day_one, day_one, day_two],
            "symbol": ["AAA", "BBB", "CCC"],
            "has_premarket_data": [True, True, True],
            "premarket_last": [5.4, 6.8, 8.0],
            "premarket_volume": [90_000, 95_000, 100_000],
            "premarket_trade_count": [350, 320, 400],
            "prev_close_to_premarket_pct": [8.0, 12.0, 14.0],
        }
    )

    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["trade_date"] == "2026-03-07"
    assert result["watchlist_table"][["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": day_one, "symbol": "BBB"},
        {"trade_date": day_two, "symbol": "CCC"},
    ]
    assert result["active_watchlist_table"][["trade_date", "symbol"]].to_dict(orient="records") == [
        {"trade_date": day_two, "symbol": "CCC"},
    ]


def test_generate_watchlist_result_uses_manifest_exported_at_and_premarket_fallback_timestamps(tmp_path) -> None:
    trade_day = date(2026, 3, 7)
    manifest = {
        "exported_at": "2026-03-07T12:15:00+00:00",
        "premarket_fetched_at": "2026-03-07T12:10:00+00:00",
    }
    (tmp_path / "databento_volatility_production_20260307_121500_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
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
            "symbol": ["AAA"],
            "has_premarket_data": [True],
            "premarket_last": [10.5],
            "premarket_volume": [100_000],
            "premarket_trade_count": [500],
            "prev_close_to_premarket_pct": [5.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["source_metadata"]["export_generated_at"] == "2026-03-07T12:15:00+00:00"
    assert result["source_data_fetched_at"] == "2026-03-07T12:10:00+00:00"


def test_generate_watchlist_result_exact_named_prefers_exact_named_state_over_newer_unrelated_manifest(tmp_path) -> None:
    trade_day = date(2026, 3, 7)
    exact_state = {
        "manifest": {
            "export_generated_at": "2026-03-07T12:15:00+00:00",
            "premarket_fetched_at": "2026-03-07T12:10:00+00:00",
            "premarket_anchor_et": "04:00:00",
        },
        "source_manifest_path": str(tmp_path / "databento_volatility_production_20260307_121500_manifest.json"),
        "artifact_paths": {
            "daily_symbol_features_full_universe": str(tmp_path / "daily_symbol_features_full_universe.parquet"),
            "premarket_features_full_universe": str(tmp_path / "premarket_features_full_universe.parquet"),
        },
    }
    (tmp_path / "databento_exact_named_state.json").write_text(__import__("json").dumps(exact_state), encoding="utf-8")
    (tmp_path / "databento_preopen_fast_20260307_130000_manifest.json").write_text(
        __import__("json").dumps({"export_generated_at": "2026-03-07T13:00:00+00:00"}),
        encoding="utf-8",
    )

    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
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
            "symbol": ["AAA"],
            "has_premarket_data": [True],
            "premarket_last": [10.5],
            "premarket_volume": [100_000],
            "premarket_trade_count": [500],
            "prev_close_to_premarket_pct": [5.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["source_metadata"]["export_generated_at"] == "2026-03-07T12:15:00+00:00"
    assert result["source_metadata"]["manifest_path"].endswith("databento_exact_named_state.json")
    assert result["source_metadata"]["source_manifest_path"].endswith("databento_volatility_production_20260307_121500_manifest.json")


def test_generate_watchlist_result_falls_back_from_non_trading_day_to_latest_populated_trade_date(tmp_path) -> None:
    friday = date(2026, 3, 13)
    saturday = date(2026, 3, 14)
    daily = pd.DataFrame(
        {
            "trade_date": [friday, saturday],
            "symbol": ["AAA", "AAA"],
            "exchange": ["NYSE", "NYSE"],
            "asset_type": ["listed_equity_issue", "listed_equity_issue"],
            "previous_close": [10.0, 10.0],
            "window_range_pct": [2.0, 2.0],
            "window_return_pct": [1.0, 1.0],
            "realized_vol_pct": [1.0, 1.0],
            "selected_top20pct": [True, False],
            "is_eligible": [True, True],
            "eligibility_reason": ["eligible", "eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [friday, saturday],
            "symbol": ["AAA", "AAA"],
            "has_premarket_data": [True, False],
            "premarket_last": [10.5, pd.NA],
            "premarket_volume": [100_000, 0],
            "premarket_trade_count": [500, 0],
            "prev_close_to_premarket_pct": [5.0, 0.0],
        }
    )

    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["trade_date"] == "2026-03-13"
    assert result["active_watchlist_table"]["trade_date"].tolist() == [friday]
    assert any("non-trading day without qualifying rows" in warning for warning in result["warnings"])


def test_merge_open_signal_metrics_preserves_existing_values_when_metrics_are_partial() -> None:
    trade_day = date(2026, 3, 7)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "exchange": ["NYSE", "NYSE"],
            "asset_type": ["listed_equity_issue", "listed_equity_issue"],
            "previous_close": [10.0, 10.0],
            "window_range_pct": [2.0, 2.0],
            "window_return_pct": [1.0, 1.0],
            "realized_vol_pct": [1.0, 1.0],
            "selected_top20pct": [True, True],
            "is_eligible": [True, True],
            "eligibility_reason": ["eligible", "eligible"],
            "open_30s_volume": [111.0, 222.0],
        }
    )
    metrics = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "open_30s_volume": [333.0],
        }
    )

    merged = _merge_open_signal_metrics(daily, metrics)

    aaa = merged.loc[merged["symbol"] == "AAA"].iloc[0]
    bbb = merged.loc[merged["symbol"] == "BBB"].iloc[0]
    assert float(aaa["open_30s_volume"]) == 333.0
    assert float(bbb["open_30s_volume"]) == 222.0


def test_watchlist_and_executor_share_long_dip_defaults() -> None:
    watchlist_args = build_watchlist_parser().parse_args([])
    execute_args = build_execute_parser().parse_args([])

    assert watchlist_args.min_gap_pct == LONG_DIP_DEFAULTS["min_gap_pct"]
    assert execute_args.min_gap_pct == LONG_DIP_DEFAULTS["min_gap_pct"]
    assert watchlist_args.max_gap_pct == LONG_DIP_DEFAULTS["max_gap_pct"]
    assert execute_args.max_gap_pct == LONG_DIP_DEFAULTS["max_gap_pct"]
    assert watchlist_args.min_previous_close == LONG_DIP_DEFAULTS["min_previous_close"]
    assert execute_args.min_previous_close == LONG_DIP_DEFAULTS["min_previous_close"]
    assert watchlist_args.min_premarket_dollar_volume == LONG_DIP_DEFAULTS["min_premarket_dollar_volume"]
    assert execute_args.min_premarket_dollar_volume == LONG_DIP_DEFAULTS["min_premarket_dollar_volume"]
    assert watchlist_args.min_premarket_volume == LONG_DIP_DEFAULTS["min_premarket_volume"]
    assert execute_args.min_premarket_volume == LONG_DIP_DEFAULTS["min_premarket_volume"]
    assert watchlist_args.min_premarket_trade_count == LONG_DIP_DEFAULTS["min_premarket_trade_count"]
    assert execute_args.min_premarket_trade_count == LONG_DIP_DEFAULTS["min_premarket_trade_count"]
    assert watchlist_args.min_premarket_active_seconds == LONG_DIP_DEFAULTS["min_premarket_active_seconds"]
    assert execute_args.min_premarket_active_seconds == LONG_DIP_DEFAULTS["min_premarket_active_seconds"]
    assert watchlist_args.position_budget_usd == LONG_DIP_DEFAULTS["position_budget_usd"]
    assert execute_args.position_budget_usd == LONG_DIP_DEFAULTS["position_budget_usd"]
    assert watchlist_args.top_n == LONG_DIP_DEFAULTS["top_n"]
    assert execute_args.watchlist_top_n == LONG_DIP_DEFAULTS["top_n"]


def test_legacy_position_budget_alias_is_still_accepted() -> None:
    watchlist_args = build_watchlist_parser().parse_args(["--position-budget-eur", "12000"])
    execute_args = build_execute_parser().parse_args(["--position-budget-eur", "12000"])

    assert watchlist_args.position_budget_usd == 12_000.0
    assert execute_args.position_budget_usd == 12_000.0


def test_generate_watchlist_result_rejects_invalid_top_n(tmp_path) -> None:
    trade_day = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "previous_close": [10.0],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "has_premarket_data": [True],
            "premarket_last": [10.5],
            "premarket_volume": [100_000],
            "premarket_trade_count": [500],
            "prev_close_to_premarket_pct": [5.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    try:
        generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=0))
        raise AssertionError("Expected ValueError for invalid top_n")
    except ValueError as exc:
        assert "top_n must be > 0" in str(exc)


def test_generate_watchlist_result_uses_early_premarket_profile_from_manifest_timestamp(tmp_path) -> None:
    trade_day = date(2026, 3, 6)
    manifest = {
        "export_generated_at": "2026-03-06T12:10:00+00:00",
        "source_data_fetched_at": "2026-03-06T12:10:00+00:00",
    }
    (tmp_path / "databento_preopen_fast_20260306_121000_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    symbols = [f"S{i:02d}" for i in range(30)]
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "exchange": ["NYSE"] * len(symbols),
            "asset_type": ["listed_equity_issue"] * len(symbols),
            "previous_close": [10.0] * len(symbols),
            "window_range_pct": [2.0] * len(symbols),
            "window_return_pct": [1.0] * len(symbols),
            "realized_vol_pct": [1.0] * len(symbols),
            "selected_top20pct": [True] * len(symbols),
            "is_eligible": [True] * len(symbols),
            "eligibility_reason": ["eligible"] * len(symbols),
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "has_premarket_data": [True] * len(symbols),
            "premarket_last": [10.3] + [9.9] * (len(symbols) - 1),
            "premarket_volume": [60_000] + [500] * (len(symbols) - 1),
            "premarket_trade_count": [180] + [2] * (len(symbols) - 1),
            "prev_close_to_premarket_pct": [3.0] + [-1.0] * (len(symbols) - 1),
            "previous_close": [10.0] * len(symbols),
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 1
    assert result["filter_profile"]["profile_name"] == "early_premarket"
    assert result["config_snapshot"]["min_gap_pct"] == 2.0


def test_generate_watchlist_result_adapts_early_activity_threshold_shortly_after_anchor(tmp_path) -> None:
    trade_day = date(2026, 3, 12)
    # 08:15:43 UTC = 04:15:43 ET
    manifest = {
        "export_generated_at": "2026-03-12T08:15:43+00:00",
        "source_data_fetched_at": "2026-03-12T08:15:43+00:00",
        "premarket_anchor_et": "04:00:00",
    }
    (tmp_path / "databento_preopen_fast_20260312_081543_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    symbols = [f"S{i:03d}" for i in range(96)]
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "exchange": ["NASDAQ"] * len(symbols),
            "asset_type": ["listed_equity_issue"] * len(symbols),
            "previous_close": [10.0] * len(symbols),
            "window_range_pct": [2.0] * len(symbols),
            "window_return_pct": [1.0] * len(symbols),
            "realized_vol_pct": [1.0] * len(symbols),
            "selected_top20pct": [True] * len(symbols),
            "is_eligible": [True] * len(symbols),
            "eligibility_reason": ["eligible"] * len(symbols),
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "has_premarket_data": [True] * len(symbols),
            "premarket_last": [10.4] + [9.9] * (len(symbols) - 1),
            "premarket_volume": [2_000] + [900] * (len(symbols) - 1),
            "premarket_dollar_volume": [20_800.0] + [8_910.0] * (len(symbols) - 1),
            "premarket_trade_count": [40] + [5] * (len(symbols) - 1),
            "premarket_trade_count_source": ["proxy_active_seconds"] * len(symbols),
            "premarket_active_seconds": [40] + [5] * (len(symbols) - 1),
            "prev_close_to_premarket_pct": [4.0] + [-1.0] * (len(symbols) - 1),
            "previous_close": [10.0] * len(symbols),
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert result["filter_profile"]["profile_name"] == "early_premarket"
    assert result["config_snapshot"]["min_premarket_active_seconds"] == 30
    assert len(result["watchlist_table"]) == 1
    assert result["watchlist_table"].iloc[0]["symbol"] == "S000"


def test_generate_watchlist_result_uses_sparse_profile_when_premarket_universe_is_thin(tmp_path) -> None:
    trade_day = date(2026, 3, 6)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
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
            "symbol": ["AAA"],
            "has_premarket_data": [True],
            "premarket_last": [10.12],
            "premarket_volume": [50_000],
            "premarket_trade_count": [90],
            "prev_close_to_premarket_pct": [1.2],
            "previous_close": [10.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 1
    assert result["filter_profile"]["profile_name"] == "sparse_premarket"
    assert result["config_snapshot"]["min_premarket_dollar_volume"] == 1000.0
    assert result["config_snapshot"]["min_premarket_volume"] == 100


def test_generate_watchlist_result_relaxes_liquidity_when_early_profile_volume_blocks_all(tmp_path) -> None:
    trade_day = date(2026, 3, 6)
    manifest = {
        "export_generated_at": "2026-03-06T12:10:00+00:00",
        "source_data_fetched_at": "2026-03-06T12:10:00+00:00",
    }
    (tmp_path / "databento_preopen_fast_20260306_121000_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    symbols = [f"S{i:02d}" for i in range(30)]
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "exchange": ["NYSE"] * len(symbols),
            "asset_type": ["listed_equity_issue"] * len(symbols),
            "previous_close": [10.0] * len(symbols),
            "window_range_pct": [2.0] * len(symbols),
            "window_return_pct": [1.0] * len(symbols),
            "realized_vol_pct": [1.0] * len(symbols),
            "selected_top20pct": [True] * len(symbols),
            "is_eligible": [True] * len(symbols),
            "eligibility_reason": ["eligible"] * len(symbols),
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day] * len(symbols),
            "symbol": symbols,
            "has_premarket_data": [True] * len(symbols),
            "premarket_last": [130.0] + [9.9] * (len(symbols) - 1),
            "premarket_volume": [4_000] + [500] * (len(symbols) - 1),
            "premarket_trade_count": [90] + [1] * (len(symbols) - 1),
            "prev_close_to_premarket_pct": [2.6] + [-1.0] * (len(symbols) - 1),
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 1
    assert result["watchlist_table"].iloc[0]["symbol"] == "S00"
    assert result["filter_profile"]["profile_name"] == "liquidity_relaxed"
    assert result["config_snapshot"]["min_premarket_dollar_volume"] == 1000.0
    assert result["config_snapshot"]["min_premarket_volume"] == 100
    assert result["config_snapshot"]["min_premarket_trade_count"] == 0
    assert result["config_snapshot"]["min_premarket_active_seconds"] == 60
    assert result["filter_funnel"] == []


def test_generate_watchlist_result_flags_premarket_not_started_before_4am_et(tmp_path) -> None:
    trade_day = date(2026, 3, 9)
    manifest = {
        "export_generated_at": "2026-03-09T07:18:16+00:00",
        "source_data_fetched_at": "2026-03-09T07:18:16+00:00",
    }
    (tmp_path / "databento_preopen_fast_20260309_071816_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
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
            "symbol": ["AAA"],
            "has_premarket_data": [False],
            "premarket_last": [None],
            "premarket_volume": [0],
            "premarket_trade_count": [0],
            "prev_close_to_premarket_pct": [None],
            "previous_close": [10.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 1
    assert result["watchlist_table"].iloc[0]["symbol"] == "AAA"
    assert result["watchlist_table"].iloc[0]["premarket_last"] == 10.0
    assert result["filter_profile"]["profile_name"] == "pre_anchor_seeded"
    assert result["warnings"] == [
        "Live premarket data is not available yet. Showing provisional pre-anchor candidates from the historical selected_top20pct_0400 scope."
    ]


def test_generate_watchlist_result_does_not_flag_premarket_not_started_after_4am_et(tmp_path) -> None:
    """Regression: export at 07:49 ET (11:49 UTC) is after standard 04:00 ET premarket start,
    so profile should not be premarket_not_started even if zero symbols have premarket data."""
    trade_day = date(2026, 3, 10)
    manifest = {
        "export_generated_at": "2026-03-10T11:49:00+00:00",
        "source_data_fetched_at": "2026-03-10T11:49:00+00:00",
    }
    (tmp_path / "databento_preopen_fast_20260310_114900_manifest.json").write_text(
        __import__("json").dumps(manifest),
        encoding="utf-8",
    )

    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "exchange": ["NASDAQ"],
            "asset_type": ["listed_equity_issue"],
            "previous_close": [25.0],
            "window_range_pct": [3.0],
            "window_return_pct": [2.0],
            "realized_vol_pct": [1.5],
            "selected_top20pct": [True],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["BBB"],
            "has_premarket_data": [False],
            "premarket_last": [None],
            "premarket_volume": [0],
            "premarket_trade_count": [0],
            "prev_close_to_premarket_pct": [None],
            "previous_close": [25.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 0
    assert result["filter_profile"]["profile_name"] != "premarket_not_started"


def test_build_preanchor_seed_candidates_prefers_0400_scope_over_legacy_scope() -> None:
    trade_day = date(2026, 3, 10)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "exchange": ["NASDAQ", "NASDAQ"],
            "asset_type": ["listed_equity_issue", "listed_equity_issue"],
            "previous_close": [12.0, 11.0],
            "window_range_pct": [3.0, 2.0],
            "window_return_pct": [1.0, 0.5],
            "realized_vol_pct": [1.5, 1.2],
            "selected_top20pct": [False, True],
            "selected_top20pct_0400": [True, False],
            "is_eligible": [True, True],
            "eligibility_reason": ["eligible", "eligible"],
            "focus_0400_open_30s_volume": [20000.0, 1000.0],
            "focus_0400_reclaim_second_30s": [12.0, pd.NA],
        }
    )

    seeded = build_preanchor_seed_candidates(
        daily=daily,
        diagnostics=None,
        cfg=LongDipConfig(top_n=5),
        trade_date=trade_day,
    )

    assert seeded["symbol"].tolist() == ["AAA"]
    assert seeded.iloc[0]["candidate_basis"] == "pre_anchor_historical_seed"


def test_build_preopen_long_candidates_passes_open_window_fields_through() -> None:
    """Regression: open-window fields must survive the daily column selection in build_preopen_long_candidates."""
    from scripts.generate_databento_watchlist import expand_candidate_trade_plan

    trade_date = date(2026, 3, 9)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_date],
            "symbol": ["XYZ"],
            "exchange": ["NASDAQ"],
            "asset_type": ["listed_equity_issue"],
            "previous_close": [5.0],
            "window_range_pct": [4.0],
            "window_return_pct": [2.0],
            "realized_vol_pct": [1.0],
            "selected_top20pct": [False],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
            "open_30s_volume": [1234.0],
            "early_dip_pct_10s": [-2.5],
            "early_dip_second": [6.0],
            "reclaimed_start_price_within_30s": [True],
            "reclaim_second_30s": [12.0],
        }
    )
    prem = pd.DataFrame(
        {
            "trade_date": [trade_date],
            "symbol": ["XYZ"],
            "has_premarket_data": [True],
            "premarket_last": [6.0],
            "premarket_volume": [100_000],
            "premarket_trade_count": [500],
            "prev_close_to_premarket_pct": [20.0],
        }
    )
    cfg = LongDipConfig(min_premarket_dollar_volume=0.0, min_premarket_volume=0, min_premarket_trade_count=0)

    candidates = build_preopen_long_candidates(daily=daily, prem=prem, cfg=cfg, trade_date=trade_date)
    assert len(candidates) == 1
    assert float(candidates.iloc[0]["open_30s_volume"]) == 1234.0
    assert float(candidates.iloc[0]["early_dip_pct_10s"]) == -2.5
    assert float(candidates.iloc[0]["reclaim_second_30s"]) == 12.0

    expanded = expand_candidate_trade_plan(candidates, cfg)
    assert len(expanded) == 1
    assert float(expanded.iloc[0]["open_30s_volume"]) == 1234.0
    assert float(expanded.iloc[0]["early_dip_pct_10s"]) == -2.5
    assert bool(expanded.iloc[0]["reclaimed_start_price_within_30s"]) is True
    assert float(expanded.iloc[0]["reclaim_second_30s"]) == 12.0


def test_active_seconds_threshold_filters_proxy_activity_when_source_is_not_actual() -> None:
    trade_day = date(2026, 3, 10)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "exchange": ["NYSE", "NYSE"],
            "asset_type": ["listed_equity_issue", "listed_equity_issue"],
            "previous_close": [10.0, 10.0],
            "window_range_pct": [2.0, 2.0],
            "window_return_pct": [1.0, 1.0],
            "realized_vol_pct": [1.0, 1.0],
            "selected_top20pct": [True, True],
            "is_eligible": [True, True],
            "eligibility_reason": ["eligible", "eligible"],
        }
    )
    # Legacy/proxy shape: no actual count column in source, premarket_trade_count acts as active_seconds proxy.
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day, trade_day],
            "symbol": ["AAA", "BBB"],
            "has_premarket_data": [True, True],
            "premarket_last": [10.2, 10.3],
            "premarket_volume": [10_000, 10_000],
            "premarket_trade_count": [30, 90],
            "prev_close_to_premarket_pct": [2.0, 3.0],
        }
    )

    loose_cfg = LongDipConfig(
        min_gap_pct=1.0,
        min_premarket_dollar_volume=0.0,
        min_premarket_volume=0,
        min_premarket_trade_count=0,
        min_premarket_active_seconds=0,
    )
    strict_cfg = LongDipConfig(
        min_gap_pct=1.0,
        min_premarket_dollar_volume=0.0,
        min_premarket_volume=0,
        min_premarket_trade_count=0,
        min_premarket_active_seconds=60,
    )

    loose = build_preopen_long_candidates(daily=daily, prem=prem, cfg=loose_cfg, trade_date=trade_day)
    strict = build_preopen_long_candidates(daily=daily, prem=prem, cfg=strict_cfg, trade_date=trade_day)

    assert set(loose["symbol"].tolist()) == {"AAA", "BBB"}
    assert strict["symbol"].tolist() == ["BBB"]
    assert strict["trade_count_source_used"].eq("proxy_active_seconds").all()


def test_active_seconds_profile_threshold_values_are_monotonic_by_strictness() -> None:
    # Threshold values: sparse <= early <= building <= standard.
    # Note: survivor counts move in the opposite direction.
    assert LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS <= LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS
    assert LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS <= LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS
    assert LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS <= LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS


def test_filter_funnel_marks_trade_count_step_skipped_when_liquidity_data_missing() -> None:
    trade_day = date(2026, 3, 10)
    daily = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "previous_close": [10.0],
        }
    )
    # No premarket_trade_count provided -> source should be treated as missing.
    prem = pd.DataFrame(
        {
            "trade_date": [trade_day],
            "symbol": ["AAA"],
            "has_premarket_data": [True],
            "premarket_last": [10.2],
            "premarket_volume": [10_000],
            "premarket_dollar_volume": [102_000],
            "premarket_trade_count": [None],
            "prev_close_to_premarket_pct": [2.0],
        }
    )

    funnel = build_filter_funnel(
        daily=daily,
        prem=prem,
        cfg=LongDipConfig(min_gap_pct=1.0, min_premarket_dollar_volume=0.0, min_premarket_volume=0),
        trade_date=trade_day,
    )
    assert funnel[-1]["filter"] == "premarket_trade_count"
    assert funnel[-1]["threshold"] == "skipped (no data)"