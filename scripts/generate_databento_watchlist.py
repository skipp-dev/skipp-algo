from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, time
import json
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from strategy_config import (
    LONG_DIP_AS_OF_LABEL,
    LONG_DIP_DEFAULTS,
    LONG_DIP_DISPLAY_TIMEZONE,
    LONG_DIP_BUILDING_MIN_GAP_PCT,
    LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_BUILDING_MIN_PREMARKET_DOLLAR_VOLUME,
    LONG_DIP_BUILDING_MIN_PREMARKET_TRADE_COUNT,
    LONG_DIP_BUILDING_MIN_PREMARKET_VOLUME,
    LONG_DIP_EARLY_MIN_GAP_PCT,
    LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_EARLY_MIN_PREMARKET_DOLLAR_VOLUME,
    LONG_DIP_EARLY_MIN_PREMARKET_TRADE_COUNT,
    LONG_DIP_EARLY_MIN_PREMARKET_VOLUME,
    LONG_DIP_HARD_STOP_PCT,
    LONG_DIP_LADDER_PCTS,
    LONG_DIP_LADDER_WEIGHTS,
    LONG_DIP_MAX_GAP_PCT,
    LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME,
    LONG_DIP_MIN_GAP_PCT,
    LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_MIN_PREMARKET_TRADE_COUNT,
    LONG_DIP_MIN_PREMARKET_VOLUME,
    LONG_DIP_MIN_PREVIOUS_CLOSE,
    LONG_DIP_POSITION_BUDGET_USD,
    LONG_DIP_SPARSE_MIN_GAP_PCT,
    LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_SPARSE_MIN_PREMARKET_DOLLAR_VOLUME,
    LONG_DIP_SPARSE_MIN_PREMARKET_TRADE_COUNT,
    LONG_DIP_SPARSE_MIN_PREMARKET_VOLUME,
    LONG_DIP_TAKE_PROFIT_1_PCT,
    LONG_DIP_TRAILING_STOP_PCT,
    LONG_DIP_TOP_N,
)
from scripts.load_databento_export_bundle import load_export_bundle, resolve_manifest_path


DEFAULT_EXPORT_DIR = Path.home() / "Downloads"
WATCHLIST_SOURCE_FILES = (
    "daily_symbol_features_full_universe.parquet",
    "premarket_features_full_universe.parquet",
    "symbol_day_diagnostics.parquet",
)


def _ensure_premarket_liquidity_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["premarket_last"] = pd.to_numeric(out.get("premarket_last"), errors="coerce")
    out["premarket_volume"] = pd.to_numeric(out.get("premarket_volume"), errors="coerce")
    out["premarket_trade_count"] = pd.to_numeric(out.get("premarket_trade_count"), errors="coerce")
    out["premarket_trade_count_actual"] = pd.to_numeric(out.get("premarket_trade_count_actual"), errors="coerce")
    out["premarket_active_seconds"] = pd.to_numeric(out.get("premarket_active_seconds"), errors="coerce")
    if "premarket_trade_count_source" not in out.columns:
        inferred_source = np.where(
            out["premarket_trade_count_actual"].notna(),
            "actual",
            np.where(out["premarket_trade_count"].notna(), "proxy_active_seconds", "missing"),
        )
        out["premarket_trade_count_source"] = inferred_source
    else:
        out["premarket_trade_count_source"] = out["premarket_trade_count_source"].astype(str).str.strip().str.lower()
        out.loc[~out["premarket_trade_count_source"].isin(["actual", "proxy_active_seconds", "missing"]), "premarket_trade_count_source"] = "missing"

    # Backfill compatibility for legacy exports that only had premarket_trade_count.
    out["premarket_trade_count_actual"] = np.where(
        out["premarket_trade_count_source"].eq("actual") & out["premarket_trade_count_actual"].isna(),
        out["premarket_trade_count"],
        out["premarket_trade_count_actual"],
    )
    out["premarket_active_seconds"] = np.where(
        out["premarket_trade_count_source"].eq("proxy_active_seconds") & out["premarket_active_seconds"].isna(),
        out["premarket_trade_count"],
        out["premarket_active_seconds"],
    )
    out["premarket_trade_count_usable"] = out["premarket_trade_count_source"].isin(["actual", "proxy_active_seconds"])
    if "premarket_dollar_volume" in out.columns:
        out["premarket_dollar_volume"] = pd.to_numeric(out.get("premarket_dollar_volume"), errors="coerce")
    else:
        out["premarket_dollar_volume"] = np.nan
    computed_dollar_volume = out["premarket_last"] * out["premarket_volume"]
    out["premarket_dollar_volume"] = out["premarket_dollar_volume"].combine_first(computed_dollar_volume)
    return out


def _load_open_signal_metrics(
    *,
    bundle: str | Path | None,
    export_dir: str | Path | None,
    trading_days: list,
) -> pd.DataFrame:
    try:
        from databento_volatility_screener import _build_open_window_aggregates
    except Exception:
        logger.warning("Failed to import _build_open_window_aggregates; open-signal metrics will be absent", exc_info=True)
        return pd.DataFrame()

    second_detail: pd.DataFrame | None = None
    if bundle is not None:
        try:
            payload = load_export_bundle(Path(bundle).expanduser())
            second_detail = payload.get("frames", {}).get("full_universe_second_detail_open")
        except Exception:
            logger.warning("Failed to load open-signal detail from bundle %s", bundle, exc_info=True)
            second_detail = None
    else:
        base_dir = Path(export_dir).expanduser() if export_dir is not None else DEFAULT_EXPORT_DIR
        second_detail_path = base_dir / "full_universe_second_detail_open.parquet"
        if second_detail_path.exists():
            try:
                second_detail = pd.read_parquet(second_detail_path)
            except Exception:
                logger.warning("Failed to read parquet %s", second_detail_path, exc_info=True)
                second_detail = None

    if second_detail is None or second_detail.empty:
        return pd.DataFrame()

    return _build_open_window_aggregates(
        second_detail,
        trading_days=trading_days,
        display_timezone=LONG_DIP_DISPLAY_TIMEZONE,
    )


