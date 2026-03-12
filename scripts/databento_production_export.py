from __future__ import annotations

import logging
import math
import os
import sys
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import (
    US_EASTERN_TZ,
    _write_tradingview_watchlist_exports,
    _read_cached_frame,
    _write_cached_frame,
    build_cache_path,
    build_export_basename,
    build_daily_features_full_universe,
    build_summary_table,
    choose_default_dataset,
    collect_full_universe_open_window_second_detail,
    default_export_directory,
    estimate_databento_costs,
    export_run_artifacts,
    fetch_symbol_day_detail,
    fetch_us_equity_universe,
    filter_supported_universe_for_databento,
    list_accessible_datasets,
    list_recent_trading_days,
    load_daily_bars,
    normalize_symbol_for_databento,
    rank_top_fraction_per_day,
    resolve_display_timezone,
    run_intraday_screen,
)
from open_prep.macro import FMPClient


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
    "has_market_cap",
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
    "premarket_trade_count_source",
    "premarket_trade_count_usable",
    "premarket_seconds",
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
            return cached

    if not str(fmp_api_key or "").strip():
        empty = _empty_fundamental_reference_frame()
        if use_file_cache:
            _write_cached_frame(cache_path, empty)
        return empty

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
            window_close_value=("dollar_volume", "sum"),
        ).reset_index()
        grouped = grouped.merge(all_features, on=["trade_date", "symbol"], how="left")
        grouped = grouped.merge(premarket_small, on=["trade_date", "symbol"], how="left")
        grouped = grouped.merge(open_confirm, on=["trade_date", "symbol"], how="left")
        grouped["window_vwap"] = np.where(
            grouped["window_volume"] > 0,
            grouped["window_close_value"] / grouped["window_volume"],
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
        grouped["gap_ok"] = pd.to_numeric(grouped.get("prev_close_to_premarket_pct"), errors="coerce") >= QUALITY_OPEN_DRIVE_HARD_FILTERS["min_prev_close_to_premarket_pct"]
        grouped["dollar_vol_ok"] = grouped["window_dollar_volume"] >= QUALITY_OPEN_DRIVE_HARD_FILTERS["min_window_dollar_volume"]
        grouped["window_return_ok"] = grouped["window_return_pct"] > QUALITY_OPEN_DRIVE_QUALITY_THRESHOLDS["min_window_return_pct"]
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
    alternate_symbols: set[str] = set()
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
        alternate_symbols.update({
            str(symbol).upper()
            for symbol in alt_detail["symbol"].dropna().astype(str).tolist()
            if str(symbol).strip()
        })
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
        if alternate_symbols:
            alt_symbol_mask = base_detail["symbol"].astype(str).str.upper().isin(alternate_symbols)
            base_for_alternate = base_detail.loc[alt_symbol_mask].copy()
            base_for_other = base_detail.loc[~alt_symbol_mask].copy()
            base_quality = pd.concat(
                [
                    _filter_quality_window_intervals(base_for_other, include_early=True, include_late=True, include_open_confirm=True),
                    _filter_quality_window_intervals(base_for_alternate, include_early=False, include_late=True, include_open_confirm=False),
                ],
                ignore_index=True,
            )
            base_premarket = _filter_premarket_rows(base_for_other)
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
    display_timezone: str,
    premarket_anchor_et: time,
    ranking_metric: str,
    top_fraction: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    features, coverage = build_daily_features_full_universe(
        trading_days=trading_days,
        universe=raw_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=second_detail_all,
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

    coverage_flags = coverage[["trade_date", "symbol", "has_daily_bar", "has_intraday_summary", "has_open_window_detail", "exclusion_reason"]].copy()
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

    early_ranking_metric = "focus_0400_open_30s_volume"
    early_has_rows = pd.to_numeric(features.get("focus_0400_open_window_second_rows"), errors="coerce").fillna(0).astype(int) > 0
    early_prev_close_mask = pd.to_numeric(features.get("previous_close"), errors="coerce").notna()
    early_metric_series = pd.to_numeric(features.get(early_ranking_metric), errors="coerce")
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
    features["selected_top20pct_0400"] = False
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
    return features[DAILY_SYMBOL_FEATURE_COLUMNS], diagnostics[SYMBOL_DAY_DIAGNOSTIC_COLUMNS]


def _prepare_full_universe_second_detail_export(second_detail_all: pd.DataFrame, daily_features: pd.DataFrame) -> pd.DataFrame:
    if second_detail_all.empty:
        return pd.DataFrame(columns=SECOND_DETAIL_EXPORT_COLUMNS)

    detail = second_detail_all.copy()
    detail["trade_date"] = pd.to_datetime(detail["trade_date"], errors="coerce").dt.date
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce")
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
    detail["timestamp"] = pd.to_datetime(detail["timestamp"], errors="coerce")
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
        frame.to_parquet(path, index=False)
        created[name] = path
    return created


def _format_optional_time(value: time | None) -> str:
    return value.strftime("%H:%M:%S") if isinstance(value, time) else "market_relative_default"


def _filter_ranked_symbol_day_scope(frame: pd.DataFrame, ranked_scope: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or ranked_scope.empty:
        return frame.iloc[0:0].copy()
    scoped = frame.copy()
    scoped["trade_date"] = pd.to_datetime(scoped["trade_date"], errors="coerce").dt.date
    scoped["symbol"] = scoped["symbol"].astype(str).str.upper()
    return scoped.merge(ranked_scope, on=["trade_date", "symbol"], how="inner").reset_index(drop=True)


def run_production_export_pipeline(
    *,
    databento_api_key: str,
    fmp_api_key: str = "",
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
) -> dict[str, Any]:
    if not databento_api_key:
        raise ValueError("Databento API key is required.")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must be between 0 and 1")
    if second_detail_scope not in {"full_universe", "ranked_only", "none"}:
        raise ValueError("second_detail_scope must be one of: full_universe, ranked_only, none")

    resolved_cache_dir = cache_dir or (REPO_ROOT / "artifacts" / "databento_volatility_cache")
    resolved_export_dir = export_dir or default_export_directory()

    trading_days = list_recent_trading_days(databento_api_key, dataset=dataset, lookback_days=lookback_days)
    cost_estimate = estimate_databento_costs(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        display_timezone=display_timezone,
        window_start=window_start,
        window_end=window_end,
        premarket_anchor_et=premarket_anchor_et,
    )

    raw_universe = fetch_us_equity_universe(fmp_api_key, min_market_cap=min_market_cap or None)
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
    supported_universe, unsupported = filter_supported_universe_for_databento(
        databento_api_key,
        dataset=dataset,
        universe=raw_universe,
        cache_dir=resolved_cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    universe_symbols = set(supported_universe["symbol"].dropna().astype(str).str.upper())

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
    intraday_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    ranked = rank_top_fraction_per_day(intraday, ranking_metric=ranking_metric, top_fraction=top_fraction)
    if ranked.empty:
        raise RuntimeError("No ranked results were returned for the production export run")

    ranked_scope = ranked[["trade_date", "symbol"]].drop_duplicates(subset=["trade_date", "symbol"]).reset_index(drop=True)

    if second_detail_scope == "none":
        full_universe_second_detail_raw = pd.DataFrame()
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
    daily_symbol_features_full_universe, symbol_day_diagnostics = _build_daily_symbol_features_full_universe_export(
        trading_days=trading_days,
        raw_universe=raw_universe,
        supported_universe=supported_universe,
        daily_bars=daily_bars,
        intraday=intraday,
        second_detail_all=full_universe_second_detail_raw,
        display_timezone=display_timezone,
        premarket_anchor_et=premarket_anchor_et,
        ranking_metric=ranking_metric,
        top_fraction=top_fraction,
    )
    full_universe_second_detail_open = _prepare_full_universe_second_detail_export(
        full_universe_second_detail_raw,
        daily_symbol_features_full_universe,
    )
    quality_window_second_detail_prepared = _prepare_full_universe_second_detail_export(
        quality_window_second_detail,
        daily_symbol_features_full_universe,
    )
    premarket_source_detail_prepared = _prepare_full_universe_second_detail_export(
        premarket_source_detail,
        daily_symbol_features_full_universe,
    )
    second_detail_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    premarket_features_full_universe = _build_premarket_features_full_universe_export(
        premarket_source_detail_prepared,
        daily_symbol_features_full_universe,
    )
    premarket_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

    latest_trade_date = pd.to_datetime(daily_symbol_features_full_universe.get("trade_date"), errors="coerce").dt.date.dropna().max()
    quality_window_status = pd.DataFrame(
        columns=[
            "symbol",
            QUALITY_OPEN_DRIVE_WINDOW_TRADE_DATE_COLUMN,
            QUALITY_OPEN_DRIVE_WINDOW_COVERAGE_COLUMN,
            QUALITY_OPEN_DRIVE_WINDOW_STATUS_COLUMN,
            QUALITY_OPEN_DRIVE_WINDOW_SCORE_COLUMN,
        ]
    )
    quality_candidate_exports: dict[str, pd.DataFrame] = {}
    if latest_trade_date is not None:
        quality_window_status, quality_candidate_exports = _compute_quality_window_signal(
            quality_window_second_detail_prepared,
            daily_symbol_features_full_universe,
            premarket_features_full_universe,
            display_timezone=display_timezone,
            latest_trade_date=latest_trade_date,
        )

    raw_universe = _enrich_universe_with_quality_window_status(
        raw_universe,
        daily_symbol_features_full_universe,
        premarket_features_full_universe,
        quality_window_second_detail_prepared,
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
        "premarket_symbol_day_rows": int(premarket_features_full_universe["has_premarket_data"].sum()),
        "batl": batl_debug,
    }

    export_generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    basename = build_export_basename(prefix="databento_volatility_production")
    manifest = {
        "dataset": dataset,
        "universe_source": "nasdaq_trader_symbol_directory",
        "universe_source_fallback": "fmp_company_screener_when_min_market_cap_is_set_or_directory_fetch_fails",
        "universe_scope_definition": "Listed non-ETF, non-test issues from Nasdaq Trader symbol directories for the requested US exchanges; Databento support is applied afterward.",
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
        "premarket_fetched_at": premarket_fetched_at,
        "source_data_fetched_at": premarket_fetched_at,
        "export_generated_at": export_generated_at,
        "trade_dates_covered": [trade_day.isoformat() for trade_day in trading_days],
        "detail_scope": "full_supported_universe_symbol_days",
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
        "quality_window_source_strategy": "Use exchange-specific early/premarket sources where configured, use the base dataset for the late 09:00-09:30 ET window, and derive open-confirm from the same source used for the early path.",
        "quality_open_drive_window_trade_date_rule": "latest trade_date covered by daily_symbol_features_full_universe",
        "quality_open_drive_window_coverage_latest_berlin_rule": "categorical latest-trade-date data-presence status derived from ET windows [04:00, 04:30) and [09:00, 09:30), rendered in the configured display_timezone local time, or none",
        "quality_open_drive_window_latest_berlin_rule": "categorical latest-trade-date high-confidence pass status derived from ET windows [04:00, 04:30) and [09:00, 09:30), rendered in the configured display_timezone local time, or none",
        "quality_open_drive_window_score_latest_berlin_rule": "latest-trade-date best window quality score across the ET windows [04:00, 04:30) and [09:00, 09:30), based on weighted hard filters, trend stability, VWAP position, and optional open confirmation",
        "quality_open_drive_window_base_filters": "previous_close >= 5, prev_close_to_premarket_pct >= 0, and 30m window_dollar_volume >= 500000",
        "quality_open_drive_window_latest_berlin_criteria": "window_return_pct > 0, window_close_vs_high_pct >= -2.0, window_range_pct <= 12.0, and window_close >= window_vwap; open confirmation contributes to score but is not required for the categorical pass label",
        "quality_open_drive_window_score_weights": QUALITY_OPEN_DRIVE_SCORE_WEIGHTS,
        "quality_window_candidate_exports": sorted(quality_candidate_exports.keys()),
        "open_1m_volume_boundary": "[regular_open, regular_open + 1 minute)",
        "open_5m_volume_boundary": "[regular_open, regular_open + 5 minutes)",
        "full_universe_open_detail_window": f"[{_format_optional_time(window_start)}, {_format_optional_time(window_end)}] {display_timezone}",
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
        "quality_window_second_detail_rows": len(quality_window_second_detail_prepared),
        "daily_symbol_features_full_universe_rows": len(daily_symbol_features_full_universe),
        "premarket_features_full_universe_rows": len(premarket_features_full_universe),
        "symbol_day_diagnostics_rows": len(symbol_day_diagnostics),
        "detail_symbol_count": int(summary[["trade_date", "symbol"]].drop_duplicates().shape[0]),
        "expected_symbol_day_rows": int(len(daily_symbol_features_full_universe)),
        "covered_symbol_day_rows": int(daily_symbol_features_full_universe["has_intraday"].sum()) if not daily_symbol_features_full_universe.empty else 0,
        "missing_open_window_symbol_day_rows": int((~daily_symbol_features_full_universe["has_intraday"]).sum()) if not daily_symbol_features_full_universe.empty else 0,
        "detail_exclusion_reasons": sorted({reason for reason in symbol_day_diagnostics.get("excluded_reason", pd.Series(dtype=str)).astype(str) if reason}),
        "unsupported_symbols": unsupported,
        "output_checks": output_summary,
        "batl_debug": batl_debug,
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
            **quality_candidate_exports,
        },
        additional_parquet_targets={
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "premarket_features_full_universe": premarket_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
            "quality_window_status_latest": quality_window_status,
            **quality_candidate_exports,
        },
        cost_estimate=cost_estimate,
        unsupported_symbols=unsupported,
        manifest=manifest,
    )

    csv_export_paths = _write_csv_exports(resolved_export_dir, quality_candidate_exports)
    for name, path in csv_export_paths.items():
        paths[f"csv_{name}"] = path

    exact_named_paths = _write_exact_named_exports(
        resolved_export_dir,
        {
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "premarket_features_full_universe": premarket_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
            "quality_window_status_latest": quality_window_status,
            **quality_candidate_exports,
        },
    )
    for name, path in exact_named_paths.items():
        paths[f"exact_{name}"] = path

    return {
        "manifest": manifest,
        "exported_paths": paths,
        "exact_named_paths": exact_named_paths,
        "summary": summary,
        "ranked": ranked,
        "intraday": intraday,
        "daily_bars": daily_bars,
        "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
        "premarket_features_full_universe": premarket_features_full_universe,
        "symbol_day_diagnostics": symbol_day_diagnostics,
        "cost_estimate": cost_estimate,
        "output_checks": output_summary,
        "batl_debug": batl_debug,
    }


def main() -> None:
    load_dotenv(REPO_ROOT / ".env")

    databento_api_key = os.getenv("DATABENTO_API_KEY", "")
    fmp_api_key = os.getenv("FMP_API_KEY", "")
    if not databento_api_key:
        raise SystemExit("DATABENTO_API_KEY must be set in .env")
    if not fmp_api_key:
        print("INFO: FMP_API_KEY not set — running without FMP enrichment (Nasdaq Trader primary universe only).")

    available = list_accessible_datasets(databento_api_key)
    requested_dataset = (os.getenv("DATABENTO_DATASET") or "").strip()
    if requested_dataset:
        dataset = choose_default_dataset(available, requested_dataset=requested_dataset)
    elif "DBEQ.BASIC" in available:
        dataset = "DBEQ.BASIC"
    else:
        dataset = choose_default_dataset(available, requested_dataset="DBEQ.BASIC")
        print(f"INFO: DBEQ.BASIC is not accessible; falling back to {dataset}.")
    result = run_production_export_pipeline(
        databento_api_key=databento_api_key,
        fmp_api_key=fmp_api_key,
        dataset=dataset,
        lookback_days=30,
        top_fraction=float(os.getenv("DATABENTO_TOP_FRACTION", "0.20")),
        ranking_metric="window_range_pct",
        display_timezone="Europe/Berlin",
        window_start=None,
        window_end=None,
        premarket_anchor_et=time(4, 0),
        min_market_cap=0.0,
        cache_dir=REPO_ROOT / "artifacts" / "databento_volatility_cache",
        export_dir=default_export_directory(),
        use_file_cache=True,
        force_refresh=False,
    )

    print("EXPORT_DIR", result["manifest"]["export_dir"])
    print("OUTPUT_CHECKS", result["output_checks"])
    print("BATL_DEBUG", result["batl_debug"])
    for key, path in sorted(result["exported_paths"].items()):
        print(key.upper(), path)


if __name__ == "__main__":
    main()