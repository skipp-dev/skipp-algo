from __future__ import annotations

from datetime import UTC, date, datetime

import pandas as pd

from scripts.databento_preopen_fast import (
    _choose_scope_days,
    _aggregate_current_premarket_features,
    _build_current_daily_features,
    _resolve_target_trade_date,
    _select_recent_scope_symbols,
    _target_scope_symbol_count,
)


def test_resolve_target_trade_date_advances_to_current_et_day() -> None:
    completed = [date(2026, 3, 5), date(2026, 3, 6)]
    now_utc = datetime(2026, 3, 9, 12, 0, tzinfo=UTC)
    assert _resolve_target_trade_date(completed, now_utc=now_utc) == date(2026, 3, 9)


def test_select_recent_scope_symbols_uses_recent_selected_days() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 3), date(2026, 3, 4), date(2026, 3, 5), date(2026, 3, 5)],
            "symbol": ["AAA", "BBB", "CCC", "AAA"],
            "selected_top20pct": [True, True, False, True],
            "exchange": ["NYSE"] * 4,
            "asset_type": ["listed_equity_issue"] * 4,
            "is_eligible": [True] * 4,
            "eligibility_reason": ["eligible"] * 4,
        }
    )

    result = _select_recent_scope_symbols(frame, scope_days=1)

    assert sorted(result["symbol"].tolist()) == ["AAA"]
    assert bool(result.iloc[0]["selected_top20pct"])


def test_target_scope_symbol_count_varies_by_time() -> None:
    assert _target_scope_symbol_count(now_utc=datetime(2026, 3, 9, 12, 0, tzinfo=UTC)) == 3200
    assert _target_scope_symbol_count(now_utc=datetime(2026, 3, 9, 13, 5, tzinfo=UTC)) == 2400


def test_choose_scope_days_expands_until_target_symbol_count() -> None:
    frame = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 1), date(2026, 3, 2), date(2026, 3, 3), date(2026, 3, 4)],
            "symbol": ["AAA", "BBB", "CCC", "DDD"],
            "selected_top20pct": [True, True, True, True],
        }
    )

    scope_days, symbol_count = _choose_scope_days(
        frame,
        min_scope_days=1,
        max_scope_days=4,
        target_symbol_count=3,
        now_utc=datetime(2026, 3, 9, 12, 0, tzinfo=UTC),
    )

    assert scope_days == 3
    assert symbol_count == 3


def test_build_current_daily_features_uses_latest_close_as_previous_close() -> None:
    scope_rows = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 6)],
            "symbol": ["AAA"],
            "exchange": ["NYSE"],
            "asset_type": ["listed_equity_issue"],
            "is_eligible": [True],
            "eligibility_reason": ["eligible"],
            "window_range_pct": [4.2],
            "window_return_pct": [2.1],
            "realized_vol_pct": [1.3],
            "selected_top20pct": [True],
            "has_reference_data": [True],
            "has_fundamentals": [False],
            "has_daily_bars": [True],
            "has_intraday": [True],
            "has_market_cap": [False],
        }
    )
    daily_bars = pd.DataFrame(
        {
            "trade_date": [date(2026, 3, 5), date(2026, 3, 6)],
            "symbol": ["AAA", "AAA"],
            "close": [10.0, 11.0],
        }
    )

    result = _build_current_daily_features(scope_rows, daily_bars, target_trade_date=date(2026, 3, 9))

    assert result.iloc[0]["trade_date"] == date(2026, 3, 9)
    assert result.iloc[0]["previous_close"] == 11.0
    assert bool(result.iloc[0]["selected_top20pct"])


def test_aggregate_current_premarket_features_computes_gap_metrics() -> None:
    frame = pd.DataFrame(
        {
            "ts": [
                datetime(2026, 3, 9, 13, 0, tzinfo=UTC),
                datetime(2026, 3, 9, 13, 0, 1, tzinfo=UTC),
            ],
            "symbol": ["AAA", "AAA"],
            "open": [10.0, 10.2],
            "high": [10.2, 10.5],
            "low": [9.9, 10.1],
            "close": [10.2, 10.5],
            "volume": [100, 150],
        }
    )

    result = _aggregate_current_premarket_features(
        frame,
        {"AAA": 10.0},
        target_trade_date=date(2026, 3, 9),
    )

    assert bool(result.iloc[0]["has_premarket_data"])
    assert result.iloc[0]["premarket_last"] == 10.5
    assert round(float(result.iloc[0]["prev_close_to_premarket_pct"]), 4) == 5.0