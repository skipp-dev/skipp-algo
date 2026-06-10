from __future__ import annotations

from skipp_config import get_trading_thresholds

_LONG_DIP_THRESHOLDS = get_trading_thresholds().long_dip

LONG_DIP_ENTRY_EARLY_DIP_MAX_SECONDS = _LONG_DIP_THRESHOLDS.entry_early_dip_max_seconds
LONG_DIP_ENTRY_EARLY_DIP_MIN_PCT = _LONG_DIP_THRESHOLDS.entry_early_dip_min_pct
LONG_DIP_ENTRY_OPEN30_VOLUME_MIN = _LONG_DIP_THRESHOLDS.entry_open30_volume_min
LONG_DIP_ENTRY_RECLAIM_MAX_SECONDS = _LONG_DIP_THRESHOLDS.entry_reclaim_max_seconds

LONG_DIP_TOP_N = _LONG_DIP_THRESHOLDS.top_n
LONG_DIP_MIN_GAP_PCT = _LONG_DIP_THRESHOLDS.min_gap_pct
LONG_DIP_MAX_GAP_PCT = _LONG_DIP_THRESHOLDS.max_gap_pct
LONG_DIP_MIN_PREVIOUS_CLOSE = _LONG_DIP_THRESHOLDS.min_previous_close
LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME = _LONG_DIP_THRESHOLDS.min_premarket_dollar_volume
LONG_DIP_MIN_PREMARKET_VOLUME = _LONG_DIP_THRESHOLDS.min_premarket_volume
LONG_DIP_MIN_PREMARKET_TRADE_COUNT = _LONG_DIP_THRESHOLDS.min_premarket_trade_count
LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS = _LONG_DIP_THRESHOLDS.sparse_min_premarket_active_seconds
LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS = _LONG_DIP_THRESHOLDS.early_min_premarket_active_seconds
LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS = _LONG_DIP_THRESHOLDS.building_min_premarket_active_seconds
LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS = _LONG_DIP_THRESHOLDS.min_premarket_active_seconds
LONG_DIP_POSITION_BUDGET_USD = _LONG_DIP_THRESHOLDS.position_budget_usd

LONG_DIP_DEFAULTS = {
    "top_n": LONG_DIP_TOP_N,
    "min_gap_pct": LONG_DIP_MIN_GAP_PCT,
    "max_gap_pct": LONG_DIP_MAX_GAP_PCT,
    "min_previous_close": LONG_DIP_MIN_PREVIOUS_CLOSE,
    "min_premarket_dollar_volume": LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME,
    "min_premarket_volume": LONG_DIP_MIN_PREMARKET_VOLUME,
    "min_premarket_trade_count": LONG_DIP_MIN_PREMARKET_TRADE_COUNT,
    "min_premarket_active_seconds": LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS,
    "position_budget_usd": LONG_DIP_POSITION_BUDGET_USD,
}