def _merge_open_signal_metrics(daily: pd.DataFrame, metrics: pd.DataFrame) -> pd.DataFrame:
    if daily.empty or metrics.empty:
        return daily
    enriched = daily.copy()
    metrics = metrics.copy()
    metrics["trade_date"] = pd.to_datetime(metrics["trade_date"], errors="coerce").dt.date
    metrics["symbol"] = metrics["symbol"].astype(str).str.upper()
    join_cols = [column for column in metrics.columns if column not in {"trade_date", "symbol"}]
    merged = enriched.merge(metrics, on=["trade_date", "symbol"], how="left", suffixes=("", "__metrics"))
    for column in join_cols:
        metric_column = f"{column}__metrics"
        if metric_column not in merged.columns:
            continue
        if column in merged.columns:
            merged[column] = merged[metric_column].combine_first(merged[column])
        else:
            merged[column] = merged[metric_column]
        merged = merged.drop(columns=[metric_column])
    return merged


def _load_bundle_watchlist_inputs(base_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, dict[str, Any]]:
    payload = load_export_bundle(base_dir)
    frames = payload["frames"]
    daily = frames["daily_symbol_features_full_universe"]
    premarket = frames["premarket_features_full_universe"]
    diagnostics = frames.get("symbol_day_diagnostics")
    metadata = {
        "source": "bundle",
        "manifest_path": str(payload["manifest_path"]),
        "bundle_dir": str(payload["bundle_dir"]),
        "base_prefix": payload["base_prefix"],
        "export_generated_at": payload["manifest"].get("export_generated_at", payload["manifest"].get("exported_at")),
        "source_data_fetched_at": payload["manifest"].get("source_data_fetched_at", payload["manifest"].get("premarket_fetched_at")),
    }
    return _normalize_trade_date(daily), _normalize_trade_date(premarket), None if diagnostics is None else _normalize_trade_date(diagnostics), metadata


def _load_exact_named_watchlist_inputs(base_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, dict[str, Any]]:
    daily = pd.read_parquet(base_dir / "daily_symbol_features_full_universe.parquet")
    premarket = pd.read_parquet(base_dir / "premarket_features_full_universe.parquet")
    diagnostics_path = base_dir / "symbol_day_diagnostics.parquet"
    diagnostics = pd.read_parquet(diagnostics_path) if diagnostics_path.exists() else None
    metadata = {
        "source": "exact_named_exports",
        "export_dir": str(base_dir),
    }
    try:
        manifest_path = resolve_manifest_path(base_dir)
    except FileNotFoundError:
        manifest_path = None
    if manifest_path is not None:
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            manifest = None
        if isinstance(manifest, dict):
            metadata.update(
                {
                    "manifest_path": str(manifest_path),
                    "export_generated_at": manifest.get("export_generated_at", manifest.get("exported_at")),
                    "source_data_fetched_at": manifest.get("source_data_fetched_at", manifest.get("premarket_fetched_at")),
                }
            )
    return _normalize_trade_date(daily), _normalize_trade_date(premarket), None if diagnostics is None else _normalize_trade_date(diagnostics), metadata


@dataclass(frozen=True)
class LongDipConfig:
    min_gap_pct: float = LONG_DIP_MIN_GAP_PCT
    max_gap_pct: float | None = LONG_DIP_MAX_GAP_PCT
    min_previous_close: float = LONG_DIP_MIN_PREVIOUS_CLOSE
    min_premarket_dollar_volume: float = LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME
    min_premarket_volume: int = LONG_DIP_MIN_PREMARKET_VOLUME
    min_premarket_trade_count: int = LONG_DIP_MIN_PREMARKET_TRADE_COUNT
    min_premarket_active_seconds: int = LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS
    ladder_pcts: tuple[float, float, float] = LONG_DIP_LADDER_PCTS
    ladder_weights: tuple[float, float, float] = LONG_DIP_LADDER_WEIGHTS
    take_profit_1_pct: float = LONG_DIP_TAKE_PROFIT_1_PCT
    hard_stop_pct: float = LONG_DIP_HARD_STOP_PCT
    trailing_stop_pct: float = LONG_DIP_TRAILING_STOP_PCT
    position_budget_usd: float = LONG_DIP_POSITION_BUDGET_USD
    top_n: int = LONG_DIP_TOP_N
    display_timezone: str = LONG_DIP_DISPLAY_TIMEZONE
    as_of_label: str = LONG_DIP_AS_OF_LABEL


@dataclass(frozen=True)
class EntryLevelPlan:
    tag: str
    weight: float
    limit_price: float
    quantity: int
    take_profit_price: float
    stop_loss_price: float
    trailing_stop_pct: float
    trailing_stop_anchor_price: float


def _safe_timestamp(value: Any) -> pd.Timestamp | None:
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if pd.isna(ts):
        return None
    return ts.tz_localize(UTC) if ts.tzinfo is None else ts.tz_convert(UTC)


def _resolve_profile_timestamp(metadata: dict[str, Any]) -> pd.Timestamp | None:
    return _safe_timestamp(metadata.get("source_data_fetched_at") or metadata.get("export_generated_at"))


