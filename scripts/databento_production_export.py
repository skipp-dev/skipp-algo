from __future__ import annotations

import argparse
import logging
import math
import os
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

FIXED_ET_DISPLAY_TIMEZONE = "America/New_York"
FUNDAMENTAL_REFERENCE_EMPTY_CACHE_TTL_SECONDS = 30 * 60

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import (
    DEFAULT_CLOSE_IMBALANCE_AFTERHOURS_END_ET,
    DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET,
    DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET,
    DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET,
    DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET,
    US_EASTERN_TZ,
    _write_exact_named_export_state,
    _write_parquet_atomic,
    _write_tradingview_watchlist_exports,
    _read_cached_frame,
    _write_cached_frame,
    build_cache_path,
    build_export_basename,
    build_run_manifest_frame,
    build_daily_features_full_universe,
    build_summary_table,
    choose_default_dataset,
    collect_full_universe_close_outcome_minute_detail,
    collect_full_universe_close_trade_detail,
    collect_full_universe_open_window_second_detail,
    default_export_directory,
    estimate_databento_costs,
    export_run_artifacts,
    fetch_symbol_day_detail,
    fetch_us_equity_universe_with_metadata,
    filter_supported_universe_for_databento,
    list_accessible_datasets,
    list_recent_trading_days,
    load_daily_bars,
    normalize_symbol_for_databento,
    rank_top_fraction_per_day,
    resolve_display_timezone,
    run_intraday_screen,
)
from newsstack_fmp.ingest_benzinga import BenzingaRestAdapter
from open_prep.macro import FMPClient
from scripts.bullish_quality_config import (
    BullishQualityConfig,
    DEFAULT_BULLISH_QUALITY_SCORE_PROFILE,
    PremarketWindowDefinition,
    build_default_bullish_quality_config,
)
from scripts.databento_production_workbook import (
    canonical_production_workbook_path,
    write_databento_production_workbook_from_frames,
)
from scripts.market_structure_features import build_market_structure_feature_frame


def _env_flag(name: str, default: bool = False) -> bool:
    raw_value = str(os.getenv(name, "")).strip().lower()
    if not raw_value:
        return default
    return raw_value in {"1", "true", "yes", "on"}


DAILY_SYMBOL_FEATURE_COLUMNS = [
    "trade_date",
    "symbol",
    "exchange",
    "asset_type",
    "is_eligible",
    "eligibility_reason",
    "window_start_price",
    "window_high",
    "window_low",
    "window_end_price",
    "window_range_pct",
    "window_return_pct",
    "realized_vol_pct",
    "previous_close",
    "market_open_price",
    "open_30s_volume",
    "focus_0930_open_window_second_rows",
    "focus_0930_open_30s_volume",
    "focus_0930_early_dip_pct_10s",
    "focus_0930_early_dip_second",
    "focus_0930_reclaimed_start_price_within_30s",
    "focus_0930_reclaim_second_30s",
    "focus_0800_open_window_second_rows",
    "focus_0800_open_1m_volume",
    "focus_0800_open_5m_volume",
    "focus_0800_open_30s_volume",
    "focus_0800_regular_open_second_rows",
    "focus_0800_regular_open_5m_second_rows",
    "focus_0800_regular_open_30s_second_rows",
    "focus_0800_regular_open_reference_price",
    "focus_0800_early_dip_low_10s",
    "focus_0800_early_dip_pct_10s",
    "focus_0800_early_dip_second",
    "focus_0800_reclaimed_start_price_within_30s",
    "focus_0800_reclaim_second_30s",
    "focus_0400_open_window_second_rows",
    "focus_0400_open_1m_volume",
    "focus_0400_open_5m_volume",
    "focus_0400_open_30s_volume",
    "focus_0400_regular_open_second_rows",
    "focus_0400_regular_open_5m_second_rows",
    "focus_0400_regular_open_30s_second_rows",
    "focus_0400_regular_open_reference_price",
    "focus_0400_early_dip_low_10s",
    "focus_0400_early_dip_pct_10s",
    "focus_0400_early_dip_second",
    "focus_0400_reclaimed_start_price_within_30s",
    "focus_0400_reclaim_second_30s",
    "close_window_second_rows",
    "close_preclose_second_rows",
    "close_last_minute_second_rows",
    "close_postclose_second_rows",
    "close_10m_volume",
    "close_last_1m_volume",
    "close_postclose_5m_volume",
    "close_last_1m_volume_share",
    "close_postclose_volume_share",
    "close_reference_price",
    "close_auction_reference_price",
    "close_preclose_return_pct",
    "close_postclose_return_pct",
    "close_postclose_high_pct",
    "close_postclose_low_pct",
    "close_trade_print_count",
    "close_trade_share_volume",
    "close_trade_clean_print_count",
    "close_trade_clean_share_volume",
    "close_trade_bad_ts_recv_count",
    "close_trade_maybe_bad_book_count",
    "close_trade_publisher_specific_flag_count",
    "close_trade_sequence_break_count",
    "close_trade_event_time_regression_count",
    "close_trade_unknown_side_count",
    "close_trade_unknown_side_share",
    "close_trade_hygiene_score",
    "close_trade_unique_publishers",
    "close_trade_trf_print_count",
    "close_trade_trf_share_volume",
    "close_trade_lit_print_count",
    "close_trade_lit_share_volume",
    "close_trade_trf_volume_share",
    "close_trade_lit_volume_share",
    "close_trade_has_trf_activity",
    "close_trade_has_lit_activity",
    "close_trade_has_lit_followthrough",
    "close_afterhours_minute_rows",
    "close_afterhours_volume",
    "close_last_price_2000",
    "close_high_price_1600_2000",
    "close_low_price_1600_2000",
    "close_to_2000_return_pct",
    "close_to_2000_high_pct",
    "close_to_2000_low_pct",
    "next_trade_date",
    "next_day_open_price",
    "next_day_window_end_price",
    "close_to_next_open_return_pct",
    "next_open_to_window_end_return_pct",
    "close_to_next_window_end_return_pct",
    "has_next_day_outcome",
    "regular_open_reference_price",
    "early_dip_low_10s",
    "early_dip_pct_10s",
    "early_dip_second",
    "reclaimed_start_price_within_30s",
    "reclaim_second_30s",
    "sector",
    "industry",
    "market_cap",
    "rank_within_trade_date",
    "eligible_count_for_trade_date",
    "take_n_for_trade_date",
    "selected_top20pct",
    "selected_top20pct_0400",
    "has_reference_data",
    "has_fundamentals",
    "has_daily_bars",
    "has_intraday",
    "structure_trend_state",
    "structure_last_event",
    "structure_break_quality_score",
    "structure_pressure_score",
    "structure_compression_score",
    "structure_distance_to_swing_high_pct",
    "structure_distance_to_swing_low_pct",
    "structure_reclaim_flag",
    "structure_failed_break_flag",
    "structure_alignment_score",
    "structure_bias_score",
    "has_market_cap",
    "has_close_window_detail",
]

SECOND_DETAIL_EXPORT_COLUMNS = [
    "trade_date",
    "symbol",
    "timestamp",
    "session",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "second_delta_pct",
    "from_previous_close_pct",
    "from_open_pct",
    "trade_count",
]

PREMARKET_FEATURE_COLUMNS = [
    "trade_date",
    "symbol",
    "has_premarket_data",
    "previous_close",
    "premarket_open",
    "premarket_high",
    "premarket_low",
    "premarket_last",
    "premarket_vwap",
    "prev_close_to_premarket_pct",
    "premarket_to_open_pct",
    "premarket_volume",
    "premarket_dollar_volume",
    "premarket_trade_count",
    "premarket_trade_count_actual",
    "premarket_active_seconds",
    "premarket_last_trade_ts",
    "premarket_trade_count_source",
    "premarket_trade_count_usable",
    "premarket_seconds",
]

RESEARCH_EVENT_FLAG_COLUMNS = [
    "trade_date",
    "symbol",
    "is_earnings_day",
    "earnings_timing_pre_open",
    "earnings_timing_post_close",
]

RESEARCH_EVENT_FLAG_COVERAGE_COLUMNS = [
    "flag_name",
    "symbol_day_rows",
    "non_null_rows",
    "null_rows",
    "non_null_rate",
    "true_rows",
    "true_rate",
    "affected_trade_dates",
    "all_false_bug",
    "all_true_bug",
]

RESEARCH_EVENT_FLAG_TRADE_DATE_COLUMNS = [
    "trade_date",
    "flag_name",
    "symbol_day_rows",
    "true_rows",
    "true_rate",
]

RESEARCH_EVENT_FLAG_OUTCOME_SLICE_COLUMNS = [
    "flag_name",
    "selected_top20pct",
    "flag_value",
    "row_count",
    "mean_window_range_pct",
    "mean_realized_vol_pct",
    "mean_close_trade_hygiene_score",
    "mean_close_last_1m_volume_share",
    "mean_close_to_next_open_return_pct",
]

RESEARCH_NEWS_FLAG_COLUMNS = [
    "trade_date",
    "symbol",
    "has_company_news_24h",
    "company_news_item_count_24h",
    "has_company_news_preopen_window",
]

RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS = [
    "has_company_news_24h",
    "has_company_news_preopen_window",
]

RESEARCH_NEWS_FLAG_COUNT_COLUMNS = [
    "company_news_item_count_24h",
]

RESEARCH_NEWS_FLAG_COVERAGE_COLUMNS = RESEARCH_EVENT_FLAG_COVERAGE_COLUMNS.copy()
RESEARCH_NEWS_FLAG_TRADE_DATE_COLUMNS = RESEARCH_EVENT_FLAG_TRADE_DATE_COLUMNS.copy()
RESEARCH_NEWS_FLAG_OUTCOME_SLICE_COLUMNS = RESEARCH_EVENT_FLAG_OUTCOME_SLICE_COLUMNS.copy()

RESEARCH_NEWS_STATUS_OK = "ok"
RESEARCH_NEWS_STATUS_OK_EMPTY = "ok_empty"
RESEARCH_NEWS_STATUS_FETCH_FAILED = "fetch_failed"
RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED = "partial_fetch_failed"
RESEARCH_NEWS_STATUS_TRUNCATED = "truncated"
RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED_TRUNCATED = "partial_fetch_failed_truncated"

CORE_BENZINGA_NEWS_SIDE_BY_SIDE_COLUMNS = [
    "trade_date",
    "symbol",
    "selected_top20pct",
    "core_news_catalyst_score",
    "core_news_event_class",
    "core_news_materiality",
    "core_news_recency_bucket",
    "core_news_source_tier",
    "core_has_news",
    "benzinga_has_company_news_24h",
    "benzinga_company_news_item_count_24h",
    "benzinga_has_company_news_preopen_window",
    "benzinga_status_bucket",
    "overlap_bucket",
]
def _coalesce_optional_merge_column(frame: pd.DataFrame, column: str) -> pd.DataFrame:
    candidate_columns = [name for name in (column, f"{column}_x", f"{column}_y") if name in frame.columns]
    if not candidate_columns:
        frame[column] = pd.Series(pd.NA, index=frame.index)
        return frame

    merged = frame[candidate_columns[0]].copy()
    for candidate in candidate_columns[1:]:
        missing_mask = merged.isna()
        if not missing_mask.any():
            break
        merged.loc[missing_mask] = frame.loc[missing_mask, candidate]
    frame[column] = merged if merged is not None else pd.Series(pd.NA, index=frame.index)

    suffix_columns = [name for name in (f"{column}_x", f"{column}_y") if name in frame.columns]
    if suffix_columns:
        frame = frame.drop(columns=suffix_columns)
    return frame

CORE_BENZINGA_NEWS_OVERLAP_COLUMNS = [
    "trade_date",
    "overlap_bucket",
    "symbol_day_rows",
    "selected_top20pct_rows",
]

CLOSE_IMBALANCE_FEATURE_COLUMNS = [
    "trade_date",
    "symbol",
    "company_name",
    "exchange",
    "sector",
    "industry",
    "market_cap",
    "float_shares",
    "shares_outstanding",
    "news_score",
    "news_category",
    "earnings_date",
    "earnings_time",
    "filing_date",
    "filing_type",
    "mna_flag",
    "mna_side",
    "previous_close",
    "window_end_price",
    "day_close",
    "has_close_window_detail",
    "close_window_second_rows",
    "close_preclose_second_rows",
    "close_last_minute_second_rows",
    "close_postclose_second_rows",
    "close_10m_volume",
    "close_last_1m_volume",
    "close_postclose_5m_volume",
    "close_last_1m_volume_share",
    "close_postclose_volume_share",
    "close_reference_price",
    "close_auction_reference_price",
    "close_preclose_return_pct",
    "close_postclose_return_pct",
    "close_postclose_high_pct",
    "close_postclose_low_pct",
    "close_trade_print_count",
    "close_trade_share_volume",
    "close_trade_clean_print_count",
    "close_trade_clean_share_volume",
    "close_trade_bad_ts_recv_count",
    "close_trade_maybe_bad_book_count",
    "close_trade_publisher_specific_flag_count",
    "close_trade_sequence_break_count",
    "close_trade_event_time_regression_count",
    "close_trade_unknown_side_count",
    "close_trade_unknown_side_share",
    "close_trade_hygiene_score",
    "close_trade_unique_publishers",
    "close_trade_trf_print_count",
    "close_trade_trf_share_volume",
    "close_trade_lit_print_count",
    "close_trade_lit_share_volume",
    "close_trade_trf_volume_share",
    "close_trade_lit_volume_share",
    "close_trade_has_trf_activity",
    "close_trade_has_lit_activity",
    "close_trade_has_lit_followthrough",
    "close_afterhours_minute_rows",
    "close_afterhours_volume",
    "close_last_price_2000",
    "close_high_price_1600_2000",
    "close_low_price_1600_2000",
    "close_to_2000_return_pct",
    "close_to_2000_high_pct",
    "close_to_2000_low_pct",
    "next_trade_date",
    "next_day_open_price",
    "next_day_window_end_price",
    "close_to_next_open_return_pct",
    "next_open_to_window_end_return_pct",
    "close_to_next_window_end_return_pct",
    "has_next_day_outcome",
]

CLOSE_IMBALANCE_OUTCOME_COLUMNS = [
    "trade_date",
    "symbol",
    "close_auction_reference_price",
    "close_last_price_2000",
    "close_high_price_1600_2000",
    "close_low_price_1600_2000",
    "close_afterhours_volume",
    "close_to_2000_return_pct",
    "close_to_2000_high_pct",
    "close_to_2000_low_pct",
    "next_trade_date",
    "next_day_open_price",
    "next_day_window_end_price",
    "close_to_next_open_return_pct",
    "next_open_to_window_end_return_pct",
    "close_to_next_window_end_return_pct",
    "has_next_day_outcome",
]


def _build_exact_window_end_lookup(
    intraday_close_outcome_anchor: pd.DataFrame,
    *,
    display_timezone: str,
    window_end_et: time = DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET,
) -> pd.DataFrame:
    columns = ["trade_date", "symbol", "exact_1000_price"]
    if intraday_close_outcome_anchor.empty:
        return pd.DataFrame(columns=columns)

    lookup = intraday_close_outcome_anchor.copy()
    lookup["trade_date"] = pd.to_datetime(lookup["trade_date"], errors="coerce").dt.date
    lookup["symbol"] = lookup["symbol"].astype(str).str.upper()
    lookup["current_price"] = pd.to_numeric(lookup.get("current_price"), errors="coerce")
    lookup["current_price_timestamp"] = pd.to_datetime(lookup.get("current_price_timestamp"), errors="coerce", utc=True)
    lookup = lookup.dropna(subset=["trade_date", "symbol", "current_price_timestamp"]).copy()
    if lookup.empty:
        return pd.DataFrame(columns=columns)

    display_tz = resolve_display_timezone(display_timezone)
    lookup["current_price_timestamp"] = lookup["current_price_timestamp"].dt.tz_convert(display_tz)
    lookup["expected_window_end"] = lookup["trade_date"].map(
        lambda trade_day: pd.Timestamp(datetime.combine(trade_day, window_end_et, tzinfo=US_EASTERN_TZ).astimezone(display_tz))
    )
    lookup = lookup[
        lookup["current_price"].gt(0)
        & lookup["current_price_timestamp"].eq(lookup["expected_window_end"])
    ].copy()
    if lookup.empty:
        return pd.DataFrame(columns=columns)

    lookup = lookup.rename(columns={"current_price": "exact_1000_price"})
    return lookup[columns].drop_duplicates(subset=["trade_date", "symbol"], keep="last").reset_index(drop=True)


def _run_fixed_et_intraday_screen(*args: Any, **kwargs: Any) -> pd.DataFrame:
    return run_intraday_screen(*args, display_timezone=FIXED_ET_DISPLAY_TIMEZONE, **kwargs)


def _collect_fixed_et_second_detail(*args: Any, **kwargs: Any) -> pd.DataFrame:
    return collect_full_universe_open_window_second_detail(*args, display_timezone=FIXED_ET_DISPLAY_TIMEZONE, **kwargs)

PREMARKET_WINDOW_FEATURE_COLUMNS = [
    "trade_date",
    "symbol",
    "window_tag",
    "window_start_ts",
    "window_end_ts",
    "dataset",
    "source_data_fetched_at",
    "has_window_data",
    "seconds_in_window",
    "window_row_count",
    "window_trade_count",
    "window_active_seconds",
    "window_open",
    "window_high",
    "window_low",
    "window_close",
    "window_vwap",
    "window_return_pct",
    "window_range_pct",
    "window_close_vs_high_pct",
    "window_close_vs_low_pct",
    "window_body_pct",
    "window_upper_wick_pct",
    "window_lower_wick_pct",
    "window_volume",
    "window_dollar_volume",
    "window_trade_count_actual",
    "window_trade_count_source",
    "window_trade_count_usable",
    "window_last_trade_ts",
    "previous_close",
    "market_open_price",
    "prev_close_to_window_open_pct",
    "prev_close_to_window_close_pct",
    "window_close_position_pct",
    "window_trend_efficiency_pct",
    "window_pullback_pct",
    "window_stability_score",
    "window_liquidity_score",
    "window_structure_score",
        "window_structure_trend_state",
        "window_structure_last_event",
        "window_structure_break_quality_score",
        "window_structure_pressure_score",
        "window_structure_compression_score",
        "window_structure_distance_to_swing_high_pct",
        "window_structure_distance_to_swing_low_pct",
        "window_structure_reclaim_flag",
        "window_structure_failed_break_flag",
        "window_structure_alignment_score",
        "window_structure_bias_score",
    "extension_score",
    "window_quality_score",
        "structure_trend_state",
        "structure_last_event",
        "structure_break_quality_score",
        "structure_pressure_score",
        "structure_compression_score",
        "structure_distance_to_swing_high_pct",
        "structure_distance_to_swing_low_pct",
        "structure_reclaim_flag",
        "structure_failed_break_flag",
        "structure_alignment_score",
        "structure_bias_score",
    "passes_min_previous_close",
    "passes_min_gap_pct",
    "passes_min_window_dollar_volume",
    "passes_min_window_trade_count",
    "passes_quality_filter",
    "quality_filter_reason",
    "quality_rank_within_window",
    "quality_selected_top_n",
]

SYMBOL_DAY_DIAGNOSTIC_COLUMNS = [
    "trade_date",
    "symbol",
    "present_in_raw_universe",
    "present_after_reference_join",
    "present_after_fundamentals_join",
    "present_after_daily_filter",
    "present_after_intraday_filter",
    "present_in_eligible",
    "selected_top20pct",
    "selected_top20pct_0400",
    "excluded_step",
    "excluded_reason",
    "exchange",
    "asset_type",
    "has_reference_data",
    "has_fundamentals",
    "has_daily_bars",
    "has_intraday",
    "has_market_cap",
    "is_supported_by_databento",
]

FUNDAMENTAL_REFERENCE_COLUMNS = [
    "symbol",
    "company_name_profile",
    "exchange_profile",
    "sector_profile",
    "industry_profile",
    "market_cap_profile",
    "asset_type_profile",
    "has_fundamental_row",
]

QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN = "quality_open_drive_window_latest_berlin"
QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN = "quality_open_drive_window_coverage_latest_berlin"
QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN = "quality_open_drive_window_trade_date"
QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN = "quality_open_drive_window_score_latest_berlin"
QUALITY_OPEN_DRIVE_ET_WINDOWS = (
    ("early", time(4, 0), time(4, 30)),
    ("late", time(9, 0), time(9, 30)),
)
QUALITY_OPEN_DRIVE_OPEN_CONFIRM_ET_WINDOW = (time(9, 30), time(9, 31))
QUALITY_OPEN_DRIVE_EARLY_EXCHANGE_DATASETS = {
    "NASDAQ": "XNAS.BASIC",
    "NYSE": "XNYS.PILLAR",
    "AMEX": "XASE.PILLAR",
}
QUALITY_OPEN_DRIVE_HARD_FILTERS = {
    "min_previous_close": 5.0,
    "min_prev_close_to_premarket_pct": 0.0,
    "min_window_dollar_volume": 500_000.0,
}
QUALITY_OPEN_DRIVE_QUALITY_THRESHOLDS = {
    "min_window_return_pct": 0.0,
    "max_window_range_pct": 12.0,
    "min_close_vs_high_pct": -2.0,
}
QUALITY_OPEN_DRIVE_SCORE_WEIGHTS = {
    "prev_close_ok": 1.0,
    "gap_ok": 1.0,
    "dollar_vol_ok": 2.0,
    "window_return_ok": 1.5,
    "close_near_high_ok": 2.0,
    "range_ok": 1.0,
    "above_vwap_ok": 1.0,
    "open_confirm_ok": 2.0,
}

_DEFAULT_BULLISH_QUALITY_CFG = build_default_bullish_quality_config()


def configure_bullish_quality_score_profile(*, score_profile: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE) -> None:
    global _DEFAULT_BULLISH_QUALITY_CFG
    _DEFAULT_BULLISH_QUALITY_CFG = build_default_bullish_quality_config(score_profile=score_profile)
QUALITY_OPEN_DRIVE_CANDIDATE_EXPORT_COLUMNS = [
    "trade_date",
    "symbol",
    "exchange",
    "window_key",
    "window_label_local",
    "previous_close",
    "prev_close_to_premarket_pct",
    "premarket_to_open_pct",
    "window_return_pct",
    "window_range_pct",
    "window_close_vs_high_pct",
    "window_dollar_volume",
    "quality_score",
    "passes_quality",
    "window_vwap_trend_ok",
    "open_confirm_ok",
]


def _bool_series(frame: pd.DataFrame, column: str, default: bool = False) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(default, index=frame.index, dtype=bool)
    series = frame[column]
    if pd.api.types.is_bool_dtype(series):
        return series.fillna(default).astype(bool)
    normalized = series.astype(str).str.strip().str.lower()
    mapped = normalized.map({"true": True, "false": False})
    return mapped.fillna(default).astype(bool)


