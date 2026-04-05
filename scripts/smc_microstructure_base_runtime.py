from __future__ import annotations

import json
import logging
import math
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from databento_utils import US_EASTERN_TZ
from scripts.databento_production_export import run_production_export_pipeline
from scripts.generate_smc_micro_profiles import load_schema, run_generation
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_enrichment_types import EnrichmentDict

# ── Re-exports from extracted modules (backward compatibility) ──────
from scripts.smc_micro_publish_guard import (  # noqa: F401
    evaluate_micro_library_publish_guard,
    inspect_generated_micro_library_contract,
    publish_micro_library_to_tradingview,
)
from scripts.smc_micro_streamlit_app import (  # noqa: F401
    _resolve_ui_dataset_options,
    list_generated_base_csvs,
    resolve_base_csv_action_target,
    resolve_base_csv_selection,
    run_streamlit_micro_base_app,
)
from scripts.smc_databento_session_detail import (  # noqa: F401
    AFTERHOURS_END_ET,
    AFTERHOURS_MINUTES,
    CLOSE_60M_START_ET,
    LATE_START_ET,
    MIDDAY_END_ET,
    MIDDAY_MINUTES,
    MIDDAY_START_ET,
    OPEN_30M_END_ET,
    PREMARKET_MINUTES,
    PREMARKET_START_ET,
    REGULAR_CLOSE_ET,
    REGULAR_MINUTES,
    REGULAR_OPEN_ET,
    _assert_complete_symbol_coverage,
    _coverage_stats,
    _universe_fingerprint,
    collect_full_universe_session_minute_detail,
)


logger = logging.getLogger(__name__)

REQUIRED_BUNDLE_FRAMES = (
    "daily_bars",
    "daily_symbol_features_full_universe",
)

# Session-time constants and coverage helpers are now re-exported from
# scripts.smc_databento_session_detail (see top-of-file imports).
# ETF keywords remain local — used only by this module.

# Each keyword starts with a space to avoid matching prefix-only company names
# (e.g., "ETFMG..." would not match " ETF"). Names that begin with the keyword
# (no preceding word) are intentionally excluded from the ETF heuristic.
ETF_KEYWORDS = (
    " ETF",
    " TRUST",
    " FUND",
    " ISHARES",
    " SPDR",
    " VANGUARD",
    " INVESCO",
    " PROSHARES",
    " DIREXION",
    " GLOBAL X",
    " WISDOMTREE",
    " VANECK",
    " ETN",
)


@dataclass(frozen=True)
class MappingStatus:
    field: str
    status: str
    source_sheet: str
    source_columns: list[str]
    note: str


def infer_asset_type(company_name: str, explicit_asset_type: str | None = None) -> str:
    explicit = str(explicit_asset_type or "").strip().lower()
    if explicit:
        return explicit
    upper_name = str(company_name or "").upper()
    return "etf" if any(keyword in upper_name for keyword in ETF_KEYWORDS) else "stock"


def infer_universe_bucket(asset_type: str, market_cap: float | None) -> str:
    if asset_type == "etf":
        return "us_etf"
    if market_cap is None or pd.isna(market_cap):
        return "us_unknown"
    if market_cap >= 10_000_000_000:
        return "us_largecap"
    if market_cap >= 2_000_000_000:
        return "us_midcap"
    return "us_smallcap"


def _clip01(value: Any) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return 0.0
    return float(max(0.0, min(1.0, float(numeric))))


def _safe_float(value: Any, default: float = 0.0) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return default
    return float(numeric)


def _series_from_frame(frame: pd.DataFrame, column: str, default: Any = np.nan) -> pd.Series:
    if column in frame.columns:
        return pd.Series(frame[column], index=frame.index)
    return pd.Series(default, index=frame.index)


def _safe_ratio(numerator: Any, denominator: Any, *, default: float = 0.0) -> float:
    numerator_value = _safe_float(numerator, default=np.nan)
    denominator_value = _safe_float(denominator, default=np.nan)
    if not np.isfinite(numerator_value) or not np.isfinite(denominator_value) or denominator_value <= 0:
        return float(default)
    return float(numerator_value / denominator_value)


def _coerce_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _mean_or_default(series: pd.Series, default: float = 0.0) -> float:
    numeric = pd.to_numeric(series, errors="coerce")
    if numeric.dropna().empty:
        return float(default)
    return float(numeric.mean())


def _quantile_or_default(series: pd.Series, quantile: float, default: float = 0.0) -> float:
    numeric = pd.to_numeric(series, errors="coerce").dropna()
    if numeric.empty:
        return float(default)
    return float(numeric.quantile(quantile))


def _build_trade_date_scope(manifest: dict[str, Any]) -> list[date]:
    trade_dates = [
        date.fromisoformat(str(raw_date))
        for raw_date in manifest.get("trade_dates_covered", [])
        if str(raw_date).strip()
    ]
    return sorted(set(trade_dates))


# collect_full_universe_session_minute_detail has been extracted to
# scripts.smc_databento_session_detail and is re-exported above.


def _session_slice(frame: pd.DataFrame, start_et: time, end_et: time) -> pd.DataFrame:
    return frame.loc[frame["et_time"].ge(start_et) & frame["et_time"].lt(end_et)].copy()