def _resolve_effective_watchlist_config(
    cfg: LongDipConfig,
    *,
    prem: pd.DataFrame,
    trade_date,
    profile_timestamp: pd.Timestamp | None,
) -> tuple[LongDipConfig, dict[str, Any]]:
    latest_prem = prem[prem["trade_date"] == trade_date].copy()
    premarket_symbols = int((latest_prem.get("has_premarket_data") == True).sum()) if not latest_prem.empty else 0
    profile_name = "standard"
    profile_reason = "default long-dip filters"
    effective_cfg = cfg

    if profile_timestamp is not None:
        profile_et = profile_timestamp.tz_convert("America/New_York")
        premarket_anchor = cfg.premarket_anchor_et if hasattr(cfg, "premarket_anchor_et") else time(8, 0)
        if premarket_symbols == 0 and profile_et.time() < premarket_anchor:
            return effective_cfg, {
                "profile_name": "premarket_not_started",
                "profile_reason": (
                    f"source_data_fetched_at={profile_et.strftime('%H:%M:%S')} ET "
                    f"before premarket anchor ({premarket_anchor.strftime('%H:%M')} ET)"
                ),
                "premarket_symbols": premarket_symbols,
                "profile_timestamp": profile_timestamp.isoformat() if profile_timestamp is not None else None,
            }

    if premarket_symbols < 25:
        effective_cfg = replace(
            cfg,
            min_gap_pct=min(cfg.min_gap_pct, LONG_DIP_SPARSE_MIN_GAP_PCT),
            min_premarket_dollar_volume=min(cfg.min_premarket_dollar_volume, LONG_DIP_SPARSE_MIN_PREMARKET_DOLLAR_VOLUME),
            min_premarket_volume=min(cfg.min_premarket_volume, LONG_DIP_SPARSE_MIN_PREMARKET_VOLUME),
            min_premarket_trade_count=min(cfg.min_premarket_trade_count, LONG_DIP_SPARSE_MIN_PREMARKET_TRADE_COUNT),
            min_premarket_active_seconds=min(cfg.min_premarket_active_seconds, LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS),
        )
        profile_name = "sparse_premarket"
        profile_reason = f"only {premarket_symbols} symbols have premarket data"
    elif profile_timestamp is not None:
        profile_et = profile_timestamp.tz_convert("America/New_York")
        if profile_et.time() < datetime.strptime("08:30:00", "%H:%M:%S").time():
            effective_cfg = replace(
                cfg,
                min_gap_pct=min(cfg.min_gap_pct, LONG_DIP_EARLY_MIN_GAP_PCT),
                min_premarket_dollar_volume=min(cfg.min_premarket_dollar_volume, LONG_DIP_EARLY_MIN_PREMARKET_DOLLAR_VOLUME),
                min_premarket_volume=min(cfg.min_premarket_volume, LONG_DIP_EARLY_MIN_PREMARKET_VOLUME),
                min_premarket_trade_count=min(cfg.min_premarket_trade_count, LONG_DIP_EARLY_MIN_PREMARKET_TRADE_COUNT),
                min_premarket_active_seconds=min(cfg.min_premarket_active_seconds, LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS),
            )
            profile_name = "early_premarket"
            profile_reason = f"source_data_fetched_at={profile_et.strftime('%H:%M:%S')} ET"
        elif profile_et.time() < datetime.strptime("09:00:00", "%H:%M:%S").time():
            effective_cfg = replace(
                cfg,
                min_gap_pct=min(cfg.min_gap_pct, LONG_DIP_BUILDING_MIN_GAP_PCT),
                min_premarket_dollar_volume=min(cfg.min_premarket_dollar_volume, LONG_DIP_BUILDING_MIN_PREMARKET_DOLLAR_VOLUME),
                min_premarket_volume=min(cfg.min_premarket_volume, LONG_DIP_BUILDING_MIN_PREMARKET_VOLUME),
                min_premarket_trade_count=min(cfg.min_premarket_trade_count, LONG_DIP_BUILDING_MIN_PREMARKET_TRADE_COUNT),
                min_premarket_active_seconds=min(cfg.min_premarket_active_seconds, LONG_DIP_BUILDING_MIN_PREMARKET_ACTIVE_SECONDS),
            )
            profile_name = "building_premarket"
            profile_reason = f"source_data_fetched_at={profile_et.strftime('%H:%M:%S')} ET"

    return effective_cfg, {
        "profile_name": profile_name,
        "profile_reason": profile_reason,
        "premarket_symbols": premarket_symbols,
        "profile_timestamp": profile_timestamp.isoformat() if profile_timestamp is not None else None,
    }


def _validate_watchlist_config(cfg: LongDipConfig) -> None:
    if cfg.top_n <= 0:
        raise ValueError(f"top_n must be > 0, got {cfg.top_n}")
    if cfg.position_budget_usd <= 0:
        raise ValueError(f"position_budget_usd must be > 0, got {cfg.position_budget_usd}")
    if cfg.min_premarket_dollar_volume < 0:
        raise ValueError(f"min_premarket_dollar_volume must be >= 0, got {cfg.min_premarket_dollar_volume}")
    if cfg.min_premarket_volume < 0:
        raise ValueError(f"min_premarket_volume must be >= 0, got {cfg.min_premarket_volume}")
    if cfg.min_premarket_trade_count < 0:
        raise ValueError(f"min_premarket_trade_count must be >= 0, got {cfg.min_premarket_trade_count}")
    if cfg.min_premarket_active_seconds < 0:
        raise ValueError(f"min_premarket_active_seconds must be >= 0, got {cfg.min_premarket_active_seconds}")
    if len(cfg.ladder_pcts) != 3 or len(cfg.ladder_weights) != 3:
        raise ValueError("ladder_pcts and ladder_weights must both have exactly 3 entries")
    if not np.isclose(sum(cfg.ladder_weights), 1.0, atol=1e-6):
        raise ValueError(f"ladder_weights must sum to 1.0, got {sum(cfg.ladder_weights)}")


