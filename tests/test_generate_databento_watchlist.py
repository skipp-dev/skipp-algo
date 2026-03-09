from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from strategy_config import LONG_DIP_DEFAULTS
from scripts.generate_databento_watchlist import (
    LongDipConfig,
    build_parser as build_watchlist_parser,
    build_daily_watchlists,
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

    cfg = LongDipConfig(min_premarket_volume=50_000, min_premarket_trade_count=200, max_gap_pct=40.0)
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
    assert [level.limit_price for level in levels] == [9.96, 9.91, 9.83]
    assert [level.quantity for level in levels] == [251, 353, 406]
    assert levels[0].take_profit_price == 10.1094
    assert levels[0].stop_loss_price == 9.8006
    assert levels[0].trailing_stop_anchor_price == 9.8604


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


def test_watchlist_and_executor_share_long_dip_defaults() -> None:
    watchlist_args = build_watchlist_parser().parse_args([])
    execute_args = build_execute_parser().parse_args([])

    assert watchlist_args.min_gap_pct == LONG_DIP_DEFAULTS["min_gap_pct"]
    assert execute_args.min_gap_pct == LONG_DIP_DEFAULTS["min_gap_pct"]
    assert watchlist_args.max_gap_pct == LONG_DIP_DEFAULTS["max_gap_pct"]
    assert execute_args.max_gap_pct == LONG_DIP_DEFAULTS["max_gap_pct"]
    assert watchlist_args.min_previous_close == LONG_DIP_DEFAULTS["min_previous_close"]
    assert execute_args.min_previous_close == LONG_DIP_DEFAULTS["min_previous_close"]
    assert watchlist_args.min_premarket_volume == LONG_DIP_DEFAULTS["min_premarket_volume"]
    assert execute_args.min_premarket_volume == LONG_DIP_DEFAULTS["min_premarket_volume"]
    assert watchlist_args.min_premarket_trade_count == LONG_DIP_DEFAULTS["min_premarket_trade_count"]
    assert execute_args.min_premarket_trade_count == LONG_DIP_DEFAULTS["min_premarket_trade_count"]
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
            "premarket_volume": [12_000] + [500] * (len(symbols) - 1),
            "premarket_trade_count": [30] + [2] * (len(symbols) - 1),
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
            "premarket_volume": [2_000],
            "premarket_trade_count": [0],
            "prev_close_to_premarket_pct": [1.2],
            "previous_close": [10.0],
        }
    )
    daily.to_parquet(tmp_path / "daily_symbol_features_full_universe.parquet", index=False)
    prem.to_parquet(tmp_path / "premarket_features_full_universe.parquet", index=False)

    result = generate_watchlist_result(export_dir=tmp_path, cfg=LongDipConfig(top_n=1))

    assert len(result["watchlist_table"]) == 1
    assert result["filter_profile"]["profile_name"] == "sparse_premarket"
    assert result["config_snapshot"]["min_premarket_volume"] == 1000