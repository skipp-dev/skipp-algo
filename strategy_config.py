from __future__ import annotations

LONG_DIP_MIN_GAP_PCT = 5.0
LONG_DIP_MAX_GAP_PCT: float | None = 40.0
LONG_DIP_MIN_PREVIOUS_CLOSE = 2.0
LONG_DIP_MIN_PREMARKET_VOLUME = 50_000
LONG_DIP_MIN_PREMARKET_TRADE_COUNT = 200
LONG_DIP_EARLY_MIN_GAP_PCT = 2.0
LONG_DIP_EARLY_MIN_PREMARKET_VOLUME = 10_000
LONG_DIP_EARLY_MIN_PREMARKET_TRADE_COUNT = 25
LONG_DIP_BUILDING_MIN_GAP_PCT = 3.0
LONG_DIP_BUILDING_MIN_PREMARKET_VOLUME = 25_000
LONG_DIP_BUILDING_MIN_PREMARKET_TRADE_COUNT = 100
LONG_DIP_SPARSE_MIN_GAP_PCT = 1.0
LONG_DIP_SPARSE_MIN_PREMARKET_VOLUME = 1_000
LONG_DIP_SPARSE_MIN_PREMARKET_TRADE_COUNT = 0
LONG_DIP_POSITION_BUDGET_USD = 10_000.0
LONG_DIP_TOP_N = 5
LONG_DIP_LADDER_PCTS = (-0.004, -0.009, -0.017)
LONG_DIP_LADDER_WEIGHTS = (0.25, 0.35, 0.40)
LONG_DIP_TAKE_PROFIT_1_PCT = 0.015
LONG_DIP_HARD_STOP_PCT = 0.016
LONG_DIP_TRAILING_STOP_PCT = 0.010
LONG_DIP_DISPLAY_TIMEZONE = "Europe/Berlin"
LONG_DIP_RECOMMENDED_RUN_WINDOW_START = "15:23:00"
LONG_DIP_RECOMMENDED_RUN_WINDOW_END = "15:26:00"
LONG_DIP_OPTIONAL_REFRESH_WINDOW_START = "15:28:00"
LONG_DIP_OPTIONAL_REFRESH_WINDOW_END = "15:29:00"
LONG_DIP_AS_OF_LABEL = "15:29:59 Europe/Berlin"


def get_long_dip_config_snapshot() -> dict[str, object]:
    return {
        "min_gap_pct": LONG_DIP_MIN_GAP_PCT,
        "max_gap_pct": LONG_DIP_MAX_GAP_PCT,
        "min_previous_close": LONG_DIP_MIN_PREVIOUS_CLOSE,
        "min_premarket_volume": LONG_DIP_MIN_PREMARKET_VOLUME,
        "min_premarket_trade_count": LONG_DIP_MIN_PREMARKET_TRADE_COUNT,
        "early_min_gap_pct": LONG_DIP_EARLY_MIN_GAP_PCT,
        "early_min_premarket_volume": LONG_DIP_EARLY_MIN_PREMARKET_VOLUME,
        "early_min_premarket_trade_count": LONG_DIP_EARLY_MIN_PREMARKET_TRADE_COUNT,
        "building_min_gap_pct": LONG_DIP_BUILDING_MIN_GAP_PCT,
        "building_min_premarket_volume": LONG_DIP_BUILDING_MIN_PREMARKET_VOLUME,
        "building_min_premarket_trade_count": LONG_DIP_BUILDING_MIN_PREMARKET_TRADE_COUNT,
        "sparse_min_gap_pct": LONG_DIP_SPARSE_MIN_GAP_PCT,
        "sparse_min_premarket_volume": LONG_DIP_SPARSE_MIN_PREMARKET_VOLUME,
        "sparse_min_premarket_trade_count": LONG_DIP_SPARSE_MIN_PREMARKET_TRADE_COUNT,
        "ladder_pcts": LONG_DIP_LADDER_PCTS,
        "ladder_weights": LONG_DIP_LADDER_WEIGHTS,
        "take_profit_1_pct": LONG_DIP_TAKE_PROFIT_1_PCT,
        "hard_stop_pct": LONG_DIP_HARD_STOP_PCT,
        "trailing_stop_pct": LONG_DIP_TRAILING_STOP_PCT,
        "position_budget_usd": LONG_DIP_POSITION_BUDGET_USD,
        "top_n": LONG_DIP_TOP_N,
        "display_timezone": LONG_DIP_DISPLAY_TIMEZONE,
        "recommended_run_window_start": LONG_DIP_RECOMMENDED_RUN_WINDOW_START,
        "recommended_run_window_end": LONG_DIP_RECOMMENDED_RUN_WINDOW_END,
        "optional_refresh_window_start": LONG_DIP_OPTIONAL_REFRESH_WINDOW_START,
        "optional_refresh_window_end": LONG_DIP_OPTIONAL_REFRESH_WINDOW_END,
        "as_of_label": LONG_DIP_AS_OF_LABEL,
    }


LONG_DIP_DEFAULTS: dict[str, object] = get_long_dip_config_snapshot()