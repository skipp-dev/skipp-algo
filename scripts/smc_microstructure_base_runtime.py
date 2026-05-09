from __future__ import annotations

import json
import logging
import math
import time as time_module
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from databento_provider import list_recent_trading_days
from databento_utils import US_EASTERN_TZ
from scripts.databento_production_export import run_production_export_pipeline
from scripts.generate_smc_micro_profiles import load_schema, run_generation
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.smc_atomic_write import atomic_write_csv, atomic_write_parquet, atomic_write_text
from scripts.smc_databento_session_detail import (
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
from scripts.smc_enrichment_types import EnrichmentDict

# ── Re-exports from extracted modules (backward compatibility) ──────
from scripts.smc_micro_publish_guard import (
    evaluate_micro_library_publish_guard,
    inspect_generated_micro_library_contract,
    publish_micro_library_to_tradingview,
)
from scripts.smc_micro_streamlit_app import (
    _resolve_ui_dataset_options,
    list_generated_base_csvs,
    resolve_base_csv_action_target,
    resolve_base_csv_selection,
    run_streamlit_micro_base_app,
)

# Public re-export surface (backward compatibility for legacy importers).
__all__ = [
    "_assert_complete_symbol_coverage",
    "_coverage_stats",
    "_resolve_ui_dataset_options",
    "_universe_fingerprint",
    "evaluate_micro_library_publish_guard",
    "inspect_generated_micro_library_contract",
    "list_generated_base_csvs",
    "publish_micro_library_to_tradingview",
    "resolve_base_csv_action_target",
    "resolve_base_csv_selection",
    "run_streamlit_micro_base_app",
]

_ET = ZoneInfo("America/New_York")


def _today_et() -> date:
    """Return today's date in US/Eastern. Hookable for deterministic tests."""
    return datetime.now(_ET).date()


logger = logging.getLogger(__name__)

REQUIRED_BUNDLE_FRAMES = (
    "daily_bars",
    "daily_symbol_features_full_universe",
)

INCREMENTAL_BASE_SEED_DIR_NAME = "incremental_base_seed"
INCREMENTAL_BASE_SEED_MANIFEST_NAME = "smc_incremental_base_seed.json"
INCREMENTAL_BASE_SEED_DAILY_BARS_NAME = "daily_bars.parquet"
INCREMENTAL_BASE_SEED_DAILY_FEATURES_NAME = "daily_symbol_features_full_universe.parquet"
INCREMENTAL_BASE_SEED_SYMBOL_DAY_FEATURES_NAME = "symbol_day_features.parquet"
INCREMENTAL_BASE_SEED_DIAGNOSTICS_NAME = "symbol_day_diagnostics.parquet"
SYMBOL_DAY_FEATURE_BATCH_ROW_THRESHOLD = 2_000_000

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
    numeric = _safe_float(value, default=np.nan)
    if not np.isfinite(numeric):
        return 0.0
    return float(max(0.0, min(1.0, numeric)))


def _incremental_base_seed_dir(export_dir: Path) -> Path:
    return export_dir / INCREMENTAL_BASE_SEED_DIR_NAME


def _incremental_base_seed_paths(export_dir: Path) -> dict[str, Path]:
    seed_dir = _incremental_base_seed_dir(export_dir)
    return {
        "seed_dir": seed_dir,
        "manifest": seed_dir / INCREMENTAL_BASE_SEED_MANIFEST_NAME,
        "daily_bars": seed_dir / INCREMENTAL_BASE_SEED_DAILY_BARS_NAME,
        "daily_features": seed_dir / INCREMENTAL_BASE_SEED_DAILY_FEATURES_NAME,
        "symbol_day_features": seed_dir / INCREMENTAL_BASE_SEED_SYMBOL_DAY_FEATURES_NAME,
        "symbol_day_diagnostics": seed_dir / INCREMENTAL_BASE_SEED_DIAGNOSTICS_NAME,
    }


def _merge_incremental_frame(
    previous: pd.DataFrame,
    current: pd.DataFrame,
    *,
    key_columns: list[str],
    sort_columns: list[str],
) -> pd.DataFrame:
    if previous.empty:
        merged = current.copy()
    elif current.empty:
        merged = previous.copy()
    else:
        prev = previous.copy()
        curr = current.copy()
        for column in key_columns:
            if column in prev.columns:
                if column == "trade_date":
                    prev[column] = pd.to_datetime(prev[column], errors="coerce").dt.date
                elif column == "symbol":
                    prev[column] = prev[column].astype(str).str.upper()
            if column in curr.columns:
                if column == "trade_date":
                    curr[column] = pd.to_datetime(curr[column], errors="coerce").dt.date
                elif column == "symbol":
                    curr[column] = curr[column].astype(str).str.upper()
        merged = pd.concat([prev, curr], ignore_index=True)
        merged = merged.drop_duplicates(subset=key_columns, keep="last")
    if sort_columns:
        available_sort_columns = [column for column in sort_columns if column in merged.columns]
        if available_sort_columns:
            merged = merged.sort_values(available_sort_columns).reset_index(drop=True)
    return merged


def _tail_trade_days(frame: pd.DataFrame, *, trade_days: list[date]) -> pd.DataFrame:
    if frame.empty or not trade_days or "trade_date" not in frame.columns:
        return frame.copy()
    scoped = frame.copy()
    scoped["trade_date"] = pd.to_datetime(scoped["trade_date"], errors="coerce").dt.date
    return scoped.loc[scoped["trade_date"].isin(set(trade_days))].reset_index(drop=True)


def _recompute_daily_feature_volume_rollups(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    features = frame.copy()
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce").dt.date
    features["symbol"] = features["symbol"].astype(str).str.upper()
    features = features.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    for column in ("open_1m_volume", "open_5m_volume", "day_volume"):
        if column not in features.columns:
            features[column] = np.nan
        features[column] = pd.to_numeric(features[column], errors="coerce")
    features["avg_open_1m_volume_20d"] = features.groupby("symbol")["open_1m_volume"].transform(
        lambda series: series.shift(1).rolling(20, min_periods=1).mean()
    )
    features["avg_open_5m_volume_20d"] = features.groupby("symbol")["open_5m_volume"].transform(
        lambda series: series.shift(1).rolling(20, min_periods=1).mean()
    )
    features["avg_day_volume_20d"] = features.groupby("symbol")["day_volume"].transform(
        lambda series: series.shift(1).rolling(20, min_periods=1).mean()
    )
    avg_open_1m = pd.to_numeric(features["avg_open_1m_volume_20d"], errors="coerce")
    avg_open_5m = pd.to_numeric(features["avg_open_5m_volume_20d"], errors="coerce")
    avg_day = pd.to_numeric(features["avg_day_volume_20d"], errors="coerce")
    features["open_1m_rvol_20d"] = np.where(
        avg_open_1m > 0,
        pd.to_numeric(features["open_1m_volume"], errors="coerce") / avg_open_1m,
        np.nan,
    )
    features["open_5m_rvol_20d"] = np.where(
        avg_open_5m > 0,
        pd.to_numeric(features["open_5m_volume"], errors="coerce") / avg_open_5m,
        np.nan,
    )
    features["day_volume_rvol_20d"] = np.where(
        avg_day > 0,
        pd.to_numeric(features["day_volume"], errors="coerce") / avg_day,
        np.nan,
    )
    return features


def _load_incremental_base_seed(export_dir: Path) -> dict[str, Any] | None:
    paths = _incremental_base_seed_paths(export_dir)
    required = ("manifest", "daily_bars", "daily_features", "symbol_day_features")
    if any(not paths[name].exists() for name in required):
        return None
    try:
        manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return None
        seed: dict[str, Any] = {
            "manifest": manifest,
            "daily_bars": pd.read_parquet(paths["daily_bars"]),
            "daily_features": pd.read_parquet(paths["daily_features"]),
            "symbol_day_features": pd.read_parquet(paths["symbol_day_features"]),
            "paths": paths,
        }
        if paths["symbol_day_diagnostics"].exists():
            seed["symbol_day_diagnostics"] = pd.read_parquet(paths["symbol_day_diagnostics"])
        else:
            seed["symbol_day_diagnostics"] = pd.DataFrame()
        return seed
    except Exception:
        logger.warning("Failed to load incremental base seed from %s", export_dir, exc_info=True)
        return None


def _write_incremental_base_seed(
    export_dir: Path,
    *,
    bundle_manifest_path: Path,
    asof_date: str,
    trade_dates_covered: list[str],
    daily_bars: pd.DataFrame,
    daily_features: pd.DataFrame,
    symbol_day_features: pd.DataFrame,
    symbol_day_diagnostics: pd.DataFrame,
) -> None:
    paths = _incremental_base_seed_paths(export_dir)
    paths["seed_dir"].mkdir(parents=True, exist_ok=True)
    # A-1: atomic writes (tempfile + os.replace) to prevent truncated parquet on crash.
    atomic_write_parquet(pd.DataFrame(daily_bars), paths["daily_bars"], index=False)
    atomic_write_parquet(pd.DataFrame(daily_features), paths["daily_features"], index=False)
    atomic_write_parquet(pd.DataFrame(symbol_day_features), paths["symbol_day_features"], index=False)
    atomic_write_parquet(pd.DataFrame(symbol_day_diagnostics), paths["symbol_day_diagnostics"], index=False)
    payload = {
        "bundle_manifest_path": str(bundle_manifest_path),
        "asof_date": str(asof_date),
        "trade_dates_covered": [str(item) for item in trade_dates_covered],
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    atomic_write_text(json.dumps(payload, indent=2) + "\n", paths["manifest"])


def _resolve_incremental_trade_days(trading_days: list[date], previous_asof_date: date | None) -> list[date]:
    if not trading_days:
        return []
    if previous_asof_date is None:
        return list(trading_days)
    if previous_asof_date not in trading_days:
        return list(trading_days)
    previous_index = trading_days.index(previous_asof_date)
    start_index = max(0, previous_index - 1)
    return list(trading_days[start_index:])


def _build_base_snapshot_from_symbol_day_features(
    symbol_day_features: pd.DataFrame,
    *,
    schema_path: Path,
    asof_date: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if symbol_day_features.empty:
        raise RuntimeError("Unable to derive symbol-day microstructure features from the bundle")

    schema = load_schema(schema_path)
    trailing_source = symbol_day_features.copy()
    trailing_source["trade_date"] = pd.to_datetime(trailing_source["trade_date"], errors="coerce").dt.strftime("%Y-%m-%d")
    resolved_asof = asof_date or str(trailing_source["trade_date"].dropna().max())
    if not resolved_asof:
        raise RuntimeError("Unable to resolve asof_date from symbol-day features")
    resolved_date = date.fromisoformat(resolved_asof)
    days_stale = (_today_et() - resolved_date).days
    if days_stale > 5:
        warnings.warn(
            f"Microstructure base asof_date is {days_stale} days old; results may be stale.",
            stacklevel=2,
        )

    trailing = trailing_source.loc[trailing_source["trade_date"] <= resolved_asof].copy()
    trailing = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(20)
    for target_column, legacy_column in (("day_close", "close"), ("day_volume", "volume")):
        if target_column not in trailing.columns:
            logger.warning(
                "Bundle symbol-day features missing %s; falling back to %s for compatibility.",
                target_column,
                legacy_column,
            )
            trailing[target_column] = pd.to_numeric(
                _series_from_frame(trailing, legacy_column, np.nan),
                errors="coerce",
            )
    trailing["minute_detail_missing_bool"] = _coerce_bool_series(_series_from_frame(trailing, "minute_detail_missing", False))
    trailing["missing_regular_session_detail_bool"] = _coerce_bool_series(
        _series_from_frame(trailing, "missing_regular_session_detail", False)
    )
    trailing["missing_midday_detail_bool"] = _coerce_bool_series(
        _series_from_frame(trailing, "missing_midday_detail", False)
    )

    latest = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(1)
    latest_by_symbol = latest.set_index("symbol", drop=False)
    rows: list[dict[str, Any]] = []
    consistency_score_columns = [
        "daily_clean_intraday_score",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_midday_efficiency",
        "daily_close_hygiene",
    ]
    minute_mean_columns = [
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
    ]
    group_mean_columns = [
        "daily_close_hygiene",
        "daily_reclaim_respect_flag",
        "daily_reclaim_failure_flag",
        "daily_reclaim_followthrough_r",
        "daily_ob_sweep_reversal_flag",
        "daily_fvg_sweep_reversal_flag",
        "daily_stop_hunt_flag",
        "daily_stale_fail_flag",
    ]
    trailing_numeric_columns: list[str] = []
    for column in minute_mean_columns + group_mean_columns + [
        "daily_rth_dollar_volume",
        "daily_ob_sweep_depth",
        "daily_fvg_sweep_depth",
        "day_close",
        "day_volume",
    ]:
        if column not in trailing_numeric_columns:
            trailing_numeric_columns.append(column)
    minute_mean_indices = [trailing_numeric_columns.index(column) for column in minute_mean_columns]
    group_mean_indices = [trailing_numeric_columns.index(column) for column in group_mean_columns]
    consistency_score_indices = [trailing_numeric_columns.index(column) for column in consistency_score_columns]
    adv_rth_index = trailing_numeric_columns.index("daily_rth_dollar_volume")
    ob_sweep_depth_index = trailing_numeric_columns.index("daily_ob_sweep_depth")
    fvg_sweep_depth_index = trailing_numeric_columns.index("daily_fvg_sweep_depth")
    day_close_index = trailing_numeric_columns.index("day_close")
    day_volume_index = trailing_numeric_columns.index("day_volume")

    for symbol, group in trailing.groupby("symbol", sort=True):
        latest_row = latest_by_symbol.loc[symbol]
        coverage_days = int(group["trade_date"].nunique())
        coverage_gap_mask = (
            group["missing_regular_session_detail_bool"].to_numpy(dtype=bool, copy=False)
            | group["missing_midday_detail_bool"].to_numpy(dtype=bool, copy=False)
        )
        covered_mask = ~(
            group["minute_detail_missing_bool"].to_numpy(dtype=bool, copy=False)
            | coverage_gap_mask
        )
        numeric_values = group[trailing_numeric_columns].to_numpy(dtype=float, copy=False)
        covered_numeric_values = numeric_values[covered_mask]
        minute_means = _nanmean_columns_or_zero(covered_numeric_values[:, minute_mean_indices])
        group_means = _nanmean_columns_or_zero(numeric_values[:, group_mean_indices])
        (
            avg_spread_bps_rth_20d,
            rth_active_minutes_share_20d,
            open_30m_dollar_share_20d,
            close_60m_dollar_share_20d,
            clean_intraday_score_20d,
            wickiness_20d,
            pm_dollar_share_20d,
            pm_trades_share_20d,
            pm_active_minutes_share_20d,
            pm_spread_bps_20d,
            pm_wickiness_20d,
            midday_dollar_share_20d,
            midday_trades_share_20d,
            midday_active_minutes_share_20d,
            midday_spread_bps_20d,
            midday_efficiency_20d,
            ah_dollar_share_20d,
            ah_trades_share_20d,
            ah_active_minutes_share_20d,
            ah_spread_bps_20d,
            ah_wickiness_20d,
            setup_decay_half_life_bars_20d,
            early_vs_late_followthrough_ratio_20d,
        ) = minute_means
        (
            close_hygiene_20d,
            reclaim_respect_rate_20d,
            reclaim_failure_rate_20d,
            reclaim_followthrough_r_20d,
            ob_sweep_reversal_rate_20d,
            fvg_sweep_reversal_rate_20d,
            stop_hunt_rate_20d,
            stale_fail_rate_20d,
        ) = group_means

        daily_close = numeric_values[:, day_close_index]
        day_volume = numeric_values[:, day_volume_index]
        adv_fallback = daily_close * day_volume
        adv_fallback[~np.isfinite(adv_fallback)] = np.nan
        adv_rth = numeric_values[:, adv_rth_index]
        adv_dollar = np.where(covered_mask & (adv_rth > 0.0) & np.isfinite(adv_rth), adv_rth, adv_fallback)
        consistency_values = covered_numeric_values[:, consistency_score_indices]
        consistency_score = _consistency_score_from_numeric_values(consistency_values)
        ob_sweep_depth_p75_20d = _nanquantile_or_default(numeric_values[:, ob_sweep_depth_index], 0.75, default=0.0)
        fvg_sweep_depth_p75_20d = _nanquantile_or_default(numeric_values[:, fvg_sweep_depth_index], 0.75, default=0.0)

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
                "adv_dollar_rth_20d": _nanmean_or_default(adv_dollar, default=0.0),
                "avg_spread_bps_rth_20d": float(avg_spread_bps_rth_20d),
                "rth_active_minutes_share_20d": _clip01(rth_active_minutes_share_20d),
                "open_30m_dollar_share_20d": _clip01(open_30m_dollar_share_20d),
                "close_60m_dollar_share_20d": _clip01(close_60m_dollar_share_20d),
                "clean_intraday_score_20d": _clip01(clean_intraday_score_20d),
                "consistency_score_20d": _clip01(consistency_score),
                "close_hygiene_20d": _clip01(close_hygiene_20d),
                "wickiness_20d": _clip01(wickiness_20d),
                "pm_dollar_share_20d": _clip01(pm_dollar_share_20d),
                "pm_trades_share_20d": _clip01(pm_trades_share_20d),
                "pm_active_minutes_share_20d": _clip01(pm_active_minutes_share_20d),
                "pm_spread_bps_20d": float(pm_spread_bps_20d),
                "pm_wickiness_20d": _clip01(pm_wickiness_20d),
                "midday_dollar_share_20d": _clip01(midday_dollar_share_20d),
                "midday_trades_share_20d": _clip01(midday_trades_share_20d),
                "midday_active_minutes_share_20d": _clip01(midday_active_minutes_share_20d),
                "midday_spread_bps_20d": float(midday_spread_bps_20d),
                "midday_efficiency_20d": _clip01(midday_efficiency_20d),
                "ah_dollar_share_20d": _clip01(ah_dollar_share_20d),
                "ah_trades_share_20d": _clip01(ah_trades_share_20d),
                "ah_active_minutes_share_20d": _clip01(ah_active_minutes_share_20d),
                "ah_spread_bps_20d": float(ah_spread_bps_20d),
                "ah_wickiness_20d": _clip01(ah_wickiness_20d),
                "reclaim_respect_rate_20d": _clip01(reclaim_respect_rate_20d),
                "reclaim_failure_rate_20d": _clip01(reclaim_failure_rate_20d),
                "reclaim_followthrough_r_20d": float(reclaim_followthrough_r_20d),
                "ob_sweep_reversal_rate_20d": _clip01(ob_sweep_reversal_rate_20d),
                "ob_sweep_depth_p75_20d": ob_sweep_depth_p75_20d,
                "fvg_sweep_reversal_rate_20d": _clip01(fvg_sweep_reversal_rate_20d),
                "fvg_sweep_depth_p75_20d": fvg_sweep_depth_p75_20d,
                "stop_hunt_rate_20d": _clip01(stop_hunt_rate_20d),
                "setup_decay_half_life_bars_20d": float(setup_decay_half_life_bars_20d),
                "early_vs_late_followthrough_ratio_20d": float(early_vs_late_followthrough_ratio_20d),
                "stale_fail_rate_20d": _clip01(stale_fail_rate_20d),
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
        "bundle_manifest_path": "incremental_seed",
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
    return output, payload


def _clip01_series(series: pd.Series) -> pd.Series:
    numeric = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    result = np.zeros(len(series), dtype=float)
    valid = np.isfinite(numeric)
    result[valid] = np.clip(numeric[valid], 0.0, 1.0)
    return pd.Series(result, index=series.index, name=series.name)


def _safe_float(value: Any, default: float = 0.0) -> float:
    if isinstance(value, str):
        value = value.strip()
    if pd.isna(value):
        return default
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return default
    if pd.isna(numeric):
        return default
    return numeric


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


def _safe_ratio_to_constant_series(series: pd.Series, *, denominator: float, default: float = 0.0) -> pd.Series:
    result = np.full(len(series), float(default), dtype=float)
    if not np.isfinite(denominator) or denominator <= 0:
        return pd.Series(result, index=series.index, name=series.name)

    numerator_values = pd.to_numeric(series, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(numerator_values)
    result[valid] = numerator_values[valid] / float(denominator)
    return pd.Series(result, index=series.index, name=series.name)


def _clock_minutes(clock_time: time) -> int:
    return (clock_time.hour * 60) + clock_time.minute


PREMARKET_START_MINUTE = _clock_minutes(PREMARKET_START_ET)
REGULAR_OPEN_MINUTE = _clock_minutes(REGULAR_OPEN_ET)
OPEN_30M_END_MINUTE = _clock_minutes(OPEN_30M_END_ET)
MIDDAY_START_MINUTE = _clock_minutes(MIDDAY_START_ET)
MIDDAY_END_MINUTE = _clock_minutes(MIDDAY_END_ET)
LATE_START_MINUTE = _clock_minutes(LATE_START_ET)
CLOSE_60M_START_MINUTE = _clock_minutes(CLOSE_60M_START_ET)
REGULAR_CLOSE_MINUTE = _clock_minutes(REGULAR_CLOSE_ET)
AFTERHOURS_END_MINUTE = _clock_minutes(AFTERHOURS_END_ET)


def _series_numeric_values(series: pd.Series, index: pd.Index) -> np.ndarray:
    return cast(np.ndarray, pd.to_numeric(series.reindex(index), errors="coerce").to_numpy(dtype=float))


def _safe_ratio_series_for_index(
    numerator: pd.Series,
    denominator: pd.Series,
    *,
    index: pd.Index,
    default: float = 0.0,
    minimum_denominator: float | None = None,
) -> pd.Series:
    numerator_values = _series_numeric_values(numerator, index)
    denominator_values = _series_numeric_values(denominator, index)
    if minimum_denominator is not None:
        denominator_values = np.where(
            np.isfinite(denominator_values),
            np.maximum(denominator_values, minimum_denominator),
            denominator_values,
        )
    result = np.full(len(index), float(default), dtype=float)
    valid = np.isfinite(numerator_values) & np.isfinite(denominator_values) & (denominator_values > 0)
    np.divide(numerator_values, denominator_values, out=result, where=valid)
    return pd.Series(result, index=index)


def _abs_return_series_for_index(close_price: pd.Series, open_price: pd.Series, *, index: pd.Index) -> pd.Series:
    close_values = _series_numeric_values(close_price, index)
    open_values = _series_numeric_values(open_price, index)
    result = np.zeros(len(index), dtype=float)
    valid = np.isfinite(open_values) & (open_values > 0) & np.isfinite(close_values)
    result[valid] = np.abs((close_values[valid] / open_values[valid]) - 1.0)
    return pd.Series(result, index=index)


def _et_minutes_since_midnight(timestamp: pd.Series) -> pd.Series:
    if timestamp.empty:
        return pd.Series(dtype=np.int16, index=timestamp.index)

    codes, uniques = pd.factorize(timestamp, sort=False)
    unique_timestamp = pd.Series(pd.DatetimeIndex(uniques), copy=False)
    et_timestamp = unique_timestamp.dt.tz_convert(US_EASTERN_TZ)
    hour_values = np.asarray(et_timestamp.dt.hour, dtype=np.int16)
    minute_values = np.asarray(et_timestamp.dt.minute, dtype=np.int16)
    unique_minutes = (hour_values * 60 + minute_values).astype(np.int16, copy=False)
    minutes = np.empty(len(codes), dtype=np.int16)
    valid = codes >= 0
    minutes[valid] = unique_minutes[codes[valid]]
    minutes[~valid] = -1
    return pd.Series(minutes, index=timestamp.index)


def _coerce_trade_date_series(values: pd.Series) -> pd.Series:
    codes, uniques = pd.factorize(values, sort=False)
    parsed_uniques = np.asarray(
        [
            pd.NaT
            if pd.isna(parsed := pd.to_datetime(pd.Index([value]), errors="coerce")[0])
            else parsed.date()
            for value in uniques
        ],
        dtype=object,
    )
    parsed_values = np.empty(len(codes), dtype=object)
    valid = codes >= 0
    parsed_values[valid] = parsed_uniques[codes[valid]]
    parsed_values[~valid] = pd.NaT
    return pd.Series(parsed_values, index=values.index, name=values.name)


def _coerce_bool(value: Any) -> bool:
    if pd.isna(value):
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _coerce_bool_series(series: pd.Series) -> pd.Series:
    result = pd.Series(False, index=series.index, dtype=bool, name=series.name)
    if series.empty:
        return result

    non_null = ~series.isna()
    if not bool(non_null.any()):
        return result

    values = series.loc[non_null]
    mapping = {value: _coerce_bool(value) for value in pd.unique(values).tolist()}
    result.loc[non_null] = values.map(mapping).fillna(False).astype(bool).to_numpy()
    return result


def _numeric_values(series: pd.Series) -> np.ndarray:
    if pd.api.types.is_numeric_dtype(series.dtype):
        return cast(np.ndarray, series.to_numpy(dtype=float, na_value=np.nan))
    return cast(np.ndarray, pd.to_numeric(series, errors="coerce").to_numpy(dtype=float))


def _nanmean_or_default(values: np.ndarray, default: float = 0.0) -> float:
    if values.size == 0:
        return float(default)
    valid_count = np.count_nonzero(~np.isnan(values))
    if valid_count == 0:
        return float(default)
    return float(np.nansum(values) / valid_count)


def _nanmean_columns_or_zero(values: np.ndarray) -> np.ndarray:
    if values.shape[0] == 0:
        return np.zeros(values.shape[1], dtype=float)

    counts = np.count_nonzero(~np.isnan(values), axis=0)
    sums = np.nansum(values, axis=0)
    return cast(np.ndarray, np.divide(sums, counts, out=np.zeros(values.shape[1], dtype=float), where=counts > 0))


def _column_nanmeans_or_zero(frame: pd.DataFrame, columns: list[str]) -> np.ndarray:
    if not columns:
        return np.empty(0, dtype=float)

    values = frame[columns].to_numpy(dtype=float, copy=False)
    return _nanmean_columns_or_zero(values)


def _consistency_score_from_numeric_values(values: np.ndarray) -> float:
    if values.shape[0] == 0:
        return 0.0

    valid = ~np.isnan(values)
    counts = valid.sum(axis=0)
    valid_columns = counts > 0
    if not bool(valid_columns.any()):
        return 0.0

    sums = np.nansum(values, axis=0)
    means = np.divide(sums, counts, out=np.zeros(values.shape[1], dtype=float), where=valid_columns)
    centered = np.where(valid, values - means, 0.0)
    variances = np.divide(
        np.square(centered).sum(axis=0),
        counts,
        out=np.zeros(values.shape[1], dtype=float),
        where=valid_columns,
    )
    baselines = np.maximum(np.abs(means[valid_columns]), 0.01)
    components = 1.0 / (1.0 + (np.sqrt(variances[valid_columns]) / baselines))
    return float(np.clip(components.mean(), 0.0, 1.0))


def _mean_or_default(series: pd.Series, default: float = 0.0) -> float:
    return _nanmean_or_default(_numeric_values(series), default)


def _nanquantile_or_default(values: np.ndarray, quantile: float, default: float = 0.0) -> float:
    if values.size == 0:
        return float(default)
    if np.isnan(values).all():
        return float(default)
    return float(np.nanquantile(values, quantile))


def _quantile_or_default(series: pd.Series, quantile: float, default: float = 0.0) -> float:
    return _nanquantile_or_default(_numeric_values(series), quantile, default)


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


def _grouped_setup_decay_half_life_30m_buckets(
    frame: pd.DataFrame,
    *,
    group_columns: list[str],
) -> pd.Series:
    if frame.empty:
        return pd.Series(dtype=float)

    bucket_frame = frame.loc[:, [*group_columns, "minutes_from_open", "dollar_volume"]].copy()
    bucket_frame["bucket_index"] = ((bucket_frame["minutes_from_open"] // 30).astype(int)).clip(lower=0)
    bucket_frame = (
        bucket_frame.groupby([*group_columns, "bucket_index"], sort=False, observed=True)["dollar_volume"]
        .sum()
        .rename("bucket_dollar")
        .reset_index()
        .sort_values([*group_columns, "bucket_index"])
        .reset_index(drop=True)
    )

    grouped = bucket_frame.groupby(group_columns, sort=False, observed=True)
    summary = grouped.agg(
        first_bucket_dollar=("bucket_dollar", "first"),
        bucket_count=("bucket_index", "size"),
    )

    result = summary["bucket_count"].clip(lower=1).astype(float)
    zero_first_bucket = summary["first_bucket_dollar"].le(0)
    if bool(zero_first_bucket.any()):
        result.loc[zero_first_bucket] = 0.0

    first_bucket_index = grouped["bucket_index"].transform("first")
    first_bucket_dollar = grouped["bucket_dollar"].transform("first")
    later_hit_mask = bucket_frame["bucket_index"].ne(first_bucket_index) & bucket_frame["bucket_dollar"].le(first_bucket_dollar * 0.5)
    if bool(later_hit_mask.any()):
        first_hits = bucket_frame.loc[later_hit_mask].groupby(group_columns, sort=False, observed=True)["bucket_index"].first().astype(float)
        positive_hit_index = first_hits.index.intersection(summary.index[~zero_first_bucket])
        result.loc[positive_hit_index] = first_hits.loc[positive_hit_index]

    return result


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
        [*group_columns, "open", "high", "low", "close", "dollar_volume", "trade_proxy", "active_minute", "spread_bps_proxy", "wickiness_proxy"],
    ]
    if subset.empty:
        return _empty_group_metrics(group_columns, columns)

    grouped = subset.groupby(group_columns, sort=False, observed=True)
    dollar_volume = grouped["dollar_volume"].sum()
    trade_proxy = grouped["trade_proxy"].sum()
    active_minutes = grouped["active_minute"].sum()
    spread_bps = grouped["spread_bps_proxy"].mean()
    wickiness = grouped["wickiness_proxy"].mean()
    open_price = grouped["open"].first()
    close_price = grouped["close"].last()
    high_price = grouped["high"].max()
    low_price = grouped["low"].min()
    aggregated = pd.DataFrame(
        {
            "dollar_volume": dollar_volume.to_numpy(),
            "trade_proxy": trade_proxy.to_numpy(),
            "active_minutes": active_minutes.to_numpy(),
            "spread_bps": spread_bps.to_numpy(),
            "wickiness": wickiness.to_numpy(),
            "open_price": open_price.to_numpy(),
            "close_price": close_price.to_numpy(),
        },
        index=open_price.index,
    )
    aggregated["active_minutes_share"] = _safe_ratio_to_constant_series(
        active_minutes,
        denominator=float(available_minutes),
        default=0.0,
    ).to_numpy()
    aggregated["efficiency"] = _window_efficiency_from_aggregates(
        open_price,
        close_price,
        high_price,
        low_price,
    ).to_numpy()
    return aggregated[columns]


def _aggregate_open_close_metrics(
    frame: pd.DataFrame,
    mask: pd.Series,
    *,
    group_columns: list[str],
) -> pd.DataFrame:
    columns = ["dollar_volume", "open_price", "close_price"]
    subset = frame.loc[mask, [*group_columns, "open", "close", "dollar_volume"]]
    if subset.empty:
        return _empty_group_metrics(group_columns, columns)
    grouped = subset.groupby(group_columns, sort=False, observed=True)
    open_price = grouped["open"].first()
    return pd.DataFrame(
        {
            "dollar_volume": grouped["dollar_volume"].sum().to_numpy(),
            "open_price": open_price.to_numpy(),
            "close_price": grouped["close"].last().to_numpy(),
        },
        index=open_price.index,
    )


def _approx_frame_memory_mebibytes(frame: pd.DataFrame) -> float:
    if frame.empty:
        return 0.0
    return float(frame.memory_usage(index=True, deep=False).sum()) / (1024.0 * 1024.0)


def _emit_frame_telemetry(
    telemetry_callback: Callable[[str], None] | None,
    *,
    label: str,
    frame: pd.DataFrame,
) -> None:
    if telemetry_callback is None:
        return
    telemetry_callback(
        f"Step 12/12 telemetry: {label} rows={len(frame)} cols={len(frame.columns)} "
        f"approx_frame_mib={_approx_frame_memory_mebibytes(frame):.1f}"
    )


def _build_symbol_day_minute_metrics(
    minute_frame: pd.DataFrame,
    *,
    metric_columns: list[str],
    telemetry_callback: Callable[[str], None] | None = None,
    frame_label_prefix: str = "minute_frame",
    metrics_label: str = "minute_metrics_by_symbol_day",
) -> pd.DataFrame:
    if minute_frame.empty:
        return pd.DataFrame(columns=metric_columns)

    minute_frame["open"] = pd.to_numeric(minute_frame.get("open"), errors="coerce")
    minute_frame["high"] = pd.to_numeric(minute_frame.get("high"), errors="coerce")
    minute_frame["low"] = pd.to_numeric(minute_frame.get("low"), errors="coerce")
    minute_frame["close"] = pd.to_numeric(minute_frame.get("close"), errors="coerce")
    minute_frame["volume"] = pd.to_numeric(minute_frame.get("volume"), errors="coerce").fillna(0.0)
    minute_frame["trade_count"] = pd.to_numeric(minute_frame.get("trade_count"), errors="coerce")
    minute_frame["et_minute"] = _et_minutes_since_midnight(minute_frame["timestamp"])
    minute_frame["dollar_volume"] = minute_frame["close"] * minute_frame["volume"]
    minute_frame["spread_bps_proxy"] = _bar_spread_bps(minute_frame)
    minute_frame["wickiness_proxy"] = _bar_wickiness(minute_frame)
    minute_frame["trade_proxy"] = minute_frame["trade_count"]
    minute_frame["trade_proxy"] = minute_frame["trade_proxy"].where(
        minute_frame["trade_proxy"].notna(),
        np.where(minute_frame["volume"] > 0, 1.0, 0.0),
    )
    minute_frame["active_minute"] = (minute_frame["volume"] > 0) | (minute_frame["trade_proxy"] > 0)
    minute_frame["minutes_from_open"] = minute_frame["et_minute"].astype(float) - float(REGULAR_OPEN_MINUTE)
    _emit_frame_telemetry(
        telemetry_callback,
        label=f"{frame_label_prefix}_pre_sort",
        frame=minute_frame,
    )
    minute_frame.sort_values(["trade_date", "symbol", "timestamp"], kind="mergesort", inplace=True)
    minute_frame.reset_index(drop=True, inplace=True)
    _emit_frame_telemetry(
        telemetry_callback,
        label=f"{frame_label_prefix}_sorted",
        frame=minute_frame,
    )

    minute_frame["trade_date"] = pd.Categorical(minute_frame["trade_date"])
    minute_frame["symbol"] = pd.Categorical(minute_frame["symbol"])
    group_columns = ["trade_date", "symbol"]
    group_index = minute_frame[group_columns].drop_duplicates().set_index(group_columns)

    grouped = minute_frame.groupby(group_columns, sort=False, observed=True)
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

    et_minute = minute_frame["et_minute"]
    is_pm = et_minute.ge(PREMARKET_START_MINUTE) & et_minute.lt(REGULAR_OPEN_MINUTE)
    is_rth = et_minute.ge(REGULAR_OPEN_MINUTE) & et_minute.lt(REGULAR_CLOSE_MINUTE)
    is_open_30 = et_minute.ge(REGULAR_OPEN_MINUTE) & et_minute.lt(OPEN_30M_END_MINUTE)
    is_midday = et_minute.ge(MIDDAY_START_MINUTE) & et_minute.lt(MIDDAY_END_MINUTE)
    is_late = et_minute.ge(LATE_START_MINUTE) & et_minute.lt(REGULAR_CLOSE_MINUTE)
    is_close_60 = et_minute.ge(CLOSE_60M_START_MINUTE) & et_minute.lt(REGULAR_CLOSE_MINUTE)
    is_ah = et_minute.ge(REGULAR_CLOSE_MINUTE) & et_minute.lt(AFTERHOURS_END_MINUTE)

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
        rth_half_life = _grouped_setup_decay_half_life_30m_buckets(
            minute_frame.loc[is_rth, [*group_columns, "minutes_from_open", "dollar_volume"]],
            group_columns=group_columns,
        )
    else:
        rth_half_life = pd.Series(dtype=float)

    minute_metrics = group_index.copy()
    minute_metrics["daily_rth_dollar_volume"] = rth_stats["dollar_volume"]
    minute_metrics["daily_avg_spread_bps_rth"] = rth_stats["spread_bps"]
    minute_metrics["daily_rth_active_minutes_share"] = rth_stats["active_minutes_share"]
    minute_metrics["daily_rth_wickiness"] = rth_stats["wickiness"]
    minute_metrics["daily_rth_efficiency"] = rth_stats["efficiency"]
    metric_index = minute_metrics.index

    total_day_dollar = pm_stats["dollar_volume"].add(rth_stats["dollar_volume"], fill_value=0.0).add(
        ah_stats["dollar_volume"], fill_value=0.0
    )
    total_day_trades = pm_stats["trade_proxy"].add(rth_stats["trade_proxy"], fill_value=0.0).add(
        ah_stats["trade_proxy"], fill_value=0.0
    )

    minute_metrics["daily_open_30m_dollar_share"] = _safe_ratio_series_for_index(
        open_30_stats["dollar_volume"],
        rth_stats["dollar_volume"],
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_close_60m_dollar_share"] = _safe_ratio_series_for_index(
        close_60_stats["dollar_volume"],
        rth_stats["dollar_volume"],
        index=metric_index,
        default=0.0,
    )

    minute_metrics["daily_pm_dollar_share"] = _safe_ratio_series_for_index(
        pm_stats["dollar_volume"],
        total_day_dollar,
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_pm_trades_share"] = _safe_ratio_series_for_index(
        pm_stats["trade_proxy"],
        total_day_trades,
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_pm_active_minutes_share"] = pm_stats["active_minutes_share"]
    minute_metrics["daily_pm_spread_bps"] = pm_stats["spread_bps"]
    minute_metrics["daily_pm_wickiness"] = pm_stats["wickiness"]

    minute_metrics["daily_midday_dollar_share"] = _safe_ratio_series_for_index(
        midday_stats["dollar_volume"],
        rth_stats["dollar_volume"],
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_midday_trades_share"] = _safe_ratio_series_for_index(
        midday_stats["trade_proxy"],
        rth_stats["trade_proxy"],
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_midday_active_minutes_share"] = midday_stats["active_minutes_share"]
    minute_metrics["daily_midday_spread_bps"] = midday_stats["spread_bps"]
    minute_metrics["daily_midday_efficiency"] = midday_stats["efficiency"]

    minute_metrics["daily_ah_dollar_share"] = _safe_ratio_series_for_index(
        ah_stats["dollar_volume"],
        total_day_dollar,
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_ah_trades_share"] = _safe_ratio_series_for_index(
        ah_stats["trade_proxy"],
        total_day_trades,
        index=metric_index,
        default=0.0,
    )
    minute_metrics["daily_ah_active_minutes_share"] = ah_stats["active_minutes_share"]
    minute_metrics["daily_ah_spread_bps"] = ah_stats["spread_bps"]
    minute_metrics["daily_ah_wickiness"] = ah_stats["wickiness"]
    minute_metrics["daily_setup_decay_half_life_bars"] = rth_half_life

    early_return = _abs_return_series_for_index(
        open_30_stats["close_price"],
        open_30_stats["open_price"],
        index=metric_index,
    )
    late_return = _abs_return_series_for_index(
        late_stats["close_price"],
        late_stats["open_price"],
        index=metric_index,
    )
    minute_metrics["daily_early_vs_late_followthrough_ratio"] = _safe_ratio_series_for_index(
        early_return,
        late_return,
        index=metric_index,
        default=0.0,
        minimum_denominator=1e-6,
    )
    minute_metrics["daily_rth_net_return_abs"] = _abs_return_series_for_index(
        rth_stats["close_price"],
        rth_stats["open_price"],
        index=metric_index,
    )

    has_pm = minute_metrics.index.isin(pm_stats.index)
    has_rth = minute_metrics.index.isin(rth_stats.index)
    has_midday = minute_metrics.index.isin(midday_stats.index)
    has_pre_midday_rth = minute_metrics.index.isin(
        minute_frame.loc[
            is_rth & et_minute.lt(MIDDAY_START_MINUTE),
            group_columns,
        ].drop_duplicates().set_index(group_columns).index
    )
    has_post_midday_rth = minute_metrics.index.isin(
        minute_frame.loc[
            is_rth & et_minute.ge(MIDDAY_END_MINUTE),
            group_columns,
        ].drop_duplicates().set_index(group_columns).index
    )
    has_ah = minute_metrics.index.isin(ah_stats.index)
    minute_metrics["missing_regular_session_detail"] = (~has_rth) & (has_pm | has_ah)
    minute_metrics["missing_midday_detail"] = has_pre_midday_rth & has_post_midday_rth & (~has_midday)
    minute_metrics["missing_premarket_detail"] = (~has_pm) & (has_rth | has_ah)
    minute_metrics["missing_afterhours_detail"] = (~has_ah) & (has_pm | has_rth)
    _emit_frame_telemetry(
        telemetry_callback,
        label=metrics_label,
        frame=minute_metrics,
    )

    missing_regular = minute_metrics.loc[minute_metrics["missing_regular_session_detail"]]
    if not missing_regular.empty:
        for trade_day, symbol in missing_regular.index.tolist():
            logger.warning(
                "Symbol %s on %s has minute detail for non-regular sessions but no regular-session bars; regular-session derived metrics will be 0.0 and excluded from 20d minute aggregation.",
                symbol,
                trade_day,
            )

    missing_midday = minute_metrics.loc[minute_metrics["missing_midday_detail"]]
    if not missing_midday.empty:
        for trade_day, symbol in missing_midday.index.tolist():
            logger.warning(
                "Symbol %s on %s has regular-session bars on both sides of the midday window but no midday bars; midday-derived metrics will be 0.0 and excluded from 20d minute aggregation.",
                symbol,
                trade_day,
            )

    minute_metrics = minute_metrics.reset_index()
    minute_metrics["trade_date"] = minute_metrics["trade_date"].astype(object)
    minute_metrics["symbol"] = minute_metrics["symbol"].astype(str)
    return minute_metrics[metric_columns]


def build_symbol_day_microstructure_feature_frame(
    session_minute_detail: pd.DataFrame,
    daily_symbol_features: pd.DataFrame,
    *,
    telemetry_callback: Callable[[str], None] | None = None,
    mutate_input: bool = False,
) -> pd.DataFrame:
    daily = daily_symbol_features.copy()
    if daily.empty:
        return pd.DataFrame()

    daily["trade_date"] = _coerce_trade_date_series(daily["trade_date"])
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
        "missing_midday_detail",
        "missing_premarket_detail",
        "missing_afterhours_detail",
    ]

    minute_metrics = pd.DataFrame(columns=metric_columns)
    if not session_minute_detail.empty:
        required_minute_columns = [
            "trade_date",
            "symbol",
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "trade_count",
        ]
        available_minute_columns = [
            column for column in required_minute_columns if column in session_minute_detail.columns
        ]
        if mutate_input:
            minute_frame = session_minute_detail
            extra_minute_columns = [
                column for column in minute_frame.columns if column not in required_minute_columns
            ]
            if extra_minute_columns:
                minute_frame.drop(columns=extra_minute_columns, inplace=True, errors="ignore")
        else:
            minute_frame = session_minute_detail.loc[:, available_minute_columns].copy()
        _emit_frame_telemetry(
            telemetry_callback,
            label=f"session_minute_detail_input mutate_input={mutate_input}",
            frame=minute_frame,
        )
        minute_frame["trade_date"] = _coerce_trade_date_series(minute_frame["trade_date"])
        minute_frame["symbol"] = minute_frame["symbol"].astype(str).str.upper()
        minute_frame["timestamp"] = pd.to_datetime(minute_frame["timestamp"], errors="coerce", utc=True)
        if mutate_input:
            minute_frame.dropna(subset=["trade_date", "symbol", "timestamp"], inplace=True)
            minute_frame.reset_index(drop=True, inplace=True)
        else:
            minute_frame = minute_frame.dropna(subset=["trade_date", "symbol", "timestamp"]).copy()
        _emit_frame_telemetry(
            telemetry_callback,
            label="minute_frame_normalized_pre_sort",
            frame=minute_frame,
        )
        if not minute_frame.empty:
            trade_day_batches = minute_frame.groupby("trade_date", sort=False, observed=True).indices
            should_batch_minute_processing = (
                len(minute_frame) >= SYMBOL_DAY_FEATURE_BATCH_ROW_THRESHOLD
                and len(trade_day_batches) > 1
            )
            if should_batch_minute_processing:
                if telemetry_callback is not None:
                    telemetry_callback(
                        "Step 12/12 telemetry: minute_frame_batching "
                        f"rows={len(minute_frame)} trade_days={len(trade_day_batches)} "
                        f"threshold_rows={SYMBOL_DAY_FEATURE_BATCH_ROW_THRESHOLD}"
                    )
                minute_metric_batches: list[pd.DataFrame] = []
                total_batches = len(trade_day_batches)
                for batch_index, (trade_day, batch_positions) in enumerate(trade_day_batches.items(), start=1):
                    trade_day_label = str(trade_day)
                    if telemetry_callback is not None:
                        telemetry_callback(
                            "Step 12/12 telemetry: minute_frame_batch_start "
                            f"batch={batch_index}/{total_batches} trade_date={trade_day_label}"
                        )
                    batch_frame = minute_frame.iloc[batch_positions].copy()
                    minute_metric_batches.append(
                        _build_symbol_day_minute_metrics(
                            batch_frame,
                            metric_columns=metric_columns,
                            telemetry_callback=telemetry_callback,
                            frame_label_prefix=f"minute_frame_batch_{trade_day_label}",
                            metrics_label=f"minute_metrics_batch_{trade_day_label}",
                        )
                    )
                if minute_metric_batches:
                    minute_metrics = pd.concat(minute_metric_batches, ignore_index=True)
                else:
                    minute_metrics = pd.DataFrame(columns=metric_columns)
                _emit_frame_telemetry(
                    telemetry_callback,
                    label="minute_metrics_batched_output",
                    frame=minute_metrics,
                )
            else:
                minute_metrics = _build_symbol_day_minute_metrics(
                    minute_frame,
                    metric_columns=metric_columns,
                    telemetry_callback=telemetry_callback,
                )

    merged = daily.merge(minute_metrics, on=["trade_date", "symbol"], how="left")
    minute_metric_value_columns = [
        column
        for column in metric_columns
        if column
        not in {
            "trade_date",
            "symbol",
            "missing_regular_session_detail",
            "missing_midday_detail",
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
                f"{row.trade_date!s}:{row.symbol!s}"
                for row in sample_rows.itertuples(index=False)
            )
            logger.warning(
                "Session minute detail missing for %d symbol-day rows; minute-derived metrics will be filled with 0.0. Sample: %s",
                missing_count,
                sample or "n/a",
            )
    for bool_column in (
        "missing_regular_session_detail",
        "missing_midday_detail",
        "missing_premarket_detail",
        "missing_afterhours_detail",
    ):
        merged[bool_column] = _coerce_bool_series(_series_from_frame(merged, bool_column, False))
    for column in metric_columns:
        if column in {
            "trade_date",
            "symbol",
            "missing_regular_session_detail",
            "missing_midday_detail",
            "missing_premarket_detail",
            "missing_afterhours_detail",
        }:
            continue
        merged[column] = pd.to_numeric(_series_from_frame(merged, column), errors="coerce").fillna(0.0)

    close_hygiene = pd.to_numeric(_series_from_frame(merged, "close_trade_hygiene_score"), errors="coerce")
    close_trade_followthrough = _coerce_bool_series(
        _series_from_frame(merged, "close_trade_has_lit_followthrough", False)
    )
    close_hygiene = close_hygiene.where(close_hygiene.notna(), np.where(close_trade_followthrough, 1.0, 0.0))
    close_hygiene = pd.Series(close_hygiene, index=merged.index).fillna(0.0).clip(lower=0.0, upper=1.0)
    merged["daily_close_hygiene"] = close_hygiene

    clipped_rth_active_minutes_share = _clip01_series(merged["daily_rth_active_minutes_share"])
    clipped_rth_efficiency = _clip01_series(merged["daily_rth_efficiency"])
    clipped_rth_wickiness = _clip01_series(merged["daily_rth_wickiness"])
    clipped_close_hygiene = _clip01_series(merged["daily_close_hygiene"])
    spread_component = 1.0 / (1.0 + (pd.to_numeric(merged["daily_avg_spread_bps_rth"], errors="coerce").fillna(0.0) / 25.0))
    merged["daily_clean_intraday_score"] = (
        clipped_rth_active_minutes_share
        + clipped_rth_efficiency
        + spread_component.clip(lower=0.0, upper=1.0)
        + (1.0 - clipped_rth_wickiness)
        + clipped_close_hygiene
    ) / 5.0

    reclaim_flag = _coerce_bool_series(_series_from_frame(merged, "reclaimed_start_price_within_30s", False))
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

    prev_day_high = pd.to_numeric(_series_from_frame(merged, "prev_day_high"), errors="coerce")
    prev_day_low = pd.to_numeric(_series_from_frame(merged, "prev_day_low"), errors="coerce")
    day_high = pd.to_numeric(_series_from_frame(merged, "day_high"), errors="coerce")
    day_low = pd.to_numeric(_series_from_frame(merged, "day_low"), errors="coerce")
    day_close = pd.to_numeric(_series_from_frame(merged, "day_close"), errors="coerce")
    day_open = pd.to_numeric(_series_from_frame(merged, "day_open"), errors="coerce")
    previous_close = pd.to_numeric(_series_from_frame(merged, "previous_close"), errors="coerce")

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

    _emit_frame_telemetry(
        telemetry_callback,
        label="symbol_day_features_output",
        frame=merged,
    )
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
        numeric_values = _numeric_values(group[column])
        if numeric_values.size == 0 or np.isnan(numeric_values).all():
            continue
        baseline = max(float(abs(np.nanmean(numeric_values))), 0.01)
        cv = float(np.nanstd(numeric_values, ddof=0) / baseline)
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
    days_stale = (_today_et() - resolved_date).days
    if days_stale > 5:
        warnings.warn(
            f"Microstructure base asof_date is {days_stale} days old; results may be stale.",
            stacklevel=2,
        )

    trailing = symbol_day_features.loc[symbol_day_features["trade_date"] <= resolved_asof].copy()
    trailing = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(20)
    for target_column, legacy_column in (("day_close", "close"), ("day_volume", "volume")):
        if target_column not in trailing.columns:
            logger.warning(
                "Bundle symbol-day features missing %s; falling back to %s for compatibility.",
                target_column,
                legacy_column,
            )
            trailing[target_column] = pd.to_numeric(
                _series_from_frame(trailing, legacy_column, np.nan),
                errors="coerce",
            )
    trailing["minute_detail_missing_bool"] = _coerce_bool_series(_series_from_frame(trailing, "minute_detail_missing", False))
    trailing["missing_regular_session_detail_bool"] = _coerce_bool_series(
        _series_from_frame(trailing, "missing_regular_session_detail", False)
    )
    trailing["missing_midday_detail_bool"] = _coerce_bool_series(
        _series_from_frame(trailing, "missing_midday_detail", False)
    )

    latest = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(1)
    latest_by_symbol = latest.set_index("symbol", drop=False)
    rows: list[dict[str, Any]] = []
    consistency_score_columns = [
        "daily_clean_intraday_score",
        "daily_open_30m_dollar_share",
        "daily_close_60m_dollar_share",
        "daily_midday_efficiency",
        "daily_close_hygiene",
    ]
    minute_mean_columns = [
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
    ]
    group_mean_columns = [
        "daily_close_hygiene",
        "daily_reclaim_respect_flag",
        "daily_reclaim_failure_flag",
        "daily_reclaim_followthrough_r",
        "daily_ob_sweep_reversal_flag",
        "daily_fvg_sweep_reversal_flag",
        "daily_stop_hunt_flag",
        "daily_stale_fail_flag",
    ]
    trailing_numeric_columns: list[str] = []
    for column in minute_mean_columns + group_mean_columns + [
        "daily_rth_dollar_volume",
        "daily_ob_sweep_depth",
        "daily_fvg_sweep_depth",
        "day_close",
        "day_volume",
    ]:
        if column not in trailing_numeric_columns:
            trailing_numeric_columns.append(column)
    minute_mean_indices = [trailing_numeric_columns.index(column) for column in minute_mean_columns]
    group_mean_indices = [trailing_numeric_columns.index(column) for column in group_mean_columns]
    consistency_score_indices = [trailing_numeric_columns.index(column) for column in consistency_score_columns]
    adv_rth_index = trailing_numeric_columns.index("daily_rth_dollar_volume")
    ob_sweep_depth_index = trailing_numeric_columns.index("daily_ob_sweep_depth")
    fvg_sweep_depth_index = trailing_numeric_columns.index("daily_fvg_sweep_depth")
    day_close_index = trailing_numeric_columns.index("day_close")
    day_volume_index = trailing_numeric_columns.index("day_volume")

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
        coverage_gap_mask = (
            group["missing_regular_session_detail_bool"].to_numpy(dtype=bool, copy=False)
            | group["missing_midday_detail_bool"].to_numpy(dtype=bool, copy=False)
        )
        if bool(coverage_gap_mask.any()):
            logger.warning(
                "Symbol %s excluded %d symbol-day rows from minute-derived 20d aggregation due missing regular-session or midday detail.",
                symbol,
                int(coverage_gap_mask.sum()),
            )
        covered_mask = ~(
            group["minute_detail_missing_bool"].to_numpy(dtype=bool, copy=False)
            | coverage_gap_mask
        )
        covered_group = group.loc[covered_mask]
        if covered_group.empty:
            logger.warning(
                "Symbol %s has no symbol-day rows with minute detail coverage for minute-derived 20d aggregation; minute-derived metrics will fall back to 0.0.",
                symbol,
            )

        numeric_values = group[trailing_numeric_columns].to_numpy(dtype=float, copy=False)
        covered_numeric_values = numeric_values[covered_mask]
        minute_means = _nanmean_columns_or_zero(covered_numeric_values[:, minute_mean_indices])
        group_means = _nanmean_columns_or_zero(numeric_values[:, group_mean_indices])
        (
            avg_spread_bps_rth_20d,
            rth_active_minutes_share_20d,
            open_30m_dollar_share_20d,
            close_60m_dollar_share_20d,
            clean_intraday_score_20d,
            wickiness_20d,
            pm_dollar_share_20d,
            pm_trades_share_20d,
            pm_active_minutes_share_20d,
            pm_spread_bps_20d,
            pm_wickiness_20d,
            midday_dollar_share_20d,
            midday_trades_share_20d,
            midday_active_minutes_share_20d,
            midday_spread_bps_20d,
            midday_efficiency_20d,
            ah_dollar_share_20d,
            ah_trades_share_20d,
            ah_active_minutes_share_20d,
            ah_spread_bps_20d,
            ah_wickiness_20d,
            setup_decay_half_life_bars_20d,
            early_vs_late_followthrough_ratio_20d,
        ) = minute_means
        (
            close_hygiene_20d,
            reclaim_respect_rate_20d,
            reclaim_failure_rate_20d,
            reclaim_followthrough_r_20d,
            ob_sweep_reversal_rate_20d,
            fvg_sweep_reversal_rate_20d,
            stop_hunt_rate_20d,
            stale_fail_rate_20d,
        ) = group_means

        daily_close = numeric_values[:, day_close_index]
        day_volume = numeric_values[:, day_volume_index]
        adv_fallback = daily_close * day_volume
        adv_fallback[~np.isfinite(adv_fallback)] = np.nan
        adv_rth = numeric_values[:, adv_rth_index]
        adv_dollar = np.where(covered_mask & (adv_rth > 0.0) & np.isfinite(adv_rth), adv_rth, adv_fallback)
        consistency_values = covered_numeric_values[:, consistency_score_indices]
        consistency_score = _consistency_score_from_numeric_values(consistency_values)
        ob_sweep_depth_p75_20d = _nanquantile_or_default(numeric_values[:, ob_sweep_depth_index], 0.75, default=0.0)
        fvg_sweep_depth_p75_20d = _nanquantile_or_default(numeric_values[:, fvg_sweep_depth_index], 0.75, default=0.0)

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
                "adv_dollar_rth_20d": _nanmean_or_default(adv_dollar, default=0.0),
                "avg_spread_bps_rth_20d": float(avg_spread_bps_rth_20d),
                "rth_active_minutes_share_20d": _clip01(rth_active_minutes_share_20d),
                "open_30m_dollar_share_20d": _clip01(open_30m_dollar_share_20d),
                "close_60m_dollar_share_20d": _clip01(close_60m_dollar_share_20d),
                "clean_intraday_score_20d": _clip01(clean_intraday_score_20d),
                "consistency_score_20d": _clip01(consistency_score),
                "close_hygiene_20d": _clip01(close_hygiene_20d),
                "wickiness_20d": _clip01(wickiness_20d),
                "pm_dollar_share_20d": _clip01(pm_dollar_share_20d),
                "pm_trades_share_20d": _clip01(pm_trades_share_20d),
                "pm_active_minutes_share_20d": _clip01(pm_active_minutes_share_20d),
                "pm_spread_bps_20d": float(pm_spread_bps_20d),
                "pm_wickiness_20d": _clip01(pm_wickiness_20d),
                "midday_dollar_share_20d": _clip01(midday_dollar_share_20d),
                "midday_trades_share_20d": _clip01(midday_trades_share_20d),
                "midday_active_minutes_share_20d": _clip01(midday_active_minutes_share_20d),
                "midday_spread_bps_20d": float(midday_spread_bps_20d),
                "midday_efficiency_20d": _clip01(midday_efficiency_20d),
                "ah_dollar_share_20d": _clip01(ah_dollar_share_20d),
                "ah_trades_share_20d": _clip01(ah_trades_share_20d),
                "ah_active_minutes_share_20d": _clip01(ah_active_minutes_share_20d),
                "ah_spread_bps_20d": float(ah_spread_bps_20d),
                "ah_wickiness_20d": _clip01(ah_wickiness_20d),
                "reclaim_respect_rate_20d": _clip01(reclaim_respect_rate_20d),
                "reclaim_failure_rate_20d": _clip01(reclaim_failure_rate_20d),
                "reclaim_followthrough_r_20d": float(reclaim_followthrough_r_20d),
                "ob_sweep_reversal_rate_20d": _clip01(ob_sweep_reversal_rate_20d),
                "ob_sweep_depth_p75_20d": ob_sweep_depth_p75_20d,
                "fvg_sweep_reversal_rate_20d": _clip01(fvg_sweep_reversal_rate_20d),
                "fvg_sweep_depth_p75_20d": fvg_sweep_depth_p75_20d,
                "stop_hunt_rate_20d": _clip01(stop_hunt_rate_20d),
                "setup_decay_half_life_bars_20d": float(setup_decay_half_life_bars_20d),
                "early_vs_late_followthrough_ratio_20d": float(early_vs_late_followthrough_ratio_20d),
                "stale_fail_rate_20d": _clip01(stale_fail_rate_20d),
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
    atomic_write_text("\n".join(lines).rstrip() + "\n", path)


def write_base_workbook(path: Path, base_snapshot: pd.DataFrame, mapping_payload: dict[str, Any]) -> None:
    excel_max_rows = 1_048_576
    max_data_rows_per_sheet = max(1, excel_max_rows - 1)
    path.parent.mkdir(parents=True, exist_ok=True)
    mapping_frame = pd.DataFrame(mapping_payload["mapping_status"])
    base_sheet_count = max(1, math.ceil(len(base_snapshot) / max_data_rows_per_sheet))
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
    # WATCHLIST (Q5a mirror, 2026-05-09): openpyxl in-memory write.
    #   Why watched: same failure class as full_universe_close_trade_detail
    #     (run 25593357307: 6.9 GB peakRSS / 7 GB ubuntu-latest → exit 143).
    #     base_snapshot is currently chunked (loop below) which mitigates today.
    #   Trigger to act (any of, dual-occurrence OR confirmed root cause):
    #     1. base_snapshot row count materially above current baseline
    #        (re-establish baseline if not on file).
    #     2. peakRSS for this step materially above current baseline
    #        (relative to runner & history; not a fixed GB number).
    #     3. Confirmed OOM evidence: exit 143 PLUS "runner has received a
    #        shutdown signal" in logs — exit 143 alone is ambiguous.
    #   Action on trigger: add `write_only=True` toggle + per-sheet flush;
    #     mirror Q5a/Q5b discipline (full sweep, ledger pre-flight).
    #   DO NOT preemptively refactor — measurement-gated only.
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
    atomic_write_text(json.dumps(payload, indent=2) + "\n", path)


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
    symbol_day_features: pd.DataFrame | None = None,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
) -> dict[str, Any]:
    bundle_payload = bundle if isinstance(bundle, dict) else load_export_bundle(
        bundle,
        required_frames=REQUIRED_BUNDLE_FRAMES,
        manifest_prefix="databento_volatility_production_",
    )
    target_dir = output_dir or Path(bundle_payload["bundle_dir"])
    if symbol_day_features is None:
        base_snapshot, mapping_payload, symbol_day_features = build_base_snapshot_from_bundle_payload(
            bundle_payload,
            schema_path=schema_path,
            session_minute_detail=session_minute_detail,
            asof_date=asof_date,
        )
    else:
        if symbol_day_features.empty:
            raise RuntimeError("Unable to derive symbol-day microstructure features from the bundle")
        base_snapshot, mapping_payload = _build_base_snapshot_from_symbol_day_features(
            symbol_day_features,
            schema_path=schema_path,
            asof_date=asof_date,
        )
        mapping_payload["bundle_manifest_path"] = str(bundle_payload["manifest_path"])
    output_paths = build_default_output_paths(bundle_payload["base_prefix"], target_dir, mapping_payload["asof_date"])
    output_paths["base_csv"].parent.mkdir(parents=True, exist_ok=True)
    # A-1: atomic writes.
    atomic_write_csv(base_snapshot, output_paths["base_csv"], index=False)
    atomic_write_parquet(symbol_day_features, output_paths["micro_day_parquet"], index=False)
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
    atomic_write_text(json.dumps(mapping_payload, indent=2) + "\n", output_paths["mapping_json"])
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


def _build_incremental_bundle_payload(
    *,
    export_dir: Path,
    trade_dates_covered: list[date],
    daily_bars: pd.DataFrame,
    daily_features: pd.DataFrame,
) -> dict[str, Any]:
    export_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    base_prefix = f"databento_volatility_production_incremental_{generated_at}"
    manifest_path = export_dir / f"{base_prefix}_manifest.json"
    # A-1: atomic writes.
    atomic_write_parquet(pd.DataFrame(daily_bars), export_dir / f"{base_prefix}__daily_bars.parquet", index=False)
    atomic_write_parquet(
        pd.DataFrame(daily_features),
        export_dir / f"{base_prefix}__daily_symbol_features_full_universe.parquet",
        index=False,
    )
    manifest = {
        "trade_dates_covered": [item.isoformat() for item in trade_dates_covered],
        "export_generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "incremental_base_only": True,
    }
    atomic_write_text(json.dumps(manifest, indent=2) + "\n", manifest_path)
    return {
        "manifest_path": manifest_path,
        "bundle_dir": export_dir,
        "base_prefix": base_prefix,
        "manifest": manifest,
        "frames": {
            "daily_bars": pd.DataFrame(daily_bars).copy(),
            "daily_symbol_features_full_universe": pd.DataFrame(daily_features).copy(),
        },
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
    incremental_base_only: bool = False,
    write_xlsx: bool = True,
    library_owner: str = "preuss_steffen",
    library_version: int = 1,
    progress_callback: Any = None,
) -> dict[str, Any]:
    def _progress(message: str) -> None:
        logger.info(message)
        if progress_callback is not None:
            progress_callback(message)

    if smc_base_only and incremental_base_only and not force_refresh:
        seed = _load_incremental_base_seed(export_dir)
        if seed is not None:
            previous_asof_raw = str(seed["manifest"].get("asof_date") or "").strip()
            previous_asof_date = date.fromisoformat(previous_asof_raw) if previous_asof_raw else None
            trading_days = list_recent_trading_days(
                databento_api_key,
                dataset=dataset,
                lookback_days=int(lookback_days),
            )
            if trading_days:
                incremental_trade_days = _resolve_incremental_trade_days(trading_days, previous_asof_date)
                if incremental_trade_days and len(incremental_trade_days) < len(trading_days):
                    _progress(
                        "Base scan: Starting incremental Databento production export pipeline "
                        f"({len(incremental_trade_days)} of {len(trading_days)} trading days)..."
                    )
                    export_started_at = time_module.perf_counter()
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
                        trading_days_override=incremental_trade_days,
                        progress_callback=progress_callback,
                    )
                    _progress(
                        "Base scan: Incremental Databento production export pipeline complete in "
                        f"{time_module.perf_counter() - export_started_at:.1f}s"
                    )

                    merged_daily_bars = _merge_incremental_frame(
                        cast(pd.DataFrame, seed["daily_bars"]),
                        pd.DataFrame(export_result.get("daily_bars", pd.DataFrame())),
                        key_columns=["trade_date", "symbol"],
                        sort_columns=["symbol", "trade_date"],
                    )
                    merged_daily_bars = _tail_trade_days(merged_daily_bars, trade_days=trading_days)
                    merged_daily_features = _merge_incremental_frame(
                        cast(pd.DataFrame, seed["daily_features"]),
                        pd.DataFrame(export_result.get("daily_symbol_features_full_universe", pd.DataFrame())),
                        key_columns=["trade_date", "symbol"],
                        sort_columns=["symbol", "trade_date"],
                    )
                    merged_daily_features = _tail_trade_days(merged_daily_features, trade_days=trading_days)
                    merged_daily_features = _recompute_daily_feature_volume_rollups(merged_daily_features)
                    merged_symbol_day_diagnostics = _merge_incremental_frame(
                        pd.DataFrame(seed.get("symbol_day_diagnostics", pd.DataFrame())),
                        pd.DataFrame(export_result.get("symbol_day_diagnostics", pd.DataFrame())),
                        key_columns=["trade_date", "symbol"],
                        sort_columns=["symbol", "trade_date"],
                    )
                    merged_symbol_day_diagnostics = _tail_trade_days(merged_symbol_day_diagnostics, trade_days=trading_days)

                    intraday_expected = merged_daily_features.copy()
                    intraday_expected["trade_date"] = _coerce_trade_date_series(intraday_expected["trade_date"])
                    intraday_expected["symbol"] = intraday_expected.get("symbol", pd.Series(index=intraday_expected.index, dtype=object)).astype(str).str.upper()
                    has_intraday_available = "has_intraday" in intraday_expected.columns
                    if has_intraday_available:
                        intraday_expected["has_intraday"] = _coerce_bool_series(intraday_expected["has_intraday"])
                    else:
                        intraday_expected["has_intraday"] = pd.Series(True, index=intraday_expected.index, dtype=bool)
                    intraday_expected = intraday_expected.loc[
                        intraday_expected["trade_date"].isin(set(incremental_trade_days))
                        & intraday_expected["trade_date"].notna()
                        & intraday_expected["symbol"].ne("")
                    ].copy()
                    if has_intraday_available:
                        has_intraday_false_count = int((~intraday_expected["has_intraday"]).sum())
                        if has_intraday_false_count > 0:
                            logger.warning(
                                "daily_symbol_features_full_universe contains %d symbol-days with has_intraday=False; keeping them in minute-detail fetch scope while excluding them from hard coverage expectations.",
                                has_intraday_false_count,
                            )
                    expected_symbols_by_trade_day = {
                        trade_day: set(group["symbol"].tolist())
                        for trade_day, group in intraday_expected.groupby("trade_date", sort=False)
                    }
                    if has_intraday_available:
                        required_symbols_by_trade_day: dict[date, set[str]] = {
                            trade_day: set() for trade_day in expected_symbols_by_trade_day
                        }
                        for trade_day, group in intraday_expected.loc[intraday_expected["has_intraday"]].groupby("trade_date", sort=False):
                            required_symbols_by_trade_day[trade_day] = set(group["symbol"].tolist())
                    else:
                        required_symbols_by_trade_day = {
                            trade_day: set(symbols)
                            for trade_day, symbols in expected_symbols_by_trade_day.items()
                        }
                    universe_symbols = set(merged_daily_features["symbol"].dropna().astype(str).str.upper())

                    _progress("Step 11/12: Collecting incremental full-session minute detail for microstructure base derivation...")
                    session_detail_started_at = time_module.perf_counter()
                    session_minute_detail = collect_full_universe_session_minute_detail(
                        databento_api_key,
                        dataset=dataset,
                        trading_days=incremental_trade_days,
                        universe_symbols=universe_symbols,
                        expected_symbols_by_trade_day=expected_symbols_by_trade_day,
                        required_symbols_by_trade_day=required_symbols_by_trade_day,
                        display_timezone=display_timezone,
                        cache_dir=cache_dir,
                        use_file_cache=use_file_cache,
                        force_refresh=force_refresh,
                    )
                    _progress(
                        "Step 11/12 complete: Incremental full-session minute detail collected in "
                        f"{time_module.perf_counter() - session_detail_started_at:.1f}s "
                        f"(rows={len(session_minute_detail)})"
                    )

                    delta_symbol_day_features = build_symbol_day_microstructure_feature_frame(
                        session_minute_detail,
                        merged_daily_features.loc[
                            pd.to_datetime(merged_daily_features["trade_date"], errors="coerce").dt.date.isin(set(incremental_trade_days))
                        ].copy(),
                    )
                    merged_symbol_day_features = _merge_incremental_frame(
                        cast(pd.DataFrame, seed["symbol_day_features"]),
                        delta_symbol_day_features,
                        key_columns=["trade_date", "symbol"],
                        sort_columns=["symbol", "trade_date"],
                    )
                    merged_symbol_day_features = _tail_trade_days(merged_symbol_day_features, trade_days=trading_days)

                    bundle_payload = _build_incremental_bundle_payload(
                        export_dir=export_dir,
                        trade_dates_covered=trading_days,
                        daily_bars=merged_daily_bars,
                        daily_features=merged_daily_features,
                    )
                    output_paths = build_default_output_paths(bundle_payload["base_prefix"], export_dir, str(max(trading_days).isoformat()))
                    if not session_minute_detail.empty:
                        atomic_write_parquet(session_minute_detail, output_paths["session_minute_parquet"], index=False)

                    _progress("Step 12/12: Building SMC microstructure base snapshot from incremental seed + delta...")
                    base_snapshot_started_at = time_module.perf_counter()
                    base_snapshot, mapping_payload = _build_base_snapshot_from_symbol_day_features(
                        merged_symbol_day_features,
                        schema_path=schema_path,
                    )
                    mapping_payload["bundle_manifest_path"] = str(bundle_payload["manifest_path"])
                    output_paths["base_csv"].parent.mkdir(parents=True, exist_ok=True)
                    # A-1: atomic writes.
                    atomic_write_csv(base_snapshot, output_paths["base_csv"], index=False)
                    atomic_write_parquet(merged_symbol_day_features, output_paths["micro_day_parquet"], index=False)
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
                    atomic_write_text(json.dumps(mapping_payload, indent=2) + "\n", output_paths["mapping_json"])
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
                    _progress(
                        "Step 12/12 complete: SMC microstructure base snapshot built in "
                        f"{time_module.perf_counter() - base_snapshot_started_at:.1f}s "
                        f"(rows={len(base_snapshot)})"
                    )
                    _write_incremental_base_seed(
                        export_dir,
                        bundle_manifest_path=Path(bundle_payload["manifest_path"]),
                        asof_date=mapping_payload["asof_date"],
                        trade_dates_covered=[item.isoformat() for item in trading_days],
                        daily_bars=merged_daily_bars,
                        daily_features=merged_daily_features,
                        symbol_day_features=merged_symbol_day_features,
                        symbol_day_diagnostics=merged_symbol_day_diagnostics,
                    )
                    return {
                        "bundle_manifest_path": Path(bundle_payload["manifest_path"]),
                        "base_snapshot": base_snapshot,
                        "mapping_payload": mapping_payload,
                        "symbol_day_features": merged_symbol_day_features,
                        "output_paths": effective_output_paths,
                        "warnings": [workbook_warning] if workbook_warning else [],
                        "workbook_written": workbook_written,
                        "production_workbook_path": None,
                        "export_result": {
                            **export_result,
                            "exported_paths": {
                                **export_result.get("exported_paths", {}),
                                "manifest": str(bundle_payload["manifest_path"]),
                            },
                            "daily_bars": merged_daily_bars,
                            "daily_symbol_features_full_universe": merged_daily_features,
                            "symbol_day_diagnostics": merged_symbol_day_diagnostics,
                        },
                    }
                _progress("Base scan: Incremental seed available but covers no smaller scope than the current window; falling back to full pipeline...")

    export_started_at = time_module.perf_counter()
    _progress("Base scan: Starting Databento production export pipeline...")
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
    _progress(
        "Base scan: Databento production export pipeline complete in "
        f"{time_module.perf_counter() - export_started_at:.1f}s"
    )
    bundle_load_started_at = time_module.perf_counter()
    manifest_path = Path(export_result["exported_paths"]["manifest"])
    bundle_payload = load_export_bundle(
        manifest_path,
        required_frames=REQUIRED_BUNDLE_FRAMES,
        manifest_prefix="databento_volatility_production_",
    )
    _progress(
        "Base scan: Export bundle load complete in "
        f"{time_module.perf_counter() - bundle_load_started_at:.1f}s"
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
    intraday_expected["trade_date"] = _coerce_trade_date_series(intraday_expected["trade_date"])
    intraday_expected["symbol"] = intraday_expected.get("symbol", pd.Series(index=intraday_expected.index, dtype=object)).astype(str).str.upper()
    has_intraday_available = "has_intraday" in intraday_expected.columns
    if has_intraday_available:
        intraday_expected["has_intraday"] = _coerce_bool_series(intraday_expected["has_intraday"])
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
                "daily_symbol_features_full_universe contains %d symbol-days with has_intraday=False; keeping them in minute-detail fetch scope while excluding them from hard coverage expectations.",
                has_intraday_false_count,
            )
    expected_symbols_by_trade_day = {
        trade_day: set(group["symbol"].tolist())
        for trade_day, group in intraday_expected.groupby("trade_date", sort=False)
    }
    if has_intraday_available:
        required_symbols_by_trade_day = {
            trade_day: set() for trade_day in expected_symbols_by_trade_day
        }
        for trade_day, group in intraday_expected.loc[intraday_expected["has_intraday"]].groupby("trade_date", sort=False):
            required_symbols_by_trade_day[trade_day] = set(group["symbol"].tolist())
    else:
        required_symbols_by_trade_day = {
            trade_day: set(symbols)
            for trade_day, symbols in expected_symbols_by_trade_day.items()
        }
    universe_symbols = set(daily_feature_frame["symbol"].dropna().astype(str).str.upper())

    _progress("Step 11/12: Collecting full-session minute detail for microstructure base derivation...")
    session_detail_started_at = time_module.perf_counter()
    session_minute_detail = collect_full_universe_session_minute_detail(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
        expected_symbols_by_trade_day=expected_symbols_by_trade_day,
        required_symbols_by_trade_day=required_symbols_by_trade_day,
        display_timezone=display_timezone,
        cache_dir=cache_dir,
        use_file_cache=use_file_cache,
        force_refresh=force_refresh,
    )
    _progress(
        "Step 11/12 complete: Full-session minute detail collected in "
        f"{time_module.perf_counter() - session_detail_started_at:.1f}s "
        f"(rows={len(session_minute_detail)})"
    )
    output_paths = build_default_output_paths(bundle_payload["base_prefix"], export_dir, str(max(trading_days).isoformat()))
    if not session_minute_detail.empty:
        atomic_write_parquet(session_minute_detail, output_paths["session_minute_parquet"], index=False)

    _progress("Step 12/12: Building SMC microstructure base snapshot...")
    base_snapshot_started_at = time_module.perf_counter()
    canonical_production_workbook = export_result.get("exported_paths", {}).get("canonical_production_workbook")
    _progress("Step 12/12a: Deriving symbol-day microstructure features from session minute detail...")
    symbol_day_features_started_at = time_module.perf_counter()
    symbol_day_features = build_symbol_day_microstructure_feature_frame(
        session_minute_detail,
        daily_feature_frame,
        telemetry_callback=_progress,
        mutate_input=True,
    )
    _progress(
        "Step 12/12a complete: Symbol-day microstructure features built in "
        f"{time_module.perf_counter() - symbol_day_features_started_at:.1f}s "
        f"(rows={len(symbol_day_features)}, approx_frame_mib={_approx_frame_memory_mebibytes(symbol_day_features):.1f})"
    )
    session_minute_detail = pd.DataFrame()
    _progress("Step 12/12b: Aggregating base snapshot from symbol-day features...")
    base_result = generate_base_from_bundle(
        bundle_payload,
        schema_path=schema_path,
        output_dir=export_dir,
        write_xlsx=write_xlsx,
        session_minute_detail=None,
        symbol_day_features=symbol_day_features,
        library_owner=library_owner,
        library_version=library_version,
    )
    _progress(
        "Step 12/12 complete: SMC microstructure base snapshot built in "
        f"{time_module.perf_counter() - base_snapshot_started_at:.1f}s "
        f"(rows={len(base_result.get('base_snapshot', []))})"
    )
    base_manifest_path = base_result["output_paths"].get("base_manifest")
    if base_manifest_path is not None:
        try:
            manifest_payload = json.loads(Path(base_manifest_path).read_text(encoding="utf-8"))
            if isinstance(manifest_payload, dict):
                manifest_payload["production_workbook_path"] = str(canonical_production_workbook) if canonical_production_workbook else None
                manifest_payload["canonical_upstream_artifact"] = "databento_production_export_bundle"
                atomic_write_text(json.dumps(manifest_payload, indent=2) + "\n", Path(base_manifest_path))
        except Exception:
            logger.warning("Failed to enrich base manifest with production workbook lineage", exc_info=True)
    try:
        _write_incremental_base_seed(
            export_dir,
            bundle_manifest_path=manifest_path,
            asof_date=str(max(trading_days).isoformat()),
            trade_dates_covered=[item.isoformat() for item in trading_days],
            daily_bars=pd.DataFrame(bundle_payload["frames"]["daily_bars"]),
            daily_features=pd.DataFrame(daily_feature_frame),
            symbol_day_features=pd.DataFrame(base_result.get("symbol_day_features", pd.DataFrame())),
            symbol_day_diagnostics=pd.DataFrame(export_result.get("symbol_day_diagnostics", pd.DataFrame())),
        )
    except Exception:
        logger.warning("Failed to write incremental base seed", exc_info=True)
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