def _numeric_series(frame: pd.DataFrame, column: str, *, fill_value: float = np.nan) -> pd.Series:
    value = frame[column] if column in frame.columns else pd.Series(fill_value, index=frame.index)
    if isinstance(value, pd.Series):
        return pd.to_numeric(value, errors="coerce")
    if isinstance(value, pd.DataFrame):
        collapsed = value.apply(lambda col: pd.to_numeric(col, errors="coerce")).bfill(axis=1).iloc[:, 0]
        return pd.to_numeric(collapsed, errors="coerce")
    return pd.Series(fill_value, index=frame.index, dtype="float64")


def _parse_window_time_et(value: str) -> time:
    return time.fromisoformat(str(value))


def _score_pct(value: Any, *, floor: float, ceiling: float) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric) or ceiling <= floor:
        return 0.0
    scaled = ((float(numeric) - floor) / (ceiling - floor)) * 100.0
    return float(np.clip(scaled, 0.0, 100.0))


def _score_inverse_pct(value: Any, *, floor: float, ceiling: float) -> float:
    return 100.0 - _score_pct(value, floor=floor, ceiling=ceiling)


def _score_log_ratio(value: Any, minimum: float) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric) or numeric <= 0 or minimum <= 0:
        return 0.0
    ratio = float(numeric) / float(minimum)
    if ratio <= 0:
        return 0.0
    return float(np.clip(50.0 + (np.log10(ratio) * 50.0), 0.0, 100.0))


