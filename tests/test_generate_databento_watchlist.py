from __future__ import annotations

from datetime import date

import pandas as pd

from strategy_config import LONG_DIP_DEFAULTS
from scripts.generate_databento_watchlist import (
    LongDipConfig,
    build_parser as build_watchlist_parser,
    build_daily_watchlists,
    build_preopen_long_candidates,
    compute_entry_ladder,
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