def _window_efficiency(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    open_price = _safe_float(frame.iloc[0].get("open"), default=np.nan)
    close_price = _safe_float(frame.iloc[-1].get("close"), default=np.nan)
    high_price = _safe_float(frame.get("high").max(), default=np.nan)
    low_price = _safe_float(frame.get("low").min(), default=np.nan)
    total_range = high_price - low_price if np.isfinite(high_price) and np.isfinite(low_price) else np.nan
    if not np.isfinite(open_price) or not np.isfinite(close_price) or not np.isfinite(total_range) or total_range <= 0:
        return 0.0
    return _clip01(abs(close_price - open_price) / total_range)


def _bar_spread_bps(frame: pd.DataFrame) -> pd.Series:
    high = pd.to_numeric(frame.get("high"), errors="coerce")
    low = pd.to_numeric(frame.get("low"), errors="coerce")
    mid = (high + low) / 2.0
    return np.where(mid > 0, ((high - low) / mid) * 10_000.0, np.nan)


def _bar_wickiness(frame: pd.DataFrame) -> pd.Series:
    open_price = pd.to_numeric(frame.get("open"), errors="coerce")
    high = pd.to_numeric(frame.get("high"), errors="coerce")
    low = pd.to_numeric(frame.get("low"), errors="coerce")
    close_price = pd.to_numeric(frame.get("close"), errors="coerce")
    total_range = high - low
    upper_wick = high - np.maximum(open_price, close_price)
    lower_wick = np.minimum(open_price, close_price) - low
    raw = np.where(total_range > 0, (upper_wick + lower_wick) / total_range, np.nan)
    return pd.Series(raw, index=frame.index).clip(lower=0.0, upper=1.0)


def _session_stats(frame: pd.DataFrame, *, available_minutes: int) -> dict[str, float]:
    if frame.empty:
        return {
            "dollar_volume": 0.0,
            "trade_proxy": 0.0,
            "active_minutes": 0.0,
            "active_minutes_share": 0.0,
            "spread_bps": 0.0,
            "wickiness": 0.0,
            "efficiency": 0.0,
        }
    return {
        "dollar_volume": float(frame["dollar_volume"].sum()),
        "trade_proxy": float(frame["trade_proxy"].sum()),
        "active_minutes": float(frame["active_minute"].sum()),
        "active_minutes_share": _safe_ratio(frame["active_minute"].sum(), available_minutes, default=0.0),
        "spread_bps": _mean_or_default(frame["spread_bps_proxy"], default=0.0),
        "wickiness": _mean_or_default(frame["wickiness_proxy"], default=0.0),
        "efficiency": _window_efficiency(frame),
    }


def _setup_decay_half_life_30m_buckets(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    bucket_index = ((frame["minutes_from_open"] // 30).astype(int)).clip(lower=0)
    bucket_dollar = frame.groupby(bucket_index, sort=True)["dollar_volume"].sum()
    if bucket_dollar.empty:
        return 0.0
    first_bucket = float(bucket_dollar.iloc[0])
    if first_bucket <= 0:
        return 0.0
    threshold = first_bucket * 0.5
    later = bucket_dollar.iloc[1:]
    hit = later[later <= threshold]
    if hit.empty:
        return float(max(len(bucket_dollar), 1))
    return float(int(hit.index[0]))


def _empty_group_metrics(group_columns: list[str], columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=columns, index=pd.MultiIndex.from_tuples([], names=group_columns))


def _window_efficiency_from_aggregates(
    open_price: pd.Series,
    close_price: pd.Series,
    high_price: pd.Series,
    low_price: pd.Series,
) -> pd.Series:
    total_range = high_price - low_price
    efficiency = np.where(
        np.isfinite(open_price)
        & np.isfinite(close_price)
        & np.isfinite(total_range)
        & (total_range > 0),
        np.abs(close_price - open_price) / total_range,
        0.0,
    )
    return pd.Series(efficiency, index=open_price.index).clip(lower=0.0, upper=1.0)


def _aggregate_window_metrics(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    group_columns: list[str],
    available_minutes: int,
) -> pd.DataFrame:
    columns = [
        "dollar_volume",
        "trade_proxy",
        "active_minutes",
        "active_minutes_share",
        "spread_bps",
        "wickiness",
        "efficiency",
        "open_price",
        "close_price",
    ]
    subset = frame.loc[
        mask,
        group_columns + [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "dollar_volume",
            "trade_proxy",
            "active_minute",
            "spread_bps_proxy",
            "wickiness_proxy",
        ],
    ]
    if subset.empty:
        return _empty_group_metrics(group_columns, columns)

    aggregated = subset.groupby(group_columns, sort=False).agg(
        dollar_volume=("dollar_volume", "sum"),
        trade_proxy=("trade_proxy", "sum"),
        active_minutes=("active_minute", "sum"),
        spread_bps=("spread_bps_proxy", "mean"),
        wickiness=("wickiness_proxy", "mean"),
        open_price=("open", "first"),
        close_price=("close", "last"),
        high_price=("high", "max"),
        low_price=("low", "min"),
    )
    aggregated["active_minutes_share"] = aggregated["active_minutes"].map(
        lambda value: _safe_ratio(value, available_minutes, default=0.0)
    )
    aggregated["efficiency"] = _window_efficiency_from_aggregates(
        aggregated["open_price"],
        aggregated["close_price"],
        aggregated["high_price"],
        aggregated["low_price"],
    )
    return aggregated[columns]


def _aggregate_open_close_metrics(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    group_columns: list[str],
) -> pd.DataFrame:
    columns = ["dollar_volume", "open_price", "close_price"]
    subset = frame.loc[mask, group_columns + ["timestamp", "open", "close", "dollar_volume"]]
    if subset.empty:
        return _empty_group_metrics(group_columns, columns)
    return subset.groupby(group_columns, sort=False).agg(
        dollar_volume=("dollar_volume", "sum"),
        open_price=("open", "first"),
        close_price=("close", "last"),
    )


def build_symbol_day_microstructure_feature_frame(
    session_minute_detail: pd.DataFrame,
    daily_symbol_features: pd.DataFrame,
) -> pd.DataFrame:
    daily = daily_symbol_features.copy()
    if daily.empty:
        return pd.DataFrame()

    daily["trade_date"] = pd.to_datetime(daily["trade_date"], errors="coerce").dt.date
    daily["symbol"] = daily["symbol"].astype(str).str.upper()
    daily = daily.dropna(subset=["trade_date", "symbol"]).copy()
    daily = daily.sort_values(["symbol", "trade_date"]).reset_index(drop=True)

    if "asset_type" not in daily.columns:
        daily["asset_type"] = [
            infer_asset_type(company_name, None)
            for company_name in daily.get("company_name", pd.Series(index=daily.index, dtype=object)).tolist()
        ]
    else:
        daily["asset_type"] = [
            infer_asset_type(company_name, asset_type)
            for company_name, asset_type in zip(
                daily.get("company_name", pd.Series(index=daily.index, dtype=object)).tolist(),
                daily["asset_type"].tolist(),
                strict=False,
            )
        ]
    daily["market_cap"] = pd.to_numeric(daily.get("market_cap"), errors="coerce")
    daily["universe_bucket"] = [
        infer_universe_bucket(asset_type, market_cap)
        for asset_type, market_cap in zip(daily["asset_type"], daily["market_cap"], strict=False)
    ]
    daily["day_open"] = pd.to_numeric(daily.get("day_open"), errors="coerce")
    daily["day_high"] = pd.to_numeric(daily.get("day_high"), errors="coerce")
    daily["day_low"] = pd.to_numeric(daily.get("day_low"), errors="coerce")
    daily["day_close"] = pd.to_numeric(daily.get("day_close"), errors="coerce")
    daily["previous_close"] = pd.to_numeric(daily.get("previous_close"), errors="coerce")
    daily["prev_day_high"] = daily.groupby("symbol")["day_high"].shift(1)
    daily["prev_day_low"] = daily.groupby("symbol")["day_low"].shift(1)

    metric_columns = [
        "trade_date",
        "symbol",
        "daily_rth_dollar_volume",
        "daily_avg_spread_bps_rth",
        "daily_rth_active_minutes_share",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_rth_wickiness",
        "daily_pm_dollar_share",
        "daily_pm_trades_share",
        "daily_pm_active_minutes_share",
        "daily_pm_spread_bps",
        "daily_pm_wickiness",
        "daily_midday_dollar_share",
        "daily_midday_trades_share",
        "daily_midday_active_minutes_share",
        "daily_midday_spread_bps",
        "daily_midday_efficiency",
        "daily_ah_dollar_share",
        "daily_ah_trades_share",
        "daily_ah_active_minutes_share",
        "daily_ah_spread_bps",
        "daily_ah_wickiness",
        "daily_setup_decay_half_life_bars",
        "daily_early_vs_late_followthrough_ratio",
        "daily_rth_efficiency",
        "daily_rth_net_return_abs",
        "missing_regular_session_detail",
        "missing_premarket_detail",
        "missing_afterhours_detail",
    ]

    minute_metrics = pd.DataFrame(columns=metric_columns)
    if not session_minute_detail.empty:
        minute_frame = session_minute_detail.copy()
        minute_frame["trade_date"] = pd.to_datetime(minute_frame["trade_date"], errors="coerce").dt.date
        minute_frame["symbol"] = minute_frame["symbol"].astype(str).str.upper()
        minute_frame["timestamp"] = pd.to_datetime(minute_frame["timestamp"], errors="coerce", utc=True)
        minute_frame = minute_frame.dropna(subset=["trade_date", "symbol", "timestamp"]).copy()
        if not minute_frame.empty:
            minute_frame["open"] = pd.to_numeric(minute_frame.get("open"), errors="coerce")
            minute_frame["high"] = pd.to_numeric(minute_frame.get("high"), errors="coerce")
            minute_frame["low"] = pd.to_numeric(minute_frame.get("low"), errors="coerce")
            minute_frame["close"] = pd.to_numeric(minute_frame.get("close"), errors="coerce")
            minute_frame["volume"] = pd.to_numeric(minute_frame.get("volume"), errors="coerce").fillna(0.0)
            minute_frame["trade_count"] = pd.to_numeric(minute_frame.get("trade_count"), errors="coerce")
            minute_frame["et_time"] = minute_frame["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
            minute_frame["dollar_volume"] = minute_frame["close"] * minute_frame["volume"]
            minute_frame["spread_bps_proxy"] = _bar_spread_bps(minute_frame)
            minute_frame["wickiness_proxy"] = _bar_wickiness(minute_frame)
            minute_frame["trade_proxy"] = minute_frame["trade_count"]
            minute_frame["trade_proxy"] = minute_frame["trade_proxy"].where(
                minute_frame["trade_proxy"].notna(),
                np.where(minute_frame["volume"] > 0, 1.0, 0.0),
            )
            minute_frame["active_minute"] = (minute_frame["volume"] > 0) | (minute_frame["trade_proxy"] > 0)
            minute_frame["minutes_from_open"] = (
                minute_frame["timestamp"].dt.tz_convert(US_EASTERN_TZ)
                - minute_frame["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.normalize()
                - pd.Timedelta(hours=9, minutes=30)
            ).dt.total_seconds() / 60.0
            minute_frame = minute_frame.sort_values(["trade_date", "symbol", "timestamp"]).reset_index(drop=True)
            group_columns = ["trade_date", "symbol"]
            group_index = minute_frame[group_columns].drop_duplicates().set_index(group_columns)

            grouped = minute_frame.groupby(group_columns, sort=False)
            close_missing = grouped["close"].count().eq(0)
            volume_inactive = grouped["volume"].max().le(0)
            null_activity = pd.DataFrame(
                {
                    "close_missing": close_missing,
                    "volume_inactive": volume_inactive,
                }
            )
            null_activity = null_activity.loc[null_activity.any(axis=1)]
            if not null_activity.empty:
                for trade_day, symbol in null_activity.index.tolist():
                    logger.warning(
                        "Symbol %s on %s has no usable close/volume activity; marking all minute bars inactive.",
                        symbol,
                        trade_day,
                    )
                null_mask = pd.MultiIndex.from_frame(minute_frame[group_columns]).isin(null_activity.index)
                minute_frame.loc[null_mask, "active_minute"] = False
                minute_frame.loc[null_mask, "trade_proxy"] = 0.0
                minute_frame.loc[null_mask, "dollar_volume"] = 0.0

            et_time = minute_frame["et_time"]
            is_pm = et_time.ge(PREMARKET_START_ET) & et_time.lt(REGULAR_OPEN_ET)
            is_rth = et_time.ge(REGULAR_OPEN_ET) & et_time.lt(REGULAR_CLOSE_ET)
            is_open_30 = et_time.ge(REGULAR_OPEN_ET) & et_time.lt(OPEN_30M_END_ET)
            is_midday = et_time.ge(MIDDAY_START_ET) & et_time.lt(MIDDAY_END_ET)
            is_late = et_time.ge(LATE_START_ET) & et_time.lt(REGULAR_CLOSE_ET)
            is_close_60 = et_time.ge(CLOSE_60M_START_ET) & et_time.lt(REGULAR_CLOSE_ET)
            is_ah = et_time.ge(REGULAR_CLOSE_ET) & et_time.lt(AFTERHOURS_END_ET)

            pm_stats = _aggregate_window_metrics(
                minute_frame,
                is_pm,
                group_columns=group_columns,
                available_minutes=PREMARKET_MINUTES,
            )
            rth_stats = _aggregate_window_metrics(
                minute_frame,
                is_rth,
                group_columns=group_columns,
                available_minutes=REGULAR_MINUTES,
            )
            midday_stats = _aggregate_window_metrics(
                minute_frame,
                is_midday,
                group_columns=group_columns,
                available_minutes=MIDDAY_MINUTES,
            )
            ah_stats = _aggregate_window_metrics(
                minute_frame,
                is_ah,
                group_columns=group_columns,
                available_minutes=AFTERHOURS_MINUTES,
            )
            open_30_stats = _aggregate_open_close_metrics(
                minute_frame,
                is_open_30,
                group_columns=group_columns,
            )
            late_stats = _aggregate_open_close_metrics(
                minute_frame,
                is_late,
                group_columns=group_columns,
            )
            close_60_stats = _aggregate_open_close_metrics(
                minute_frame,
                is_close_60,
                group_columns=group_columns,
            )

            if is_rth.any():
                rth_half_life = minute_frame.loc[is_rth, group_columns + ["minutes_from_open", "dollar_volume"]]
                rth_half_life = rth_half_life.groupby(group_columns, sort=False)[["minutes_from_open", "dollar_volume"]].apply(
                    lambda group: _setup_decay_half_life_30m_buckets(group.reset_index(drop=True))
                )
            else:
                rth_half_life = pd.Series(dtype=float)

            minute_metrics = group_index.copy()
            minute_metrics["daily_rth_dollar_volume"] = rth_stats["dollar_volume"]
            minute_metrics["daily_avg_spread_bps_rth"] = rth_stats["spread_bps"]
            minute_metrics["daily_rth_active_minutes_share"] = rth_stats["active_minutes_share"]
            minute_metrics["daily_rth_wickiness"] = rth_stats["wickiness"]
            minute_metrics["daily_rth_efficiency"] = rth_stats["efficiency"]

            total_day_dollar = pm_stats["dollar_volume"].add(rth_stats["dollar_volume"], fill_value=0.0).add(
                ah_stats["dollar_volume"], fill_value=0.0
            )
            total_day_trades = pm_stats["trade_proxy"].add(rth_stats["trade_proxy"], fill_value=0.0).add(
                ah_stats["trade_proxy"], fill_value=0.0
            )

            minute_metrics["daily_open_30m_dollar_share"] = open_30_stats["dollar_volume"].combine(
                rth_stats["dollar_volume"],
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_close_60m_dollar_share"] = close_60_stats["dollar_volume"].combine(
                rth_stats["dollar_volume"],
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )

            minute_metrics["daily_pm_dollar_share"] = pm_stats["dollar_volume"].combine(
                total_day_dollar,
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_pm_trades_share"] = pm_stats["trade_proxy"].combine(
                total_day_trades,
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_pm_active_minutes_share"] = pm_stats["active_minutes_share"]
            minute_metrics["daily_pm_spread_bps"] = pm_stats["spread_bps"]
            minute_metrics["daily_pm_wickiness"] = pm_stats["wickiness"]

            minute_metrics["daily_midday_dollar_share"] = midday_stats["dollar_volume"].combine(
                rth_stats["dollar_volume"],
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_midday_trades_share"] = midday_stats["trade_proxy"].combine(
                rth_stats["trade_proxy"],
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_midday_active_minutes_share"] = midday_stats["active_minutes_share"]
            minute_metrics["daily_midday_spread_bps"] = midday_stats["spread_bps"]
            minute_metrics["daily_midday_efficiency"] = midday_stats["efficiency"]

            minute_metrics["daily_ah_dollar_share"] = ah_stats["dollar_volume"].combine(
                total_day_dollar,
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_ah_trades_share"] = ah_stats["trade_proxy"].combine(
                total_day_trades,
                lambda numerator, denominator: _safe_ratio(numerator, denominator, default=0.0),
            )
            minute_metrics["daily_ah_active_minutes_share"] = ah_stats["active_minutes_share"]
            minute_metrics["daily_ah_spread_bps"] = ah_stats["spread_bps"]
            minute_metrics["daily_ah_wickiness"] = ah_stats["wickiness"]
            minute_metrics["daily_setup_decay_half_life_bars"] = rth_half_life

            early_return = open_30_stats["close_price"].combine(
                open_30_stats["open_price"],
                lambda close_price, open_price: abs((close_price / open_price) - 1.0)
                if np.isfinite(open_price) and open_price > 0 and np.isfinite(close_price)
                else 0.0,
            )
            late_return = late_stats["close_price"].combine(
                late_stats["open_price"],
                lambda close_price, open_price: abs((close_price / open_price) - 1.0)
                if np.isfinite(open_price) and open_price > 0 and np.isfinite(close_price)
                else 0.0,
            )
            minute_metrics["daily_early_vs_late_followthrough_ratio"] = early_return.combine(
                late_return,
                lambda numerator, denominator: _safe_ratio(numerator, max(denominator, 1e-6), default=0.0),
            )
            minute_metrics["daily_rth_net_return_abs"] = rth_stats["close_price"].combine(
                rth_stats["open_price"],
                lambda close_price, open_price: abs((close_price / open_price) - 1.0)
                if np.isfinite(open_price) and open_price > 0 and np.isfinite(close_price)
                else 0.0,
            )

            has_pm = minute_metrics.index.isin(pm_stats.index)
            has_rth = minute_metrics.index.isin(rth_stats.index)
            has_ah = minute_metrics.index.isin(ah_stats.index)
            minute_metrics["missing_regular_session_detail"] = (~has_rth) & (has_pm | has_ah)
            minute_metrics["missing_premarket_detail"] = (~has_pm) & (has_rth | has_ah)
            minute_metrics["missing_afterhours_detail"] = (~has_ah) & (has_pm | has_rth)

            missing_regular = minute_metrics.loc[minute_metrics["missing_regular_session_detail"]]
            if not missing_regular.empty:
                for trade_day, symbol in missing_regular.index.tolist():
                    logger.warning(
                        "Symbol %s on %s has minute detail for non-regular sessions but no regular-session bars; regular-session derived metrics will be 0.0.",
                        symbol,
                        trade_day,
                    )

            minute_metrics = minute_metrics.reset_index()
            minute_metrics = minute_metrics[metric_columns]

    merged = daily.merge(minute_metrics, on=["trade_date", "symbol"], how="left")
    minute_metric_value_columns = [
        column
        for column in metric_columns
        if column
        not in {
            "trade_date",
            "symbol",
            "missing_regular_session_detail",
            "missing_premarket_detail",
            "missing_afterhours_detail",
        }
    ]
    merged["minute_detail_missing"] = False
    if minute_metric_value_columns:
        missing_minute_rows = merged[minute_metric_value_columns].isna().all(axis=1)
        merged["minute_detail_missing"] = missing_minute_rows
        if bool(missing_minute_rows.any()):
            missing_count = int(missing_minute_rows.sum())
            sample_rows = merged.loc[missing_minute_rows, ["trade_date", "symbol"]].head(10)
            sample = ", ".join(
                f"{str(row.trade_date)}:{str(row.symbol)}"
                for row in sample_rows.itertuples(index=False)
            )
            logger.warning(
                "Session minute detail missing for %d symbol-day rows; minute-derived metrics will be filled with 0.0. Sample: %s",
                missing_count,
                sample or "n/a",
            )
    for bool_column in (
        "missing_regular_session_detail",
        "missing_premarket_detail",
        "missing_afterhours_detail",
    ):
        merged[bool_column] = merged.get(bool_column, False).map(_coerce_bool)
    for column in metric_columns:
        if column in {
            "trade_date",
            "symbol",
            "missing_regular_session_detail",
            "missing_premarket_detail",
            "missing_afterhours_detail",
        }:
            continue
        merged[column] = pd.to_numeric(merged.get(column), errors="coerce").fillna(0.0)

    close_hygiene = pd.to_numeric(merged.get("close_trade_hygiene_score"), errors="coerce")
    close_hygiene = close_hygiene.where(close_hygiene.notna(), np.where(merged.get("close_trade_has_lit_followthrough", False), 1.0, 0.0))
    close_hygiene = pd.Series(close_hygiene, index=merged.index).fillna(0.0).clip(lower=0.0, upper=1.0)
    merged["daily_close_hygiene"] = close_hygiene

    spread_component = 1.0 / (1.0 + (pd.to_numeric(merged["daily_avg_spread_bps_rth"], errors="coerce").fillna(0.0) / 25.0))
    merged["daily_clean_intraday_score"] = (
        merged["daily_rth_active_minutes_share"].map(_clip01)
        + merged["daily_rth_efficiency"].map(_clip01)
        + spread_component.clip(lower=0.0, upper=1.0)
        + (1.0 - merged["daily_rth_wickiness"].map(_clip01))
        + merged["daily_close_hygiene"].map(_clip01)
    ) / 5.0

    reclaim_flag = _series_from_frame(merged, "reclaimed_start_price_within_30s", False).map(_coerce_bool)
    early_dip_pct = pd.to_numeric(_series_from_frame(merged, "early_dip_pct_10s"), errors="coerce").fillna(0.0)
    followthrough_pct = pd.to_numeric(_series_from_frame(merged, "open_to_current_pct"), errors="coerce").fillna(
        pd.to_numeric(_series_from_frame(merged, "window_return_pct"), errors="coerce").fillna(0.0)
    )
    merged["daily_reclaim_respect_flag"] = reclaim_flag.astype(int)
    merged["daily_reclaim_failure_flag"] = ((early_dip_pct < 0) & (~reclaim_flag | (followthrough_pct <= 0))).astype(int)
    merged["daily_reclaim_followthrough_r"] = np.where(
        reclaim_flag & (early_dip_pct.abs() > 0.0001),
        followthrough_pct.abs() / early_dip_pct.abs().clip(lower=0.0001),
        0.0,
    )

    prev_day_high = pd.to_numeric(merged.get("prev_day_high"), errors="coerce")
    prev_day_low = pd.to_numeric(merged.get("prev_day_low"), errors="coerce")
    day_high = pd.to_numeric(merged.get("day_high"), errors="coerce")
    day_low = pd.to_numeric(merged.get("day_low"), errors="coerce")
    day_close = pd.to_numeric(merged.get("day_close"), errors="coerce")
    day_open = pd.to_numeric(merged.get("day_open"), errors="coerce")
    previous_close = pd.to_numeric(merged.get("previous_close"), errors="coerce")

    ob_up = prev_day_high.gt(0) & day_high.gt(prev_day_high) & day_close.lt(prev_day_high)
    ob_down = prev_day_low.gt(0) & day_low.lt(prev_day_low) & day_close.gt(prev_day_low)
    ob_depth = np.maximum(
        np.where(prev_day_high > 0, ((day_high - prev_day_high).clip(lower=0.0) / prev_day_high) * 100.0, 0.0),
        np.where(prev_day_low > 0, ((prev_day_low - day_low).clip(lower=0.0) / prev_day_low) * 100.0, 0.0),
    )
    merged["daily_ob_sweep_reversal_flag"] = (ob_up | ob_down).astype(int)
    merged["daily_ob_sweep_depth"] = pd.Series(ob_depth, index=merged.index).fillna(0.0)

    gap_up = day_open.gt(previous_close) & previous_close.gt(0)
    gap_down = day_open.lt(previous_close) & previous_close.gt(0)
    gap_size_up = (day_open - previous_close).clip(lower=0.0)
    gap_size_down = (previous_close - day_open).clip(lower=0.0)
    fvg_up = gap_up & day_low.le(previous_close) & day_close.gt(previous_close)
    fvg_down = gap_down & day_high.ge(previous_close) & day_close.lt(previous_close)
    fvg_depth_up = np.where(gap_size_up > 0, ((previous_close - day_low).clip(lower=0.0) / gap_size_up) * 100.0, 0.0)
    fvg_depth_down = np.where(gap_size_down > 0, ((day_high - previous_close).clip(lower=0.0) / gap_size_down) * 100.0, 0.0)
    merged["daily_fvg_sweep_reversal_flag"] = (fvg_up | fvg_down).astype(int)
    merged["daily_fvg_sweep_depth"] = pd.Series(np.maximum(fvg_depth_up, fvg_depth_down), index=merged.index).fillna(0.0)

    merged["daily_stop_hunt_flag"] = (
        merged["daily_ob_sweep_reversal_flag"].gt(0)
        | (reclaim_flag & early_dip_pct.abs().ge(0.3))
        | (merged["daily_rth_wickiness"].ge(0.55) & reclaim_flag)
    ).astype(int)
    merged["daily_stale_fail_flag"] = (
        merged["daily_open_30m_dollar_share"].ge(0.35)
        & merged["daily_midday_efficiency"].lt(0.35)
        & merged["daily_early_vs_late_followthrough_ratio"].gt(1.2)
        & pd.to_numeric(_series_from_frame(merged, "close_preclose_return_pct"), errors="coerce").fillna(0.0).lt(0.0)
    ).astype(int)

    return merged


def _consistency_score(group: pd.DataFrame) -> float:
    score_columns = [
        "daily_clean_intraday_score",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_midday_efficiency",
        "daily_close_hygiene",
    ]
    components: list[float] = []
    for column in score_columns:
        numeric = pd.to_numeric(group.get(column), errors="coerce").dropna()
        if numeric.empty:
            continue
        baseline = max(float(abs(numeric.mean())), 0.01)
        cv = float(numeric.std(ddof=0) / baseline)
        components.append(1.0 / (1.0 + cv))
    if not components:
        return 0.0
    return float(np.clip(np.mean(components), 0.0, 1.0))


def build_bundle_mapping_statuses(required_columns: list[str]) -> list[MappingStatus]:
    direct_fields = {
        "asof_date": MappingStatus("asof_date", "direct", "manifest", ["trade_dates_covered"], "Latest trade_date from the resolved Databento production bundle."),
        "symbol": MappingStatus("symbol", "direct", "daily_symbol_features_full_universe", ["symbol"], "Direct symbol from daily feature export."),
        "exchange": MappingStatus("exchange", "direct", "daily_symbol_features_full_universe", ["exchange"], "Direct exchange from daily feature export."),
    }
    derived_note = {
        "asset_type": "Derived from explicit asset_type when present, else ETF/fund keyword heuristic on company_name.",
        "universe_bucket": "Derived from asset_type and market_cap bands.",
        "history_coverage_days_20d": "Derived as trailing unique trade_date count per symbol, capped at 20 sessions.",
        "adv_dollar_rth_20d": "Derived from trailing regular-session dollar volume mean, with daily close*volume fallback.",
        "setup_decay_half_life_bars_20d": "Derived as the average half-life measured in 30-minute regular-session volume buckets, not literal chart bars.",
        "avg_spread_bps_rth_20d": "Derived from OHLCV bar spread proxies, not quote-level bid/ask spreads.",
        "pm_spread_bps_20d": "Derived from OHLCV bar spread proxies, not quote-level bid/ask spreads.",
        "midday_spread_bps_20d": "Derived from OHLCV bar spread proxies, not quote-level bid/ask spreads.",
        "ah_spread_bps_20d": "Derived from OHLCV bar spread proxies, not quote-level bid/ask spreads.",
        "wickiness_20d": "Derived from OHLCV candle wick geometry proxies, not quote-level microstructure measurements.",
        "pm_wickiness_20d": "Derived from OHLCV candle wick geometry proxies, not quote-level microstructure measurements.",
        "ah_wickiness_20d": "Derived from OHLCV candle wick geometry proxies, not quote-level microstructure measurements.",
    }
    statuses: list[MappingStatus] = []
    for field in required_columns:
        if field in direct_fields:
            statuses.append(direct_fields[field])
            continue
        note = derived_note.get(
            field,
            "Derived from the Databento production bundle plus session-minute detail generated by the base pipeline.",
        )
        statuses.append(
            MappingStatus(
                field,
                "derived",
                "daily_symbol_features_full_universe,session_minute_detail_full_universe",
                [],
                note,
            )
        )
    return statuses


def build_base_snapshot_from_bundle_payload(
    bundle_payload: dict[str, Any],
    *,
    schema_path: Path,
    session_minute_detail: pd.DataFrame | None = None,
    asof_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    schema = load_schema(schema_path)
    frames = bundle_payload["frames"]
    daily_features = frames["daily_symbol_features_full_universe"]
    if session_minute_detail is None:
        session_minute_detail = frames.get("session_minute_detail_full_universe", pd.DataFrame())
    symbol_day_features = build_symbol_day_microstructure_feature_frame(session_minute_detail, daily_features)
    if symbol_day_features.empty:
        raise RuntimeError("Unable to derive symbol-day microstructure features from the bundle")

    symbol_day_features["trade_date"] = pd.to_datetime(symbol_day_features["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    resolved_asof = asof_date or str(symbol_day_features["trade_date"].dropna().max())
    if not resolved_asof:
        raise RuntimeError("Unable to resolve asof_date from bundle symbol-day features")
    resolved_date = date.fromisoformat(resolved_asof)
    days_stale = (date.today() - resolved_date).days
    if days_stale > 5:
        warnings.warn(
            f"Microstructure base asof_date is {days_stale} days old; results may be stale.",
            stacklevel=2,
        )

    trailing = symbol_day_features.loc[symbol_day_features["trade_date"] <= resolved_asof].copy()
    trailing = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(20)

    latest = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(1)
    latest_by_symbol = latest.set_index("symbol", drop=False)
    rows: list[dict[str, Any]] = []
    minute_derived_aggregate_columns = {
        "daily_avg_spread_bps_rth",
        "daily_rth_active_minutes_share",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_clean_intraday_score",
        "daily_rth_wickiness",
        "daily_pm_dollar_share",
        "daily_pm_trades_share",
        "daily_pm_active_minutes_share",
        "daily_pm_spread_bps",
        "daily_pm_wickiness",
        "daily_midday_dollar_share",
        "daily_midday_trades_share",
        "daily_midday_active_minutes_share",
        "daily_midday_spread_bps",
        "daily_midday_efficiency",
        "daily_ah_dollar_share",
        "daily_ah_trades_share",
        "daily_ah_active_minutes_share",
        "daily_ah_spread_bps",
        "daily_ah_wickiness",
        "daily_setup_decay_half_life_bars",
        "daily_early_vs_late_followthrough_ratio",
        "daily_rth_efficiency",
        "daily_rth_dollar_volume",
    }

    for symbol, group in trailing.groupby("symbol", sort=True):
        latest_row = latest_by_symbol.loc[symbol]
        coverage_days = int(group["trade_date"].nunique())
        coverage_days_min = 5
        if coverage_days < coverage_days_min:
            logger.warning(
                "Symbol %s has only %d trading days in trailing window; "
                "coverage quality is limited and 20d metrics may be unstable.",
                symbol,
                coverage_days,
            )
        covered_group = group.loc[~group.get("minute_detail_missing", False).map(_coerce_bool)].copy()
        warned_missing_minute_detail = False

        def _group_for_metric(column: str) -> pd.DataFrame:
            nonlocal warned_missing_minute_detail
            if column not in minute_derived_aggregate_columns:
                return group
            if covered_group.empty and not warned_missing_minute_detail:
                logger.warning(
                    "Symbol %s has no symbol-day rows with minute detail coverage for minute-derived 20d aggregation; minute-derived metrics will fall back to 0.0.",
                    symbol,
                )
                warned_missing_minute_detail = True
            return covered_group

        daily_close = pd.to_numeric(group.get("day_close"), errors="coerce")
        day_volume = pd.to_numeric(group.get("day_volume"), errors="coerce")
        adv_fallback = (daily_close * day_volume).replace([np.inf, -np.inf], np.nan)
        adv_group = _group_for_metric("daily_rth_dollar_volume")
        adv_rth = pd.to_numeric(adv_group.get("daily_rth_dollar_volume"), errors="coerce")
        adv_dollar = adv_rth.where(adv_rth > 0).combine_first(adv_fallback)

        rows.append(
            {
                "asof_date": resolved_asof,
                "symbol": symbol,
                "exchange": str(latest_row.get("exchange") or "").upper(),
                "asset_type": infer_asset_type(str(latest_row.get("company_name") or ""), str(latest_row.get("asset_type") or "")),
                "universe_bucket": infer_universe_bucket(
                    infer_asset_type(str(latest_row.get("company_name") or ""), str(latest_row.get("asset_type") or "")),
                    _safe_float(latest_row.get("market_cap"), default=np.nan),
                ),
                "history_coverage_days_20d": coverage_days,
                "adv_dollar_rth_20d": _mean_or_default(adv_dollar, default=0.0),
                "avg_spread_bps_rth_20d": _mean_or_default(_group_for_metric("daily_avg_spread_bps_rth")["daily_avg_spread_bps_rth"], default=0.0),
                "rth_active_minutes_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_rth_active_minutes_share")["daily_rth_active_minutes_share"], default=0.0)
                ),
                "open_30m_dollar_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_open_30m_dollar_share")["daily_open_30m_dollar_share"], default=0.0)
                ),
                "close_60m_dollar_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_close_60m_dollar_share")["daily_close_60m_dollar_share"], default=0.0)
                ),
                "clean_intraday_score_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_clean_intraday_score")["daily_clean_intraday_score"], default=0.0)
                ),
                "consistency_score_20d": _clip01(_consistency_score(_group_for_metric("daily_clean_intraday_score"))),
                "close_hygiene_20d": _clip01(_mean_or_default(group["daily_close_hygiene"], default=0.0)),
                "wickiness_20d": _clip01(_mean_or_default(_group_for_metric("daily_rth_wickiness")["daily_rth_wickiness"], default=0.0)),
                "pm_dollar_share_20d": _clip01(_mean_or_default(_group_for_metric("daily_pm_dollar_share")["daily_pm_dollar_share"], default=0.0)),
                "pm_trades_share_20d": _clip01(_mean_or_default(_group_for_metric("daily_pm_trades_share")["daily_pm_trades_share"], default=0.0)),
                "pm_active_minutes_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_pm_active_minutes_share")["daily_pm_active_minutes_share"], default=0.0)
                ),
                "pm_spread_bps_20d": _mean_or_default(_group_for_metric("daily_pm_spread_bps")["daily_pm_spread_bps"], default=0.0),
                "pm_wickiness_20d": _clip01(_mean_or_default(_group_for_metric("daily_pm_wickiness")["daily_pm_wickiness"], default=0.0)),
                "midday_dollar_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_midday_dollar_share")["daily_midday_dollar_share"], default=0.0)
                ),
                "midday_trades_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_midday_trades_share")["daily_midday_trades_share"], default=0.0)
                ),
                "midday_active_minutes_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_midday_active_minutes_share")["daily_midday_active_minutes_share"], default=0.0)
                ),
                "midday_spread_bps_20d": _mean_or_default(
                    _group_for_metric("daily_midday_spread_bps")["daily_midday_spread_bps"], default=0.0
                ),
                "midday_efficiency_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_midday_efficiency")["daily_midday_efficiency"], default=0.0)
                ),
                "ah_dollar_share_20d": _clip01(_mean_or_default(_group_for_metric("daily_ah_dollar_share")["daily_ah_dollar_share"], default=0.0)),
                "ah_trades_share_20d": _clip01(_mean_or_default(_group_for_metric("daily_ah_trades_share")["daily_ah_trades_share"], default=0.0)),
                "ah_active_minutes_share_20d": _clip01(
                    _mean_or_default(_group_for_metric("daily_ah_active_minutes_share")["daily_ah_active_minutes_share"], default=0.0)
                ),
                "ah_spread_bps_20d": _mean_or_default(_group_for_metric("daily_ah_spread_bps")["daily_ah_spread_bps"], default=0.0),
                "ah_wickiness_20d": _clip01(_mean_or_default(_group_for_metric("daily_ah_wickiness")["daily_ah_wickiness"], default=0.0)),
                "reclaim_respect_rate_20d": _clip01(_mean_or_default(group["daily_reclaim_respect_flag"], default=0.0)),
                "reclaim_failure_rate_20d": _clip01(_mean_or_default(group["daily_reclaim_failure_flag"], default=0.0)),
                "reclaim_followthrough_r_20d": _mean_or_default(group["daily_reclaim_followthrough_r"], default=0.0),
                "ob_sweep_reversal_rate_20d": _clip01(_mean_or_default(group["daily_ob_sweep_reversal_flag"], default=0.0)),
                "ob_sweep_depth_p75_20d": _quantile_or_default(group["daily_ob_sweep_depth"], 0.75, default=0.0),
                "fvg_sweep_reversal_rate_20d": _clip01(_mean_or_default(group["daily_fvg_sweep_reversal_flag"], default=0.0)),
                "fvg_sweep_depth_p75_20d": _quantile_or_default(group["daily_fvg_sweep_depth"], 0.75, default=0.0),
                "stop_hunt_rate_20d": _clip01(_mean_or_default(group["daily_stop_hunt_flag"], default=0.0)),
                "setup_decay_half_life_bars_20d": _mean_or_default(
                    _group_for_metric("daily_setup_decay_half_life_bars")["daily_setup_decay_half_life_bars"], default=0.0
                ),
                "early_vs_late_followthrough_ratio_20d": _mean_or_default(
                    _group_for_metric("daily_early_vs_late_followthrough_ratio")["daily_early_vs_late_followthrough_ratio"], default=0.0
                ),
                "stale_fail_rate_20d": _clip01(_mean_or_default(group["daily_stale_fail_flag"], default=0.0)),
            }
        )

    output = pd.DataFrame(rows)
    required_columns = [str(column) for column in schema["required_columns"]]
    for column in required_columns:
        if column not in output.columns:
            output[column] = 0.0
    output = output[required_columns].sort_values(["symbol"]).reset_index(drop=True)

    statuses = build_bundle_mapping_statuses(required_columns)
    payload = {
        "bundle_manifest_path": str(bundle_payload["manifest_path"]),
        "asof_date": resolved_asof,
        "row_count": len(output),
        "direct_fields": [status.field for status in statuses if status.status == "direct"],
        "derived_fields": [status.field for status in statuses if status.status == "derived"],
        "missing_fields": [],
        "mapping_status": [
            {
                "field": status.field,
                "status": status.status,
                "source_sheet": status.source_sheet,
                "source_columns": status.source_columns,
                "note": status.note,
            }
            for status in statuses
        ],
    }
    return output, payload, symbol_day_features


