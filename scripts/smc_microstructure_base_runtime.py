from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
import warnings
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from databento_volatility_screener import (
    US_EASTERN_TZ,
    _clamp_request_end,
    _databento_get_range_with_retry,
    _extract_unresolved_symbols_from_warning_messages,
    _get_schema_available_end,
    _iter_symbol_batches,
    _make_databento_client,
    _read_cached_frame,
    _store_to_frame,
    _trade_day_cache_max_age_seconds,
    _validate_frame_columns,
    _warn_with_redacted_exception,
    _write_cached_frame,
    build_cache_path,
    choose_default_dataset,
    list_accessible_datasets,
    PREFERRED_DATABENTO_DATASETS,
    resolve_display_timezone,
)
from scripts.databento_production_export import run_production_export_pipeline
from scripts.generate_smc_micro_profiles import load_schema, run_generation
from scripts.load_databento_export_bundle import load_export_bundle
from scripts.verify_smc_micro_publish_contract import verify_publish_contract


logger = logging.getLogger(__name__)


def _resolve_ui_dataset_options(databento_api_key: str, requested_dataset: str | None) -> tuple[list[str], str, str | None]:
    fallback_options = list(dict.fromkeys([*(str(dataset) for dataset in PREFERRED_DATABENTO_DATASETS), "DBEQ.BASIC"]))
    requested = str(requested_dataset or "").strip() or "DBEQ.BASIC"
    if not databento_api_key:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        return fallback_options, selected, None
    try:
        available = list_accessible_datasets(databento_api_key)
    except Exception as exc:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        warning = f"Could not load Databento datasets from metadata; using fallback list ({exc})."
        return fallback_options, selected, warning
    options = [str(dataset).strip() for dataset in available if str(dataset).strip()]
    if not options:
        selected = choose_default_dataset(fallback_options, requested_dataset=requested)
        return fallback_options, selected, "Databento metadata returned no datasets; using fallback list."
    selected = choose_default_dataset(options, requested_dataset=requested)
    return options, selected, None


def publish_micro_library_to_tradingview(
    *,
    repo_root: Path,
    report_path: Path,
) -> dict[str, Any]:
    command = [
        "npm",
        "run",
        "--silent",
        "tv:publish-micro-library",
        "--",
        "--out",
        str(report_path),
    ]
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    stdout = (completed.stdout or "").strip()
    stderr = (completed.stderr or "").strip()
    payload: dict[str, Any] | None = None
    if stdout:
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            payload = None
    if payload is None and report_path.exists():
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    if payload is None:
        raise RuntimeError(stderr or stdout or "TradingView micro-library publish did not return a readable report.")
    payload["report_path"] = str(report_path)
    payload["stdout"] = stdout
    payload["stderr"] = stderr
    payload["returncode"] = completed.returncode
    if completed.returncode != 0:
        raise RuntimeError(str(payload.get("error") or stderr or stdout or "TradingView micro-library publish failed."))
    return payload


def inspect_generated_micro_library_contract(repo_root: Path) -> dict[str, Any]:
    manifest_path = repo_root / "pine" / "generated" / "smc_micro_profiles_generated.json"
    if not manifest_path.exists():
        return {
            "exists": False,
            "manifest_path": manifest_path,
            "owner": None,
            "version": None,
            "import_path": None,
            "reason": "Generate Pine Library first. No generated micro-library manifest exists yet.",
        }

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "exists": False,
            "manifest_path": manifest_path,
            "owner": None,
            "version": None,
            "import_path": None,
            "reason": f"Generated micro-library manifest could not be read: {exc}",
        }

    owner = str(payload.get("library_owner") or "").strip() or None
    raw_version = payload.get("library_version")
    try:
        version = int(raw_version) if raw_version is not None else None
    except (TypeError, ValueError):
        version = None

    return {
        "exists": True,
        "manifest_path": manifest_path,
        "owner": owner,
        "version": version,
        "import_path": str(payload.get("recommended_import_path") or "").strip() or None,
        "owner_version_ready": bool(owner and version is not None),
        "full_contract_ready": False,
        "reason": None,
    }


def evaluate_micro_library_publish_guard(
    *,
    repo_root: Path,
    library_owner: str,
    library_version: int,
) -> dict[str, Any]:
    contract = inspect_generated_micro_library_contract(repo_root)
    configured_owner = str(library_owner).strip()
    configured_version = int(library_version)

    if not contract["exists"]:
        return {
            "can_publish": False,
            "message": str(contract["reason"]),
            "severity": "warning",
            "contract": contract,
        }

    generated_owner = str(contract.get("owner") or "").strip()
    generated_version = contract.get("version")
    if generated_owner != configured_owner or generated_version != configured_version:
        contract["owner_version_ready"] = False
        return {
            "can_publish": False,
            "message": (
                "Publish blocked: the sidebar owner/version do not match the generated library artifacts. "
                f"Generated = {generated_owner or 'n/a'}/{generated_version if generated_version is not None else 'n/a'}, "
                f"Configured = {configured_owner or 'n/a'}/{configured_version}. Regenerate the Pine library first."
            ),
            "severity": "error",
            "contract": contract,
        }

    contract["owner_version_ready"] = True
    try:
        verify_publish_contract(Path(contract["manifest_path"]), repo_root / "SMC_Core_Engine.pine")
    except Exception as exc:
        contract["full_contract_ready"] = False
        return {
            "can_publish": False,
            "message": (
                "Publish blocked: owner/version match, but the full manifest/snippet/core contract is not valid. "
                f"Details: {exc}"
            ),
            "severity": "error",
            "contract": contract,
        }

    contract["full_contract_ready"] = True

    return {
        "can_publish": True,
        "message": (
            "Publish ready: owner/version match and the full manifest/snippet/core contract validated successfully. "
            f"Import path: {contract.get('import_path') or 'n/a'}"
        ),
        "severity": "success",
        "contract": contract,
    }