def _normalize_trade_date(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce").dt.date
    normalized["symbol"] = normalized["symbol"].astype(str).str.upper()
    return normalized


def load_watchlist_inputs(
    *,
    bundle: str | Path | None = None,
    export_dir: str | Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame | None, dict[str, Any]]:
    if bundle is not None:
        return _load_bundle_watchlist_inputs(Path(bundle).expanduser())

    base_dir = Path(export_dir).expanduser() if export_dir is not None else DEFAULT_EXPORT_DIR
    try:
        return _load_exact_named_watchlist_inputs(base_dir)
    except Exception as exact_error:
        daily_path = base_dir / "daily_symbol_features_full_universe.parquet"
        premarket_path = base_dir / "premarket_features_full_universe.parquet"
        if not daily_path.exists() and not premarket_path.exists():
            raise
        fallback_daily, fallback_premarket, fallback_diagnostics, metadata = _load_bundle_watchlist_inputs(base_dir)
        metadata["fallback_reason"] = f"exact_named_exports_failed: {type(exact_error).__name__}: {exact_error}"
        metadata["export_dir"] = str(base_dir)
        return fallback_daily, fallback_premarket, fallback_diagnostics, metadata


def _safe_iso_from_path(path: Path) -> str | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat(timespec="seconds")


def _resolve_source_data_fetched_at(metadata: dict[str, Any]) -> str | None:
    source_data_fetched_at = metadata.get("source_data_fetched_at")
    if source_data_fetched_at:
        return str(source_data_fetched_at)

    export_generated_at = metadata.get("export_generated_at")
    if export_generated_at:
        return str(export_generated_at)

    export_dir = metadata.get("export_dir")
    if not export_dir:
        return None

    timestamps = [
        _safe_iso_from_path(Path(export_dir).expanduser() / filename)
        for filename in WATCHLIST_SOURCE_FILES
    ]
    available = [timestamp for timestamp in timestamps if timestamp]
    return max(available) if available else None


def _find_filter_bottleneck(filter_funnel: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((step for index, step in enumerate(filter_funnel) if index > 0 and step.get("remaining") == 0), None)


def _build_liquidity_relaxed_config(
    cfg: LongDipConfig,
    *,
    filter_funnel: list[dict[str, Any]],
    filter_profile: dict[str, Any],
) -> tuple[LongDipConfig, dict[str, Any]] | None:
    bottleneck = _find_filter_bottleneck(filter_funnel)
    if bottleneck is None or bottleneck.get("filter") not in {"premarket_dollar_volume", "premarket_volume", "premarket_trade_count", "premarket_activity_proxy"}:
        return None

    relaxed_cfg = replace(
        cfg,
        min_premarket_dollar_volume=min(cfg.min_premarket_dollar_volume, LONG_DIP_SPARSE_MIN_PREMARKET_DOLLAR_VOLUME),
        min_premarket_volume=min(cfg.min_premarket_volume, LONG_DIP_SPARSE_MIN_PREMARKET_VOLUME),
        min_premarket_trade_count=min(cfg.min_premarket_trade_count, LONG_DIP_SPARSE_MIN_PREMARKET_TRADE_COUNT),
        min_premarket_active_seconds=min(cfg.min_premarket_active_seconds, LONG_DIP_SPARSE_MIN_PREMARKET_ACTIVE_SECONDS),
    )
    if relaxed_cfg == cfg:
        return None

    relaxed_profile = dict(filter_profile)
    relaxed_profile.update(
        {
            "profile_name": "liquidity_relaxed",
            "profile_reason": (
                f"{bottleneck['filter']} bottleneck under {filter_profile.get('profile_name', 'standard')} "
                f"profile; retry with sparse liquidity thresholds"
            ),
            "base_profile_name": filter_profile.get("profile_name", "standard"),
            "base_profile_reason": filter_profile.get("profile_reason", "default long-dip filters"),
            "relaxed_bottleneck": bottleneck.get("filter"),
            "relaxed_from_dollar_volume": cfg.min_premarket_dollar_volume,
            "relaxed_from_volume": cfg.min_premarket_volume,
            "relaxed_from_trade_count": cfg.min_premarket_trade_count,
            "relaxed_from_active_seconds": cfg.min_premarket_active_seconds,
        }
    )
    return relaxed_cfg, relaxed_profile


def generate_watchlist_result(
    *,
    bundle: str | Path | None = None,
    export_dir: str | Path | None = None,
    cfg: LongDipConfig | None = None,
) -> dict[str, Any]:
    resolved_cfg = cfg or LongDipConfig()
    _validate_watchlist_config(resolved_cfg)
    daily, prem, diagnostics, metadata = load_watchlist_inputs(bundle=bundle, export_dir=export_dir)
    prem = _ensure_premarket_liquidity_columns(prem)
    trading_days = sorted(set(daily.get("trade_date", pd.Series(dtype=object)).dropna().tolist()))
    open_signal_metrics = _load_open_signal_metrics(bundle=bundle, export_dir=export_dir, trading_days=trading_days)
    daily = _merge_open_signal_metrics(daily, open_signal_metrics)
    trade_dates = sorted(set(daily["trade_date"].dropna().tolist()) & set(prem["trade_date"].dropna().tolist()))
    latest_td = trade_dates[-1] if trade_dates else None
    effective_cfg = resolved_cfg
    filter_profile = {
        "profile_name": "standard",
        "profile_reason": "default long-dip filters",
        "premarket_symbols": 0,
        "profile_timestamp": None,
    }
    if latest_td is not None:
        effective_cfg, filter_profile = _resolve_effective_watchlist_config(
            resolved_cfg,
            prem=prem,
            trade_date=latest_td,
            profile_timestamp=_resolve_profile_timestamp(metadata),
        )
    watchlists = build_daily_watchlists(daily=daily, prem=prem, diagnostics=diagnostics, cfg=effective_cfg)

    warnings: list[str] = []
    if daily.empty or prem.empty:
        warnings.append("The watchlist inputs are incomplete. Run the data pipeline first.")
    filter_funnel: list[dict[str, Any]] = []
    if latest_td is not None and watchlists.empty:
        filter_funnel = build_filter_funnel(daily=daily, prem=prem, cfg=effective_cfg, trade_date=latest_td)
        relaxed = _build_liquidity_relaxed_config(
            effective_cfg,
            filter_funnel=filter_funnel,
            filter_profile=filter_profile,
        )
        if relaxed is not None:
            relaxed_cfg, relaxed_profile = relaxed
            relaxed_watchlists = build_daily_watchlists(daily=daily, prem=prem, diagnostics=diagnostics, cfg=relaxed_cfg)
            if not relaxed_watchlists.empty:
                effective_cfg = relaxed_cfg
                filter_profile = relaxed_profile
                watchlists = relaxed_watchlists
                filter_funnel = []

    if watchlists.empty:
        if filter_profile["profile_name"] == "premarket_not_started":
            warnings.append(
                "No premarket data available yet. The latest refresh completed before the US premarket session opened."
            )
        else:
            warnings.append("No symbols matched the current long-dip filters.")

    trade_date = None if watchlists.empty else max(pd.to_datetime(watchlists["trade_date"], errors="coerce").dt.date.dropna())
    active_watchlist_table = watchlists
    if trade_date is not None and not watchlists.empty:
        active_mask = pd.to_datetime(watchlists["trade_date"], errors="coerce").dt.date == trade_date
        active_watchlist_table = watchlists.loc[active_mask].reset_index(drop=True)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    return {
        "generated_at": generated_at,
        "source_data_fetched_at": _resolve_source_data_fetched_at(metadata),
        "trade_date": trade_date.isoformat() if trade_date else None,
        "as_of_label": resolved_cfg.as_of_label,
        "config_snapshot": asdict(effective_cfg),
        "requested_config_snapshot": asdict(resolved_cfg),
        "watchlist_table": watchlists,
        "active_watchlist_table": active_watchlist_table,
        "run_notes": [
            f"source={metadata.get('source', 'unknown')}",
            f"rows={len(watchlists)}",
            f"display_timezone={resolved_cfg.display_timezone}",
            f"filter_profile={filter_profile['profile_name']}",
        ],
        "warnings": warnings,
        "source_metadata": metadata,
        "filter_funnel": filter_funnel,
        "filter_profile": filter_profile,
    }


def build_filter_funnel(
    *,
    daily: pd.DataFrame,
    prem: pd.DataFrame,
    cfg: LongDipConfig,
    trade_date,
) -> list[dict[str, Any]]:
    """Return step-by-step filter counts for diagnostic display."""
    cols_daily = ["trade_date", "symbol", "previous_close"]
    cols_prem = [
        "trade_date", "symbol", "has_premarket_data", "premarket_last",
        "premarket_volume", "premarket_dollar_volume", "premarket_trade_count", "prev_close_to_premarket_pct",
    ]
    merged = daily.loc[daily["trade_date"] == trade_date, cols_daily].merge(
        prem.loc[prem["trade_date"] == trade_date, cols_prem],
        on=["trade_date", "symbol"], how="inner",
    )
    merged = _ensure_premarket_liquidity_columns(merged)
    total = len(merged)
    steps: list[dict[str, Any]] = [{"filter": "Total symbols", "remaining": total, "threshold": ""}]
    mask = merged["has_premarket_data"] == True
    steps.append({"filter": "has_premarket_data", "remaining": int(mask.sum()), "threshold": "True"})
    mask = mask & merged["premarket_last"].notna() & (pd.to_numeric(merged["premarket_last"], errors="coerce") > 0)
    steps.append({"filter": "premarket_last > 0", "remaining": int(mask.sum()), "threshold": "> 0"})
    mask = mask & merged["previous_close"].notna() & (pd.to_numeric(merged["previous_close"], errors="coerce") >= cfg.min_previous_close)
    steps.append({"filter": "previous_close", "remaining": int(mask.sum()), "threshold": f">= ${cfg.min_previous_close:.2f}"})
    mask = mask & merged["prev_close_to_premarket_pct"].notna() & (pd.to_numeric(merged["prev_close_to_premarket_pct"], errors="coerce") >= cfg.min_gap_pct)
    steps.append({"filter": "gap %", "remaining": int(mask.sum()), "threshold": f">= {cfg.min_gap_pct:.1f}%"})
    if cfg.max_gap_pct is not None:
        mask = mask & (pd.to_numeric(merged["prev_close_to_premarket_pct"], errors="coerce") <= cfg.max_gap_pct)
        steps.append({"filter": "gap % cap", "remaining": int(mask.sum()), "threshold": f"<= {cfg.max_gap_pct:.1f}%"})
    mask = mask & (merged["premarket_dollar_volume"].fillna(0) >= cfg.min_premarket_dollar_volume)
    steps.append({"filter": "premarket_dollar_volume", "remaining": int(mask.sum()), "threshold": f">= {cfg.min_premarket_dollar_volume:,.0f}"})
    mask = mask & (merged["premarket_volume"].fillna(0) >= cfg.min_premarket_volume)
    steps.append({"filter": "premarket_volume", "remaining": int(mask.sum()), "threshold": f">= {cfg.min_premarket_volume:,}"})
    tc_actual = pd.to_numeric(merged["premarket_trade_count_actual"], errors="coerce")
    tc_proxy = pd.to_numeric(merged["premarket_active_seconds"], errors="coerce")
    if tc_actual.notna().any():
        mask = mask & (tc_actual.fillna(0) >= cfg.min_premarket_trade_count)
        steps.append({"filter": "premarket_trade_count", "remaining": int(mask.sum()), "threshold": f"actual >= {cfg.min_premarket_trade_count:,}"})
    elif tc_proxy.notna().any():
        mask = mask & (tc_proxy.fillna(0) >= cfg.min_premarket_active_seconds)
        steps.append({"filter": "premarket_activity_proxy", "remaining": int(mask.sum()), "threshold": f"active_seconds >= {cfg.min_premarket_active_seconds:,}"})
    else:
        steps.append({"filter": "premarket_trade_count", "remaining": int(mask.sum()), "threshold": "skipped (no data)"})
    return steps


def build_preopen_long_candidates(
    *,
    daily: pd.DataFrame,
    prem: pd.DataFrame,
    cfg: LongDipConfig,
    trade_date,
    diagnostics: pd.DataFrame | None = None,
) -> pd.DataFrame:
    prem = _ensure_premarket_liquidity_columns(prem)

    cols_daily = [
        "trade_date",
        "symbol",
        "exchange",
        "asset_type",
        "previous_close",
        "window_range_pct",
        "window_return_pct",
        "realized_vol_pct",
        "selected_top20pct",
        "is_eligible",
        "eligibility_reason",
        "open_30s_volume",
        "early_dip_pct_10s",
        "early_dip_second",
        "reclaimed_start_price_within_30s",
        "reclaim_second_30s",
    ]
    cols_prem = [
        "trade_date",
        "symbol",
        "has_premarket_data",
        "premarket_last",
        "premarket_volume",
        "premarket_dollar_volume",
        "premarket_trade_count",
        "prev_close_to_premarket_pct",
    ]
    available_daily_cols = [c for c in cols_daily if c in daily.columns]
    merged = daily.loc[daily["trade_date"] == trade_date, available_daily_cols].merge(
        prem.loc[prem["trade_date"] == trade_date, cols_prem],
        on=["trade_date", "symbol"],
        how="inner",
    )

    if diagnostics is not None and not diagnostics.empty:
        diag_cols = ["trade_date", "symbol", "present_in_eligible", "excluded_reason"]
        merged = merged.merge(
            diagnostics.loc[diagnostics["trade_date"] == trade_date, diag_cols],
            on=["trade_date", "symbol"],
            how="left",
        )
    else:
        merged["present_in_eligible"] = pd.NA
        merged["excluded_reason"] = ""

    merged = _ensure_premarket_liquidity_columns(merged)

    trade_count_actual_series = pd.to_numeric(merged["premarket_trade_count_actual"], errors="coerce")
    trade_count_proxy_series = pd.to_numeric(merged["premarket_active_seconds"], errors="coerce")
    trade_count_actual_available = trade_count_actual_series.notna().any()
    trade_count_proxy_available = trade_count_proxy_series.notna().any()

    candidates = merged[
        (merged["has_premarket_data"] == True)
        & merged["premarket_last"].notna()
        & (pd.to_numeric(merged["premarket_last"], errors="coerce") > 0)
        & merged["previous_close"].notna()
        & (pd.to_numeric(merged["previous_close"], errors="coerce") >= cfg.min_previous_close)
        & merged["prev_close_to_premarket_pct"].notna()
        & (pd.to_numeric(merged["prev_close_to_premarket_pct"], errors="coerce") >= cfg.min_gap_pct)
        & (merged["premarket_dollar_volume"].fillna(0) >= cfg.min_premarket_dollar_volume)
        & (merged["premarket_volume"].fillna(0) >= cfg.min_premarket_volume)
    ].copy()

    if trade_count_actual_available:
        candidates = candidates[trade_count_actual_series.loc[candidates.index].fillna(0) >= cfg.min_premarket_trade_count].copy()
    elif trade_count_proxy_available:
        candidates = candidates[trade_count_proxy_series.loc[candidates.index].fillna(0) >= cfg.min_premarket_active_seconds].copy()

    if cfg.max_gap_pct is not None:
        candidates = candidates[pd.to_numeric(candidates["prev_close_to_premarket_pct"], errors="coerce") <= cfg.max_gap_pct].copy()

    candidates["gap_component"] = pd.to_numeric(candidates["prev_close_to_premarket_pct"], errors="coerce").clip(lower=0)
    candidates["volume_component"] = np.log10(candidates["premarket_dollar_volume"].fillna(0).clip(lower=0) + 1.0)
    if trade_count_actual_available:
        trade_metric_for_score = pd.to_numeric(candidates["premarket_trade_count_actual"], errors="coerce")
        candidates["trade_count_source_used"] = "actual"
    elif trade_count_proxy_available:
        trade_metric_for_score = pd.to_numeric(candidates["premarket_active_seconds"], errors="coerce")
        candidates["trade_count_source_used"] = "proxy_active_seconds"
    else:
        trade_metric_for_score = pd.Series(0.0, index=candidates.index, dtype=float)
        candidates["trade_count_source_used"] = "missing"
    candidates["trade_component"] = np.log10(trade_metric_for_score.fillna(0).clip(lower=0) + 1.0)
    candidates["trade_count_available"] = trade_count_actual_available or trade_count_proxy_available
    candidates["watchlist_score"] = (
        candidates["gap_component"]
        + 0.75 * candidates["volume_component"]
        + 0.50 * candidates["trade_component"]
    )
    candidates["research_score"] = (
        candidates["watchlist_score"]
        + 0.25 * pd.to_numeric(candidates["window_range_pct"], errors="coerce").fillna(0.0)
        + 0.10 * pd.to_numeric(candidates["realized_vol_pct"], errors="coerce").fillna(0.0)
    )

    candidates = candidates.sort_values(
        ["watchlist_score", "premarket_dollar_volume", "premarket_volume", "premarket_trade_count", "symbol"],
        ascending=[False, False, False, False, True],
    ).reset_index(drop=True)
    candidates["watchlist_rank"] = np.arange(1, len(candidates) + 1)
    return candidates


def compute_entry_ladder(premarket_last: float, cfg: LongDipConfig) -> list[EntryLevelPlan]:
    levels: list[EntryLevelPlan] = []
    for index, (pct, weight) in enumerate(zip(cfg.ladder_pcts, cfg.ladder_weights), start=1):
        limit_price = round(float(premarket_last) * (1.0 + pct), 4)
        quantity = int((cfg.position_budget_usd * weight) // max(limit_price, 0.0001))
        if quantity <= 0:
            continue
        take_profit_price = round(limit_price * (1.0 + cfg.take_profit_1_pct), 4)
        stop_loss_price = round(limit_price * (1.0 - cfg.hard_stop_pct), 4)
        trailing_anchor = round(limit_price * (1.0 - cfg.trailing_stop_pct), 4)
        levels.append(
            EntryLevelPlan(
                tag=f"L{index}",
                weight=weight,
                limit_price=limit_price,
                quantity=quantity,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                trailing_stop_pct=cfg.trailing_stop_pct,
                trailing_stop_anchor_price=trailing_anchor,
            )
        )
    return levels


def expand_candidate_trade_plan(candidates: pd.DataFrame, cfg: LongDipConfig) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for _, row in candidates.iterrows():
        base = {
            "trade_date": row["trade_date"],
            "as_of_label": cfg.as_of_label,
            "watchlist_rank": int(row["watchlist_rank"]),
            "symbol": row["symbol"],
            "exchange": row.get("exchange", ""),
            "asset_type": row.get("asset_type", ""),
            "watchlist_score": round(float(row["watchlist_score"]), 6),
            "research_score": round(float(row["research_score"]), 6),
            "previous_close": row.get("previous_close"),
            "premarket_last": row.get("premarket_last"),
            "prev_close_to_premarket_pct": row.get("prev_close_to_premarket_pct"),
            "premarket_volume": row.get("premarket_volume"),
            "premarket_dollar_volume": row.get("premarket_dollar_volume"),
            "premarket_trade_count": row.get("premarket_trade_count"),
            "open_30s_volume": row.get("open_30s_volume"),
            "early_dip_pct_10s": row.get("early_dip_pct_10s"),
            "early_dip_second": row.get("early_dip_second"),
            "reclaimed_start_price_within_30s": row.get("reclaimed_start_price_within_30s"),
            "reclaim_second_30s": row.get("reclaim_second_30s"),
            "selected_top20pct": bool(row.get("selected_top20pct", False)),
            "is_eligible_label": bool(row.get("is_eligible", False)),
            "eligibility_reason": row.get("eligibility_reason", ""),
            "present_in_eligible": row.get("present_in_eligible"),
            "excluded_reason": row.get("excluded_reason", ""),
        }
        levels = compute_entry_ladder(float(row["premarket_last"]), cfg)
        for level in levels:
            tag = level.tag.lower()
            base[f"{tag}_weight"] = level.weight
            base[f"{tag}_quantity"] = level.quantity
            base[f"{tag}_limit_buy"] = level.limit_price
            base[f"{tag}_take_profit"] = level.take_profit_price
            base[f"{tag}_stop_loss"] = level.stop_loss_price
            base[f"{tag}_trailing_stop_pct"] = level.trailing_stop_pct
            base[f"{tag}_trailing_stop_anchor"] = level.trailing_stop_anchor_price
        rows.append(base)
    return pd.DataFrame(rows)


def build_daily_watchlists(
    *,
    daily: pd.DataFrame,
    prem: pd.DataFrame,
    diagnostics: pd.DataFrame | None,
    cfg: LongDipConfig,
) -> pd.DataFrame:
    all_rows: list[pd.DataFrame] = []
    trade_dates = sorted(set(daily["trade_date"].dropna().tolist()) & set(prem["trade_date"].dropna().tolist()))
    for trade_date in trade_dates:
        candidates = build_preopen_long_candidates(
            daily=daily,
            prem=prem,
            cfg=cfg,
            trade_date=trade_date,
            diagnostics=diagnostics,
        )
        top_candidates = candidates.head(cfg.top_n).copy()
        if top_candidates.empty:
            continue
        all_rows.append(expand_candidate_trade_plan(top_candidates, cfg))
    if not all_rows:
        return pd.DataFrame()
    result = pd.concat(all_rows, ignore_index=True)
    result = result.sort_values(["trade_date", "watchlist_rank", "symbol"]).reset_index(drop=True)
    return result


def render_markdown_report(watchlists: pd.DataFrame, cfg: LongDipConfig, metadata: dict[str, Any]) -> str:
    lines = [
        "# Databento Pre-15:30 Watchlists",
        "",
        f"Source: {metadata.get('source', 'unknown')}",
        f"As of: {cfg.as_of_label}",
        f"Filters: gap >= {cfg.min_gap_pct:.1f}%, previous_close >= {cfg.min_previous_close:.2f}, premarket_dollar_volume >= {cfg.min_premarket_dollar_volume:,.0f}, premarket_volume >= {cfg.min_premarket_volume}, premarket_trade_count >= {cfg.min_premarket_trade_count}",
        f"Position budget: USD {cfg.position_budget_usd:,.0f}",
        f"Trailing stop distance: {cfg.trailing_stop_pct * 100.0:.2f}% below the filled level",
        "",
    ]
    if watchlists.empty:
        lines.append("No candidates matched the configured filters.")
        return "\n".join(lines)

    for trade_date, frame in watchlists.groupby("trade_date", sort=True):
        lines.append(f"## {trade_date}")
        lines.append("")
        lines.append("| Rank | Symbol | Gap % | PM Last | PM $ Vol | PM Vol | PM Trades | L1 Buy | L1 TP | L1 SL | L1 Trail | L2 Buy | L2 TP | L2 SL | L2 Trail | L3 Buy | L3 TP | L3 SL | L3 Trail |")
        lines.append("| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for _, row in frame.iterrows():
            pm_trades_value = pd.to_numeric(pd.Series([row.get("premarket_trade_count")]), errors="coerce").iloc[0]
            lines.append(
                "| {rank} | {symbol} | {gap:.2f} | {pm_last:.4f} | {pm_dollar_vol:.0f} | {pm_vol:.0f} | {pm_trades} | {l1_buy:.4f} | {l1_tp:.4f} | {l1_sl:.4f} | {l1_trail:.4f} | {l2_buy:.4f} | {l2_tp:.4f} | {l2_sl:.4f} | {l2_trail:.4f} | {l3_buy:.4f} | {l3_tp:.4f} | {l3_sl:.4f} | {l3_trail:.4f} |".format(
                    rank=int(row["watchlist_rank"]),
                    symbol=row["symbol"],
                    gap=float(row["prev_close_to_premarket_pct"]),
                    pm_last=float(row["premarket_last"]),
                    pm_dollar_vol=float(row.get("premarket_dollar_volume", 0.0) or 0.0),
                    pm_vol=float(row["premarket_volume"]),
                    pm_trades=("n/a" if pd.isna(pm_trades_value) else f"{float(pm_trades_value):.0f}"),
                    l1_buy=float(row["l1_limit_buy"]),
                    l1_tp=float(row["l1_take_profit"]),
                    l1_sl=float(row["l1_stop_loss"]),
                    l1_trail=float(row["l1_trailing_stop_anchor"]),
                    l2_buy=float(row["l2_limit_buy"]),
                    l2_tp=float(row["l2_take_profit"]),
                    l2_sl=float(row["l2_stop_loss"]),
                    l2_trail=float(row["l2_trailing_stop_anchor"]),
                    l3_buy=float(row["l3_limit_buy"]),
                    l3_tp=float(row["l3_take_profit"]),
                    l3_sl=float(row["l3_stop_loss"]),
                    l3_trail=float(row["l3_trailing_stop_anchor"]),
                )
            )
        lines.append("")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate top-5 pre-15:30 watchlists and ladder order plans from Databento export files.")
    parser.add_argument("--bundle", default=None, help="Manifest path, bundle directory, or bundle basename. Defaults to exact named parquet files in ~/Downloads.")
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR), help="Directory for exact named parquet files when --bundle is not used.")
    parser.add_argument("--top-n", type=int, default=LONG_DIP_TOP_N, help="Candidates per trade date.")
    parser.add_argument(
        "--position-budget-usd",
        "--position-budget-eur",
        dest="position_budget_usd",
        type=float,
        default=LONG_DIP_POSITION_BUDGET_USD,
        help="Gross USD budget per symbol.",
    )
    parser.add_argument("--min-gap-pct", type=float, default=LONG_DIP_MIN_GAP_PCT, help="Minimum previous-close to premarket gap in percent.")
    parser.add_argument("--max-gap-pct", type=float, default=LONG_DIP_MAX_GAP_PCT, help="Optional maximum gap in percent; use a negative value to disable.")
    parser.add_argument("--min-previous-close", type=float, default=LONG_DIP_MIN_PREVIOUS_CLOSE, help="Minimum previous close price.")
    parser.add_argument("--min-premarket-dollar-volume", type=float, default=LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME, help="Minimum premarket dollar volume.")
    parser.add_argument("--min-premarket-volume", type=int, default=LONG_DIP_MIN_PREMARKET_VOLUME, help="Minimum premarket share volume.")
    parser.add_argument("--min-premarket-trade-count", type=int, default=LONG_DIP_MIN_PREMARKET_TRADE_COUNT, help="Minimum premarket trade count.")
    parser.add_argument("--output-csv", default=str(DEFAULT_EXPORT_DIR / "databento_watchlist_top5_pre1530.csv"), help="CSV output path.")
    parser.add_argument("--output-md", default=str(DEFAULT_EXPORT_DIR / "databento_watchlist_top5_pre1530.md"), help="Markdown output path.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    max_gap_pct = None if args.max_gap_pct is not None and args.max_gap_pct < 0 else args.max_gap_pct
    cfg = LongDipConfig(
        min_gap_pct=args.min_gap_pct,
        max_gap_pct=max_gap_pct,
        min_previous_close=args.min_previous_close,
        min_premarket_dollar_volume=args.min_premarket_dollar_volume,
        min_premarket_volume=args.min_premarket_volume,
        min_premarket_trade_count=args.min_premarket_trade_count,
        position_budget_usd=args.position_budget_usd,
        top_n=args.top_n,
    )

    daily, prem, diagnostics, metadata = load_watchlist_inputs(
        bundle=args.bundle,
        export_dir=args.export_dir,
    )
    watchlists = build_daily_watchlists(daily=daily, prem=prem, diagnostics=diagnostics, cfg=cfg)

    output_csv = Path(args.output_csv).expanduser()
    output_md = Path(args.output_md).expanduser()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)

    watchlists.to_csv(output_csv, index=False)
    output_md.write_text(render_markdown_report(watchlists, cfg, metadata), encoding="utf-8")

    print("SOURCE", metadata)
    print("CONFIG", asdict(cfg))
    print("CSV", output_csv)
    print("MARKDOWN", output_md)
    if watchlists.empty:
        print("WATCHLIST_ROWS 0")
        return
    print("WATCHLIST_ROWS", len(watchlists))
    preview_cols = [
        "trade_date",
        "watchlist_rank",
        "symbol",
        "prev_close_to_premarket_pct",
        "premarket_last",
        "premarket_dollar_volume",
        "premarket_volume",
        "premarket_trade_count",
        "l1_limit_buy",
        "l1_take_profit",
        "l1_stop_loss",
        "l1_trailing_stop_anchor",
        "l2_limit_buy",
        "l2_take_profit",
        "l2_stop_loss",
        "l2_trailing_stop_anchor",
        "l3_limit_buy",
        "l3_take_profit",
        "l3_stop_loss",
        "l3_trailing_stop_anchor",
    ]
    print(watchlists[preview_cols].to_string(index=False))


if __name__ == "__main__":
    main()