def _score_extension(prev_close_to_window_close_pct: Any) -> float:
    numeric = pd.to_numeric(pd.Series([prev_close_to_window_close_pct]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    numeric = float(numeric)
    if numeric <= 0:
        return 0.0
    if numeric <= 2.0:
        return _score_pct(numeric, floor=0.0, ceiling=2.0)
    if numeric <= 12.0:
        return 100.0
    if numeric >= 25.0:
        return 0.0
    return _score_inverse_pct(numeric, floor=12.0, ceiling=25.0)


def _window_bounds_for_trade_date(trade_day: Any, window_definition: PremarketWindowDefinition) -> tuple[pd.Timestamp, pd.Timestamp]:
    trade_ts = pd.Timestamp(trade_day)
    start_et = pd.Timestamp.combine(trade_ts.date(), _parse_window_time_et(window_definition.start_time_et)).tz_localize(US_EASTERN_TZ)
    end_et = pd.Timestamp.combine(trade_ts.date(), _parse_window_time_et(window_definition.end_time_et)).tz_localize(US_EASTERN_TZ)
    return start_et.tz_convert(UTC), end_et.tz_convert(UTC)


def _build_empty_premarket_window_features_export(expected: pd.DataFrame) -> pd.DataFrame:
    out = expected.copy()
    out["has_window_data"] = False
    out["passes_quality_filter"] = False
    out["quality_filter_reason"] = "no_window_data"
    out["quality_rank_within_window"] = pd.Series(pd.array([pd.NA] * len(out), dtype="Int64"), index=out.index)
    out["quality_selected_top_n"] = False
    for column in PREMARKET_WINDOW_FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = False if column == "quality_selected_top_n" else np.nan
    out["quality_rank_within_window"] = out["quality_rank_within_window"].astype("Int64")
    out["quality_selected_top_n"] = out["quality_selected_top_n"].fillna(False).astype(bool)
    return out[PREMARKET_WINDOW_FEATURE_COLUMNS].sort_values(["trade_date", "window_tag", "symbol"]).reset_index(drop=True)


def _populate_quality_window_ranks(frame: pd.DataFrame, *, top_n: int) -> pd.DataFrame:
    ranked = frame.copy()
    ranked["quality_rank_within_window"] = pd.Series(pd.array([pd.NA] * len(ranked), dtype="Int64"), index=ranked.index)
    ranked["quality_selected_top_n"] = False
    eligible = ranked["passes_quality_filter"].fillna(False).astype(bool)
    if not eligible.any():
        ranked["quality_rank_within_window"] = ranked["quality_rank_within_window"].astype("Int64")
        ranked["quality_selected_top_n"] = ranked["quality_selected_top_n"].astype(bool)
        return ranked

    ranked["window_quality_score"] = pd.to_numeric(ranked.get("window_quality_score"), errors="coerce")
    ranked["window_structure_bias_score"] = pd.to_numeric(ranked.get("window_structure_bias_score"), errors="coerce")
    ranked["window_structure_alignment_score"] = pd.to_numeric(ranked.get("window_structure_alignment_score"), errors="coerce")
    ranked["window_dollar_volume"] = pd.to_numeric(ranked.get("window_dollar_volume"), errors="coerce")
    ordered = ranked.loc[eligible].sort_values(
        [
            "trade_date",
            "window_tag",
            "window_quality_score",
            "window_structure_bias_score",
            "window_structure_alignment_score",
            "window_dollar_volume",
            "symbol",
        ],
        ascending=[True, True, False, False, False, False, True],
    )
    ranks = ordered.groupby(["trade_date", "window_tag"]).cumcount() + 1
    ranked.loc[ordered.index, "quality_rank_within_window"] = pd.array(ranks.tolist(), dtype="Int64")
    ranked.loc[ordered.index, "quality_selected_top_n"] = ranks <= int(top_n)
    ranked["quality_rank_within_window"] = ranked["quality_rank_within_window"].astype("Int64")
    ranked["quality_selected_top_n"] = ranked["quality_selected_top_n"].fillna(False).astype(bool)
    return ranked


def _compute_quality_reason(frame: pd.DataFrame, *, cfg: BullishQualityConfig | None = None) -> pd.Series:
    resolved_cfg = cfg or _DEFAULT_BULLISH_QUALITY_CFG
    reason = pd.Series("eligible", index=frame.index, dtype=object)
    reason = pd.Series(np.where(~frame["has_window_data"].fillna(False).astype(bool), "no_window_data", reason), index=frame.index, dtype=object)
    reason = pd.Series(np.where((reason == "eligible") & ~frame["passes_min_previous_close"].fillna(False), "previous_close_below_min", reason), index=frame.index, dtype=object)
    reason = pd.Series(np.where((reason == "eligible") & ~frame["passes_min_gap_pct"].fillna(False), "gap_below_min", reason), index=frame.index, dtype=object)
    reason = pd.Series(np.where((reason == "eligible") & ~frame["passes_min_window_dollar_volume"].fillna(False), "window_dollar_volume_below_min", reason), index=frame.index, dtype=object)
    reason = pd.Series(np.where((reason == "eligible") & ~frame["passes_min_window_trade_count"].fillna(False), "window_trade_count_below_min", reason), index=frame.index, dtype=object)
    _close_pos = pd.to_numeric(frame["window_close_position_pct"], errors="coerce")
    reason = pd.Series(
        np.where(
            (reason == "eligible")
            & (~(_close_pos >= resolved_cfg.min_window_close_position_pct)),
            "close_position_below_min",
            reason,
        ),
        index=frame.index,
        dtype=object,
    )
    _return_pct = pd.to_numeric(frame["window_return_pct"], errors="coerce")
    reason = pd.Series(
        np.where(
            (reason == "eligible")
            & (~(_return_pct >= resolved_cfg.min_window_return_pct)),
            "window_return_below_min",
            reason,
        ),
        index=frame.index,
        dtype=object,
    )
    _pullback = pd.to_numeric(frame["window_pullback_pct"], errors="coerce")
    reason = pd.Series(
        np.where(
            (reason == "eligible")
            & (~(_pullback <= resolved_cfg.max_window_pullback_pct)),
            "window_pullback_above_max",
            reason,
        ),
        index=frame.index,
        dtype=object,
    )
    _wclose = pd.to_numeric(frame["window_close"], errors="coerce")
    _wvwap = pd.to_numeric(frame["window_vwap"], errors="coerce")
    reason = pd.Series(
        np.where(
            (reason == "eligible")
            & resolved_cfg.require_close_above_vwap
            & (~(_wclose >= _wvwap)),
            "close_below_vwap",
            reason,
        ),
        index=frame.index,
        dtype=object,
    )
    return reason


def compute_single_window_features(
    symbol_day_second_detail: pd.DataFrame,
    daily_context_row: pd.Series | dict[str, Any],
    *,
    window_definition: PremarketWindowDefinition,
    dataset: str,
    source_data_fetched_at: str | None,
    cfg: BullishQualityConfig | None = None,
) -> dict[str, Any]:
    daily_context = pd.DataFrame([dict(daily_context_row)])
    result = build_premarket_window_features_full_universe_export(
        symbol_day_second_detail,
        daily_context,
        window_definitions=(window_definition,),
        source_data_fetched_at=source_data_fetched_at,
        dataset=dataset,
        cfg=cfg,
    )
    if result.empty:
        return {}
    return dict(result.iloc[0].to_dict())


def build_premarket_window_features_full_universe_export(
    second_detail_all: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    window_definitions: tuple[PremarketWindowDefinition, ...],
    source_data_fetched_at: str | None,
    dataset: str,
    cfg: BullishQualityConfig | None = None,
) -> pd.DataFrame:
    resolved_cfg = cfg or _DEFAULT_BULLISH_QUALITY_CFG
    daily_context = daily_bars.copy()
    if daily_context.empty:
        return pd.DataFrame(columns=PREMARKET_WINDOW_FEATURE_COLUMNS)

    daily_context["trade_date"] = pd.to_datetime(daily_context["trade_date"], errors="coerce").dt.date
    daily_context["symbol"] = daily_context["symbol"].astype(str).str.upper()
    base_columns = [column for column in ["trade_date", "symbol", "previous_close", "market_open_price"] if column in daily_context.columns]
    daily_context = daily_context[base_columns].drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)

    expected_rows: list[dict[str, Any]] = []
    for trade_day in daily_context["trade_date"].dropna().drop_duplicates().tolist():
        for definition in window_definitions:
            start_ts, end_ts = _window_bounds_for_trade_date(trade_day, definition)
            expected_rows.append(
                {
                    "trade_date": trade_day,
                    "window_tag": definition.tag,
                    "window_start_ts": start_ts,
                    "window_end_ts": end_ts,
                    "seconds_in_window": int((end_ts - start_ts).total_seconds()),
                }
            )
    expected = daily_context.merge(pd.DataFrame(expected_rows), on="trade_date", how="left")
    expected["dataset"] = str(dataset).strip().upper()
    expected["source_data_fetched_at"] = source_data_fetched_at

    if second_detail_all.empty:
        return _build_empty_premarket_window_features_export(expected)

    detail = second_detail_all.copy()
    detail["trade_date"] = pd.to_datetime(detail["trade_date"], errors="coerce").dt.date
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce", utc=True)
    detail = detail.dropna(subset=["trade_date", "symbol", "timestamp"]).copy()
    if "session" in detail.columns:
        detail = detail.loc[detail["session"].astype(str).str.lower().eq("premarket")].copy()
    else:
        detail["et_time"] = detail["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
        detail = detail.loc[detail["et_time"] < time(9, 30)].copy()
    if detail.empty:
        return _build_empty_premarket_window_features_export(expected)

    detail["open"] = pd.to_numeric(detail.get("open"), errors="coerce")
    detail["high"] = pd.to_numeric(detail.get("high"), errors="coerce")
    detail["low"] = pd.to_numeric(detail.get("low"), errors="coerce")
    detail["close"] = pd.to_numeric(detail.get("close"), errors="coerce")
    detail["volume"] = pd.to_numeric(detail.get("volume"), errors="coerce").fillna(0.0)
    detail["trade_count_numeric"] = pd.to_numeric(detail.get("trade_count"), errors="coerce") if "trade_count" in detail.columns else np.nan
    detail["dollar_volume"] = detail["close"] * detail["volume"]
    detail["et_time"] = detail["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time

    window_masks = []
    for definition in window_definitions:
        start_time = _parse_window_time_et(definition.start_time_et)
        end_time = _parse_window_time_et(definition.end_time_et)
        window_masks.append(detail["et_time"].ge(start_time) & detail["et_time"].lt(end_time))
    detail["window_tag"] = np.select(window_masks, [definition.tag for definition in window_definitions], default=None)
    detail = detail.loc[detail["window_tag"].notna()].copy()
    if detail.empty:
        return _build_empty_premarket_window_features_export(expected)

    window_structure = build_market_structure_feature_frame(
        detail,
        group_keys=["trade_date", "symbol", "window_tag"],
        prefix="window_structure",
    )

    detail = detail.sort_values(["trade_date", "symbol", "window_tag", "timestamp"]).reset_index(drop=True)
    grouped = detail.groupby(["trade_date", "symbol", "window_tag"], sort=False).agg(
        window_row_count=("timestamp", "size"),
        window_open=("open", "first"),
        window_high=("high", "max"),
        window_low=("low", "min"),
        window_close=("close", "last"),
        window_volume=("volume", "sum"),
        window_dollar_volume=("dollar_volume", "sum"),
        window_trade_count_actual=("trade_count_numeric", lambda s: s.sum(min_count=1)),
        window_active_seconds=("volume", lambda s: int((pd.to_numeric(s, errors="coerce").fillna(0.0) > 0).sum())),
        window_last_trade_ts=("timestamp", "max"),
    ).reset_index()
    grouped["window_vwap"] = np.where(grouped["window_volume"] > 0, grouped["window_dollar_volume"] / grouped["window_volume"], np.nan)
    grouped["window_trade_count_source"] = np.where(grouped["window_trade_count_actual"].notna(), "actual", "proxy_active_seconds")
    grouped["window_trade_count_usable"] = True
    grouped["window_trade_count"] = np.where(grouped["window_trade_count_actual"].notna(), grouped["window_trade_count_actual"], grouped["window_active_seconds"])

    out = expected.merge(grouped, on=["trade_date", "symbol", "window_tag"], how="left")
    if not window_structure.empty:
        out = out.merge(window_structure, on=["trade_date", "symbol", "window_tag"], how="left")
    if {"trade_date", "symbol", "structure_trend_state"}.issubset(daily_bars.columns):
        daily_structure = daily_bars[
            [column for column in ["trade_date", "symbol", "structure_trend_state", "structure_bias_score"] if column in daily_bars.columns]
        ].copy()
        daily_structure["trade_date"] = pd.to_datetime(daily_structure["trade_date"], errors="coerce").dt.date
        daily_structure["symbol"] = daily_structure["symbol"].astype(str).str.upper()
        daily_structure = daily_structure.drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
        out = out.merge(daily_structure, on=["trade_date", "symbol"], how="left", suffixes=("", "_daily"))
        current_window_trend = _numeric_series(out, "window_structure_trend_state", fill_value=0.0).fillna(0.0)
        parent_trend = _numeric_series(out, "structure_trend_state", fill_value=0.0).fillna(0.0)
        out["window_structure_alignment_score"] = np.where(
            current_window_trend.eq(0.0) | parent_trend.eq(0.0),
            _numeric_series(out, "window_structure_alignment_score", fill_value=50.0).fillna(50.0),
            np.where(current_window_trend.eq(parent_trend), 100.0, 0.0),
        )
        out["window_structure_bias_score"] = (
            _numeric_series(out, "window_structure_bias_score", fill_value=0.0).fillna(0.0) * 0.7
            + _numeric_series(out, "structure_bias_score", fill_value=0.0).fillna(0.0) * 0.3
        )
    out["has_window_data"] = out["window_row_count"].fillna(0).astype(int) > 0
    out["window_return_pct"] = np.where(
        pd.to_numeric(out["window_open"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_close"], errors="coerce") / pd.to_numeric(out["window_open"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    out["window_range_pct"] = np.where(
        pd.to_numeric(out["window_open"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_high"], errors="coerce") - pd.to_numeric(out["window_low"], errors="coerce")) / pd.to_numeric(out["window_open"], errors="coerce")) * 100.0,
        np.nan,
    )
    out["window_close_vs_high_pct"] = np.where(
        pd.to_numeric(out["window_high"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_close"], errors="coerce") / pd.to_numeric(out["window_high"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    out["window_close_vs_low_pct"] = np.where(
        pd.to_numeric(out["window_low"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_close"], errors="coerce") / pd.to_numeric(out["window_low"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    candle_range = pd.to_numeric(out["window_high"], errors="coerce") - pd.to_numeric(out["window_low"], errors="coerce")
    body = (pd.to_numeric(out["window_close"], errors="coerce") - pd.to_numeric(out["window_open"], errors="coerce")).abs()
    upper_wick = pd.to_numeric(out["window_high"], errors="coerce") - np.maximum(pd.to_numeric(out["window_open"], errors="coerce"), pd.to_numeric(out["window_close"], errors="coerce"))
    lower_wick = np.minimum(pd.to_numeric(out["window_open"], errors="coerce"), pd.to_numeric(out["window_close"], errors="coerce")) - pd.to_numeric(out["window_low"], errors="coerce")
    out["window_body_pct"] = np.where(candle_range > 0, (body / candle_range) * 100.0, np.where(out["has_window_data"], 100.0, np.nan))
    out["window_upper_wick_pct"] = np.where(candle_range > 0, (upper_wick / candle_range) * 100.0, np.where(out["has_window_data"], 0.0, np.nan))
    out["window_lower_wick_pct"] = np.where(candle_range > 0, (lower_wick / candle_range) * 100.0, np.where(out["has_window_data"], 0.0, np.nan))
    out["prev_close_to_window_open_pct"] = np.where(
        pd.to_numeric(out["previous_close"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_open"], errors="coerce") / pd.to_numeric(out["previous_close"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    out["prev_close_to_window_close_pct"] = np.where(
        pd.to_numeric(out["previous_close"], errors="coerce") > 0,
        ((pd.to_numeric(out["window_close"], errors="coerce") / pd.to_numeric(out["previous_close"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    out["window_close_position_pct"] = np.where(
        candle_range > 0,
        ((pd.to_numeric(out["window_close"], errors="coerce") - pd.to_numeric(out["window_low"], errors="coerce")) / candle_range) * 100.0,
        np.where(out["has_window_data"], 100.0, np.nan),
    )
    out["window_trend_efficiency_pct"] = np.where(candle_range > 0, (body / candle_range) * 100.0, np.where(out["has_window_data"], 100.0, np.nan))
    out["window_pullback_pct"] = np.where(
        candle_range > 0,
        ((pd.to_numeric(out["window_high"], errors="coerce") - pd.to_numeric(out["window_close"], errors="coerce")) / candle_range) * 100.0,
        np.where(out["has_window_data"], 0.0, np.nan),
    )
    out["window_structure_score"] = (
        pd.Series([_score_pct(value, floor=0.0, ceiling=5.0) for value in out["window_return_pct"]], index=out.index)
        + pd.to_numeric(out["window_close_position_pct"], errors="coerce").fillna(0.0)
        + pd.Series([_score_pct(value, floor=-5.0, ceiling=0.0) for value in out["window_close_vs_high_pct"]], index=out.index)
        + (100.0 - pd.to_numeric(out["window_pullback_pct"], errors="coerce").fillna(100.0))
        + _numeric_series(out, "window_structure_break_quality_score", fill_value=0.0).fillna(0.0)
        + _numeric_series(out, "window_structure_pressure_score", fill_value=0.0).fillna(0.0)
        + _numeric_series(out, "window_structure_alignment_score", fill_value=50.0).fillna(50.0)
        + _numeric_series(out, "window_structure_bias_score", fill_value=0.0).fillna(0.0)
    ) / 8.0
    out["window_stability_score"] = (
        pd.to_numeric(out["window_trend_efficiency_pct"], errors="coerce").fillna(0.0)
        + (100.0 - pd.to_numeric(out["window_upper_wick_pct"], errors="coerce").fillna(100.0))
        + pd.Series([_score_inverse_pct(value, floor=8.0, ceiling=20.0) for value in out["window_range_pct"]], index=out.index)
        + np.where(pd.to_numeric(out["window_close"], errors="coerce") >= pd.to_numeric(out["window_vwap"], errors="coerce"), 100.0, 0.0)
    ) / 4.0
    out["window_liquidity_score"] = (
        pd.Series([_score_log_ratio(value, resolved_cfg.min_window_dollar_volume) for value in out["window_dollar_volume"]], index=out.index)
        + pd.Series([_score_log_ratio(value, resolved_cfg.min_window_trade_count) for value in out["window_trade_count"]], index=out.index)
        + pd.Series([_score_log_ratio(value, 60.0) for value in out["window_active_seconds"]], index=out.index)
    ) / 3.0
    out["extension_score"] = [_score_extension(value) for value in out["prev_close_to_window_close_pct"]]
    out["window_quality_score"] = (
        pd.to_numeric(out["window_structure_score"], errors="coerce").fillna(0.0) * float(resolved_cfg.weights["structure"])
        + pd.to_numeric(out["window_stability_score"], errors="coerce").fillna(0.0) * float(resolved_cfg.weights["stability"])
        + pd.to_numeric(out["window_liquidity_score"], errors="coerce").fillna(0.0) * float(resolved_cfg.weights["liquidity"])
        + pd.to_numeric(out["extension_score"], errors="coerce").fillna(0.0) * float(resolved_cfg.weights["extension"])
    )
    out["passes_min_previous_close"] = pd.to_numeric(out["previous_close"], errors="coerce") >= resolved_cfg.min_previous_close
    out["passes_min_gap_pct"] = pd.to_numeric(out["prev_close_to_window_close_pct"], errors="coerce") >= resolved_cfg.min_gap_pct
    out["passes_min_window_dollar_volume"] = pd.to_numeric(out["window_dollar_volume"], errors="coerce") >= resolved_cfg.min_window_dollar_volume
    out["passes_min_window_trade_count"] = pd.to_numeric(out["window_trade_count"], errors="coerce") >= resolved_cfg.min_window_trade_count
    _vwap_ok = (
        pd.Series(True, index=out.index, dtype=bool)
        if not resolved_cfg.require_close_above_vwap
        else (pd.to_numeric(out["window_close"], errors="coerce") >= pd.to_numeric(out["window_vwap"], errors="coerce"))
    )
    out["passes_quality_filter"] = (
        out["has_window_data"].fillna(False).astype(bool)
        & out["passes_min_previous_close"].fillna(False)
        & out["passes_min_gap_pct"].fillna(False)
        & out["passes_min_window_dollar_volume"].fillna(False)
        & out["passes_min_window_trade_count"].fillna(False)
        & (pd.to_numeric(out["window_close_position_pct"], errors="coerce") >= resolved_cfg.min_window_close_position_pct)
        & (pd.to_numeric(out["window_return_pct"], errors="coerce") >= resolved_cfg.min_window_return_pct)
        & (pd.to_numeric(out["window_pullback_pct"], errors="coerce") <= resolved_cfg.max_window_pullback_pct)
        & _vwap_ok
    )
    out["quality_filter_reason"] = _compute_quality_reason(out, cfg=resolved_cfg)
    out = _populate_quality_window_ranks(out, top_n=resolved_cfg.top_n)
    for column in PREMARKET_WINDOW_FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = False if column == "quality_selected_top_n" else np.nan
    out["quality_rank_within_window"] = out["quality_rank_within_window"].astype("Int64")
    out["quality_selected_top_n"] = out["quality_selected_top_n"].fillna(False).astype(bool)
    return out[PREMARKET_WINDOW_FEATURE_COLUMNS].sort_values(["trade_date", "window_tag", "symbol"]).reset_index(drop=True)


def _fundamental_reference_cache_path(cache_dir: Path) -> Path:
    return build_cache_path(
        cache_dir,
        "fundamental_reference",
        dataset="FMP.PROFILE_BULK",
        parts=["us_equity_profiles"],
    )


def _empty_fundamental_reference_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=FUNDAMENTAL_REFERENCE_COLUMNS)


def _load_fundamental_reference(
    fmp_api_key: str,
    *,
    cache_dir: Path,
    use_file_cache: bool,
    force_refresh: bool,
) -> pd.DataFrame:
    cache_path = _fundamental_reference_cache_path(cache_dir)
    if use_file_cache and not force_refresh:
        cached = _read_cached_frame(cache_path)
        if cached is not None:
            if cached.empty and cache_path.exists():
                age_seconds = (datetime.now(UTC) - datetime.fromtimestamp(cache_path.stat().st_mtime, tz=UTC)).total_seconds()
                if age_seconds > FUNDAMENTAL_REFERENCE_EMPTY_CACHE_TTL_SECONDS:
                    logger.info(
                        "Negative FMP fundamentals cache expired (%.1f min old), refreshing.",
                        age_seconds / 60.0,
                    )
                else:
                    return cached
            else:
                return cached

    if not str(fmp_api_key or "").strip():
        return _empty_fundamental_reference_frame()

    try:
        rows = FMPClient(fmp_api_key).get_profile_bulk()
    except Exception:
        logger.warning("FMP bulk profile fetch failed; fundamentals will be empty for this run", exc_info=True)
        rows = []
    if not rows:
        empty = _empty_fundamental_reference_frame()
        if use_file_cache:
            _write_cached_frame(cache_path, empty)
        return empty

    frame = pd.DataFrame(rows)
    if frame.empty:
        empty = _empty_fundamental_reference_frame()
        if use_file_cache:
            _write_cached_frame(cache_path, empty)
        return empty

    out = pd.DataFrame(
        {
            "symbol": frame.get("symbol", "").astype(str).str.upper().str.strip(),
            "company_name_profile": frame.get("companyName", frame.get("companyNameLong", frame.get("name", ""))),
            "exchange_profile": frame.get("exchangeShortName", frame.get("exchange", "")),
            "sector_profile": frame.get("sector", ""),
            "industry_profile": frame.get("industry", ""),
            "market_cap_profile": pd.to_numeric(frame.get("marketCap", np.nan), errors="coerce"),
            "asset_type_profile": frame.get("type", frame.get("instrumentType", frame.get("securityType", "listed_equity_issue"))),
            "has_fundamental_row": True,
        }
    )
    out = out[out["symbol"].ne("")].drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    if use_file_cache:
        _write_cached_frame(cache_path, out)
    return out


def _enrich_universe_with_fundamentals(universe: pd.DataFrame, fundamentals: pd.DataFrame) -> pd.DataFrame:
    enriched = universe.copy()
    enriched["symbol"] = enriched["symbol"].astype(str).str.upper().str.strip()
    enriched["asset_type"] = "listed_equity_issue"
    enriched["has_reference_data"] = True
    enriched["has_fundamental_row"] = False
    if not fundamentals.empty:
        enriched = enriched.merge(fundamentals, on="symbol", how="left")
        for column, fallback in [
            ("company_name", "company_name_profile"),
            ("exchange", "exchange_profile"),
            ("sector", "sector_profile"),
            ("industry", "industry_profile"),
            ("market_cap", "market_cap_profile"),
            ("asset_type", "asset_type_profile"),
        ]:
            if fallback in enriched.columns:
                if column in enriched.columns:
                    enriched[column] = enriched[column].replace("", pd.NA).combine_first(enriched[fallback])
                else:
                    enriched[column] = enriched[fallback]
        enriched["has_fundamental_row"] = _bool_series(enriched, "has_fundamental_row", default=False)

    for column in [
        "company_name_profile",
        "exchange_profile",
        "sector_profile",
        "industry_profile",
        "market_cap_profile",
        "asset_type_profile",
    ]:
        if column in enriched.columns:
            enriched = enriched.drop(columns=[column])

    enriched["market_cap"] = pd.to_numeric(enriched.get("market_cap"), errors="coerce")
    enriched["asset_type"] = enriched.get("asset_type", "listed_equity_issue").replace("", pd.NA).fillna("listed_equity_issue")
    enriched["has_market_cap"] = enriched["market_cap"].notna()
    enriched["has_fundamentals"] = enriched["has_fundamental_row"].astype(bool)
    return enriched


def _format_quality_window_label(
    trade_date,
    *,
    start_et: time,
    end_et: time,
    display_timezone: str,
) -> str:
    display_tz = resolve_display_timezone(display_timezone)
    start_local = datetime.combine(trade_date, start_et, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
    end_local = datetime.combine(trade_date, end_et, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
    return f"{start_local.strftime('%H:%M')}-{end_local.strftime('%H:%M')}"


def _quality_window_export_tag(start_et: time, end_et: time) -> str:
    return f"{start_et.strftime('%H%M')}_{end_et.strftime('%H%M')}_et"


def _window_label_from_tag(trade_day, tag: str, *, display_timezone: str) -> str:
    definitions = {definition.tag: definition for definition in _DEFAULT_BULLISH_QUALITY_CFG.window_definitions}
    definition = definitions.get(str(tag))
    if definition is None:
        return str(tag)
    return _format_quality_window_label(
        trade_day,
        start_et=_parse_window_time_et(definition.start_time_et),
        end_et=_parse_window_time_et(definition.end_time_et),
        display_timezone=display_timezone,
    )


def _build_quality_window_status_latest(
    window_features: pd.DataFrame,
    *,
    display_timezone: str,
) -> pd.DataFrame:
    columns = [
        "symbol",
        QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN,
        QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN,
        QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN,
        QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN,
    ]
    if window_features.empty:
        return pd.DataFrame(columns=columns)

    frame = window_features.copy()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date
    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame = frame.dropna(subset=["trade_date", "symbol"])
    if frame.empty:
        return pd.DataFrame(columns=columns)

    latest_trade_date = frame["trade_date"].max()
    latest = frame.loc[frame["trade_date"] == latest_trade_date].copy()
    latest["has_window_data"] = latest["has_window_data"].fillna(False).astype(bool)
    latest["passes_quality_filter"] = latest["passes_quality_filter"].fillna(False).astype(bool)
    latest["quality_selected_top_n"] = latest["quality_selected_top_n"].fillna(False).astype(bool)
    latest["window_quality_score"] = pd.to_numeric(latest["window_quality_score"], errors="coerce")
    latest["window_label_local"] = [
        _window_label_from_tag(trade_day, tag, display_timezone=display_timezone)
        for trade_day, tag in zip(latest["trade_date"], latest["window_tag"], strict=False)
    ]

    order_map = {definition.tag: index for index, definition in enumerate(_DEFAULT_BULLISH_QUALITY_CFG.window_definitions)}
    latest["window_order"] = latest["window_tag"].map(order_map).fillna(10_000).astype(int)

    coverage_rows = latest.loc[latest["has_window_data"], ["symbol", "window_order", "window_label_local"]].copy()
    status_rows = latest.loc[
        latest["passes_quality_filter"] | latest["quality_selected_top_n"],
        ["symbol", "window_order", "window_label_local", "window_quality_score"],
    ].copy()

    coverage = (
        coverage_rows.sort_values(["symbol", "window_order"])
        .groupby("symbol", sort=False)["window_label_local"]
        .agg(lambda values: "+".join(values.tolist()))
        .rename(QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN)
        .reset_index()
        if not coverage_rows.empty
        else pd.DataFrame(columns=["symbol", QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN])
    )
    status_sorted = (
        status_rows.sort_values(["symbol", "window_quality_score", "window_order"], ascending=[True, False, False])
        .drop_duplicates(subset=["symbol"], keep="first")
        if not status_rows.empty
        else pd.DataFrame(columns=["symbol", "window_label_local", "window_quality_score"])
    )
    status = (
        status_sorted[["symbol", "window_label_local"]]
        .rename(columns={"window_label_local": QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN})
        if not status_sorted.empty
        else pd.DataFrame(columns=["symbol", QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN])
    )
    score = (
        status_sorted[["symbol", "window_quality_score"]]
        .rename(columns={"window_quality_score": QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN})
        if not status_sorted.empty
        else pd.DataFrame(columns=["symbol", QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN])
    )

    base = latest[["symbol"]].drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    base[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN] = latest_trade_date
    base = base.merge(coverage, on="symbol", how="left")
    base = base.merge(status, on="symbol", how="left")
    base = base.merge(score, on="symbol", how="left")
    base[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = base[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN].fillna("none")
    base[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = base[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN].fillna("none")
    base[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = pd.to_numeric(base[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN], errors="coerce")
    return base[columns]


def _enrich_universe_with_quality_window_status_from_window_features(
    universe: pd.DataFrame,
    window_features: pd.DataFrame,
    *,
    display_timezone: str,
) -> pd.DataFrame:
    enriched = universe.copy()
    enriched["symbol"] = enriched["symbol"].astype(str).str.upper().str.strip()
    status = _build_quality_window_status_latest(window_features, display_timezone=display_timezone)
    if status.empty:
        enriched[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN] = pd.NA
        enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = "none"
        enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = "none"
        enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = np.nan
        return enriched
    enriched = enriched.merge(status, on="symbol", how="left")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN].fillna("none")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN].fillna("none")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = pd.to_numeric(enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN], errors="coerce")
    return enriched


def _empty_quality_window_candidate_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=QUALITY_OPEN_DRIVE_CANDIDATE_EXPORT_COLUMNS)


def _select_top_candidates_per_day(frame: pd.DataFrame, top_n: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    if top_n <= 0:
        return frame.iloc[0:0].copy()
    ordered = frame.sort_values(
        ["trade_date", "quality_score", "window_dollar_volume", "window_return_pct", "symbol"],
        ascending=[True, False, False, False, True],
    )
    return ordered.groupby("trade_date", group_keys=False).head(top_n).reset_index(drop=True)


def _compute_open_confirm_flags(detail: pd.DataFrame) -> pd.DataFrame:
    columns = ["trade_date", "symbol", "open_confirm_ok"]
    if detail.empty:
        return pd.DataFrame(columns=columns)

    open_frame = detail.copy()
    open_frame["trade_date"] = pd.to_datetime(open_frame["trade_date"], errors="coerce").dt.date
    open_frame["symbol"] = open_frame["symbol"].astype(str).str.upper()
    open_frame["timestamp"] = pd.to_datetime(open_frame["timestamp"], errors="coerce", utc=True)
    _n_before = len(open_frame)
    open_frame = open_frame.dropna(subset=["trade_date", "symbol", "timestamp"]).copy()
    _n_dropped = _n_before - len(open_frame)
    if _n_dropped:
        logger.debug("open_confirm_flags: dropped %d/%d rows with null trade_date/symbol/timestamp", _n_dropped, _n_before)
    if open_frame.empty:
        return pd.DataFrame(columns=columns)

    open_frame["et_timestamp"] = open_frame["timestamp"].dt.tz_convert(US_EASTERN_TZ)
    open_frame["et_time"] = open_frame["et_timestamp"].dt.time
    for column in ["open", "high", "low", "close"]:
        open_frame[column] = pd.to_numeric(open_frame.get(column), errors="coerce")
    open_frame = open_frame.loc[
        open_frame["et_time"].ge(time(9, 30)) & open_frame["et_time"].lt(time(9, 31)),
        ["trade_date", "symbol", "timestamp", "open", "high", "low", "close"],
    ].copy()
    if open_frame.empty:
        return pd.DataFrame(columns=columns)

    open_frame = open_frame.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
    grouped = open_frame.groupby(["trade_date", "symbol"], sort=False).agg(
        open_start=("open", "first"),
        open_high_60s=("high", "max"),
        open_low_60s=("low", "min"),
        open_end_60s=("close", "last"),
    ).reset_index()
    midpoint = (grouped["open_high_60s"] + grouped["open_low_60s"]) / 2.0
    no_hard_break = grouped["open_low_60s"] >= (grouped["open_start"] * 0.99)
    quick_reclaim = (grouped["open_high_60s"] >= grouped["open_start"]) & (grouped["open_end_60s"] >= midpoint)
    closes_green = grouped["open_end_60s"] >= grouped["open_start"]
    grouped["open_confirm_ok"] = (closes_green | no_hard_break | quick_reclaim).fillna(False)
    return grouped[columns]


def _compute_quality_window_signal(
    detail: pd.DataFrame,
    daily_features: pd.DataFrame,
    premarket_features: pd.DataFrame,
    *,
    display_timezone: str,
    latest_trade_date,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    if detail.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN,
            ]
        ), {}

    feature_columns = [column for column in ["trade_date", "symbol", "exchange", "previous_close"] if column in daily_features.columns]
    all_features = daily_features.copy()
    all_features["trade_date"] = pd.to_datetime(all_features["trade_date"], errors="coerce").dt.date
    all_features["symbol"] = all_features["symbol"].astype(str).str.upper()
    all_features = all_features.loc[:, feature_columns].drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    latest_features = all_features.loc[all_features["trade_date"] == latest_trade_date].copy()
    if latest_features.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN,
                QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN,
            ]
        ), {}

    premarket_columns = [
        column
        for column in ["trade_date", "symbol", "prev_close_to_premarket_pct", "premarket_to_open_pct"]
        if column in premarket_features.columns
    ]
    premarket_small = premarket_features.copy()
    if premarket_columns:
        premarket_small["trade_date"] = pd.to_datetime(premarket_small["trade_date"], errors="coerce").dt.date
        premarket_small["symbol"] = premarket_small["symbol"].astype(str).str.upper()
        premarket_small = premarket_small.loc[:, premarket_columns].drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    else:
        premarket_small = pd.DataFrame(columns=["trade_date", "symbol", "prev_close_to_premarket_pct", "premarket_to_open_pct"])

    detail = detail.copy()
    detail["trade_date"] = pd.to_datetime(detail["trade_date"], errors="coerce").dt.date
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    if detail.empty:
        return latest_features.assign(
            **{
                QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN: latest_trade_date,
                QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN: "none",
                QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN: "none",
                QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN: np.nan,
            }
        )[["symbol", QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN]], {}

    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce", utc=True)
    _n_before = len(detail)
    detail = detail.dropna(subset=["timestamp"]).copy()
    _n_dropped = _n_before - len(detail)
    if _n_dropped:
        logger.debug("quality_window_signal: dropped %d/%d rows with null timestamp", _n_dropped, _n_before)
    if detail.empty:
        return latest_features.assign(
            **{
                QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN: latest_trade_date,
                QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN: "none",
                QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN: "none",
                QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN: np.nan,
            }
        )[["symbol", QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN]], {}

    detail["et_timestamp"] = detail["timestamp"].dt.tz_convert(US_EASTERN_TZ)
    detail["et_time"] = detail["et_timestamp"].dt.time
    detail["open"] = pd.to_numeric(detail.get("open"), errors="coerce")
    detail["close"] = pd.to_numeric(detail.get("close"), errors="coerce")
    detail["high"] = pd.to_numeric(detail.get("high"), errors="coerce")
    detail["low"] = pd.to_numeric(detail.get("low"), errors="coerce")
    detail["volume"] = pd.to_numeric(detail.get("volume"), errors="coerce")
    detail["dollar_volume"] = detail["close"] * detail["volume"]
    open_confirm = _compute_open_confirm_flags(detail)

    def _metrics_between(key: str, start_time: time, end_time: time) -> tuple[pd.DataFrame, pd.DataFrame]:
        window_frame = detail.loc[
            detail["et_time"].ge(start_time) & detail["et_time"].lt(end_time),
            ["trade_date", "symbol", "timestamp", "open", "close", "high", "low", "volume", "dollar_volume"],
        ].copy()
        if window_frame.empty:
            return pd.DataFrame(columns=["symbol", f"has_data_{key}", f"passes_quality_{key}", f"quality_score_{key}"]), _empty_quality_window_candidate_frame()
        window_frame = window_frame.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
        grouped = window_frame.groupby(["trade_date", "symbol"], sort=False).agg(
            start_price=("open", "first"),
            last_close=("close", "last"),
            window_high=("high", "max"),
            window_low=("low", "min"),
            window_volume=("volume", "sum"),
            window_dollar_volume=("dollar_volume", "sum"),
        ).reset_index()
        grouped = grouped.merge(all_features, on=["trade_date", "symbol"], how="left")
        grouped = grouped.merge(premarket_small, on=["trade_date", "symbol"], how="left")
        grouped = grouped.merge(open_confirm, on=["trade_date", "symbol"], how="left")
        grouped["window_vwap"] = np.where(
            grouped["window_volume"] > 0,
            grouped["window_dollar_volume"] / grouped["window_volume"],
            np.nan,
        )
        grouped["window_return_pct"] = np.where(
            grouped["start_price"] > 0,
            ((grouped["last_close"] / grouped["start_price"]) - 1.0) * 100.0,
            np.nan,
        )
        grouped["window_range_pct"] = np.where(
            grouped["start_price"] > 0,
            ((grouped["window_high"] - grouped["window_low"]) / grouped["start_price"]) * 100.0,
            np.nan,
        )
        grouped["window_close_vs_high_pct"] = np.where(
            grouped["window_high"] > 0,
            ((grouped["last_close"] / grouped["window_high"]) - 1.0) * 100.0,
            np.nan,
        )
        grouped["window_vwap_trend_ok"] = (grouped["last_close"] >= grouped["window_vwap"]).fillna(False)
        grouped["prev_close_ok"] = pd.to_numeric(grouped.get("previous_close"), errors="coerce") >= QUALITY_OPEN_DRIVE_HARD_FILTERS["min_previous_close"]
        grouped["prev_close_to_window_close_pct"] = np.where(
            pd.to_numeric(grouped.get("previous_close"), errors="coerce") > 0,
            ((pd.to_numeric(grouped["last_close"], errors="coerce") / pd.to_numeric(grouped.get("previous_close"), errors="coerce")) - 1.0) * 100.0,
            np.nan,
        )
        grouped["gap_ok"] = pd.to_numeric(grouped["prev_close_to_window_close_pct"], errors="coerce") >= QUALITY_OPEN_DRIVE_HARD_FILTERS["min_prev_close_to_premarket_pct"]
        grouped["dollar_vol_ok"] = grouped["window_dollar_volume"] >= QUALITY_OPEN_DRIVE_HARD_FILTERS["min_window_dollar_volume"]
        grouped["window_return_ok"] = grouped["window_return_pct"] >= QUALITY_OPEN_DRIVE_QUALITY_THRESHOLDS["min_window_return_pct"]
        grouped["close_near_high_ok"] = grouped["window_close_vs_high_pct"] >= QUALITY_OPEN_DRIVE_QUALITY_THRESHOLDS["min_close_vs_high_pct"]
        grouped["range_ok"] = grouped["window_range_pct"] <= QUALITY_OPEN_DRIVE_QUALITY_THRESHOLDS["max_window_range_pct"]
        grouped["above_vwap_ok"] = grouped["window_vwap_trend_ok"].fillna(False)
        open_confirm_series = grouped.get("open_confirm_ok")
        if open_confirm_series is None:
            open_confirm_series = pd.Series(False, index=grouped.index, dtype=bool)
        else:
            open_confirm_series = open_confirm_series.astype("boolean").fillna(False).astype(bool)
        grouped["open_confirm_ok"] = (
            (pd.to_numeric(grouped.get("premarket_to_open_pct"), errors="coerce") >= 0.0)
            | open_confirm_series
        )
        grouped["base_candidate"] = grouped["prev_close_ok"] & grouped["gap_ok"] & grouped["dollar_vol_ok"]
        grouped["quality_score"] = sum(
            grouped[column].fillna(False).astype(float) * weight
            for column, weight in QUALITY_OPEN_DRIVE_SCORE_WEIGHTS.items()
        )
        grouped["has_data"] = True
        grouped["passes_quality"] = (
            grouped["base_candidate"]
            & grouped["window_return_ok"]
            & grouped["close_near_high_ok"]
            & grouped["range_ok"]
            & grouped["above_vwap_ok"]
        )
        grouped["window_key"] = key
        grouped["window_label_local"] = grouped["trade_date"].map(
            lambda trade_day: _format_quality_window_label(
                trade_day,
                start_et=start_time,
                end_et=end_time,
                display_timezone=display_timezone,
            )
        )
        if "exchange" not in grouped.columns:
            grouped["exchange"] = ""
        else:
            grouped["exchange"] = grouped["exchange"].fillna("")
        candidate = grouped.loc[grouped["base_candidate"]].copy()
        candidate = candidate.sort_values(
            ["trade_date", "quality_score", "window_dollar_volume", "window_return_pct", "symbol"],
            ascending=[True, False, False, False, True],
        ).reset_index(drop=True)
        candidate = candidate.reindex(columns=QUALITY_OPEN_DRIVE_CANDIDATE_EXPORT_COLUMNS)
        latest_metrics = grouped.loc[
            grouped["trade_date"] == latest_trade_date,
            ["symbol", "has_data", "passes_quality", "quality_score", "base_candidate"],
        ].copy()
        latest_metrics = latest_metrics.rename(
            columns={
                "has_data": f"has_data_{key}",
                "passes_quality": f"passes_quality_{key}",
                "quality_score": f"quality_score_{key}",
                "base_candidate": f"base_candidate_{key}",
            }
        )
        return latest_metrics, candidate

    window_labels = {
        key: _format_quality_window_label(
            latest_trade_date,
            start_et=start_time,
            end_et=end_time,
            display_timezone=display_timezone,
        )
        for key, start_time, end_time in QUALITY_OPEN_DRIVE_ET_WINDOWS
    }
    candidate_exports: dict[str, pd.DataFrame] = {}
    status = latest_features[["symbol"]].drop_duplicates(subset=["symbol"]).reset_index(drop=True)
    for key, start_time, end_time in QUALITY_OPEN_DRIVE_ET_WINDOWS:
        latest_metrics, candidate = _metrics_between(key, start_time, end_time)
        status = status.merge(latest_metrics, on="symbol", how="left")
        export_tag = _quality_window_export_tag(start_time, end_time)
        candidate_exports[f"quality_candidates_{export_tag}_all"] = candidate
        candidate_exports[f"quality_candidates_{export_tag}_top20_per_day"] = _select_top_candidates_per_day(candidate, 20)
        candidate_exports[f"quality_candidates_{export_tag}_top50_per_day"] = _select_top_candidates_per_day(candidate, 50)
    for column in [
        "has_data_early",
        "has_data_late",
        "passes_quality_early",
        "passes_quality_late",
        "base_candidate_early",
        "base_candidate_late",
    ]:
        if column not in status.columns:
            status[column] = pd.Series(False, index=status.index, dtype=bool)
            continue
        status[column] = status[column].astype("boolean").fillna(False).astype(bool)
    for column in ["quality_score_early", "quality_score_late"]:
        if column not in status.columns:
            status[column] = pd.Series(np.nan, index=status.index, dtype=float)
            continue
        status[column] = pd.to_numeric(status[column], errors="coerce")
    status.loc[~status["base_candidate_early"], "quality_score_early"] = np.nan
    status.loc[~status["base_candidate_late"], "quality_score_late"] = np.nan
    status[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN] = latest_trade_date
    status[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = np.select(
        [
            status["has_data_early"] & status["has_data_late"],
            status["has_data_early"],
            status["has_data_late"],
        ],
        [
            f"{window_labels['early']}+{window_labels['late']}",
            window_labels["early"],
            window_labels["late"],
        ],
        default="none",
    )
    status[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = np.select(
        [
            status["passes_quality_early"] & status["passes_quality_late"],
            status["passes_quality_early"],
            status["passes_quality_late"],
        ],
        [
            f"{window_labels['early']}+{window_labels['late']}",
            window_labels["early"],
            window_labels["late"],
        ],
        default="none",
    )
    status[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = status[["quality_score_early", "quality_score_late"]].max(axis=1, skipna=True)
    return status[["symbol", QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN, QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN]], candidate_exports


def _enrich_universe_with_quality_window_status(
    universe: pd.DataFrame,
    daily_features: pd.DataFrame,
    premarket_features: pd.DataFrame,
    second_detail_all: pd.DataFrame,
    *,
    display_timezone: str,
) -> pd.DataFrame:
    enriched = universe.copy()
    enriched["symbol"] = enriched["symbol"].astype(str).str.upper().str.strip()
    latest_trade_date = pd.to_datetime(daily_features.get("trade_date"), errors="coerce").dt.date.dropna().max()
    if latest_trade_date is None:
        enriched[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN] = pd.NA
        enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = "none"
        enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = "none"
        enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = np.nan
        return enriched

    status, _ = _compute_quality_window_signal(
        second_detail_all,
        daily_features,
        premarket_features,
        display_timezone=display_timezone,
        latest_trade_date=latest_trade_date,
    )
    enriched = enriched.merge(status, on="symbol", how="left")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN] = enriched[QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN].fillna(latest_trade_date)
    enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN] = enriched[QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN].fillna("none")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN] = enriched[QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN].fillna("none")
    enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN] = pd.to_numeric(enriched[QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN], errors="coerce")
    return enriched


def _write_csv_exports(export_dir: Path, named_frames: dict[str, pd.DataFrame]) -> dict[str, Path]:
    created: dict[str, Path] = {}
    export_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in named_frames.items():
        path = export_dir / f"{name}.csv"
        frame.to_csv(path, index=False)
        created[name] = path
    return created


def _normalize_exchange_key(value: object) -> str:
    normalized = str(value or "").strip().upper()
    compact = normalized.replace(" ", "").replace("-", "")
    if compact in {"NASDAQ", "XNAS"}:
        return "NASDAQ"
    if compact in {"NYSE", "XNYS"}:
        return "NYSE"
    if compact in {"AMEX", "XASE", "NYSEAMERICAN", "NYSEMKT"}:
        return "AMEX"
    return normalized


def _normalize_quality_window_exchange_dataset_map(exchange_dataset_map: dict[str, str] | None) -> dict[str, str]:
    if not exchange_dataset_map:
        return {}
    normalized: dict[str, str] = {}
    for exchange, dataset_name in exchange_dataset_map.items():
        exchange_key = _normalize_exchange_key(exchange)
        dataset_key = str(dataset_name or "").strip().upper()
        if exchange_key and dataset_key:
            normalized[exchange_key] = dataset_key
    return normalized


def _attach_exchange_lookup(detail: pd.DataFrame, exchange_lookup: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    enriched = detail.copy()
    enriched["symbol"] = enriched["symbol"].astype(str).str.upper()
    if "exchange_key" not in exchange_lookup.columns:
        return enriched
    return enriched.merge(exchange_lookup, on="symbol", how="left")


def _with_source_priority(frame: pd.DataFrame, *, source_priority: int) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    enriched = frame.copy()
    enriched["_source_priority"] = int(source_priority)
    return enriched


def _filter_quality_window_intervals(
    detail: pd.DataFrame,
    *,
    include_early: bool,
    include_late: bool,
    include_open_confirm: bool,
) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()

    filtered = detail.copy()
    filtered["timestamp"] = pd.to_datetime(filtered["timestamp"], errors="coerce", utc=True)
    _n_before = len(filtered)
    filtered = filtered.dropna(subset=["timestamp"]).copy()
    _n_dropped = _n_before - len(filtered)
    if _n_dropped:
        logger.debug("filter_quality_window_intervals: dropped %d/%d rows with null timestamp", _n_dropped, _n_before)
    if filtered.empty:
        return filtered

    filtered["et_time"] = filtered["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
    mask = pd.Series(False, index=filtered.index, dtype=bool)
    if include_early:
        mask = mask | (filtered["et_time"].ge(QUALITY_OPEN_DRIVE_ET_WINDOWS[0][1]) & filtered["et_time"].lt(QUALITY_OPEN_DRIVE_ET_WINDOWS[0][2]))
    if include_late:
        mask = mask | (filtered["et_time"].ge(QUALITY_OPEN_DRIVE_ET_WINDOWS[1][1]) & filtered["et_time"].lt(QUALITY_OPEN_DRIVE_ET_WINDOWS[1][2]))
    if include_open_confirm:
        mask = mask | (
            filtered["et_time"].ge(QUALITY_OPEN_DRIVE_OPEN_CONFIRM_ET_WINDOW[0])
            & filtered["et_time"].lt(QUALITY_OPEN_DRIVE_OPEN_CONFIRM_ET_WINDOW[1])
        )
    filtered = filtered.loc[mask].copy()
    return filtered.drop(columns=["et_time"], errors="ignore")


def _filter_premarket_rows(detail: pd.DataFrame) -> pd.DataFrame:
    if detail.empty:
        return detail.copy()
    filtered = detail.copy()
    if "session" in filtered.columns:
        return filtered.loc[filtered["session"].astype(str).str.strip().str.lower().eq("premarket")].copy()
    filtered["timestamp"] = pd.to_datetime(filtered["timestamp"], errors="coerce", utc=True)
    _n_before = len(filtered)
    filtered = filtered.dropna(subset=["timestamp"]).copy()
    _n_dropped = _n_before - len(filtered)
    if _n_dropped:
        logger.debug("filter_premarket_rows: dropped %d/%d rows with null timestamp", _n_dropped, _n_before)
    if filtered.empty:
        return filtered
    filtered["et_time"] = filtered["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
    filtered = filtered.loc[filtered["et_time"].lt(QUALITY_OPEN_DRIVE_OPEN_CONFIRM_ET_WINDOW[0])].copy()
    return filtered.drop(columns=["et_time"], errors="ignore")


def _collect_quality_window_source_frames(
    *,
    databento_api_key: str,
    base_dataset: str,
    trading_days: list,
    raw_universe: pd.DataFrame,
    supported_universe: pd.DataFrame,
    daily_bars: pd.DataFrame,
    symbol_day_scope: pd.DataFrame | None,
    display_timezone: str,
    window_start: time | None,
    window_end: time | None,
    premarket_anchor_et: time,
    cache_dir: Path,
    use_file_cache: bool,
    force_refresh: bool,
    early_exchange_datasets: dict[str, str] | None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    empty = pd.DataFrame(
        columns=[
            "trade_date", "symbol", "timestamp", "session", "open", "high", "low", "close", "volume",
            "second_delta_pct", "from_previous_close_pct",
        ]
    )
    if supported_universe.empty:
        return empty.copy(), empty.copy(), {
            "base_dataset": base_dataset,
            "early_exchange_datasets": {},
            "applied_early_exchange_datasets": {},
        }

    exchange_lookup = raw_universe[["symbol", "exchange"]].copy() if "exchange" in raw_universe.columns else raw_universe[["symbol"]].copy()
    exchange_lookup["symbol"] = exchange_lookup["symbol"].map(lambda value: normalize_symbol_for_databento(str(value)))
    exchange_lookup = exchange_lookup.loc[exchange_lookup["symbol"] != ""].copy()
    exchange_lookup["exchange_key"] = exchange_lookup.get("exchange", "").map(_normalize_exchange_key)
    exchange_lookup = exchange_lookup[["symbol", "exchange_key"]].drop_duplicates(subset=["symbol"]).reset_index(drop=True)

    supported_symbols = {
        normalized
        for value in supported_universe["symbol"].dropna().astype(str).tolist()
        if (normalized := normalize_symbol_for_databento(value))
    }
    normalized_map = _normalize_quality_window_exchange_dataset_map(early_exchange_datasets)

    base_detail = collect_full_universe_open_window_second_detail(
        databento_api_key,
        dataset=base_dataset,
        trading_days=trading_days,
        universe_symbols=supported_symbols,
        daily_bars=daily_bars,
        symbol_day_scope=symbol_day_scope,
        display_timezone=display_timezone,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor_et,
        cache_dir=cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    base_detail = _attach_exchange_lookup(base_detail, exchange_lookup)

    applied_datasets: dict[str, str] = {}
    alternate_quality_parts: list[pd.DataFrame] = []
    alternate_premarket_parts: list[pd.DataFrame] = []
    early_symbol_counts: dict[str, int] = {}

    for exchange_key, dataset_name in normalized_map.items():
        exchange_symbols = supported_symbols.intersection(
            set(exchange_lookup.loc[exchange_lookup["exchange_key"] == exchange_key, "symbol"])
        )
        if not exchange_symbols:
            continue
        early_symbol_counts[exchange_key] = len(exchange_symbols)
        if dataset_name == str(base_dataset).strip().upper():
            continue
        alt_detail = collect_full_universe_open_window_second_detail(
            databento_api_key,
            dataset=dataset_name,
            trading_days=trading_days,
            universe_symbols=exchange_symbols,
            daily_bars=daily_bars,
            symbol_day_scope=symbol_day_scope,
            display_timezone=display_timezone,
            window_start=window_start,
            window_end=window_end,
            premarket_anchor_et=premarket_anchor_et,
            cache_dir=cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
        if alt_detail.empty:
            continue
        alt_detail = _attach_exchange_lookup(alt_detail, exchange_lookup)
        alt_detail = alt_detail.loc[alt_detail["exchange_key"] == exchange_key].copy()
        if alt_detail.empty:
            continue
        applied_datasets[exchange_key] = dataset_name
        alternate_quality_parts.append(
            _filter_quality_window_intervals(
                alt_detail,
                include_early=True,
                include_late=False,
                include_open_confirm=True,
            )
        )
        alternate_premarket_parts.append(_filter_premarket_rows(alt_detail))

    if base_detail.empty:
        base_quality = empty.copy()
        base_premarket = empty.copy()
    else:
        base_quality = _filter_quality_window_intervals(base_detail, include_early=True, include_late=True, include_open_confirm=True)
        base_premarket = _filter_premarket_rows(base_detail)

    base_quality = _with_source_priority(base_quality, source_priority=0)
    base_premarket = _with_source_priority(base_premarket, source_priority=0)
    alternate_quality_parts = [_with_source_priority(part, source_priority=1) for part in alternate_quality_parts]
    alternate_premarket_parts = [_with_source_priority(part, source_priority=1) for part in alternate_premarket_parts]

    quality_detail = pd.concat([base_quality, *alternate_quality_parts], ignore_index=True) if alternate_quality_parts else base_quality.copy()
    premarket_detail = pd.concat([base_premarket, *alternate_premarket_parts], ignore_index=True) if alternate_premarket_parts else base_premarket.copy()

    for frame in (quality_detail, premarket_detail):
        if not frame.empty:
            frame["symbol"] = frame["symbol"].astype(str).str.upper()
            frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce", utc=True)
            _n_before = len(frame)
            frame.dropna(subset=["timestamp"], inplace=True)
            _n_dropped = _n_before - len(frame)
            if _n_dropped:
                logger.debug("collect_quality_window_source_frames: dropped %d/%d rows with null timestamp", _n_dropped, _n_before)
            frame.sort_values(["trade_date", "symbol", "timestamp", "_source_priority"], inplace=True, kind="stable")
            frame.drop_duplicates(subset=["trade_date", "symbol", "timestamp"], keep="last", inplace=True)
            frame.drop(columns=["_source_priority"], errors="ignore", inplace=True)
            frame.reset_index(drop=True, inplace=True)

    metadata = {
        "base_dataset": str(base_dataset).strip().upper(),
        "early_exchange_datasets": normalized_map,
        "applied_early_exchange_datasets": applied_datasets,
        "early_exchange_symbol_counts": early_symbol_counts,
        "quality_window_detail_rows": int(len(quality_detail)),
        "premarket_detail_rows": int(len(premarket_detail)),
    }
    return quality_detail, premarket_detail, metadata


def _build_daily_symbol_features_full_universe_export(
    *,
    trading_days: list,
    raw_universe: pd.DataFrame,
    supported_universe: pd.DataFrame,
    daily_bars: pd.DataFrame,
    intraday: pd.DataFrame,
    second_detail_all: pd.DataFrame,
    close_detail_all: pd.DataFrame,
    close_trade_detail_all: pd.DataFrame,
    close_outcome_minute_detail_all: pd.DataFrame,
    display_timezone: str,
    premarket_anchor_et: time,
    ranking_metric: str,
    top_fraction: float,
    smc_base_only: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=raw_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail_all,
        close_detail_all=close_detail_all,
        close_trade_detail_all=close_trade_detail_all,
        close_outcome_minute_detail_all=close_outcome_minute_detail_all,
        display_timezone=display_timezone,
        premarket_anchor_et=premarket_anchor_et,
    )
    if features.empty:
        return pd.DataFrame(columns=DAILY_SYMBOL_FEATURE_COLUMNS), pd.DataFrame(columns=SYMBOL_DAY_DIAGNOSTIC_COLUMNS)

    features = features.copy()
    coverage = coverage.copy()
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce").dt.date
    features["symbol"] = features["symbol"].astype(str).str.upper()
    coverage["trade_date"] = pd.to_datetime(coverage["trade_date"], errors="coerce").dt.date
    coverage["symbol"] = coverage["symbol"].astype(str).str.upper()

    coverage_flags = coverage[["trade_date", "symbol", "has_daily_bar", "has_intraday_summary", "has_open_window_detail", "has_close_window_detail", "exclusion_reason"]].copy()
    coverage_flags = coverage_flags.rename(
        columns={
            "has_daily_bar": "has_daily_bars",
            "has_intraday_summary": "has_intraday",
        }
    )
    coverage_flags = coverage_flags.drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    # Drop columns already present in features to avoid _x/_y suffix pollution.
    overlap_cols = (set(coverage_flags.columns) & set(features.columns)) - {"trade_date", "symbol"}
    if overlap_cols:
        features = features.drop(columns=list(overlap_cols))
    features = features.merge(coverage_flags, on=["trade_date", "symbol"], how="left")
    structure_features = build_market_structure_feature_frame(
        second_detail_all,
        group_keys=["trade_date", "symbol"],
        prefix="structure",
    )
    if not structure_features.empty:
        features = features.merge(structure_features, on=["trade_date", "symbol"], how="left")

    features["exchange"] = features.get("exchange", "").fillna("")
    asset_type = features.get("asset_type")
    if asset_type is None:
        features["asset_type"] = "listed_equity_issue"
    else:
        features["asset_type"] = asset_type.replace("", None).fillna("listed_equity_issue")
    features["window_end_price"] = pd.to_numeric(features.get("current_price"), errors="coerce")
    features["market_cap"] = pd.to_numeric(features.get("market_cap"), errors="coerce")
    features["has_reference_data"] = _bool_series(features, "has_reference_data", default=True)
    features["has_fundamentals"] = _bool_series(features, "has_fundamentals", default=False)
    features["has_daily_bars"] = _bool_series(features, "has_daily_bars", default=False)
    features["has_intraday"] = _bool_series(features, "has_intraday", default=False)
    features["has_market_cap"] = features.get("has_market_cap", features["market_cap"].notna()).fillna(False).astype(bool)
    features["is_supported_by_databento"] = features["symbol"].isin(set(supported_universe["symbol"].astype(str).str.upper()))

    features["eligibility_reason"] = "eligible"
    unsupported_mask = ~features["is_supported_by_databento"]
    missing_reference_mask = ~features["has_reference_data"]
    missing_intraday_mask = ~features["has_intraday"]
    missing_prev_close_mask = pd.to_numeric(features.get("previous_close"), errors="coerce").isna()
    missing_open_prices_mask = pd.to_numeric(features.get("market_open_price"), errors="coerce").isna() | pd.to_numeric(features.get("window_start_price"), errors="coerce").isna()
    missing_range_mask = pd.to_numeric(features.get(ranking_metric), errors="coerce").isna()
    features.loc[unsupported_mask, "eligibility_reason"] = "unsupported_by_databento"
    features.loc[~unsupported_mask & missing_reference_mask, "eligibility_reason"] = "missing_reference_data"
    features.loc[~unsupported_mask & ~missing_reference_mask & missing_intraday_mask, "eligibility_reason"] = "missing_intraday_summary"
    features.loc[~unsupported_mask & ~missing_reference_mask & ~missing_intraday_mask & missing_prev_close_mask, "eligibility_reason"] = "missing_previous_close"
    features.loc[~unsupported_mask & ~missing_reference_mask & ~missing_intraday_mask & ~missing_prev_close_mask & missing_open_prices_mask, "eligibility_reason"] = "missing_open_window_prices"
    features.loc[
        ~unsupported_mask & ~missing_reference_mask & ~missing_intraday_mask & ~missing_prev_close_mask & ~missing_open_prices_mask & missing_range_mask,
        "eligibility_reason",
    ] = "missing_window_range_pct"
    features["is_eligible"] = features["eligibility_reason"].eq("eligible")

    eligible_count_map = features.groupby("trade_date")["is_eligible"].sum().astype(int).to_dict()
    take_n_map = {trade_day: int(math.ceil(count * top_fraction)) if int(count) > 0 else 0 for trade_day, count in eligible_count_map.items()}
    features["eligible_count_for_trade_date"] = features["trade_date"].map(eligible_count_map).fillna(0).astype(int)
    features["take_n_for_trade_date"] = features["trade_date"].map(take_n_map).fillna(0).astype(int)
    features["rank_within_trade_date"] = pd.Series(pd.array([pd.NA] * len(features), dtype="Int64"), index=features.index)

    ranked_candidates = features[features["is_eligible"]].copy()
    if not ranked_candidates.empty:
        ranked_candidates[ranking_metric] = pd.to_numeric(ranked_candidates[ranking_metric], errors="coerce")
        ranked_candidates = ranked_candidates.sort_values(["trade_date", ranking_metric, "symbol"], ascending=[True, False, True]).reset_index(drop=True)
        ranked_candidates["rank_within_trade_date"] = ranked_candidates.groupby("trade_date").cumcount() + 1
        features = features.drop(columns=["rank_within_trade_date"]).merge(
            ranked_candidates[["trade_date", "symbol", "rank_within_trade_date"]],
            on=["trade_date", "symbol"],
            how="left",
        )
        features["rank_within_trade_date"] = features["rank_within_trade_date"].astype("Int64")
    else:
        features["rank_within_trade_date"] = features["rank_within_trade_date"].astype("Int64")

    features["selected_top20pct"] = (
        features["is_eligible"]
        & features["rank_within_trade_date"].notna()
        & (features["rank_within_trade_date"].astype("Int64") <= features["take_n_for_trade_date"])
    )

    features["selected_top20pct_0400"] = False
    if not smc_base_only:
        early_ranking_metric = "focus_0400_open_30s_volume"
        early_has_rows = _numeric_series(features, "focus_0400_open_window_second_rows", fill_value=0.0).fillna(0).astype(int) > 0
        early_prev_close_mask = pd.to_numeric(features.get("previous_close"), errors="coerce").notna()
        early_metric_series = _numeric_series(features, early_ranking_metric)
        early_eligible_mask = (
            features["is_supported_by_databento"]
            & features["has_reference_data"]
            & features["has_daily_bars"]
            & early_prev_close_mask
            & early_has_rows
            & early_metric_series.notna()
        )
        early_eligible_count_map = early_eligible_mask.groupby(features["trade_date"]).sum().astype(int).to_dict()
        early_take_n_map = {
            trade_day: int(math.ceil(count * top_fraction)) if int(count) > 0 else 0
            for trade_day, count in early_eligible_count_map.items()
        }
        early_candidates = features.loc[early_eligible_mask].copy()
        if not early_candidates.empty:
            early_candidates[early_ranking_metric] = pd.to_numeric(early_candidates[early_ranking_metric], errors="coerce")
            early_candidates = early_candidates.sort_values(
                ["trade_date", early_ranking_metric, "symbol"],
                ascending=[True, False, True],
            ).reset_index(drop=True)
            early_candidates["rank_within_trade_date_0400"] = early_candidates.groupby("trade_date").cumcount() + 1
            early_candidates["take_n_for_trade_date_0400"] = early_candidates["trade_date"].map(early_take_n_map).fillna(0).astype(int)
            early_selected = early_candidates[
                early_candidates["rank_within_trade_date_0400"] <= early_candidates["take_n_for_trade_date_0400"]
            ][["trade_date", "symbol"]].copy()
            early_selected["selected_top20pct_0400"] = True
            features = features.drop(columns=["selected_top20pct_0400"]).merge(
                early_selected,
                on=["trade_date", "symbol"],
                how="left",
            )
            features["selected_top20pct_0400"] = pd.Series(features["selected_top20pct_0400"], dtype="boolean").fillna(False)
            features["selected_top20pct_0400"] = features["selected_top20pct_0400"].astype(bool)

    diagnostics = features[
        [
            "trade_date",
            "symbol",
            "exchange",
            "asset_type",
            "has_reference_data",
            "has_fundamentals",
            "has_daily_bars",
            "has_intraday",
            "has_market_cap",
            "is_supported_by_databento",
            "is_eligible",
            "selected_top20pct",
            "selected_top20pct_0400",
            "eligibility_reason",
        ]
    ].copy()
    diagnostics["present_in_raw_universe"] = True
    diagnostics["present_after_reference_join"] = diagnostics["has_reference_data"]
    diagnostics["present_after_fundamentals_join"] = diagnostics["has_fundamentals"]
    diagnostics["present_after_daily_filter"] = diagnostics["has_daily_bars"]
    diagnostics["present_after_intraday_filter"] = diagnostics["has_intraday"]
    diagnostics["present_in_eligible"] = diagnostics["is_eligible"]
    diagnostics["excluded_step"] = ""
    diagnostics["excluded_reason"] = ""
    diagnostics.loc[~diagnostics["is_supported_by_databento"], ["excluded_step", "excluded_reason"]] = ["databento_support_filter", "unsupported_by_databento"]
    diagnostics.loc[
        diagnostics["is_supported_by_databento"] & ~diagnostics["has_daily_bars"],
        ["excluded_step", "excluded_reason"],
    ] = ["daily_filter", "missing_daily_bar"]
    diagnostics.loc[
        diagnostics["is_supported_by_databento"] & diagnostics["has_daily_bars"] & ~diagnostics["has_intraday"],
        ["excluded_step", "excluded_reason"],
    ] = ["intraday_filter", "missing_intraday_summary"]
    eligibility_excluded_mask = diagnostics["is_supported_by_databento"] & diagnostics["has_intraday"] & ~diagnostics["is_eligible"]
    diagnostics.loc[eligibility_excluded_mask, "excluded_step"] = "eligibility"
    diagnostics.loc[eligibility_excluded_mask, "excluded_reason"] = diagnostics.loc[eligibility_excluded_mask, "eligibility_reason"]
    diagnostics.loc[
        diagnostics["is_eligible"] & ~diagnostics["selected_top20pct"],
        ["excluded_step", "excluded_reason"],
    ] = ["top20pct_selection", "outside_top20pct_cutoff"]

    features = features.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    diagnostics = diagnostics.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    features = features.reindex(columns=DAILY_SYMBOL_FEATURE_COLUMNS)
    diagnostics = diagnostics.reindex(columns=SYMBOL_DAY_DIAGNOSTIC_COLUMNS)
    return features, diagnostics


def _prepare_full_universe_second_detail_export(second_detail_all: pd.DataFrame, daily_features: pd.DataFrame) -> pd.DataFrame:
    if second_detail_all.empty:
        return pd.DataFrame(columns=SECOND_DETAIL_EXPORT_COLUMNS)

    detail = second_detail_all.copy()
    detail["trade_date"] = pd.to_datetime(detail["trade_date"], errors="coerce").dt.date
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce", utc=True)
    lookup = daily_features[["trade_date", "symbol", "previous_close", "market_open_price"]].copy()
    lookup["trade_date"] = pd.to_datetime(lookup["trade_date"], errors="coerce").dt.date
    lookup["symbol"] = lookup["symbol"].astype(str).str.upper()
    lookup = lookup.drop_duplicates(subset=["trade_date", "symbol"], keep="first").reset_index(drop=True)
    detail = detail.merge(lookup, on=["trade_date", "symbol"], how="left")
    detail["second_delta_pct"] = pd.to_numeric(detail.get("second_delta_pct"), errors="coerce")
    detail["from_previous_close_pct"] = np.where(
        pd.to_numeric(detail.get("previous_close"), errors="coerce") > 0,
        ((pd.to_numeric(detail.get("close"), errors="coerce") / pd.to_numeric(detail.get("previous_close"), errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    detail["from_open_pct"] = np.where(
        pd.to_numeric(detail.get("market_open_price"), errors="coerce") > 0,
        ((pd.to_numeric(detail.get("close"), errors="coerce") / pd.to_numeric(detail.get("market_open_price"), errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    trade_count_source = None
    for column in ["trade_count", "count", "n_trades", "num_trades"]:
        if column in detail.columns:
            trade_count_source = column
            break
    detail["trade_count"] = pd.to_numeric(detail.get(trade_count_source), errors="coerce") if trade_count_source else np.nan
    detail = detail.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
    return detail[SECOND_DETAIL_EXPORT_COLUMNS]


def _build_premarket_features_full_universe_export(second_detail_all: pd.DataFrame, daily_features: pd.DataFrame) -> pd.DataFrame:
    expected = daily_features[["trade_date", "symbol", "previous_close", "market_open_price"]].copy()
    expected["trade_date"] = pd.to_datetime(expected["trade_date"], errors="coerce").dt.date
    expected["symbol"] = expected["symbol"].astype(str).str.upper()
    if second_detail_all.empty:
        out = expected.copy()
        out["has_premarket_data"] = False
        for column in PREMARKET_FEATURE_COLUMNS:
            if column not in out.columns:
                out[column] = np.nan if column not in {"trade_date", "symbol", "has_premarket_data"} else out.get(column)
        out["has_premarket_data"] = False
        return out[PREMARKET_FEATURE_COLUMNS]

    detail = second_detail_all.copy()
    detail["trade_date"] = pd.to_datetime(detail["trade_date"], errors="coerce").dt.date
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce", utc=True)
    detail = detail[detail["session"].astype(str).str.lower().eq("premarket")].copy()

    if detail.empty:
        out = expected.copy()
        out["has_premarket_data"] = False
        for column in PREMARKET_FEATURE_COLUMNS:
            if column not in out.columns:
                out[column] = np.nan if column not in {"trade_date", "symbol", "has_premarket_data"} else out.get(column)
        out["has_premarket_data"] = False
        return out[PREMARKET_FEATURE_COLUMNS]

    trade_count_available = detail["trade_count"].notna().any() if "trade_count" in detail.columns else False
    metrics: list[dict[str, object]] = []
    for (trade_day, symbol), group in detail.groupby(["trade_date", "symbol"], sort=False):
        ordered = group.sort_values("timestamp")
        volume = pd.to_numeric(ordered["volume"], errors="coerce").fillna(0.0)
        close = pd.to_numeric(ordered["close"], errors="coerce")
        dollar_volume = float((close * volume).sum())
        total_volume = float(volume.sum())
        premarket_trade_count_actual = (
            float(pd.to_numeric(ordered["trade_count"], errors="coerce").sum())
            if trade_count_available
            else np.nan
        )
        premarket_active_seconds = float((volume > 0).sum())
        premarket_trade_count = premarket_trade_count_actual if math.isfinite(premarket_trade_count_actual) else premarket_active_seconds
        premarket_trade_count_source = "actual" if math.isfinite(premarket_trade_count_actual) else "proxy_active_seconds"
        metrics.append(
            {
                "trade_date": trade_day,
                "symbol": symbol,
                "premarket_open": pd.to_numeric(ordered["open"], errors="coerce").iloc[0],
                "premarket_high": pd.to_numeric(ordered["high"], errors="coerce").max(),
                "premarket_low": pd.to_numeric(ordered["low"], errors="coerce").min(),
                "premarket_last": close.iloc[-1],
                "premarket_vwap": (dollar_volume / total_volume) if total_volume > 0 else np.nan,
                "premarket_volume": total_volume,
                "premarket_dollar_volume": dollar_volume,
                "premarket_trade_count": premarket_trade_count,
                "premarket_trade_count_actual": premarket_trade_count_actual,
                "premarket_active_seconds": premarket_active_seconds,
                "premarket_last_trade_ts": ordered["timestamp"].max(),
                "premarket_trade_count_source": premarket_trade_count_source,
                "premarket_trade_count_usable": True,
                "premarket_seconds": int(len(ordered)),
            }
        )

    out = expected.merge(pd.DataFrame(metrics), on=["trade_date", "symbol"], how="left")
    out["has_premarket_data"] = out["premarket_seconds"].fillna(0).astype(int) > 0
    out["prev_close_to_premarket_pct"] = np.where(
        pd.to_numeric(out["previous_close"], errors="coerce") > 0,
        ((pd.to_numeric(out["premarket_last"], errors="coerce") / pd.to_numeric(out["previous_close"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    out["premarket_to_open_pct"] = np.where(
        pd.to_numeric(out["premarket_last"], errors="coerce") > 0,
        ((pd.to_numeric(out["market_open_price"], errors="coerce") / pd.to_numeric(out["premarket_last"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    return out[PREMARKET_FEATURE_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _build_close_imbalance_features_full_universe_export(daily_features: pd.DataFrame) -> pd.DataFrame:
    if daily_features.empty:
        return pd.DataFrame(columns=CLOSE_IMBALANCE_FEATURE_COLUMNS)

    out = daily_features.copy()
    for column in CLOSE_IMBALANCE_FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan
    out["has_close_window_detail"] = out["has_close_window_detail"].fillna(False).astype(bool)
    return out[CLOSE_IMBALANCE_FEATURE_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _build_close_imbalance_outcomes_full_universe_export(daily_features: pd.DataFrame) -> pd.DataFrame:
    if daily_features.empty:
        return pd.DataFrame(columns=CLOSE_IMBALANCE_OUTCOME_COLUMNS)

    out = daily_features.copy()
    for column in CLOSE_IMBALANCE_OUTCOME_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan
    if "has_next_day_outcome" in out.columns:
        out["has_next_day_outcome"] = out["has_next_day_outcome"].fillna(False).astype(bool)
    return out[CLOSE_IMBALANCE_OUTCOME_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _build_batl_debug_payload(daily_features: pd.DataFrame, diagnostics: pd.DataFrame) -> dict[str, object]:
    batl_rows = daily_features[daily_features["symbol"].astype(str).str.upper().eq("BATL")].copy()
    if not batl_rows.empty:
        batl_rows = batl_rows.sort_values(["trade_date", "selected_top20pct", "rank_within_trade_date"], ascending=[False, False, True])
        row = batl_rows.iloc[0]
        return {
            "present_in_daily_symbol_features_full_universe": True,
            "trade_date": str(row["trade_date"]),
            "is_eligible": bool(row["is_eligible"]),
            "eligibility_reason": str(row["eligibility_reason"]),
            "rank_within_trade_date": None if pd.isna(row["rank_within_trade_date"]) else int(row["rank_within_trade_date"]),
            "selected_top20pct": bool(row["selected_top20pct"]),
        }
    diag_rows = diagnostics[diagnostics["symbol"].astype(str).str.upper().eq("BATL")].copy()
    if diag_rows.empty:
        return {
            "present_in_daily_symbol_features_full_universe": False,
            "excluded_step": "raw_universe",
            "excluded_reason": "symbol_not_present_in_raw_universe",
        }
    row = diag_rows.sort_values("trade_date", ascending=False).iloc[0]
    return {
        "present_in_daily_symbol_features_full_universe": False,
        "trade_date": str(row["trade_date"]),
        "selected_top20pct": bool(row["selected_top20pct"]),
        "excluded_step": str(row["excluded_step"]),
        "excluded_reason": str(row["excluded_reason"]),
    }


def _write_exact_named_exports(export_dir: Path, named_frames: dict[str, pd.DataFrame]) -> dict[str, Path]:
    created: dict[str, Path] = {}
    export_dir.mkdir(parents=True, exist_ok=True)
    for name, frame in named_frames.items():
        path = export_dir / f"{name}.parquet"
        _write_parquet_atomic(path, frame)
        created[name] = path
    return created


def _format_optional_time(value: time | None) -> str:
    return value.strftime("%H:%M:%S") if isinstance(value, time) else "market_relative_default"


def _resolve_latest_iso_timestamp(frame: pd.DataFrame, *, candidates: tuple[str, ...]) -> str | None:
    if frame.empty:
        return None
    for column in candidates:
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce", utc=True)
        if parsed.isna().all():
            continue
        latest = parsed.max()
        if pd.isna(latest):
            continue
        return str(latest.isoformat(timespec="seconds"))
    return None


def _parse_calendar_trade_date(value: Any) -> date | None:
    parsed = pd.to_datetime(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(parsed):
        return None
    if isinstance(parsed, pd.Timestamp):
        return parsed.date()
    return None


def _normalize_earnings_timing(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().replace("_", " ").replace("-", " ").split())


def _normalize_research_symbol(value: Any) -> str:
    raw_symbol = str(value or "").strip()
    if not raw_symbol:
        return ""
    normalized = normalize_symbol_for_databento(raw_symbol)
    return str(normalized or raw_symbol).strip().upper()


def _research_news_window_bounds_for_trade_date(trade_day: Any) -> dict[str, pd.Timestamp]:
    trade_ts = pd.Timestamp(trade_day)
    trade_open_et = pd.Timestamp.combine(trade_ts.date(), time(9, 30)).tz_localize(US_EASTERN_TZ)
    preopen_start_et = pd.Timestamp.combine(trade_ts.date(), time(4, 0)).tz_localize(US_EASTERN_TZ)
    window_24h_start_et = trade_open_et - pd.Timedelta(hours=24)
    return {
        "window_24h_start_et": window_24h_start_et,
        "preopen_start_et": preopen_start_et,
        "trade_open_et": trade_open_et,
        "window_24h_start_utc": window_24h_start_et.tz_convert(UTC),
        "preopen_start_utc": preopen_start_et.tz_convert(UTC),
        "trade_open_utc": trade_open_et.tz_convert(UTC),
    }


def _benzinga_date_utc(value: pd.Timestamp) -> str:
    timestamp = value.tz_convert(UTC) if value.tzinfo is not None else value.tz_localize(UTC)
    return str(timestamp.strftime("%Y-%m-%d"))


def _iter_symbol_batches(symbols: Sequence[str], *, batch_size: int) -> list[list[str]]:
    ordered = [symbol for symbol in symbols if str(symbol).strip()]
    if batch_size <= 0:
        return [ordered]
    return [ordered[index:index + batch_size] for index in range(0, len(ordered), batch_size)]


def _research_news_article_key(item: Any) -> str:
    item_id = str(getattr(item, "item_id", "") or "").strip()
    if item_id:
        return item_id
    url = str(getattr(item, "url", "") or "").strip()
    headline = str(getattr(item, "headline", "") or "").strip().lower()
    published_ts = int(float(getattr(item, "published_ts", 0.0) or 0.0))
    return "|".join(part for part in (url, headline, str(published_ts)) if part)


def _timing_is_pre_open(value: Any) -> bool:
    normalized = _normalize_earnings_timing(value)
    return normalized in {"bmo", "before market open", "before open", "pre market", "premarket"}


def _timing_is_post_close(value: Any) -> bool:
    normalized = _normalize_earnings_timing(value)
    return normalized in {"amc", "after market close", "after close", "post market", "postmarket"}


def _empty_research_event_flags(scope: pd.DataFrame, *, missing: bool) -> pd.DataFrame:
    out = scope[["trade_date", "symbol"]].drop_duplicates(subset=["trade_date", "symbol"]).copy()
    dtype = "boolean"
    fill_value = pd.NA if missing else False
    for column in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        out[column] = pd.Series([fill_value] * len(out), dtype=dtype)
    return out[RESEARCH_EVENT_FLAG_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _empty_research_news_flags(scope: pd.DataFrame, *, missing: bool) -> pd.DataFrame:
    out = scope[["trade_date", "symbol"]].drop_duplicates(subset=["trade_date", "symbol"]).copy()
    bool_fill_value = pd.NA if missing else False
    count_fill_value = pd.NA if missing else 0
    for column in RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS:
        out[column] = pd.Series([bool_fill_value] * len(out), dtype="boolean")
    for column in RESEARCH_NEWS_FLAG_COUNT_COLUMNS:
        out[column] = pd.Series([count_fill_value] * len(out), dtype="Int64")
    return out[RESEARCH_NEWS_FLAG_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _research_news_positive_mask(frame: pd.DataFrame, column: str) -> pd.Series:
    if column in RESEARCH_NEWS_FLAG_COUNT_COLUMNS:
        numeric = pd.to_numeric(frame.get(column, pd.Series(dtype=float)), errors="coerce")
        return numeric.gt(0).fillna(False)
    return pd.Series(frame.get(column, pd.Series(dtype="boolean")), dtype="boolean").fillna(False)


def _resolve_research_news_status(
    *,
    resolved_symbol_days: int,
    failed_symbol_days: int,
    truncated_symbol_days: int,
    matched_symbol_articles: int,
) -> str:
    if failed_symbol_days and resolved_symbol_days == 0:
        return RESEARCH_NEWS_STATUS_FETCH_FAILED
    if failed_symbol_days and truncated_symbol_days:
        return RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED_TRUNCATED
    if failed_symbol_days:
        return RESEARCH_NEWS_STATUS_PARTIAL_FETCH_FAILED
    if truncated_symbol_days:
        return RESEARCH_NEWS_STATUS_TRUNCATED
    if matched_symbol_articles == 0:
        return RESEARCH_NEWS_STATUS_OK_EMPTY
    return RESEARCH_NEWS_STATUS_OK


def _apply_research_news_symbol_day_semantics(
    merged: pd.DataFrame,
    *,
    resolved_mask: pd.Series,
    failed_mask: pd.Series,
    truncated_mask: pd.Series,
) -> pd.DataFrame:
    out = merged.copy()

    has_news = pd.Series(out.get("has_company_news_24h"), dtype="boolean")
    has_preopen = pd.Series(out.get("has_company_news_preopen_window"), dtype="boolean")
    count_series = pd.Series(out.get("company_news_item_count_24h"), dtype="Int64")

    observed_has_news = has_news.fillna(False)
    observed_has_preopen = has_preopen.fillna(False)

    has_news.loc[failed_mask] = pd.NA
    has_news.loc[truncated_mask & observed_has_news] = True
    has_news.loc[truncated_mask & ~observed_has_news] = pd.NA
    has_news.loc[resolved_mask & ~(failed_mask | truncated_mask) & has_news.isna()] = False

    has_preopen.loc[failed_mask] = pd.NA
    has_preopen.loc[truncated_mask & observed_has_preopen] = True
    has_preopen.loc[truncated_mask & ~observed_has_preopen] = pd.NA
    has_preopen.loc[resolved_mask & ~(failed_mask | truncated_mask) & has_preopen.isna()] = False

    count_series.loc[failed_mask | truncated_mask] = pd.NA
    count_series.loc[resolved_mask & ~(failed_mask | truncated_mask) & count_series.isna()] = 0

    out["has_company_news_24h"] = has_news
    out["has_company_news_preopen_window"] = has_preopen
    out["company_news_item_count_24h"] = count_series
    return out


def _benzinga_flag_status_bucket(row: pd.Series) -> str:
    if pd.isna(row.get("benzinga_has_company_news_24h")) and pd.isna(row.get("benzinga_company_news_item_count_24h")):
        return "unknown"
    if pd.isna(row.get("benzinga_company_news_item_count_24h")):
        return "degraded"
    return "full"


def _core_vs_benzinga_overlap_bucket(row: pd.Series) -> str:
    benzinga_flag = row.get("benzinga_has_company_news_24h")
    if pd.isna(benzinga_flag):
        return "benzinga_unknown"
    core_has_news = bool(row.get("core_has_news", False))
    benzinga_has_news = bool(benzinga_flag)
    if core_has_news and benzinga_has_news:
        return "both"
    if core_has_news:
        return "core_only"
    if benzinga_has_news:
        return "benzinga_only"
    return "neither"


def _build_core_vs_benzinga_news_side_by_side(
    *,
    daily_features: pd.DataFrame,
    research_news_flags: pd.DataFrame,
    fmp_api_key: str,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    scope = daily_features[[col for col in ("trade_date", "symbol", "selected_top20pct") if col in daily_features.columns]].copy()
    if "selected_top20pct" not in scope.columns:
        scope["selected_top20pct"] = False
    scope["trade_date"] = pd.to_datetime(scope["trade_date"], errors="coerce").dt.date
    scope["symbol"] = scope["symbol"].map(_normalize_research_symbol)
    scope = scope.dropna(subset=["trade_date", "symbol"])
    scope = scope[scope["symbol"].astype(str).str.len() > 0]
    scope = scope.drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    if scope.empty:
        return (
            pd.DataFrame(columns=CORE_BENZINGA_NEWS_SIDE_BY_SIDE_COLUMNS),
            pd.DataFrame(columns=CORE_BENZINGA_NEWS_OVERLAP_COLUMNS),
            {"enabled": False, "status": "empty_scope"},
        )

    latest_trade_date = max(scope["trade_date"])
    latest_scope = scope[scope["trade_date"] == latest_trade_date].copy().reset_index(drop=True)
    if latest_scope.empty:
        return (
            pd.DataFrame(columns=CORE_BENZINGA_NEWS_SIDE_BY_SIDE_COLUMNS),
            pd.DataFrame(columns=CORE_BENZINGA_NEWS_OVERLAP_COLUMNS),
            {"enabled": False, "status": "empty_latest_trade_date_scope"},
        )

    latest_flags = research_news_flags.copy()
    latest_flags["trade_date"] = pd.to_datetime(latest_flags["trade_date"], errors="coerce").dt.date
    latest_flags["symbol"] = latest_flags["symbol"].map(_normalize_research_symbol)
    latest_flags = latest_flags[latest_flags["trade_date"] == latest_trade_date].copy()

    merged = latest_scope.merge(latest_flags, on=["trade_date", "symbol"], how="left")
    merged.rename(columns={
        "has_company_news_24h": "benzinga_has_company_news_24h",
        "company_news_item_count_24h": "benzinga_company_news_item_count_24h",
        "has_company_news_preopen_window": "benzinga_has_company_news_preopen_window",
    }, inplace=True)

    core_scores: dict[str, float] = {}
    core_metrics: dict[str, dict[str, Any]] = {}
    core_fetch_error: str | None = None
    if not fmp_api_key:
        core_fetch_error = "missing_fmp_api_key"
    else:
        from open_prep import run_open_prep as open_prep_run

        client = FMPClient(api_key=fmp_api_key)
        core_scores, core_metrics, core_fetch_error = open_prep_run._fetch_news_context(
            client=client,
            symbols=latest_scope["symbol"].tolist(),
        )

    merged["core_news_catalyst_score"] = merged["symbol"].map(lambda sym: float(core_scores.get(str(sym).upper(), 0.0) or 0.0))
    merged["core_news_event_class"] = merged["symbol"].map(lambda sym: (core_metrics.get(str(sym).upper(), {}) or {}).get("event_class", "UNKNOWN"))
    merged["core_news_materiality"] = merged["symbol"].map(lambda sym: (core_metrics.get(str(sym).upper(), {}) or {}).get("materiality", "LOW"))
    merged["core_news_recency_bucket"] = merged["symbol"].map(lambda sym: (core_metrics.get(str(sym).upper(), {}) or {}).get("recency_bucket", "UNKNOWN"))
    merged["core_news_source_tier"] = merged["symbol"].map(lambda sym: (core_metrics.get(str(sym).upper(), {}) or {}).get("source_tier", "TIER_3"))
    merged["core_has_news"] = merged["core_news_catalyst_score"].gt(0.0)
    merged["benzinga_status_bucket"] = merged.apply(_benzinga_flag_status_bucket, axis=1)
    merged["overlap_bucket"] = merged.apply(_core_vs_benzinga_overlap_bucket, axis=1)

    overlap_stats = (
        merged.groupby("overlap_bucket", dropna=False)
        .agg(
            symbol_day_rows=("symbol", "size"),
            selected_top20pct_rows=("selected_top20pct", lambda s: int(pd.Series(s).fillna(False).astype(bool).sum())),
        )
        .reset_index()
    )
    overlap_stats.insert(0, "trade_date", latest_trade_date)

    return (
        merged[CORE_BENZINGA_NEWS_SIDE_BY_SIDE_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True),
        overlap_stats[CORE_BENZINGA_NEWS_OVERLAP_COLUMNS],
        {
            "enabled": True,
            "status": "ok" if core_fetch_error is None else "core_fetch_degraded",
            "trade_date": latest_trade_date.isoformat(),
            "symbol_day_rows": int(len(merged)),
            "core_nonzero_symbols": int(merged["core_has_news"].sum()),
            "core_fetch_error": core_fetch_error,
        },
    )


def _build_research_news_flags_full_universe_export(
    *,
    daily_features: pd.DataFrame,
    benzinga_api_key: str,
    symbol_batch_size: int = 100,
    page_size: int = 100,
    max_pages_per_request: int = 10,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    scope = daily_features[["trade_date", "symbol"]].copy()
    scope["trade_date"] = pd.to_datetime(scope["trade_date"], errors="coerce").dt.date
    scope["symbol"] = scope["symbol"].map(_normalize_research_symbol)
    scope = scope.dropna(subset=["trade_date", "symbol"])
    scope = scope[scope["symbol"].astype(str).str.len() > 0]
    scope = scope.drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    if scope.empty:
        return pd.DataFrame(columns=RESEARCH_NEWS_FLAG_COLUMNS), {
            "enabled": False,
            "source": "benzinga_news",
            "status": "empty_scope",
        }
    if not benzinga_api_key:
        return _empty_research_news_flags(scope, missing=True), {
            "enabled": False,
            "source": "benzinga_news",
            "status": "missing_api_key",
            "window_24h_anchor_et": "09:30:00",
            "preopen_window_et": "04:00:00-09:30:00",
        }

    adapter = BenzingaRestAdapter(benzinga_api_key)
    resolved_symbol_days: set[tuple[date, str]] = set()
    failed_symbol_days: set[tuple[date, str]] = set()
    truncated_symbol_days: set[tuple[date, str]] = set()
    article_rows: list[dict[str, Any]] = []
    fetched_items = 0
    ignored_items_missing_timestamp = 0
    truncated_requests = 0
    sample_errors: list[str] = []

    try:
        for trade_day, symbol_frame in scope.groupby("trade_date", sort=True):
            if pd.isna(trade_day):
                continue
            windows = _research_news_window_bounds_for_trade_date(trade_day)
            date_from = _benzinga_date_utc(windows["window_24h_start_utc"])
            date_to = _benzinga_date_utc(windows["trade_open_utc"])
            symbols = sorted({_normalize_research_symbol(value) for value in symbol_frame["symbol"].tolist() if _normalize_research_symbol(value)})
            for batch in _iter_symbol_batches(symbols, batch_size=symbol_batch_size):
                batch_keys = {(trade_day, symbol) for symbol in batch}
                try:
                    for page in range(max_pages_per_request):
                        items = adapter.fetch_news(
                            page_size=page_size,
                            page=page,
                            date_from=date_from,
                            date_to=date_to,
                            tickers=",".join(batch),
                        )
                        fetched_items += len(items)
                        if not items:
                            break
                        for item in items:
                            published_ts = float(getattr(item, "published_ts", 0.0) or 0.0)
                            if published_ts <= 0:
                                ignored_items_missing_timestamp += 1
                                continue
                            published_at_utc = pd.Timestamp(datetime.fromtimestamp(published_ts, tz=UTC))
                            if not (windows["window_24h_start_utc"] <= published_at_utc < windows["trade_open_utc"]):
                                continue
                            article_key = _research_news_article_key(item)
                            for raw_symbol in getattr(item, "tickers", []) or []:
                                normalized_symbol = _normalize_research_symbol(raw_symbol)
                                if (trade_day, normalized_symbol) not in batch_keys:
                                    continue
                                article_rows.append(
                                    {
                                        "trade_date": trade_day,
                                        "symbol": normalized_symbol,
                                        "article_key": article_key,
                                        "published_at_utc": published_at_utc,
                                        "is_preopen_window": bool(windows["preopen_start_utc"] <= published_at_utc < windows["trade_open_utc"]),
                                    }
                                )
                        if len(items) < page_size:
                            break
                        if page == max_pages_per_request - 1:
                            truncated_requests += 1
                            truncated_symbol_days.update(batch_keys)
                    resolved_symbol_days.update(batch_keys)
                except Exception as exc:
                    logger.warning(
                        "Research news flag fetch failed for %s (%d symbols); leaving symbol-days missing: %s",
                        trade_day,
                        len(batch),
                        exc,
                    )
                    sample_errors.append(str(exc))
                    failed_symbol_days.update(batch_keys)
    finally:
        adapter.close()

    if article_rows:
        article_frame = pd.DataFrame(article_rows)
        article_frame["trade_date"] = pd.to_datetime(article_frame["trade_date"], errors="coerce").dt.date
        article_frame["symbol"] = article_frame["symbol"].map(_normalize_research_symbol)
        article_frame["published_at_utc"] = pd.to_datetime(article_frame["published_at_utc"], errors="coerce", utc=True)
        article_frame = article_frame.dropna(subset=["trade_date", "symbol", "article_key", "published_at_utc"])
        article_frame = article_frame.drop_duplicates(subset=["trade_date", "symbol", "article_key"]).reset_index(drop=True)
        aggregated = (
            article_frame.groupby(["trade_date", "symbol"], as_index=False)
            .agg(
                company_news_item_count_24h=("article_key", "size"),
                has_company_news_preopen_window=("is_preopen_window", "max"),
            )
        )
        aggregated["has_company_news_24h"] = aggregated["company_news_item_count_24h"].gt(0)
        aggregated["company_news_item_count_24h"] = pd.Series(aggregated["company_news_item_count_24h"], dtype="Int64")
        aggregated["has_company_news_24h"] = pd.Series(aggregated["has_company_news_24h"], dtype="boolean")
        aggregated["has_company_news_preopen_window"] = pd.Series(aggregated["has_company_news_preopen_window"], dtype="boolean")
    else:
        article_frame = pd.DataFrame(columns=["trade_date", "symbol", "article_key", "published_at_utc", "is_preopen_window"])
        aggregated = pd.DataFrame(columns=RESEARCH_NEWS_FLAG_COLUMNS)

    merged = scope.merge(aggregated, on=["trade_date", "symbol"], how="left")
    key_series = merged.apply(lambda row: (row["trade_date"], row["symbol"]), axis=1)
    resolved_mask = key_series.isin(resolved_symbol_days)
    failed_mask = key_series.isin(failed_symbol_days)
    truncated_mask = key_series.isin(truncated_symbol_days)
    merged = _apply_research_news_symbol_day_semantics(
        merged,
        resolved_mask=resolved_mask,
        failed_mask=failed_mask,
        truncated_mask=truncated_mask,
    )

    status = _resolve_research_news_status(
        resolved_symbol_days=len(resolved_symbol_days),
        failed_symbol_days=len(failed_symbol_days),
        truncated_symbol_days=len(truncated_symbol_days),
        matched_symbol_articles=len(article_frame),
    )

    return merged[RESEARCH_NEWS_FLAG_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True), {
        "enabled": True,
        "source": "benzinga_news",
        "status": status,
        "window_24h_anchor_et": "09:30:00",
        "window_24h_rule": "[trade_date 09:30 ET - 24h, trade_date 09:30 ET)",
        "preopen_window_et": "04:00:00-09:30:00",
        "request_mode": "dateFrom/dateTo-date+ticker_batches",
        "requested_symbol_days": int(len(scope)),
        "resolved_symbol_days": int(len(resolved_symbol_days)),
        "failed_symbol_days": int(len(failed_symbol_days)),
        "truncated_symbol_days": int(len(truncated_symbol_days)),
        "degraded_symbol_days": int(len(failed_symbol_days | truncated_symbol_days)),
        "fetched_provider_items": int(fetched_items),
        "matched_symbol_articles": int(len(article_frame)),
        "ignored_items_missing_timestamp": int(ignored_items_missing_timestamp),
        "truncated_requests": int(truncated_requests),
        "sample_errors": sample_errors[:3],
    }


def _build_research_news_flag_coverage(flags_frame: pd.DataFrame) -> pd.DataFrame:
    if flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_NEWS_FLAG_COVERAGE_COLUMNS)
    rows: list[dict[str, Any]] = []
    total_rows = int(len(flags_frame))
    for flag_name in RESEARCH_NEWS_FLAG_COLUMNS[2:]:
        series = flags_frame.get(flag_name, pd.Series(dtype=object))
        non_null_rows = int(pd.Series(series).notna().sum())
        positive_mask = _research_news_positive_mask(flags_frame, flag_name)
        true_rows = int(positive_mask.sum())
        rows.append(
            {
                "flag_name": flag_name,
                "symbol_day_rows": total_rows,
                "non_null_rows": non_null_rows,
                "null_rows": total_rows - non_null_rows,
                "non_null_rate": float(non_null_rows / total_rows) if total_rows else 0.0,
                "true_rows": true_rows,
                "true_rate": float(true_rows / non_null_rows) if non_null_rows else 0.0,
                "affected_trade_dates": int(flags_frame.loc[positive_mask, "trade_date"].nunique()),
                "all_false_bug": bool(non_null_rows > 0 and true_rows == 0),
                "all_true_bug": bool(non_null_rows > 0 and true_rows == non_null_rows),
            }
        )
    return pd.DataFrame(rows, columns=RESEARCH_NEWS_FLAG_COVERAGE_COLUMNS)


def _build_research_news_flag_trade_date_distribution(flags_frame: pd.DataFrame) -> pd.DataFrame:
    if flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_NEWS_FLAG_TRADE_DATE_COLUMNS)
    rows: list[dict[str, Any]] = []
    total_by_date = flags_frame.groupby("trade_date")["symbol"].size().to_dict()
    for flag_name in RESEARCH_NEWS_FLAG_COLUMNS[2:]:
        positive_mask = _research_news_positive_mask(flags_frame, flag_name)
        grouped = (
            flags_frame.assign(_flag_value=positive_mask)
            .groupby("trade_date", sort=True)["_flag_value"]
            .sum()
            .to_dict()
        )
        for trade_day, symbol_day_rows in total_by_date.items():
            true_rows = int(grouped.get(trade_day, 0))
            rows.append(
                {
                    "trade_date": trade_day,
                    "flag_name": flag_name,
                    "symbol_day_rows": int(symbol_day_rows),
                    "true_rows": true_rows,
                    "true_rate": float(true_rows / symbol_day_rows) if symbol_day_rows else 0.0,
                }
            )
    return pd.DataFrame(rows, columns=RESEARCH_NEWS_FLAG_TRADE_DATE_COLUMNS).sort_values(["trade_date", "flag_name"]).reset_index(drop=True)


def _build_research_news_flag_outcome_slices(daily_features: pd.DataFrame, flags_frame: pd.DataFrame) -> pd.DataFrame:
    if daily_features.empty or flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_NEWS_FLAG_OUTCOME_SLICE_COLUMNS)
    merged = daily_features.merge(flags_frame, on=["trade_date", "symbol"], how="left")
    for flag_name in RESEARCH_NEWS_FLAG_COLUMNS[2:]:
        merged = _coalesce_optional_merge_column(merged, flag_name)
    rows: list[dict[str, Any]] = []
    metric_columns = {
        "mean_window_range_pct": "window_range_pct",
        "mean_realized_vol_pct": "realized_vol_pct",
        "mean_close_trade_hygiene_score": "close_trade_hygiene_score",
        "mean_close_last_1m_volume_share": "close_last_1m_volume_share",
        "mean_close_to_next_open_return_pct": "close_to_next_open_return_pct",
    }
    for flag_name in RESEARCH_NEWS_FLAG_COLUMNS[2:]:
        positive_mask = _research_news_positive_mask(merged, flag_name)
        for selected in (False, True):
            selected_slice = merged[merged["selected_top20pct"].astype(bool) == selected]
            selected_positive_mask = positive_mask.loc[selected_slice.index]
            for flag_value in (False, True):
                cohort = selected_slice[selected_positive_mask == flag_value]
                row: dict[str, Any] = {
                    "flag_name": flag_name,
                    "selected_top20pct": bool(selected),
                    "flag_value": bool(flag_value),
                    "row_count": int(len(cohort)),
                }
                for output_name, source_name in metric_columns.items():
                    numeric = pd.to_numeric(cohort.get(source_name, pd.Series(dtype=float)), errors="coerce")
                    row[output_name] = float(numeric.mean()) if not numeric.dropna().empty else 0.0
                rows.append(row)
    return pd.DataFrame(rows, columns=RESEARCH_NEWS_FLAG_OUTCOME_SLICE_COLUMNS)


def _build_research_event_flags_full_universe_export(
    *,
    daily_features: pd.DataFrame,
    fmp_api_key: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    scope = daily_features[["trade_date", "symbol"]].copy()
    scope["trade_date"] = pd.to_datetime(scope["trade_date"], errors="coerce").dt.date
    scope["symbol"] = scope["symbol"].astype(str).str.upper()
    scope = scope.dropna(subset=["trade_date", "symbol"]).drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)
    if scope.empty:
        return pd.DataFrame(columns=RESEARCH_EVENT_FLAG_COLUMNS), {
            "enabled": False,
            "source": "fmp_earnings_calendar",
            "status": "empty_scope",
        }
    if not fmp_api_key:
        return _empty_research_event_flags(scope, missing=True), {
            "enabled": False,
            "source": "fmp_earnings_calendar",
            "status": "missing_api_key",
        }

    trade_dates = sorted(set(scope["trade_date"].tolist()))
    client = FMPClient(fmp_api_key)
    try:
        earnings_rows = client.get_earnings_calendar(trade_dates[0], trade_dates[-1])
    except Exception as exc:
        logger.warning("Research event flag fetch failed; leaving earnings flags missing: %s", exc)
        return _empty_research_event_flags(scope, missing=True), {
            "enabled": False,
            "source": "fmp_earnings_calendar",
            "status": "fetch_failed",
            "error": str(exc),
        }

    aggregated: dict[tuple[date, str], dict[str, bool]] = {}
    for item in earnings_rows:
        trade_day = _parse_calendar_trade_date(item.get("date"))
        symbol = str(item.get("symbol") or "").strip().upper()
        if trade_day is None or not symbol:
            continue
        key = (trade_day, symbol)
        entry = aggregated.setdefault(
            key,
            {
                "is_earnings_day": True,
                "earnings_timing_pre_open": False,
                "earnings_timing_post_close": False,
            },
        )
        raw_timing = item.get("time") or item.get("releaseTime")
        entry["earnings_timing_pre_open"] = bool(entry["earnings_timing_pre_open"] or _timing_is_pre_open(raw_timing))
        entry["earnings_timing_post_close"] = bool(entry["earnings_timing_post_close"] or _timing_is_post_close(raw_timing))

    if not aggregated:
        return _empty_research_event_flags(scope, missing=False), {
            "enabled": True,
            "source": "fmp_earnings_calendar",
            "status": "ok_empty_calendar",
            "fetched_rows": 0,
        }

    event_frame = pd.DataFrame(
        [
            {
                "trade_date": trade_day,
                "symbol": symbol,
                **values,
            }
            for (trade_day, symbol), values in aggregated.items()
        ]
    )
    event_frame["trade_date"] = pd.to_datetime(event_frame["trade_date"], errors="coerce").dt.date
    event_frame["symbol"] = event_frame["symbol"].astype(str).str.upper()
    for column in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        event_frame[column] = pd.Series(event_frame[column], dtype="boolean")

    merged = scope.merge(event_frame, on=["trade_date", "symbol"], how="left")
    for column in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        merged[column] = pd.Series(merged[column], dtype="boolean").fillna(False)
    return merged[RESEARCH_EVENT_FLAG_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True), {
        "enabled": True,
        "source": "fmp_earnings_calendar",
        "status": "ok",
        "fetched_rows": int(len(earnings_rows)),
        "matched_symbol_days": int(len(event_frame)),
    }


def _build_research_event_flag_coverage(flags_frame: pd.DataFrame) -> pd.DataFrame:
    if flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_EVENT_FLAG_COVERAGE_COLUMNS)
    rows: list[dict[str, Any]] = []
    total_rows = int(len(flags_frame))
    for flag_name in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        series = pd.Series(flags_frame[flag_name], dtype="boolean")
        non_null_rows = int(series.notna().sum())
        true_rows = int(series.fillna(False).sum())
        rows.append(
            {
                "flag_name": flag_name,
                "symbol_day_rows": total_rows,
                "non_null_rows": non_null_rows,
                "null_rows": total_rows - non_null_rows,
                "non_null_rate": float(non_null_rows / total_rows) if total_rows else 0.0,
                "true_rows": true_rows,
                "true_rate": float(true_rows / non_null_rows) if non_null_rows else 0.0,
                "affected_trade_dates": int(flags_frame.loc[series.fillna(False), "trade_date"].nunique()),
                "all_false_bug": bool(non_null_rows > 0 and true_rows == 0),
                "all_true_bug": bool(non_null_rows > 0 and true_rows == non_null_rows),
            }
        )
    return pd.DataFrame(rows, columns=RESEARCH_EVENT_FLAG_COVERAGE_COLUMNS)


def _build_research_event_flag_trade_date_distribution(flags_frame: pd.DataFrame) -> pd.DataFrame:
    if flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_EVENT_FLAG_TRADE_DATE_COLUMNS)
    rows: list[dict[str, Any]] = []
    total_by_date = flags_frame.groupby("trade_date")["symbol"].size().to_dict()
    for flag_name in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        series = pd.Series(flags_frame[flag_name], dtype="boolean").fillna(False)
        grouped = (
            flags_frame.assign(_flag_value=series)
            .groupby("trade_date", sort=True)["_flag_value"]
            .sum()
            .to_dict()
        )
        for trade_day, symbol_day_rows in total_by_date.items():
            true_rows = int(grouped.get(trade_day, 0))
            rows.append(
                {
                    "trade_date": trade_day,
                    "flag_name": flag_name,
                    "symbol_day_rows": int(symbol_day_rows),
                    "true_rows": true_rows,
                    "true_rate": float(true_rows / symbol_day_rows) if symbol_day_rows else 0.0,
                }
            )
    return pd.DataFrame(rows, columns=RESEARCH_EVENT_FLAG_TRADE_DATE_COLUMNS).sort_values(["trade_date", "flag_name"]).reset_index(drop=True)


def _build_research_event_flag_outcome_slices(daily_features: pd.DataFrame, flags_frame: pd.DataFrame) -> pd.DataFrame:
    if daily_features.empty or flags_frame.empty:
        return pd.DataFrame(columns=RESEARCH_EVENT_FLAG_OUTCOME_SLICE_COLUMNS)
    merged = daily_features.merge(flags_frame, on=["trade_date", "symbol"], how="left")
    for flag_name in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        merged = _coalesce_optional_merge_column(merged, flag_name)
    rows: list[dict[str, Any]] = []
    metric_columns = {
        "mean_window_range_pct": "window_range_pct",
        "mean_realized_vol_pct": "realized_vol_pct",
        "mean_close_trade_hygiene_score": "close_trade_hygiene_score",
        "mean_close_last_1m_volume_share": "close_last_1m_volume_share",
        "mean_close_to_next_open_return_pct": "close_to_next_open_return_pct",
    }
    for flag_name in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        merged[flag_name] = pd.Series(merged[flag_name], dtype="boolean")
        for selected in (False, True):
            selected_slice = merged[merged["selected_top20pct"].astype(bool) == selected]
            for flag_value in (False, True):
                cohort = selected_slice[pd.Series(selected_slice[flag_name], dtype="boolean").fillna(False) == flag_value]
                row: dict[str, Any] = {
                    "flag_name": flag_name,
                    "selected_top20pct": bool(selected),
                    "flag_value": bool(flag_value),
                    "row_count": int(len(cohort)),
                }
                for output_name, source_name in metric_columns.items():
                    numeric = pd.to_numeric(cohort.get(source_name, pd.Series(dtype=float)), errors="coerce")
                    row[output_name] = float(numeric.mean()) if not numeric.dropna().empty else 0.0
                rows.append(row)
    return pd.DataFrame(rows, columns=RESEARCH_EVENT_FLAG_OUTCOME_SLICE_COLUMNS)


def _filter_ranked_symbol_day_scope(frame: pd.DataFrame, ranked_scope: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or ranked_scope.empty:
        return frame.iloc[0:0].copy()
    scoped = frame.copy()
    scoped["trade_date"] = pd.to_datetime(scoped["trade_date"], errors="coerce").dt.date
    scoped["symbol"] = scoped["symbol"].astype(str).str.upper()
    return scoped.merge(ranked_scope, on=["trade_date", "symbol"], how="inner").reset_index(drop=True)


def _write_canonical_production_workbook(
    *,
    export_dir: Path,
    summary: pd.DataFrame,
    minute_detail: pd.DataFrame,
    second_detail: pd.DataFrame,
    manifest: dict[str, Any],
    raw_universe: pd.DataFrame,
    daily_bars: pd.DataFrame,
    intraday: pd.DataFrame,
    ranked: pd.DataFrame,
    daily_symbol_features_full_universe: pd.DataFrame,
    full_universe_second_detail_open: pd.DataFrame,
    full_universe_second_detail_close: pd.DataFrame,
    full_universe_close_trade_detail: pd.DataFrame,
    full_universe_close_outcome_minute: pd.DataFrame,
    close_imbalance_features_full_universe: pd.DataFrame,
    close_imbalance_outcomes_full_universe: pd.DataFrame,
    premarket_features_full_universe: pd.DataFrame,
    premarket_window_features_full_universe: pd.DataFrame,
    symbol_day_diagnostics: pd.DataFrame,
    research_event_flags_full_universe: pd.DataFrame,
    research_event_flag_coverage: pd.DataFrame,
    research_event_flag_trade_date_distribution: pd.DataFrame,
    research_event_flag_outcome_slices: pd.DataFrame,
    research_news_flags_full_universe: pd.DataFrame,
    research_news_flag_coverage: pd.DataFrame,
    research_news_flag_trade_date_distribution: pd.DataFrame,
    research_news_flag_outcome_slices: pd.DataFrame,
    core_vs_benzinga_news_side_by_side: pd.DataFrame,
    core_vs_benzinga_news_overlap_stats: pd.DataFrame,
    quality_window_status: pd.DataFrame,
    batl_debug: dict[str, Any],
    output_summary: dict[str, Any],
) -> Path:
    canonical_workbook = canonical_production_workbook_path(export_dir=export_dir)
    workbook_result = write_databento_production_workbook_from_frames(
        summary=summary,
        output_path=canonical_workbook,
        minute_detail=minute_detail,
        second_detail=second_detail,
        additional_sheets={
            "manifest": build_run_manifest_frame(manifest),
            "universe": raw_universe,
            "daily_bars": daily_bars,
            "intraday_all": intraday,
            "ranked": ranked,
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "full_universe_second_detail_close": full_universe_second_detail_close,
            "full_universe_close_trade_detail": full_universe_close_trade_detail,
            "full_universe_close_outcome_minute": full_universe_close_outcome_minute,
            "close_imbalance_features_full_universe": close_imbalance_features_full_universe,
            "close_imbalance_outcomes_full_universe": close_imbalance_outcomes_full_universe,
            "premarket_features_full_universe": premarket_features_full_universe,
            "premarket_window_features_full_universe": premarket_window_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
            "research_event_flags_full_universe": research_event_flags_full_universe,
            "research_event_flag_coverage": research_event_flag_coverage,
            "research_event_flag_trade_date_distribution": research_event_flag_trade_date_distribution,
            "research_event_flag_outcome_slices": research_event_flag_outcome_slices,
            "research_news_flags_full_universe": research_news_flags_full_universe,
            "research_news_flag_coverage": research_news_flag_coverage,
            "research_news_flag_trade_date_distribution": research_news_flag_trade_date_distribution,
            "research_news_flag_outcome_slices": research_news_flag_outcome_slices,
            "core_vs_benzinga_news_side_by_side": core_vs_benzinga_news_side_by_side,
            "core_vs_benzinga_news_overlap_stats": core_vs_benzinga_news_overlap_stats,
            "quality_window_status_latest": quality_window_status,
            "batl_debug": pd.DataFrame([batl_debug]),
            "output_checks": pd.DataFrame([output_summary]),
        },
    )
    return workbook_result.output_path


def run_production_export_pipeline(
    *,
    databento_api_key: str,
    fmp_api_key: str = "",
    benzinga_api_key: str = "",
    dataset: str,
    quality_window_early_exchange_datasets: dict[str, str] | None = None,
    lookback_days: int = 30,
    top_fraction: float = 0.20,
    ranking_metric: str = "window_range_pct",
    display_timezone: str = "Europe/Berlin",
    window_start: time | None = None,
    window_end: time | None = None,
    premarket_anchor_et: time = time(4, 0),
    min_market_cap: float = 0.0,
    cache_dir: Path | None = None,
    export_dir: Path | None = None,
    use_file_cache: bool = True,
    force_refresh: bool = False,
    second_detail_scope: str = "full_universe",
    bullish_score_profile: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE,
    skip_cost_estimate: bool | None = None,
    smc_base_only: bool = False,
    progress_callback: Any = None,
) -> dict[str, Any]:
    if not databento_api_key:
        raise ValueError("Databento API key is required.")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must be between 0 and 1")
    if second_detail_scope not in {"full_universe", "ranked_only", "none"}:
        raise ValueError("second_detail_scope must be one of: full_universe, ranked_only, none")
    resolved_bullish_cfg = build_default_bullish_quality_config(score_profile=bullish_score_profile)
    resolved_skip_cost_estimate = True if skip_cost_estimate is None else bool(skip_cost_estimate)

    def _progress(msg: str) -> None:
        logger.info(msg)
        if progress_callback is not None:
            progress_callback(msg)

    resolved_cache_dir = cache_dir or (REPO_ROOT / "artifacts" / "databento_volatility_cache")
    resolved_export_dir = export_dir or default_export_directory()

    _progress("Step 1/10: Listing recent trading days...")
    trading_days = list_recent_trading_days(databento_api_key, dataset=dataset, lookback_days=lookback_days)
    if resolved_skip_cost_estimate:
        _progress("Step 2/10: Skipping cost estimate (default operational mode)...")
        cost_estimate = pd.DataFrame(columns=["scope", "cost_usd", "billable_size_bytes"])
    else:
        _progress(f"Step 2/10: Estimating costs ({len(trading_days)} trading days)...")
        cost_estimate = estimate_databento_costs(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            display_timezone=display_timezone,
            window_start=window_start,
            window_end=window_end,
            premarket_anchor_et=premarket_anchor_et,
        )

    _progress("Step 3/10: Fetching equity universe...")
    raw_universe, universe_metadata = fetch_us_equity_universe_with_metadata(
        fmp_api_key,
        min_market_cap=min_market_cap or None,
    )
    if fmp_api_key:
        raw_universe = _enrich_universe_with_fundamentals(
            raw_universe,
            _load_fundamental_reference(
                fmp_api_key,
                cache_dir=resolved_cache_dir,
                use_file_cache=use_file_cache,
                force_refresh=force_refresh,
            ),
        )
    else:
        raw_universe = _enrich_universe_with_fundamentals(raw_universe, pd.DataFrame())
    _progress("Step 4/10: Filtering supported universe...")
    supported_universe, unsupported = filter_supported_universe_for_databento(
        databento_api_key,
        dataset=dataset,
        universe=raw_universe,
        cache_dir=resolved_cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    universe_symbols = set(supported_universe["symbol"].dropna().astype(str).str.upper())

    _progress(f"Step 5/10: Loading daily bars ({len(universe_symbols)} symbols, {len(trading_days)} days)...")
    daily_bars = load_daily_bars(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        cache_dir=resolved_cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    daily_bars_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    if smc_base_only:
        _progress(f"Step 6/10: Running intraday screens ({len(trading_days)} days, SMC base-only mode without fixed 10:00 ET outcome snapshot)...")
    else:
        _progress(f"Step 6/10: Running intraday screens ({len(trading_days)} days, including fixed 10:00 ET outcome snapshot)...")
    intraday = run_intraday_screen(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        daily_bars=daily_bars,
        display_timezone=display_timezone,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor_et,
        cache_dir=resolved_cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    intraday_close_outcome_anchor = pd.DataFrame()
    if not smc_base_only:
        intraday_close_outcome_anchor = _run_fixed_et_intraday_screen(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            universe_symbols=universe_symbols,
            daily_bars=daily_bars,
            window_start=time(9, 30),
            window_end=DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET,
            premarket_anchor_et=time(9, 30),
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
    if not intraday_close_outcome_anchor.empty:
        exact_1000_lookup = _build_exact_window_end_lookup(
            intraday_close_outcome_anchor,
            display_timezone=FIXED_ET_DISPLAY_TIMEZONE,
        )
        intraday = intraday.copy()
        intraday["trade_date"] = pd.to_datetime(intraday["trade_date"], errors="coerce").dt.date
        intraday["symbol"] = intraday["symbol"].astype(str).str.upper()
        intraday = intraday.merge(exact_1000_lookup, on=["trade_date", "symbol"], how="left")
    intraday_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    _progress("Step 7/10: Ranking top fraction per day...")
    ranked = rank_top_fraction_per_day(intraday, ranking_metric=ranking_metric, top_fraction=top_fraction)
    if ranked.empty:
        raise RuntimeError("No ranked results were returned for the production export run")

    ranked_scope = ranked[["trade_date", "symbol"]].drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)

    if second_detail_scope == "none":
        full_universe_second_detail_raw = pd.DataFrame()
        full_universe_close_detail_raw = pd.DataFrame()
        full_universe_close_trade_detail_raw = pd.DataFrame()
        full_universe_close_outcome_minute_raw = pd.DataFrame()
        quality_window_second_detail = pd.DataFrame()
        premarket_source_detail = pd.DataFrame()
        quality_window_source_metadata = {
            "base_dataset": str(dataset).strip().upper(),
            "early_exchange_datasets": _normalize_quality_window_exchange_dataset_map(quality_window_early_exchange_datasets or QUALITY_OPEN_DRIVE_EARLY_EXCHANGE_DATASETS),
            "applied_early_exchange_datasets": {},
            "early_exchange_symbol_counts": {},
            "quality_window_detail_rows": 0,
            "premarket_detail_rows": 0,
        }
    else:
        if smc_base_only:
            _progress(
                f"Step 8/10: Collecting full-universe symbol-day detail for SMC feature derivation "
                f"(open-window, close-window, close-trade metadata; {second_detail_scope})..."
            )
        else:
            _progress(
                f"Step 8/10: Collecting research/export detail "
                f"(open-window, close-window, close-trade metadata; {second_detail_scope})..."
            )
        full_universe_second_detail_raw = collect_full_universe_open_window_second_detail(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            universe_symbols=universe_symbols,
            daily_bars=daily_bars,
            symbol_day_scope=ranked_scope if second_detail_scope == "ranked_only" else None,
            display_timezone=display_timezone,
            window_start=window_start,
            window_end=window_end,
            premarket_anchor_et=premarket_anchor_et,
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
        full_universe_close_detail_raw = _collect_fixed_et_second_detail(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            universe_symbols=universe_symbols,
            daily_bars=daily_bars,
            symbol_day_scope=ranked_scope if second_detail_scope == "ranked_only" else None,
            window_start=DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET,
            window_end=DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET,
            premarket_anchor_et=DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET,
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
        full_universe_close_trade_detail_raw = collect_full_universe_close_trade_detail(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            universe_symbols=universe_symbols,
            symbol_day_scope=ranked_scope if second_detail_scope == "ranked_only" else None,
            display_timezone=display_timezone,
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
        full_universe_close_outcome_minute_raw = collect_full_universe_close_outcome_minute_detail(
            databento_api_key,
            dataset=dataset,
            trading_days=trading_days,
            universe_symbols=universe_symbols,
            symbol_day_scope=ranked_scope if second_detail_scope == "ranked_only" else None,
            display_timezone=display_timezone,
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
        )
        quality_window_second_detail, premarket_source_detail, quality_window_source_metadata = _collect_quality_window_source_frames(
            databento_api_key=databento_api_key,
            base_dataset=dataset,
            trading_days=trading_days,
            raw_universe=raw_universe,
            supported_universe=supported_universe,
            daily_bars=daily_bars,
            symbol_day_scope=ranked_scope if second_detail_scope == "ranked_only" else None,
            display_timezone=display_timezone,
            window_start=window_start,
            window_end=window_end,
            premarket_anchor_et=premarket_anchor_et,
            cache_dir=resolved_cache_dir,
            use_file_cache=use_file_cache,
            force_refresh=force_refresh,
            early_exchange_datasets=quality_window_early_exchange_datasets or QUALITY_OPEN_DRIVE_EARLY_EXCHANGE_DATASETS,
        )
    _progress("Step 9/10: Building features and exports...")
    daily_symbol_features_full_universe, symbol_day_diagnostics = _build_daily_symbol_features_full_universe_export(
        trading_days=trading_days,
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=full_universe_second_detail_raw,
        close_detail_all=full_universe_close_detail_raw,
        close_trade_detail_all=full_universe_close_trade_detail_raw,
        close_outcome_minute_detail_all=full_universe_close_outcome_minute_raw,
        display_timezone=display_timezone,
        premarket_anchor_et=premarket_anchor_et,
        ranking_metric=ranking_metric,
        top_fraction=top_fraction,
        smc_base_only=smc_base_only,
    )
    research_event_flags_full_universe, research_event_flag_metadata = _build_research_event_flags_full_universe_export(
        daily_features=daily_symbol_features_full_universe,
        fmp_api_key=fmp_api_key,
    )
    research_news_flags_full_universe, research_news_flag_metadata = _build_research_news_flags_full_universe_export(
        daily_features=daily_symbol_features_full_universe,
        benzinga_api_key=benzinga_api_key,
    )
    daily_symbol_features_full_universe = daily_symbol_features_full_universe.merge(
        research_event_flags_full_universe,
        on=["trade_date", "symbol"],
        how="left",
    )
    for column in RESEARCH_EVENT_FLAG_COLUMNS[2:]:
        daily_symbol_features_full_universe = _coalesce_optional_merge_column(daily_symbol_features_full_universe, column)
        daily_symbol_features_full_universe[column] = pd.Series(daily_symbol_features_full_universe[column], dtype="boolean")
    daily_symbol_features_full_universe = daily_symbol_features_full_universe.merge(
        research_news_flags_full_universe,
        on=["trade_date", "symbol"],
        how="left",
    )
    for column in RESEARCH_NEWS_FLAG_BOOLEAN_COLUMNS:
        daily_symbol_features_full_universe = _coalesce_optional_merge_column(daily_symbol_features_full_universe, column)
        daily_symbol_features_full_universe[column] = pd.Series(daily_symbol_features_full_universe[column], dtype="boolean")
    for column in RESEARCH_NEWS_FLAG_COUNT_COLUMNS:
        daily_symbol_features_full_universe = _coalesce_optional_merge_column(daily_symbol_features_full_universe, column)
        daily_symbol_features_full_universe[column] = pd.Series(daily_symbol_features_full_universe[column], dtype="Int64")
    research_event_flag_coverage = _build_research_event_flag_coverage(research_event_flags_full_universe)
    research_event_flag_trade_date_distribution = _build_research_event_flag_trade_date_distribution(research_event_flags_full_universe)
    research_event_flag_outcome_slices = _build_research_event_flag_outcome_slices(
        daily_symbol_features_full_universe,
        research_event_flags_full_universe,
    )
    research_news_flag_coverage = _build_research_news_flag_coverage(research_news_flags_full_universe)
    research_news_flag_trade_date_distribution = _build_research_news_flag_trade_date_distribution(research_news_flags_full_universe)
    research_news_flag_outcome_slices = _build_research_news_flag_outcome_slices(
        daily_symbol_features_full_universe,
        research_news_flags_full_universe,
    )
    core_vs_benzinga_news_side_by_side, core_vs_benzinga_news_overlap_stats, core_vs_benzinga_news_metadata = _build_core_vs_benzinga_news_side_by_side(
        daily_features=daily_symbol_features_full_universe,
        research_news_flags=research_news_flags_full_universe,
        fmp_api_key=fmp_api_key,
    )
    full_universe_second_detail_open = _prepare_full_universe_second_detail_export(
        full_universe_second_detail_raw,
        daily_symbol_features_full_universe,
    )
    full_universe_second_detail_close = _prepare_full_universe_second_detail_export(
        full_universe_close_detail_raw,
        daily_symbol_features_full_universe,
    )
    full_universe_close_trade_detail = full_universe_close_trade_detail_raw.copy()
    if not full_universe_close_trade_detail.empty:
        full_universe_close_trade_detail["trade_date"] = pd.to_datetime(full_universe_close_trade_detail["trade_date"], errors="coerce").dt.date
        full_universe_close_trade_detail["symbol"] = full_universe_close_trade_detail["symbol"].astype(str).str.upper()
        full_universe_close_trade_detail["timestamp"] = pd.to_datetime(full_universe_close_trade_detail["timestamp"], errors="coerce", utc=True)
        full_universe_close_trade_detail = full_universe_close_trade_detail.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
    full_universe_close_outcome_minute = full_universe_close_outcome_minute_raw.copy()
    if not full_universe_close_outcome_minute.empty:
        full_universe_close_outcome_minute["trade_date"] = pd.to_datetime(full_universe_close_outcome_minute["trade_date"], errors="coerce").dt.date
        full_universe_close_outcome_minute["symbol"] = full_universe_close_outcome_minute["symbol"].astype(str).str.upper()
        full_universe_close_outcome_minute["timestamp"] = pd.to_datetime(full_universe_close_outcome_minute["timestamp"], errors="coerce", utc=True)
        full_universe_close_outcome_minute = full_universe_close_outcome_minute.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
    quality_window_second_detail_prepared = _prepare_full_universe_second_detail_export(
        quality_window_second_detail,
        daily_symbol_features_full_universe,
    )
    premarket_source_detail_prepared = _prepare_full_universe_second_detail_export(
        premarket_source_detail,
        daily_symbol_features_full_universe,
    )
    second_detail_fetched_at = _resolve_latest_iso_timestamp(
        full_universe_second_detail_open,
        candidates=("timestamp", "ts", "source_data_fetched_at", "fetched_at"),
    )
    premarket_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    source_data_fetched_at = _resolve_latest_iso_timestamp(
        premarket_source_detail_prepared,
        candidates=("timestamp", "ts", "source_data_fetched_at", "fetched_at"),
    )
    premarket_features_full_universe = _build_premarket_features_full_universe_export(
        premarket_source_detail_prepared,
        daily_symbol_features_full_universe,
    )
    premarket_window_features_full_universe = build_premarket_window_features_full_universe_export(
        premarket_source_detail_prepared,
        daily_symbol_features_full_universe,
        window_definitions=resolved_bullish_cfg.window_definitions,
        source_data_fetched_at=source_data_fetched_at,
        dataset=dataset,
        cfg=resolved_bullish_cfg,
    )
    close_imbalance_features_full_universe = _build_close_imbalance_features_full_universe_export(
        daily_symbol_features_full_universe,
    )
    close_imbalance_outcomes_full_universe = _build_close_imbalance_outcomes_full_universe_export(
        daily_symbol_features_full_universe,
    )

    latest_trade_date = pd.to_datetime(daily_symbol_features_full_universe.get("trade_date"), errors="coerce").dt.date.dropna().max()
    quality_window_status = _build_quality_window_status_latest(
        premarket_window_features_full_universe,
        display_timezone=display_timezone,
    )

    raw_universe = _enrich_universe_with_quality_window_status_from_window_features(
        raw_universe,
        premarket_window_features_full_universe,
        display_timezone=display_timezone,
    )
    summary = build_summary_table(ranked, raw_universe)
    if summary.empty:
        raise RuntimeError("No ranked results were returned for the production export run")

    selected_row = summary.iloc[0]
    selected_trade_date = pd.Timestamp(selected_row["trade_date"]).date()
    selected_symbol = str(selected_row["symbol"])
    selected_previous_close = pd.to_numeric(pd.Series([selected_row.get("previous_close")]), errors="coerce").iloc[0]
    second_detail, minute_detail = fetch_symbol_day_detail(
        databento_api_key,
        dataset=dataset,
        symbol=selected_symbol,
        trade_date=selected_trade_date,
        display_timezone=display_timezone,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor_et,
        previous_close=float(selected_previous_close) if pd.notna(selected_previous_close) else None,
        cache_dir=resolved_cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    minute_detail_all = pd.DataFrame()
    second_detail_all = pd.DataFrame()
    selected_trade_date_str = pd.Timestamp(selected_trade_date).strftime("%Y-%m-%d")
    batl_debug = _build_batl_debug_payload(daily_symbol_features_full_universe, symbol_day_diagnostics)

    output_summary = {
        "full_universe_symbol_count": int(raw_universe["symbol"].astype(str).str.upper().nunique()),
        "trade_date_count": int(pd.Series(trading_days).nunique()),
        "daily_symbol_feature_rows": int(len(daily_symbol_features_full_universe)),
        "eligible_symbol_day_rows": int(daily_symbol_features_full_universe["is_eligible"].sum()),
        "selected_top20pct_symbol_day_rows": int(daily_symbol_features_full_universe["selected_top20pct"].sum()),
        "full_universe_second_detail_open_rows": int(len(full_universe_second_detail_open)),
        "full_universe_second_detail_close_rows": int(len(full_universe_second_detail_close)),
        "full_universe_close_trade_detail_rows": int(len(full_universe_close_trade_detail)),
        "full_universe_close_outcome_minute_rows": int(len(full_universe_close_outcome_minute)),
        "premarket_symbol_day_rows": int(premarket_features_full_universe["has_premarket_data"].sum()),
        "premarket_window_feature_rows": int(len(premarket_window_features_full_universe)),
        "close_imbalance_symbol_day_rows": int(close_imbalance_features_full_universe["has_close_window_detail"].sum()) if not close_imbalance_features_full_universe.empty else 0,
        "close_imbalance_outcome_rows": int(len(close_imbalance_outcomes_full_universe)),
        "research_event_flag_rows": int(len(research_event_flags_full_universe)),
        "research_news_flag_rows": int(len(research_news_flags_full_universe)),
        "core_vs_benzinga_news_side_by_side_rows": int(len(core_vs_benzinga_news_side_by_side)),
        "core_vs_benzinga_news_overlap_stats_rows": int(len(core_vs_benzinga_news_overlap_stats)),
        "batl": batl_debug,
    }

    _progress("Step 10/10: Writing export artifacts...")
    export_generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    basename = build_export_basename(prefix="databento_volatility_production")
    manifest = {
        "dataset": dataset,
        "universe_source": universe_metadata.get("source"),
        "universe_source_fallback": universe_metadata.get("fallback_source"),
        "universe_scope_definition": universe_metadata.get("scope_definition"),
        "universe_selection_reason": universe_metadata.get("selection_reason"),
        "universe_min_market_cap_requested": universe_metadata.get("min_market_cap_requested"),
        "universe_min_market_cap_effective": universe_metadata.get("min_market_cap_effective"),
        "universe_min_market_cap_applied": universe_metadata.get("min_market_cap_applied"),
        "lookback_days": lookback_days,
        "top_fraction": top_fraction,
        "ranking_metric": ranking_metric,
        "display_timezone": display_timezone,
        "window_start": _format_optional_time(window_start),
        "window_end": _format_optional_time(window_end),
        "premarket_anchor_et": premarket_anchor_et.strftime("%H:%M:%S"),
        "daily_bars_fetched_at": daily_bars_fetched_at,
        "intraday_fetched_at": intraday_fetched_at,
        "second_detail_fetched_at": second_detail_fetched_at,
        "close_second_detail_fetched_at": _resolve_latest_iso_timestamp(
            full_universe_second_detail_close,
            candidates=("timestamp", "ts", "source_data_fetched_at", "fetched_at"),
        ),
        "close_trade_detail_fetched_at": _resolve_latest_iso_timestamp(
            full_universe_close_trade_detail,
            candidates=("timestamp", "ts_recv", "ts_event"),
        ),
        "close_outcome_minute_fetched_at": _resolve_latest_iso_timestamp(
            full_universe_close_outcome_minute,
            candidates=("timestamp",),
        ),
        "premarket_fetched_at": premarket_fetched_at,
        "source_data_fetched_at": source_data_fetched_at,
        "source_data_fetched_at_semantics": "Latest source-data event timestamp (UTC) observed in premarket source detail used to build window features; null when no source rows were available.",
        "export_generated_at": export_generated_at,
        "trade_dates_covered": [trade_day.isoformat() for trade_day in trading_days],
        "detail_scope": {"none": "no_second_detail", "ranked_only": "ranked_symbol_day_only", "full_universe": "full_supported_universe_symbol_days"}[second_detail_scope],
        "second_detail_scope": second_detail_scope,
        "selected_symbol_detail_scope": "selected_top_ranked_symbol_day_only",
        "internal_timezone": display_timezone,
        "session_documentation": f"second_detail export spans from the configured premarket anchor ({premarket_anchor_et.strftime('%H:%M:%S')} ET) through the configured open-window local end in {display_timezone}; session is labeled as premarket before 09:30 ET and regular from 09:30 ET onward",
        "second_delta_pct_formula": "((close_t / close_t_minus_1) - 1) * 100 within each symbol-day open-window second series",
        "window_range_pct_formula": "((window_high - window_low) / window_start_price) * 100",
        "window_return_pct_formula": "((window_end_price / window_start_price) - 1) * 100",
        "rank_within_trade_date_rule": "rank eligible symbol-days within each trade_date by window_range_pct descending, ties by symbol ascending",
        "take_n_for_trade_date_rule": f"ceil(eligible_count_for_trade_date * {top_fraction:.2f})",
        "selected_top20pct_rule": "rank_within_trade_date <= take_n_for_trade_date for eligible symbol-days",
        "selected_top20pct_0400_enabled": not smc_base_only,
        "fixed_1000_et_outcome_snapshot_enabled": not smc_base_only,
        "prev_close_to_premarket_pct_formula": "((premarket_last / previous_close) - 1) * 100, where premarket_last is the last premarket 1s close before the regular open",
        "premarket_to_open_pct_formula": "((market_open_price / premarket_last) - 1) * 100",
        "premarket_last_rule": "last 1-second close in the premarket session before 09:30 ET",
        "premarket_vwap_rule": "sum(close * volume) / sum(volume) across premarket 1-second bars",
        "has_premarket_data_rule": "True when at least one premarket 1-second bar exists and premarket_last is not null",
        "premarket_price_anchor_rule": f"last_ohlcv_1s_close in [{premarket_anchor_et.strftime('%H:%M:%S')} ET, regular_open) for the trade date",
        "quality_window_source_base_dataset": quality_window_source_metadata["base_dataset"],
        "quality_window_source_early_exchange_datasets": quality_window_source_metadata["early_exchange_datasets"],
        "quality_window_source_applied_early_exchange_datasets": quality_window_source_metadata["applied_early_exchange_datasets"],
        "quality_window_source_early_exchange_symbol_counts": quality_window_source_metadata["early_exchange_symbol_counts"],
        "quality_window_source_strategy": "Use exchange-specific early/premarket sources where configured with row-level fallback to the base dataset for missing timestamps, use the base dataset for the late 09:00-09:30 ET window, and derive open-confirm from the same merged early-path source.",
        "quality_open_drive_window_trade_date_rule": "latest trade_date covered by daily_symbol_features_full_universe",
        "quality_open_drive_window_coverage_latest_berlin_rule": "categorical latest-trade-date data-presence status derived from canonical premarket_window_features_full_universe rows across bullish_quality_window_tags, rendered as display_timezone-local window labels joined by '+', or none",
        "quality_open_drive_window_latest_berlin_rule": "categorical latest-trade-date bullish-quality status derived from the best-scoring passing canonical window row on the latest trade date, ties broken by later configured window order, rendered as a display_timezone-local window label, or none",
        "quality_open_drive_window_score_latest_berlin_rule": "latest-trade-date best canonical window_quality_score from premarket_window_features_full_universe across bullish_quality_window_tags for each symbol, ties broken by later configured window order",
        "quality_open_drive_window_base_filters": {
            "min_previous_close": resolved_bullish_cfg.min_previous_close,
            "min_gap_pct": resolved_bullish_cfg.min_gap_pct,
            "min_window_dollar_volume": resolved_bullish_cfg.min_window_dollar_volume,
            "min_window_trade_count": resolved_bullish_cfg.min_window_trade_count,
        },
        "quality_open_drive_window_latest_berlin_criteria": {
            "min_window_close_position_pct": resolved_bullish_cfg.min_window_close_position_pct,
            "min_window_return_pct": resolved_bullish_cfg.min_window_return_pct,
            "max_window_pullback_pct": resolved_bullish_cfg.max_window_pullback_pct,
            "require_close_above_vwap": resolved_bullish_cfg.require_close_above_vwap,
            "top_n_per_trade_date_window": resolved_bullish_cfg.top_n,
        },
        "quality_open_drive_window_score_profile": resolved_bullish_cfg.score_profile,
        "quality_open_drive_window_score_weights": resolved_bullish_cfg.weights,
        "quality_window_candidate_exports": "not_applicable_in_current_pipeline",
        "bullish_quality_window_tags": [definition.tag for definition in resolved_bullish_cfg.window_definitions],
        "bullish_quality_status_source": "premarket_window_features_full_universe_latest_trade_date",
        "open_1m_volume_boundary": "[regular_open, regular_open + 1 minute)",
        "open_5m_volume_boundary": "[regular_open, regular_open + 5 minutes)",
        "full_universe_open_detail_window": f"[{_format_optional_time(window_start)}, {_format_optional_time(window_end)}] {display_timezone}",
        "close_imbalance_mode": "v1_close_window_features",
        "close_imbalance_window_et": f"[{DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET.strftime('%H:%M:%S')}, {DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET.strftime('%H:%M:%S')}) ET",
        "close_imbalance_auction_time_et": DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET.strftime("%H:%M:%S"),
        "close_10m_volume_rule": "sum(volume) across 1-second bars in [15:50:00, 16:00:00) ET",
        "close_last_1m_volume_rule": "sum(volume) across 1-second bars in [15:59:00, 16:00:00) ET",
        "close_postclose_5m_volume_rule": "sum(volume) across 1-second bars in [16:00:00, 16:05:00) ET",
        "close_auction_reference_price_rule": "last 1-second close observed before 16:00:00 ET within the close-imbalance window",
        "close_preclose_return_pct_formula": "((close_auction_reference_price / close_reference_price) - 1) * 100",
        "close_postclose_return_pct_formula": "((last_postclose_close / close_auction_reference_price) - 1) * 100",
        "close_last_1m_volume_share_formula": "close_last_1m_volume / close_10m_volume",
        "close_postclose_volume_share_formula": "close_postclose_5m_volume / (close_10m_volume + close_postclose_5m_volume)",
        "full_universe_close_detail_window": f"[{DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET.strftime('%H:%M:%S')}, {DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET.strftime('%H:%M:%S')}) ET",
        "full_universe_close_trade_detail_window": f"[{DEFAULT_CLOSE_IMBALANCE_WINDOW_START_ET.strftime('%H:%M:%S')}, {DEFAULT_CLOSE_IMBALANCE_WINDOW_END_ET.strftime('%H:%M:%S')}) ET trades schema",
        "full_universe_close_outcome_window": f"[{DEFAULT_CLOSE_IMBALANCE_AUCTION_TIME_ET.strftime('%H:%M:%S')}, {DEFAULT_CLOSE_IMBALANCE_AFTERHOURS_END_ET.strftime('%H:%M:%S')}) ET ohlcv-1m",
        "close_trade_hygiene_rule": "clean prints exclude rows with F_BAD_TS_RECV or F_MAYBE_BAD_BOOK and require positive size and price",
        "close_trade_venue_rule": "publisher descriptions containing 'TRF' are classified as off_exchange_trf; all other mapped publishers are treated as lit_exchange",
        "close_trade_lit_followthrough_rule": "True when at least one lit_exchange trade occurs in the final pre-close minute at or after the first off_exchange_trf trade in that minute",
        "close_to_2000_return_pct_formula": "((close_last_price_2000 / close_auction_reference_price) - 1) * 100",
        "close_to_next_open_return_pct_formula": "((next_day_open_price / close_auction_reference_price) - 1) * 100",
        "next_open_to_window_end_return_pct_formula": "((next_day_window_end_price / next_day_open_price) - 1) * 100",
        "close_to_next_window_end_return_pct_formula": "((next_day_window_end_price / close_auction_reference_price) - 1) * 100",
        "next_day_window_end_semantics": (
            f"Derived from a dedicated next-trade-date intraday snapshot with fixed window_end={DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET.strftime('%H:%M:%S')} ET; exact_1000_price is only populated when the 1-second intraday summary contains a bar exactly at that boundary, and next_day_window_end_price prefers that exact label before falling back row-wise to the latest in-window current_price"
            if not smc_base_only
            else "SMC base-only mode disabled the dedicated fixed 10:00 ET outcome snapshot; exact_1000_price remains unpopulated and any next-day outcome fields depend only on other exported outcome sources."
        ),
        "next_day_window_end_time_et": DEFAULT_CLOSE_IMBALANCE_NEXT_DAY_OUTCOME_TIME_ET.strftime("%H:%M:%S"),
        "min_market_cap": min_market_cap,
        "cache_dir": str(resolved_cache_dir),
        "export_dir": str(resolved_export_dir),
        "selected_symbol": str(selected_row["symbol"]),
        "selected_trade_date": selected_trade_date_str,
        "summary_rows": len(summary),
        "ranked_rows": len(ranked),
        "intraday_rows": len(intraday),
        "daily_rows": len(daily_bars),
        "universe_rows": len(raw_universe),
        "supported_universe_rows": len(supported_universe),
        "minute_detail_all_rows": len(minute_detail_all),
        "second_detail_all_rows": len(second_detail_all),
        "full_universe_second_detail_open_rows": len(full_universe_second_detail_open),
        "full_universe_second_detail_close_rows": len(full_universe_second_detail_close),
        "full_universe_close_trade_detail_rows": len(full_universe_close_trade_detail),
        "full_universe_close_outcome_minute_rows": len(full_universe_close_outcome_minute),
        "quality_window_second_detail_rows": len(quality_window_second_detail_prepared),
        "daily_symbol_features_full_universe_rows": len(daily_symbol_features_full_universe),
        "close_imbalance_features_full_universe_rows": len(close_imbalance_features_full_universe),
        "close_imbalance_outcomes_full_universe_rows": len(close_imbalance_outcomes_full_universe),
        "premarket_features_full_universe_rows": len(premarket_features_full_universe),
        "premarket_window_features_full_universe_rows": len(premarket_window_features_full_universe),
        "symbol_day_diagnostics_rows": len(symbol_day_diagnostics),
        "research_event_flags_full_universe_rows": len(research_event_flags_full_universe),
        "research_event_flag_coverage_rows": len(research_event_flag_coverage),
        "research_event_flag_trade_date_distribution_rows": len(research_event_flag_trade_date_distribution),
        "research_event_flag_outcome_slices_rows": len(research_event_flag_outcome_slices),
        "research_event_flags_source": research_event_flag_metadata,
        "research_news_flags_full_universe_rows": len(research_news_flags_full_universe),
        "research_news_flag_coverage_rows": len(research_news_flag_coverage),
        "research_news_flag_trade_date_distribution_rows": len(research_news_flag_trade_date_distribution),
        "research_news_flag_outcome_slices_rows": len(research_news_flag_outcome_slices),
        "research_news_flags_source": research_news_flag_metadata,
        "core_vs_benzinga_news_side_by_side_rows": len(core_vs_benzinga_news_side_by_side),
        "core_vs_benzinga_news_overlap_stats_rows": len(core_vs_benzinga_news_overlap_stats),
        "core_vs_benzinga_news_source": core_vs_benzinga_news_metadata,
        "detail_symbol_count": int(summary["symbol"].nunique()) if not summary.empty else 0,
        "expected_symbol_day_rows": int(len(daily_symbol_features_full_universe)),
        "covered_symbol_day_rows": int(daily_symbol_features_full_universe["has_intraday"].sum()) if not daily_symbol_features_full_universe.empty else 0,
        "missing_open_window_symbol_day_rows": int((~daily_symbol_features_full_universe["has_open_window_detail"]).sum()) if "has_open_window_detail" in daily_symbol_features_full_universe.columns else int((~daily_symbol_features_full_universe["has_intraday"]).sum()) if not daily_symbol_features_full_universe.empty else 0,
        "detail_exclusion_reasons": sorted({reason for reason in symbol_day_diagnostics.get("excluded_reason", pd.Series(dtype=str)).astype(str) if reason}),
        "unsupported_symbols": unsupported,
        "output_checks": output_summary,
        "batl_debug": batl_debug,
        "canonical_production_artifact": "export_bundle",
        "derived_workbook_artifact": "databento_volatility_production_workbook.xlsx",
        "workbook_freshness_model": "per_daily_run_overwrite",
    }
    paths = export_run_artifacts(
        export_dir=resolved_export_dir,
        basename=basename,
        summary=summary,
        universe=raw_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        ranked=ranked,
        minute_detail=minute_detail,
        second_detail=second_detail,
        minute_detail_all=minute_detail_all,
        second_detail_all=second_detail_all,
        additional_sheets={
            "batl_debug": pd.DataFrame([batl_debug]),
            "output_checks": pd.DataFrame([output_summary]),
        },
        additional_parquet_targets={
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "full_universe_second_detail_close": full_universe_second_detail_close,
            "full_universe_close_trade_detail": full_universe_close_trade_detail,
            "full_universe_close_outcome_minute": full_universe_close_outcome_minute,
            "close_imbalance_features_full_universe": close_imbalance_features_full_universe,
            "close_imbalance_outcomes_full_universe": close_imbalance_outcomes_full_universe,
            "premarket_features_full_universe": premarket_features_full_universe,
            "premarket_window_features_full_universe": premarket_window_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
            "research_event_flags_full_universe": research_event_flags_full_universe,
            "research_event_flag_coverage": research_event_flag_coverage,
            "research_event_flag_trade_date_distribution": research_event_flag_trade_date_distribution,
            "research_event_flag_outcome_slices": research_event_flag_outcome_slices,
            "research_news_flags_full_universe": research_news_flags_full_universe,
            "research_news_flag_coverage": research_news_flag_coverage,
            "research_news_flag_trade_date_distribution": research_news_flag_trade_date_distribution,
            "research_news_flag_outcome_slices": research_news_flag_outcome_slices,
            "core_vs_benzinga_news_side_by_side": core_vs_benzinga_news_side_by_side,
            "core_vs_benzinga_news_overlap_stats": core_vs_benzinga_news_overlap_stats,
            "quality_window_status_latest": quality_window_status,
        },
        cost_estimate=cost_estimate,
        unsupported_symbols=unsupported,
        manifest=manifest,
    )
    paths["canonical_production_workbook"] = _write_canonical_production_workbook(
        export_dir=resolved_export_dir,
        summary=summary,
        minute_detail=minute_detail,
        second_detail=second_detail,
        manifest=manifest,
        raw_universe=raw_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        ranked=ranked,
        daily_symbol_features_full_universe=daily_symbol_features_full_universe,
        full_universe_second_detail_open=full_universe_second_detail_open,
        full_universe_second_detail_close=full_universe_second_detail_close,
        full_universe_close_trade_detail=full_universe_close_trade_detail,
        full_universe_close_outcome_minute=full_universe_close_outcome_minute,
        close_imbalance_features_full_universe=close_imbalance_features_full_universe,
        close_imbalance_outcomes_full_universe=close_imbalance_outcomes_full_universe,
        premarket_features_full_universe=premarket_features_full_universe,
        premarket_window_features_full_universe=premarket_window_features_full_universe,
        symbol_day_diagnostics=symbol_day_diagnostics,
        research_event_flags_full_universe=research_event_flags_full_universe,
        research_event_flag_coverage=research_event_flag_coverage,
        research_event_flag_trade_date_distribution=research_event_flag_trade_date_distribution,
        research_event_flag_outcome_slices=research_event_flag_outcome_slices,
        research_news_flags_full_universe=research_news_flags_full_universe,
        research_news_flag_coverage=research_news_flag_coverage,
        research_news_flag_trade_date_distribution=research_news_flag_trade_date_distribution,
        research_news_flag_outcome_slices=research_news_flag_outcome_slices,
        core_vs_benzinga_news_side_by_side=core_vs_benzinga_news_side_by_side,
        core_vs_benzinga_news_overlap_stats=core_vs_benzinga_news_overlap_stats,
        quality_window_status=quality_window_status,
        batl_debug=batl_debug,
        output_summary=output_summary,
    )
    exact_named_paths = _write_exact_named_exports(
        resolved_export_dir,
        {
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "full_universe_second_detail_close": full_universe_second_detail_close,
            "full_universe_close_trade_detail": full_universe_close_trade_detail,
            "full_universe_close_outcome_minute": full_universe_close_outcome_minute,
            "close_imbalance_features_full_universe": close_imbalance_features_full_universe,
            "close_imbalance_outcomes_full_universe": close_imbalance_outcomes_full_universe,
            "premarket_features_full_universe": premarket_features_full_universe,
            "premarket_window_features_full_universe": premarket_window_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
            "research_event_flags_full_universe": research_event_flags_full_universe,
            "research_event_flag_coverage": research_event_flag_coverage,
            "research_event_flag_trade_date_distribution": research_event_flag_trade_date_distribution,
            "research_event_flag_outcome_slices": research_event_flag_outcome_slices,
            "research_news_flags_full_universe": research_news_flags_full_universe,
            "research_news_flag_coverage": research_news_flag_coverage,
            "research_news_flag_trade_date_distribution": research_news_flag_trade_date_distribution,
            "research_news_flag_outcome_slices": research_news_flag_outcome_slices,
            "core_vs_benzinga_news_side_by_side": core_vs_benzinga_news_side_by_side,
            "core_vs_benzinga_news_overlap_stats": core_vs_benzinga_news_overlap_stats,
            "quality_window_status_latest": quality_window_status,
        },
    )
    exact_named_state_path = _write_exact_named_export_state(
        resolved_export_dir,
        manifest=manifest,
        artifact_paths=exact_named_paths,
        source_manifest_path=paths.get("manifest"),
    )
    for name, path in exact_named_paths.items():
        paths[f"exact_{name}"] = path
    paths["exact_named_state"] = exact_named_state_path

    return {
        "manifest": manifest,
        "exported_paths": paths,
        "exact_named_paths": exact_named_paths,
        "summary": summary,
        "ranked": ranked,
        "intraday": intraday,
        "daily_bars": daily_bars,
        "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
        "full_universe_close_trade_detail": full_universe_close_trade_detail,
        "full_universe_close_outcome_minute": full_universe_close_outcome_minute,
        "close_imbalance_features_full_universe": close_imbalance_features_full_universe,
        "close_imbalance_outcomes_full_universe": close_imbalance_outcomes_full_universe,
        "premarket_features_full_universe": premarket_features_full_universe,
        "premarket_window_features_full_universe": premarket_window_features_full_universe,
        "symbol_day_diagnostics": symbol_day_diagnostics,
        "research_event_flags_full_universe": research_event_flags_full_universe,
        "research_event_flag_coverage": research_event_flag_coverage,
        "research_event_flag_trade_date_distribution": research_event_flag_trade_date_distribution,
        "research_event_flag_outcome_slices": research_event_flag_outcome_slices,
        "research_news_flags_full_universe": research_news_flags_full_universe,
        "research_news_flag_coverage": research_news_flag_coverage,
        "research_news_flag_trade_date_distribution": research_news_flag_trade_date_distribution,
        "research_news_flag_outcome_slices": research_news_flag_outcome_slices,
        "core_vs_benzinga_news_side_by_side": core_vs_benzinga_news_side_by_side,
        "core_vs_benzinga_news_overlap_stats": core_vs_benzinga_news_overlap_stats,
        "cost_estimate": cost_estimate,
        "output_checks": output_summary,
        "batl_debug": batl_debug,
    }


def main(argv: Sequence[str] | None = None) -> None:
    load_dotenv(REPO_ROOT / ".env")

    parser = argparse.ArgumentParser(description="Run the Databento production export pipeline.")
    parser.add_argument("--dataset", default=(os.getenv("DATABENTO_DATASET") or "").strip() or None)
    parser.add_argument("--lookback-days", type=int, default=30)
    parser.add_argument("--top-fraction", type=float, default=float(os.getenv("DATABENTO_TOP_FRACTION", "0.20")))
    parser.add_argument(
        "--bullish-score-profile",
        choices=["conservative", "balanced", "aggressive"],
        default=os.getenv("DATABENTO_BULLISH_SCORE_PROFILE", DEFAULT_BULLISH_QUALITY_SCORE_PROFILE),
        help="Bullish-quality score weighting profile used for premarket window exports.",
    )
    parser.add_argument(
        "--estimate-costs",
        action="store_true",
        help="Opt in to the Databento cost-estimate step before the export pipeline runs.",
    )
    parser.add_argument(
        "--smc-base-only",
        action="store_true",
        help="Disable preopen 04:00 scope selection and the fixed 10:00 ET outcome snapshot for SMC base-generation focused exports.",
    )
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else [])

    databento_api_key = os.getenv("DATABENTO_API_KEY", "")
    fmp_api_key = os.getenv("FMP_API_KEY", "")
    benzinga_api_key = os.getenv("BENZINGA_API_KEY", "")
    if not databento_api_key:
        raise SystemExit("DATABENTO_API_KEY must be set in .env")
    if not fmp_api_key:
        print("INFO: FMP_API_KEY not set — running without FMP enrichment (Nasdaq Trader primary universe only).")

    available = list_accessible_datasets(databento_api_key)
    requested_dataset = str(args.dataset or "").strip()
    dataset = choose_default_dataset(available, requested_dataset=requested_dataset or None)
    result = run_production_export_pipeline(
        databento_api_key=databento_api_key,
        fmp_api_key=fmp_api_key,
        benzinga_api_key=benzinga_api_key,
        dataset=dataset,
        lookback_days=int(args.lookback_days),
        top_fraction=float(args.top_fraction),
        ranking_metric="window_range_pct",
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        min_market_cap=0.0,
        cache_dir=REPO_ROOT / "artifacts" / "databento_volatility_cache",
        export_dir=default_export_directory(),
        use_file_cache=True,
        force_refresh=bool(args.force_refresh),
        bullish_score_profile=str(args.bullish_score_profile),
        skip_cost_estimate=not bool(args.estimate_costs),
        smc_base_only=bool(args.smc_base_only),
    )

    print("EXPORT_DIR", result["manifest"]["export_dir"])
    print("OUTPUT_CHECKS", result["output_checks"])
    print("BATL_DEBUG", result["batl_debug"])
    for key, path in sorted(result["exported_paths"].items()):
        print(key.upper(), path)


if __name__ == "__main__":
    main(sys.argv[1:])