REQUIRED_BUNDLE_FRAMES = (
    "daily_bars",
    "daily_symbol_features_full_universe",
)

PREMARKET_START_ET = time(4, 0)
REGULAR_OPEN_ET = time(9, 30)
OPEN_30M_END_ET = time(10, 0)
MIDDAY_START_ET = time(11, 0)
MIDDAY_END_ET = time(14, 0)
LATE_START_ET = time(14, 30)
CLOSE_60M_START_ET = time(15, 0)
REGULAR_CLOSE_ET = time(16, 0)
AFTERHOURS_END_ET = time(20, 0)

PREMARKET_MINUTES = 330
REGULAR_MINUTES = 390
MIDDAY_MINUTES = 180
AFTERHOURS_MINUTES = 240

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


def _universe_fingerprint(symbols: set[str]) -> str:
    normalized = ",".join(sorted(str(symbol).strip().upper() for symbol in symbols if str(symbol).strip()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]


def _coverage_stats(frame: pd.DataFrame, expected_symbols: set[str]) -> dict[str, Any]:
    normalized_expected = {str(symbol).strip().upper() for symbol in expected_symbols if str(symbol).strip()}
    if frame.empty or "symbol" not in frame.columns:
        actual_symbols: set[str] = set()
    else:
        actual_symbols = set(frame["symbol"].dropna().astype(str).str.upper())
    missing_symbols = sorted(normalized_expected - actual_symbols)
    coverage_ratio = 1.0 if not normalized_expected else float(len(actual_symbols & normalized_expected) / len(normalized_expected))
    return {
        "expected_count": len(normalized_expected),
        "actual_count": len(actual_symbols & normalized_expected),
        "coverage_ratio": coverage_ratio,
        "missing_symbols": missing_symbols,
    }


def _assert_complete_symbol_coverage(frame: pd.DataFrame, expected_symbols: set[str], *, context: str) -> None:
    coverage = _coverage_stats(frame, expected_symbols)
    if coverage["missing_symbols"]:
        sample = ", ".join(coverage["missing_symbols"][:10])
        raise RuntimeError(
            f"{context}: incomplete symbol coverage ({coverage['actual_count']}/{coverage['expected_count']}). "
            f"Missing symbols include: {sample}"
        )


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


def collect_full_universe_session_minute_detail(
    databento_api_key: str,
    *,
    dataset: str,
    trading_days: list[date],
    universe_symbols: set[str],
    display_timezone: str,
    cache_dir: str | Path | None = None,
    use_file_cache: bool = True,
    force_refresh: bool = False,
) -> pd.DataFrame:
    output_columns = [
        "trade_date",
        "symbol",
        "timestamp",
        "session",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trade_count",
    ]
    if not trading_days or not universe_symbols:
        return pd.DataFrame(columns=output_columns)

    client = _make_databento_client(databento_api_key)
    available_end = _get_schema_available_end(client, dataset, "ohlcv-1m")
    display_tz = resolve_display_timezone(display_timezone)
    all_rows: list[pd.DataFrame] = []
    runtime_unsupported_symbols: set[str] = set()
    latest_trade_day = max(trading_days)

    for trade_day in trading_days:
        local_start = datetime.combine(trade_day, PREMARKET_START_ET, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
        local_end = datetime.combine(trade_day, AFTERHOURS_END_ET, tzinfo=US_EASTERN_TZ).astimezone(display_tz)
        fetch_start_utc = pd.Timestamp(local_start.astimezone(UTC))
        fetch_end_utc = _clamp_request_end(pd.Timestamp(local_end.astimezone(UTC)), available_end)
        if fetch_end_utc <= fetch_start_utc:
            continue

        cache_path = build_cache_path(
            cache_dir,
            "full_universe_session_minute_detail",
            dataset=dataset,
            parts=[
                trade_day.isoformat(),
                display_timezone,
                PREMARKET_START_ET.strftime("%H%M%S"),
                AFTERHOURS_END_ET.strftime("%H%M%S"),
                _universe_fingerprint(universe_symbols),
            ],
        )
        day_frame: pd.DataFrame | None = None
        if use_file_cache and not force_refresh:
            day_frame = _read_cached_frame(
                cache_path,
                max_age_seconds=_trade_day_cache_max_age_seconds(trade_day, latest_trade_day),
            )
            if day_frame is not None:
                try:
                    _assert_complete_symbol_coverage(
                        day_frame,
                        universe_symbols,
                        context=f"Cached session minute detail for {trade_day}",
                    )
                except RuntimeError as exc:
                    logger.warning("Ignoring incomplete session-minute cache for %s: %s", trade_day, exc)
                    day_frame = None

        if day_frame is None:
            day_parts: list[pd.DataFrame] = []
            active_symbols = set(universe_symbols) - runtime_unsupported_symbols
            for symbols_batch in _iter_symbol_batches(active_symbols):
                try:
                    with warnings.catch_warnings(record=True) as caught_warnings:
                        warnings.simplefilter("always")
                        store = _databento_get_range_with_retry(
                            client,
                            context="collect_full_universe_session_minute_detail",
                            dataset=dataset,
                            symbols=symbols_batch,
                            schema="ohlcv-1m",
                            start=fetch_start_utc.isoformat(),
                            end=fetch_end_utc.isoformat(),
                        )
                    frame = _store_to_frame(store, count=250_000, context="collect_full_universe_session_minute_detail")
                    runtime_unsupported_symbols.update(
                        _extract_unresolved_symbols_from_warning_messages([str(item.message) for item in caught_warnings])
                    )
                    if not frame.empty:
                        _validate_frame_columns(
                            frame,
                            required={"symbol", "open", "high", "low", "close", "volume"},
                            context="collect_full_universe_session_minute_detail",
                        )
                except Exception as exc:
                    _warn_with_redacted_exception(
                        f"Session minute detail fetch failed for batch on {trade_day}, skipping",
                        exc,
                        include_traceback=True,
                    )
                    continue
                if frame.empty or "symbol" not in frame.columns:
                    continue

                frame = frame.copy()
                frame["symbol"] = frame["symbol"].astype(str).str.upper()
                frame = frame[frame["symbol"].isin(universe_symbols)].copy()
                if frame.empty:
                    continue

                frame["timestamp"] = pd.to_datetime(frame["ts"], errors="coerce", utc=True).dt.tz_convert(display_tz)
                et_time = frame["timestamp"].dt.tz_convert(US_EASTERN_TZ).dt.time
                frame["session"] = np.select(
                    [
                        et_time < REGULAR_OPEN_ET,
                        et_time < REGULAR_CLOSE_ET,
                        et_time <= AFTERHOURS_END_ET,
                    ],
                    ["premarket", "regular", "afterhours"],
                    default="overnight",
                )
                trade_count_column = next(
                    (candidate for candidate in ("trade_count", "count", "n_trades", "num_trades") if candidate in frame.columns),
                    None,
                )
                if trade_count_column is not None:
                    frame["trade_count"] = pd.to_numeric(frame[trade_count_column], errors="coerce")
                else:
                    frame["trade_count"] = np.nan
                frame.insert(0, "trade_date", trade_day)
                day_parts.append(frame[output_columns].reset_index(drop=True))

            day_frame = pd.concat(day_parts, ignore_index=True) if day_parts else pd.DataFrame(columns=output_columns)
            _assert_complete_symbol_coverage(
                day_frame,
                universe_symbols,
                context=f"Session minute detail for {trade_day}",
            )
            if use_file_cache and not day_frame.empty:
                _write_cached_frame(cache_path, day_frame)

        if day_frame is not None and not day_frame.empty:
            all_rows.append(day_frame)

    return pd.concat(all_rows, ignore_index=True) if all_rows else pd.DataFrame(columns=output_columns)


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

            rows: list[dict[str, Any]] = []
            for (trade_day, symbol), group in minute_frame.groupby(["trade_date", "symbol"], sort=False):
                ordered = group.sort_values("timestamp").reset_index(drop=True)
                pm = _session_slice(ordered, PREMARKET_START_ET, REGULAR_OPEN_ET)
                rth = _session_slice(ordered, REGULAR_OPEN_ET, REGULAR_CLOSE_ET)
                open_30 = _session_slice(ordered, REGULAR_OPEN_ET, OPEN_30M_END_ET)
                midday = _session_slice(ordered, MIDDAY_START_ET, MIDDAY_END_ET)
                late = _session_slice(ordered, LATE_START_ET, REGULAR_CLOSE_ET)
                close_60 = _session_slice(ordered, CLOSE_60M_START_ET, REGULAR_CLOSE_ET)
                ah = _session_slice(ordered, REGULAR_CLOSE_ET, AFTERHOURS_END_ET)

                pm_stats = _session_stats(pm, available_minutes=PREMARKET_MINUTES)
                rth_stats = _session_stats(rth, available_minutes=REGULAR_MINUTES)
                midday_stats = _session_stats(midday, available_minutes=MIDDAY_MINUTES)
                ah_stats = _session_stats(ah, available_minutes=AFTERHOURS_MINUTES)

                total_day_dollar = pm_stats["dollar_volume"] + rth_stats["dollar_volume"] + ah_stats["dollar_volume"]
                total_day_trades = pm_stats["trade_proxy"] + rth_stats["trade_proxy"] + ah_stats["trade_proxy"]

                early_return = 0.0
                if not open_30.empty:
                    early_open = _safe_float(open_30.iloc[0].get("open"), default=np.nan)
                    early_close = _safe_float(open_30.iloc[-1].get("close"), default=np.nan)
                    if np.isfinite(early_open) and early_open > 0 and np.isfinite(early_close):
                        early_return = abs((early_close / early_open) - 1.0)

                late_return = 0.0
                if not late.empty:
                    late_open = _safe_float(late.iloc[0].get("open"), default=np.nan)
                    late_close = _safe_float(late.iloc[-1].get("close"), default=np.nan)
                    if np.isfinite(late_open) and late_open > 0 and np.isfinite(late_close):
                        late_return = abs((late_close / late_open) - 1.0)

                rth_open = _safe_float(rth.iloc[0].get("open"), default=np.nan) if not rth.empty else np.nan
                rth_close = _safe_float(rth.iloc[-1].get("close"), default=np.nan) if not rth.empty else np.nan
                rth_net_return_abs = abs((rth_close / rth_open) - 1.0) if np.isfinite(rth_open) and rth_open > 0 and np.isfinite(rth_close) else 0.0

                rows.append(
                    {
                        "trade_date": trade_day,
                        "symbol": symbol,
                        "daily_rth_dollar_volume": rth_stats["dollar_volume"],
                        "daily_avg_spread_bps_rth": rth_stats["spread_bps"],
                        "daily_rth_active_minutes_share": rth_stats["active_minutes_share"],
                        "daily_open_30m_dollar_share": _safe_ratio(open_30["dollar_volume"].sum(), rth_stats["dollar_volume"], default=0.0),
                        "daily_close_60m_dollar_share": _safe_ratio(close_60["dollar_volume"].sum(), rth_stats["dollar_volume"], default=0.0),
                        "daily_rth_wickiness": rth_stats["wickiness"],
                        "daily_pm_dollar_share": _safe_ratio(pm_stats["dollar_volume"], total_day_dollar, default=0.0),
                        "daily_pm_trades_share": _safe_ratio(pm_stats["trade_proxy"], total_day_trades, default=0.0),
                        "daily_pm_active_minutes_share": pm_stats["active_minutes_share"],
                        "daily_pm_spread_bps": pm_stats["spread_bps"],
                        "daily_pm_wickiness": pm_stats["wickiness"],
                        "daily_midday_dollar_share": _safe_ratio(midday_stats["dollar_volume"], rth_stats["dollar_volume"], default=0.0),
                        "daily_midday_trades_share": _safe_ratio(midday_stats["trade_proxy"], rth_stats["trade_proxy"], default=0.0),
                        "daily_midday_active_minutes_share": midday_stats["active_minutes_share"],
                        "daily_midday_spread_bps": midday_stats["spread_bps"],
                        "daily_midday_efficiency": midday_stats["efficiency"],
                        "daily_ah_dollar_share": _safe_ratio(ah_stats["dollar_volume"], total_day_dollar, default=0.0),
                        "daily_ah_trades_share": _safe_ratio(ah_stats["trade_proxy"], total_day_trades, default=0.0),
                        "daily_ah_active_minutes_share": ah_stats["active_minutes_share"],
                        "daily_ah_spread_bps": ah_stats["spread_bps"],
                        "daily_ah_wickiness": ah_stats["wickiness"],
                        "daily_setup_decay_half_life_bars": _setup_decay_half_life_30m_buckets(rth),
                        "daily_early_vs_late_followthrough_ratio": _safe_ratio(early_return, max(late_return, 1e-6), default=0.0),
                        "daily_rth_efficiency": rth_stats["efficiency"],
                        "daily_rth_net_return_abs": rth_net_return_abs,
                    }
                )
            minute_metrics = pd.DataFrame(rows, columns=metric_columns)

    merged = daily.merge(minute_metrics, on=["trade_date", "symbol"], how="left")
    for column in metric_columns:
        if column in {"trade_date", "symbol"}:
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

    reclaim_flag = merged.get("reclaimed_start_price_within_30s", pd.Series(False, index=merged.index)).map(_coerce_bool)
    early_dip_pct = pd.to_numeric(merged.get("early_dip_pct_10s"), errors="coerce").fillna(0.0)
    followthrough_pct = pd.to_numeric(merged.get("open_to_current_pct"), errors="coerce").fillna(
        pd.to_numeric(merged.get("window_return_pct"), errors="coerce").fillna(0.0)
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
        & pd.to_numeric(merged.get("close_preclose_return_pct"), errors="coerce").fillna(0.0).lt(0.0)
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
            f"Bundle asof_date is {days_stale} trading days old ({resolved_asof}). "
            "The generated Pine library will reflect stale microstructure data.",
            stacklevel=2,
        )

    trailing = symbol_day_features.loc[symbol_day_features["trade_date"] <= resolved_asof].copy()
    trailing = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(20)

    latest = trailing.sort_values(["symbol", "trade_date"]).groupby("symbol", group_keys=False).tail(1)
    rows: list[dict[str, Any]] = []
    for symbol, group in trailing.groupby("symbol", sort=True):
        latest_row = latest.loc[latest["symbol"] == symbol].iloc[0]
        coverage_days = int(group["trade_date"].nunique())
        coverage_days_min = 3  # Minimum sessions for meaningful 20d metrics
        if coverage_days < coverage_days_min:
            logger.warning(
                "Symbol %s has only %d trading days in trailing window; "
                "20d metrics are not statistically meaningful.",
                symbol,
                coverage_days,
            )
        daily_close = pd.to_numeric(group.get("day_close"), errors="coerce")
        day_volume = pd.to_numeric(group.get("day_volume"), errors="coerce")
        adv_fallback = (daily_close * day_volume).replace([np.inf, -np.inf], np.nan)
        adv_rth = pd.to_numeric(group.get("daily_rth_dollar_volume"), errors="coerce")
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
                "avg_spread_bps_rth_20d": _mean_or_default(group["daily_avg_spread_bps_rth"], default=0.0),
                "rth_active_minutes_share_20d": _clip01(_mean_or_default(group["daily_rth_active_minutes_share"], default=0.0)),
                "open_30m_dollar_share_20d": _clip01(_mean_or_default(group["daily_open_30m_dollar_share"], default=0.0)),
                "close_60m_dollar_share_20d": _clip01(_mean_or_default(group["daily_close_60m_dollar_share"], default=0.0)),
                "clean_intraday_score_20d": _clip01(_mean_or_default(group["daily_clean_intraday_score"], default=0.0)),
                "consistency_score_20d": _clip01(_consistency_score(group)),
                "close_hygiene_20d": _clip01(_mean_or_default(group["daily_close_hygiene"], default=0.0)),
                "wickiness_20d": _clip01(_mean_or_default(group["daily_rth_wickiness"], default=0.0)),
                "pm_dollar_share_20d": _clip01(_mean_or_default(group["daily_pm_dollar_share"], default=0.0)),
                "pm_trades_share_20d": _clip01(_mean_or_default(group["daily_pm_trades_share"], default=0.0)),
                "pm_active_minutes_share_20d": _clip01(_mean_or_default(group["daily_pm_active_minutes_share"], default=0.0)),
                "pm_spread_bps_20d": _mean_or_default(group["daily_pm_spread_bps"], default=0.0),
                "pm_wickiness_20d": _clip01(_mean_or_default(group["daily_pm_wickiness"], default=0.0)),
                "midday_dollar_share_20d": _clip01(_mean_or_default(group["daily_midday_dollar_share"], default=0.0)),
                "midday_trades_share_20d": _clip01(_mean_or_default(group["daily_midday_trades_share"], default=0.0)),
                "midday_active_minutes_share_20d": _clip01(_mean_or_default(group["daily_midday_active_minutes_share"], default=0.0)),
                "midday_spread_bps_20d": _mean_or_default(group["daily_midday_spread_bps"], default=0.0),
                "midday_efficiency_20d": _clip01(_mean_or_default(group["daily_midday_efficiency"], default=0.0)),
                "ah_dollar_share_20d": _clip01(_mean_or_default(group["daily_ah_dollar_share"], default=0.0)),
                "ah_trades_share_20d": _clip01(_mean_or_default(group["daily_ah_trades_share"], default=0.0)),
                "ah_active_minutes_share_20d": _clip01(_mean_or_default(group["daily_ah_active_minutes_share"], default=0.0)),
                "ah_spread_bps_20d": _mean_or_default(group["daily_ah_spread_bps"], default=0.0),
                "ah_wickiness_20d": _clip01(_mean_or_default(group["daily_ah_wickiness"], default=0.0)),
                "reclaim_respect_rate_20d": _clip01(_mean_or_default(group["daily_reclaim_respect_flag"], default=0.0)),
                "reclaim_failure_rate_20d": _clip01(_mean_or_default(group["daily_reclaim_failure_flag"], default=0.0)),
                "reclaim_followthrough_r_20d": _mean_or_default(group["daily_reclaim_followthrough_r"], default=0.0),
                "ob_sweep_reversal_rate_20d": _clip01(_mean_or_default(group["daily_ob_sweep_reversal_flag"], default=0.0)),
                "ob_sweep_depth_p75_20d": _quantile_or_default(group["daily_ob_sweep_depth"], 0.75, default=0.0),
                "fvg_sweep_reversal_rate_20d": _clip01(_mean_or_default(group["daily_fvg_sweep_reversal_flag"], default=0.0)),
                "fvg_sweep_depth_p75_20d": _quantile_or_default(group["daily_fvg_sweep_depth"], 0.75, default=0.0),
                "stop_hunt_rate_20d": _clip01(_mean_or_default(group["daily_stop_hunt_flag"], default=0.0)),
                "setup_decay_half_life_bars_20d": _mean_or_default(group["daily_setup_decay_half_life_bars"], default=0.0),
                "early_vs_late_followthrough_ratio_20d": _mean_or_default(group["daily_early_vs_late_followthrough_ratio"], default=0.0),
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
    path.parent.mkdir(parents=True, exist_ok=True)
    mapping_frame = pd.DataFrame(mapping_payload["mapping_status"])
    summary_frame = pd.DataFrame(
        [
            {
                "bundle_manifest_path": mapping_payload["bundle_manifest_path"],
                "asof_date": mapping_payload["asof_date"],
                "row_count": mapping_payload["row_count"],
                "direct_fields": len(mapping_payload["direct_fields"]),
                "derived_fields": len(mapping_payload["derived_fields"]),
                "missing_fields": len(mapping_payload["missing_fields"]),
            }
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        base_snapshot.to_excel(writer, sheet_name="base_snapshot", index=False)
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
        "recommended_library_import": f"{library_owner}/smc_micro_profiles_generated/{library_version}",
        "core_ready": core_ready,
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
    universe_symbols = set(daily_feature_frame["symbol"].dropna().astype(str).str.upper())

    _progress("Step 11/12: Collecting full-session minute detail for microstructure base derivation...")
    session_minute_detail = collect_full_universe_session_minute_detail(
        databento_api_key,
        dataset=dataset,
        trading_days=trading_days,
        universe_symbols=universe_symbols,
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
    base_result = generate_base_from_bundle(
        bundle_payload,
        schema_path=schema_path,
        output_dir=export_dir,
        write_xlsx=write_xlsx,
        session_minute_detail=session_minute_detail,
        library_owner=library_owner,
        library_version=library_version,
    )
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
) -> dict[str, Path]:
    return run_generation(
        schema_path=schema_path,
        input_path=base_csv_path,
        overrides_path=overrides_path,
        output_root=output_root,
        library_owner=library_owner,
        library_version=library_version,
    )


def list_generated_base_csvs(export_dir: Path) -> list[Path]:
    return sorted(
        export_dir.glob("*__smc_microstructure_base_*.csv"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def resolve_latest_base_csv(export_dir: Path) -> Path | None:
    candidates = list_generated_base_csvs(export_dir)
    return candidates[0] if candidates else None


def resolve_base_csv_selection(candidates: list[Path], selected_label: str | None) -> Path | None:
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    selected = str(selected_label or "").strip()
    if not selected:
        return None
    return next((path for path in candidates if path.name == selected), None)


def resolve_base_csv_action_target(candidates: list[Path], selected_label: str | None) -> tuple[Path | None, str | None]:
    selected = resolve_base_csv_selection(candidates, selected_label)
    if not candidates:
        return None, "No generated base CSV found yet. Run the SMC base scan first."
    if len(candidates) > 1 and selected is None:
        return None, "Select an explicit generated base CSV before generating or publishing Pine artifacts."
    return selected, None


def run_streamlit_micro_base_app() -> None:
    import os
    import streamlit as st
    from dotenv import load_dotenv

    repo_root = Path(__file__).resolve().parents[1]
    load_dotenv(repo_root / ".env", override=True)

    st.set_page_config(page_title="SMC Microstructure Base Generator", layout="wide")
    st.title("SMC Microstructure Base Generator")
    st.caption("Runs the full Databento universe scan, creates Parquet and manifest artifacts, derives the daily base snapshot, and optionally generates the Pine library.")

    if "smc_base_logs" not in st.session_state:
        st.session_state["smc_base_logs"] = []
    if "smc_base_result" not in st.session_state:
        st.session_state["smc_base_result"] = None
    if "smc_pine_result" not in st.session_state:
        st.session_state["smc_pine_result"] = None
    if "smc_publish_result" not in st.session_state:
        st.session_state["smc_publish_result"] = None

    def add_log(message: str) -> None:
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        st.session_state["smc_base_logs"] = [*st.session_state["smc_base_logs"], f"{timestamp} {message}"][-100:]

    default_export_dir = repo_root / "artifacts" / "smc_microstructure_exports"
    with st.sidebar:
        databento_api_key = st.text_input("Databento API Key", value=os.getenv("DATABENTO_API_KEY", ""), type="password")
        fmp_api_key = st.text_input("FMP API Key (optional)", value=os.getenv("FMP_API_KEY", ""), type="password")
        export_dir_raw = st.text_input("Export directory", value=str(default_export_dir))
        dataset_options, dataset_default, dataset_warning = _resolve_ui_dataset_options(
            databento_api_key,
            os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"),
        )
        dataset = st.selectbox(
            "Databento dataset",
            options=dataset_options,
            index=dataset_options.index(dataset_default),
            help="Open-focused scan: keep DBEQ.BASIC for broad coverage, or switch to XNAS.BASIC/XNAS.ITCH when your signal quality depends mainly on Nasdaq open behavior.",
        )
        if dataset_warning:
            st.caption(dataset_warning)
        st.caption("Open/first-hours mode: default to DBEQ.BASIC for broad base generation; use XNAS.BASIC or XNAS.ITCH only when you intentionally bias the base toward Nasdaq open behavior.")
        lookback_days = st.number_input("Trading days", min_value=5, max_value=90, value=30)
        bullish_score_profile = st.text_input("Bullish score profile", value="balanced")
        smc_base_only = st.checkbox(
            "SMC base-only export mode",
            value=True,
            help="Disables the preopen 04:00 seed selection and the fixed 10:00 ET outcome snapshot when the export is used only to derive the SMC microstructure base.",
        )
        write_xlsx = st.checkbox("Write Base workbook (.xlsx)", value=True)
        if smc_base_only:
            st.caption("Base-only mode is active: the export skips the 04:00 preopen seed scope and the fixed 10:00 ET outcome snapshot.")
        else:
            st.caption("Full research export mode is active: the export also keeps the 04:00 preopen seed scope and the fixed 10:00 ET outcome snapshot.")
        library_owner = st.text_input("TradingView owner", value="preuss_steffen")
        library_version = st.number_input("TradingView library version", min_value=1, max_value=99, value=1)
        st.caption("SMC_Core_Engine.pine is already wired to import the generated TradingView library path.")

    export_dir = Path(export_dir_raw).expanduser()
    schema_path = repo_root / "schema" / "schema.json"
    overrides_path = repo_root / "data" / "input" / "microstructure_overrides.csv"
    try:
        publish_guard = evaluate_micro_library_publish_guard(
            repo_root=repo_root,
            library_owner=str(library_owner),
            library_version=int(library_version),
        )
    except Exception as exc:
        publish_guard = {
            "can_publish": False,
            "message": f"Publish guard evaluation failed: {exc}",
            "severity": "error",
            "contract": {},
        }
    base_csv_candidates = list_generated_base_csvs(export_dir)
    base_csv_option_labels = [path.name for path in base_csv_candidates]
    base_csv_requires_explicit_selection = len(base_csv_candidates) > 1
    selected_base_csv_label = st.selectbox(
        "Base snapshot for Pine generation",
        options=base_csv_option_labels,
        index=None if base_csv_requires_explicit_selection else 0,
        placeholder="Select a generated base CSV" if base_csv_requires_explicit_selection else None,
        disabled=not base_csv_candidates,
        help="Select the exact generated base CSV to convert into Pine artifacts. This avoids silently using the most recently modified file.",
    ) if base_csv_candidates else None
    selected_base_csv = resolve_base_csv_selection(base_csv_candidates, selected_base_csv_label)
    if base_csv_requires_explicit_selection and selected_base_csv is None:
        st.info("Multiple generated base snapshots were found. Select the exact base CSV before generating or publishing Pine artifacts.")
    action_base_csv, action_base_csv_error = resolve_base_csv_action_target(base_csv_candidates, selected_base_csv_label)

    action_cols = st.columns(4)
    run_base_scan = action_cols[0].button("Run SMC Base Scan", type="primary")
    refresh_base_scan = action_cols[1].button("Refresh Data")
    generate_pine = action_cols[2].button("Generate Pine Library")
    publish_pine = action_cols[3].button(
        "Publish To TradingView",
        disabled=not bool(publish_guard["can_publish"]) or action_base_csv_error is not None,
    )

    if publish_guard["severity"] == "error":
        st.error(str(publish_guard["message"]))
    elif publish_guard["severity"] == "warning":
        st.warning(str(publish_guard["message"]))
    else:
        st.success(str(publish_guard["message"]))

    contract = publish_guard["contract"]
    if isinstance(contract, dict):
        st.caption(
            "Configured publish target: "
            f"owner={str(library_owner).strip() or 'n/a'}, "
            f"version={int(library_version)}"
        )
        st.caption(
            "Generated manifest contract: "
            f"owner={contract.get('owner') or 'n/a'}, "
            f"version={contract.get('version') if contract.get('version') is not None else 'n/a'}, "
            f"import={contract.get('import_path') or 'n/a'}"
        )
        st.caption(
            "Publish guard status: "
            f"owner_version_ready={bool(contract.get('owner_version_ready'))}, "
            f"full_contract_ready={bool(contract.get('full_contract_ready'))}"
        )
        st.caption(f"Generated manifest path: {contract.get('manifest_path')}")

    if run_base_scan or refresh_base_scan:
        if not databento_api_key:
            st.error("Databento API key is required for the base scan.")
        else:
            effective_force_refresh = bool(refresh_base_scan)
            status_label = "Refreshing SMC base data..." if effective_force_refresh else "Starting SMC base scan..."
            status = st.status(status_label, expanded=True)

            def _progress(message: str) -> None:
                status.update(label=message)
                status.write(message)
                add_log(message)

            try:
                result = run_databento_base_scan_pipeline(
                    databento_api_key=databento_api_key,
                    fmp_api_key=fmp_api_key,
                    dataset=dataset,
                    export_dir=export_dir,
                    schema_path=schema_path,
                    lookback_days=int(lookback_days),
                    force_refresh=effective_force_refresh,
                    cache_dir=repo_root / "artifacts" / "databento_volatility_cache",
                    use_file_cache=True,
                    display_timezone="Europe/Berlin",
                    bullish_score_profile=str(bullish_score_profile),
                    smc_base_only=bool(smc_base_only),
                    write_xlsx=write_xlsx,
                    library_owner=str(library_owner),
                    library_version=int(library_version),
                    progress_callback=_progress,
                )
            except Exception as exc:
                add_log(f"SMC base scan failed: {type(exc).__name__}: {exc}")
                status.update(label="SMC base scan failed.", state="error", expanded=True)
                st.error(f"SMC base scan failed: {type(exc).__name__}: {exc}")
            else:
                st.session_state["smc_base_result"] = result
                completion_label = "SMC base data refresh complete." if effective_force_refresh else "SMC base scan complete."
                success_message = "SMC base snapshot created from a forced-refresh Databento export run." if effective_force_refresh else "SMC base snapshot created from a fresh Databento export run."
                status.update(label=completion_label, state="complete", expanded=True)
                st.success(success_message)

    if generate_pine:
        if action_base_csv is None:
            st.error(str(action_base_csv_error))
        else:
            try:
                pine_result = generate_pine_library_from_base(
                    base_csv_path=action_base_csv,
                    schema_path=schema_path,
                    output_root=repo_root,
                    overrides_path=overrides_path if overrides_path.exists() else None,
                    library_owner=str(library_owner),
                    library_version=int(library_version),
                )
            except Exception as exc:
                add_log(f"Pine generation failed: {type(exc).__name__}: {exc}")
                st.error(f"Pine generation failed: {type(exc).__name__}: {exc}")
            else:
                st.session_state["smc_pine_result"] = pine_result
                add_log(f"Pine library generated from {action_base_csv}")
                st.success("Pine library artifacts generated. TradingView publish can now be triggered from this UI.")

    if publish_pine:
        report_path = repo_root / "automation" / "tradingview" / "reports" / f"publish-micro-library-{datetime.now(UTC).strftime('%Y-%m-%dT%H-%M-%S-%fZ')}.json"
        status = st.status("Publishing micro-library to TradingView...", expanded=True)
        status.write("Step 1/3: Verifying manifest, generated snippet, and SMC core import contract...")
        add_log("TradingView micro-library publish started.")
        try:
            if action_base_csv is None:
                raise RuntimeError(str(action_base_csv_error))
            if not publish_guard["can_publish"]:
                raise RuntimeError(str(publish_guard["message"]))
            publish_result = publish_micro_library_to_tradingview(
                repo_root=repo_root,
                report_path=report_path,
            )
        except Exception as exc:
            add_log(f"TradingView publish failed: {type(exc).__name__}: {exc}")
            status.update(label="TradingView micro-library publish failed.", state="error", expanded=True)
            st.error(f"TradingView publish failed: {type(exc).__name__}: {exc}")
        else:
            st.session_state["smc_publish_result"] = publish_result
            add_log(
                "TradingView micro-library publish succeeded; core import contract and post-publish core validation were rechecked."
            )
            status.write("Step 2/3: TradingView library publish completed.")
            status.write("Step 3/3: Core-only TradingView preflight stayed green against the generated import path.")
            status.update(label="TradingView micro-library publish complete.", state="complete", expanded=True)
            st.success(
                "TradingView micro-library published and validated. Versioning remains explicit: owner/version changes require regenerating the library artifacts first."
            )

    base_result = st.session_state.get("smc_base_result")
    if isinstance(base_result, dict):
        mapping_payload = base_result.get("mapping_payload", {})
        output_paths = base_result.get("output_paths", {})
        for warning in base_result.get("warnings", []):
            st.warning(str(warning))
        metrics = st.columns(4)
        metrics[0].metric("Base rows", str(mapping_payload.get("row_count", "n/a")))
        metrics[1].metric("Direct fields", str(len(mapping_payload.get("direct_fields", []))))
        metrics[2].metric("Derived fields", str(len(mapping_payload.get("derived_fields", []))))
        metrics[3].metric("Missing fields", str(len(mapping_payload.get("missing_fields", []))))
        if output_paths:
            st.subheader("Base Artifacts")
            output_table = pd.DataFrame(
                [{"artifact": name, "path": str(path)} for name, path in output_paths.items() if name != "session_minute_parquet"]
            )
            st.dataframe(output_table, hide_index=True, use_container_width=True)

    pine_result = st.session_state.get("smc_pine_result")
    if isinstance(pine_result, dict):
        st.subheader("Pine Artifacts")
        pine_table = pd.DataFrame([{"artifact": name, "path": str(path)} for name, path in pine_result.items()])
        st.dataframe(pine_table, hide_index=True, use_container_width=True)
        st.info(
            "Publish path: the generated library can now be pushed from this UI. The import version stays explicit in the core import path, so owner/version bumps remain the operator's responsibility."
        )

    publish_result = st.session_state.get("smc_publish_result")
    if isinstance(publish_result, dict):
        st.subheader("TradingView Publish Result")
        publish_table = pd.DataFrame(
            [
                {"field": "publish_status", "value": str(publish_result.get("publishStatus", "n/a"))},
                {"field": "expected_import_path", "value": str(publish_result.get("expectedImportPath", "n/a"))},
                {"field": "expected_version", "value": str(publish_result.get("expectedVersion", "n/a"))},
                {"field": "published_version", "value": str(publish_result.get("publishedVersion", "n/a"))},
                {"field": "published_script_verified", "value": str(publish_result.get("publishedScriptVerified", "n/a"))},
                {"field": "repo_core_validation_report", "value": str(publish_result.get("repoCoreValidationReport", publish_result.get("coreValidationReport", "n/a")))},
                {"field": "release_manifest_path", "value": str(publish_result.get("releaseManifestPath", "n/a"))},
                {"field": "publish_report_path", "value": str(publish_result.get("report_path", "n/a"))},
            ]
        )
        st.dataframe(publish_table, hide_index=True, use_container_width=True)
        if publish_result.get("error"):
            st.warning(str(publish_result["error"]))
        st.caption(
            "Post-publish validation checks two things: the local contract must match exactly across manifest, generated import snippet, and SMC_Core_Engine, and a core-only TradingView preflight must still compile against that exact import path."
        )

    with st.expander("Run Logs", expanded=False):
        logs = st.session_state.get("smc_base_logs", [])
        if logs:
            st.text("\n".join(logs))
        else:
            st.caption("No base-generation actions executed in this session yet.")