def write_mapping_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def md_row(*cells: str) -> str:
        return "|" + "|".join(cells) + "|"

    lines = [
        f"# Databento Bundle To Microstructure Base Mapping: {Path(payload['bundle_manifest_path']).name}",
        "",
        f"- Bundle manifest: {payload['bundle_manifest_path']}",
        f"- Selected asof_date: {payload['asof_date']}",
        f"- Output rows: {payload['row_count']}",
        f"- Direct fields: {len(payload['direct_fields'])}",
        f"- Derived fields: {len(payload['derived_fields'])}",
        f"- Missing fields: {len(payload['missing_fields'])}",
        "",
        md_row("Contract field", "Status", "Source sheet", "Source columns", "Note"),
        md_row("---", "---", "---", "---", "---"),
    ]
    for status in payload["mapping_status"]:
        source_columns = ", ".join(status["source_columns"]) if status["source_columns"] else ""
        lines.append(md_row(status["field"], status["status"], status["source_sheet"], source_columns, status["note"]))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def write_base_workbook(path: Path, base_snapshot: pd.DataFrame, mapping_payload: dict[str, Any]) -> None:
    excel_max_rows = 1_048_576
    max_data_rows_per_sheet = max(1, excel_max_rows - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    mapping_frame = pd.DataFrame(mapping_payload["mapping_status"])
    base_sheet_count = max(1, int(math.ceil(len(base_snapshot) / max_data_rows_per_sheet)))
    summary_frame = pd.DataFrame(
        [
            {
                "bundle_manifest_path": mapping_payload["bundle_manifest_path"],
                "asof_date": mapping_payload["asof_date"],
                "row_count": mapping_payload["row_count"],
                "base_snapshot_sheet_count": base_sheet_count,
                "direct_fields": len(mapping_payload["direct_fields"]),
                "derived_fields": len(mapping_payload["derived_fields"]),
                "missing_fields": len(mapping_payload["missing_fields"]),
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet_index, start_row in enumerate(range(0, len(base_snapshot), max_data_rows_per_sheet), start=1):
            end_row = start_row + max_data_rows_per_sheet
            sheet_name = "base_snapshot" if sheet_index == 1 else f"base_snapshot_{sheet_index:03d}"
            base_snapshot.iloc[start_row:end_row].to_excel(writer, sheet_name=sheet_name, index=False)
        if base_snapshot.empty:
            base_snapshot.to_excel(writer, sheet_name="base_snapshot", index=False)
        elif base_sheet_count > 1:
            logger.warning(
                "Base snapshot exceeded Excel row limit; wrote %d rows across %d sheets.",
                len(base_snapshot),
                base_sheet_count,
            )
        summary_frame.to_excel(writer, sheet_name="summary", index=False)
        mapping_frame.to_excel(writer, sheet_name="mapping_status", index=False)


def write_base_manifest(
    path: Path,
    *,
    bundle_manifest_path: Path,
    asof_date: str,
    base_csv_path: Path,
    base_xlsx_path: Path | None,
    micro_day_parquet_path: Path,
    mapping_md_path: Path,
    mapping_json_path: Path,
    production_workbook_path: Path | None,
    library_owner: str,
    library_version: int,
    core_ready: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "asof_date": asof_date,
        "bundle_manifest_path": str(bundle_manifest_path),
        "base_csv_path": str(base_csv_path),
        "base_xlsx_path": str(base_xlsx_path) if base_xlsx_path is not None else None,
        "micro_day_parquet_path": str(micro_day_parquet_path),
        "mapping_md_path": str(mapping_md_path),
        "mapping_json_path": str(mapping_json_path),
        "production_workbook_path": str(production_workbook_path) if production_workbook_path is not None else None,
        "canonical_upstream_artifact": "databento_production_export_bundle",
        "recommended_library_import": f"{library_owner}/smc_micro_profiles_generated/{library_version}",
        "core_ready": core_ready,
        "core_ready_note": "core_ready only describes the generated base snapshot artifact state; TradingView contract readiness is validated later via verify_publish_contract and tv_publish_micro_library.",
        "tradingview_publish_required": True,
        "tradingview_publish_note": "The Pine library artifact is ready for manual TradingView publish; SMC_Core_Engine already imports the generated library path.",
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def build_default_output_paths(base_prefix: str, output_dir: Path, asof_date: str) -> dict[str, Path]:
    safe_prefix = base_prefix or f"databento_microstructure_{asof_date}"
    return {
        "base_csv": output_dir / f"{safe_prefix}__smc_microstructure_base_{asof_date}.csv",
        "base_xlsx": output_dir / f"{safe_prefix}__smc_microstructure_base_{asof_date}.xlsx",
        "micro_day_parquet": output_dir / f"{safe_prefix}__smc_microstructure_symbol_day_features.parquet",
        "mapping_md": output_dir / f"{safe_prefix}__smc_microstructure_mapping_{asof_date}.md",
        "mapping_json": output_dir / f"{safe_prefix}__smc_microstructure_mapping_{asof_date}.json",
        "base_manifest": output_dir / f"{safe_prefix}__smc_microstructure_base_manifest.json",
        "session_minute_parquet": output_dir / f"{safe_prefix}__session_minute_detail_full_universe.parquet",
    }


def generate_base_from_bundle(
    bundle: str | Path | dict[str, Any],
    *,
    schema_path: Path,
    output_dir: Path | None = None,
    asof_date: str | None = None,
    write_xlsx: bool = True,
    session_minute_detail: pd.DataFrame | None = None,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
) -> dict[str, Any]:
    bundle_payload = bundle if isinstance(bundle, dict) else load_export_bundle(
        bundle,
        required_frames=REQUIRED_BUNDLE_FRAMES,
        manifest_prefix="databento_volatility_production_",
    )
    target_dir = output_dir or Path(bundle_payload["bundle_dir"])
    base_snapshot, mapping_payload, symbol_day_features = build_base_snapshot_from_bundle_payload(
        bundle_payload,
        schema_path=schema_path,
        session_minute_detail=session_minute_detail,
        asof_date=asof_date,
    )
    output_paths = build_default_output_paths(bundle_payload["base_prefix"], target_dir, mapping_payload["asof_date"])
    output_paths["base_csv"].parent.mkdir(parents=True, exist_ok=True)
    base_snapshot.to_csv(output_paths["base_csv"], index=False)
    symbol_day_features.to_parquet(output_paths["micro_day_parquet"], index=False)
    workbook_warning: str | None = None
    workbook_written = False
    if write_xlsx:
        try:
            write_base_workbook(output_paths["base_xlsx"], base_snapshot, mapping_payload)
        except ModuleNotFoundError as exc:
            missing_name = str(getattr(exc, "name", "") or "")
            if missing_name.startswith("openpyxl"):
                workbook_warning = (
                    "XLSX workbook export was skipped because the active Python environment has an incomplete "
                    f"openpyxl installation ({missing_name}). CSV, Parquet, JSON, and Markdown artifacts were still written."
                )
                logger.warning(workbook_warning)
            else:
                raise
        else:
            workbook_written = True
    effective_output_paths = dict(output_paths)
    if write_xlsx and not workbook_written:
        effective_output_paths.pop("base_xlsx", None)
    write_mapping_report(output_paths["mapping_md"], mapping_payload)
    output_paths["mapping_json"].write_text(json.dumps(mapping_payload, indent=2) + "\n", encoding="utf-8")
    write_base_manifest(
        output_paths["base_manifest"],
        bundle_manifest_path=Path(bundle_payload["manifest_path"]),
        asof_date=mapping_payload["asof_date"],
        base_csv_path=output_paths["base_csv"],
        base_xlsx_path=output_paths["base_xlsx"] if workbook_written else None,
        micro_day_parquet_path=output_paths["micro_day_parquet"],
        mapping_md_path=output_paths["mapping_md"],
        mapping_json_path=output_paths["mapping_json"],
        production_workbook_path=None,
        library_owner=library_owner,
        library_version=library_version,
        core_ready=False,
    )
    return {
        "bundle_manifest_path": Path(bundle_payload["manifest_path"]),
        "base_snapshot": base_snapshot,
        "mapping_payload": mapping_payload,
        "symbol_day_features": symbol_day_features,
        "output_paths": effective_output_paths,
        "warnings": [workbook_warning] if workbook_warning else [],
        "workbook_written": workbook_written,
    }


def run_databento_base_scan_pipeline(
    *,
    databento_api_key: str,
    fmp_api_key: str = "",
    dataset: str,
    export_dir: Path,
    schema_path: Path,
    lookback_days: int = 30,
    force_refresh: bool = False,
    cache_dir: Path | None = None,
    use_file_cache: bool = True,
    display_timezone: str = "Europe/Berlin",
    bullish_score_profile: str = "balanced",
    smc_base_only: bool = True,
    write_xlsx: bool = True,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    progress_callback: Any = None,
) -> dict[str, Any]:
    def _progress(message: str) -> None:
        logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    export_result = run_production_export_pipeline(
        databento_api_key=databento_api_key,
        fmp_api_key=fmp_api_key,
        dataset=dataset,
        lookback_days=int(lookback_days),
        export_dir=export_dir,
        cache_dir=cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
        second_detail_scope="full_universe",
        bullish_score_profile=bullish_score_profile,
        smc_base_only=smc_base_only,
        progress_callback=progress_callback,
    )
    manifest_path = Path(export_result["exported_paths"]["manifest"])
    bundle_payload = load_export_bundle(
        manifest_path,
        required_frames=REQUIRED_BUNDLE_FRAMES,
        manifest_prefix="databento_volatility_production_",
    )
    trading_days = _build_trade_date_scope(bundle_payload["manifest"])
    daily_feature_frame = bundle_payload["frames"]["daily_symbol_features_full_universe"]
    if not trading_days and "trade_date" in daily_feature_frame.columns:
        trading_days = sorted(
            {
                pd.Timestamp(value).date()
                for value in pd.to_datetime(daily_feature_frame["trade_date"], errors="coerce").dropna()
            }
        )
    if not trading_days:
        raise RuntimeError(
            "Unable to resolve trade dates for the SMC base scan. The export manifest is missing trade_dates_covered "
            "and no fallback trade_date values were available in daily_symbol_features_full_universe."
        )
    intraday_expected = daily_feature_frame.copy()
    intraday_expected["trade_date"] = pd.to_datetime(intraday_expected.get("trade_date"), errors="coerce").dt.date
    intraday_expected["symbol"] = intraday_expected.get("symbol", pd.Series(index=intraday_expected.index, dtype=object)).astype(str).str.upper()
    has_intraday_available = "has_intraday" in intraday_expected.columns
    if has_intraday_available:
        intraday_expected["has_intraday"] = intraday_expected["has_intraday"].map(_coerce_bool)
    else:
        intraday_expected["has_intraday"] = pd.Series(True, index=intraday_expected.index, dtype=bool)
        logger.warning(
            "daily_symbol_features_full_universe is missing has_intraday; defaulting to fetch all symbol-days for minute detail coverage."
        )
    intraday_expected = intraday_expected.loc[
        intraday_expected["trade_date"].notna() & intraday_expected["symbol"].ne("")
    ].copy()
    if has_intraday_available:
        has_intraday_false_count = int((~intraday_expected["has_intraday"]).sum())
        if has_intraday_false_count > 0:
            logger.warning(
                "daily_symbol_features_full_universe contains %d symbol-days with has_intraday=False; keeping them in minute-detail fetch scope and treating has_intraday as diagnostic-only.",
                has_intraday_false_count,
            )
    expected_symbols_by_trade_day = {
        trade_day: set(group["symbol"].tolist())
        for trade_day, group in intraday_expected.groupby("trade_date", sort=False)
    }
    universe_symbols = set(daily_feature_frame["symbol"].dropna().astype(str).str.upper())

    _progress("Step 11/12: Collecting full-session minute detail for microstructure base derivation...")
    session_minute_detail = collect_full_universe_session_minute_detail(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        expected_symbols_by_trade_day=expected_symbols_by_trade_day,
        display_timezone=display_timezone,
        cache_dir=cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    output_paths = build_default_output_paths(bundle_payload["base_prefix"], export_dir, str(max(trading_days).isoformat()))
    if not session_minute_detail.empty:
        session_minute_detail.to_parquet(output_paths["session_minute_parquet"], index=False)
        bundle_payload["frames"]["session_minute_detail_full_universe"] = session_minute_detail

    _progress("Step 12/12: Building SMC microstructure base snapshot...")
    canonical_production_workbook = export_result.get("exported_paths", {}).get("canonical_production_workbook")
    base_result = generate_base_from_bundle(
        bundle_payload,
        schema_path=schema_path,
        output_dir=export_dir,
        write_xlsx=write_xlsx,
        session_minute_detail=session_minute_detail,
        library_owner=library_owner,
        library_version=library_version,
    )
    base_manifest_path = base_result["output_paths"].get("base_manifest")
    if base_manifest_path is not None:
        try:
            manifest_payload = json.loads(Path(base_manifest_path).read_text(encoding="utf-8"))
            if isinstance(manifest_payload, dict):
                manifest_payload["production_workbook_path"] = str(canonical_production_workbook) if canonical_production_workbook else None
                manifest_payload["canonical_upstream_artifact"] = "databento_production_export_bundle"
                Path(base_manifest_path).write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
        except Exception:
            logger.warning("Failed to enrich base manifest with production workbook lineage", exc_info=True)
    base_result["production_workbook_path"] = Path(canonical_production_workbook) if canonical_production_workbook else None
    base_result["export_result"] = export_result
    return base_result


def generate_pine_library_from_base(
    *,
    base_csv_path: Path,
    schema_path: Path,
    output_root: Path,
    overrides_path: Path | None = None,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    enrichment: EnrichmentDict | None = None,
) -> dict[str, Path]:
    """Generate a Pine library from a base snapshot CSV.

    Thin wrapper around :func:`scripts.generate_smc_micro_profiles.run_generation`
    that provides the stable public API for callers like ``finalize_pipeline()``
    and the Streamlit UI.

    Parameters
    ----------
    base_csv_path:
        Path to a validated microstructure base snapshot CSV.
    schema_path:
        Path to the JSON microstructure schema.
    output_root:
        Directory for all generated artifacts (Pine, state CSV, manifest, etc.).
    overrides_path:
        Optional per-run membership overrides CSV.
    library_owner:
        TradingView owner name emitted in the import snippet.
    library_version:
        TradingView library version for import metadata.
    enrichment:
        Optional enrichment dict produced by ``build_enrichment()``.
        When provided, the generated Pine library includes extra
        ``export const`` blocks for regime, news, calendar, layering,
        provider status, and volume-regime data.  When ``None``, all
        enrichment constants receive safe neutral defaults.

    Returns
    -------
    dict[str, Path]
        Mapping of artifact names to their written file paths
        (e.g. ``{"pine_path": Path(...), "features_path": Path(...), ...}``).
    """
    return run_generation(
        schema_path=schema_path,
        input_path=base_csv_path,
        overrides_path=overrides_path,
        output_root=output_root,
        library_owner=library_owner,
        library_version=library_version,
        enrichment=enrichment,
    )


