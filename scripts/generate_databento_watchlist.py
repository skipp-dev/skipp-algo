from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import pandas as pd

from strategy_config import LONG_DIP_MIN_GAP_PCT, LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME
from scripts.load_databento_export_bundle import load_export_bundle


@dataclass(frozen=True)
class LongDipConfig:
    top_n: int = 5
    min_gap_pct: float = LONG_DIP_MIN_GAP_PCT
    min_premarket_dollar_volume: float = LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME
    min_premarket_volume: int = 0
    min_premarket_trade_count: int = 0
    min_premarket_active_seconds: int = 0


class WatchlistResult(TypedDict):
    generated_at: str
    source_data_fetched_at: str | None
    trade_date: str | None
    watchlist_table: pd.DataFrame
    active_watchlist_table: pd.DataFrame
    summary_table: pd.DataFrame
    latest_trade_date_table: pd.DataFrame
    full_history_table: pd.DataFrame
    filter_funnel: list[dict[str, Any]]
    filter_profile: dict[str, Any]
    warnings: list[str]
    config_snapshot: dict[str, Any]
    requested_config_snapshot: dict[str, Any]
    source_metadata: dict[str, Any]


def _safe_read_parquet(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    if "trade_date" in normalized.columns:
        normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce").dt.date
    if "symbol" in normalized.columns:
        normalized["symbol"] = normalized["symbol"].astype(str).str.strip().str.upper()
    return normalized


def _resolve_source_data_fetched_at(frames: list[pd.DataFrame], manifest: dict[str, Any] | None) -> str | None:
    for frame in frames:
        for column in ("source_data_fetched_at", "premarket_fetched_at", "daily_bars_fetched_at"):
            if column in frame.columns:
                values = frame[column].dropna().astype(str)
                if not values.empty:
                    return values.iloc[-1]
    if manifest:
        for key in ("source_data_fetched_at", "premarket_fetched_at", "export_generated_at"):
            value = manifest.get(key)
            if value:
                return str(value)
    return None


def _load_watchlist_inputs(export_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any], list[str]]:
    warnings: list[str] = []
    daily_path = export_dir / "daily_symbol_features_full_universe.parquet"
    premarket_path = export_dir / "premarket_features_full_universe.parquet"
    diagnostics_path = export_dir / "symbol_day_diagnostics.parquet"

    daily = _safe_read_parquet(daily_path)
    premarket = _safe_read_parquet(premarket_path)
    diagnostics = _safe_read_parquet(diagnostics_path)
    if daily is not None and premarket is not None:
        exact_paths = [path for path in (daily_path, premarket_path, diagnostics_path) if path.exists()]
        exact_source_data_fetched_at = (
            datetime.fromtimestamp(max(path.stat().st_mtime for path in exact_paths), tz=UTC).isoformat(timespec="seconds")
            if exact_paths
            else None
        )
        return (
            _normalize_frame(daily),
            _normalize_frame(premarket),
            _normalize_frame(diagnostics if diagnostics is not None else pd.DataFrame()),
            {
                "source": "exact_named",
                "paths": [str(daily_path), str(premarket_path)],
                "source_data_fetched_at": exact_source_data_fetched_at,
            },
            warnings,
        )

    fallback_reason_parts: list[str] = []
    if daily is None:
        fallback_reason_parts.append("daily_symbol_features_full_universe missing_or_corrupt")
    if premarket is None:
        fallback_reason_parts.append("premarket_features_full_universe missing_or_corrupt")

    payload = load_export_bundle(export_dir)
    frames = payload["frames"]
    bundle_daily = frames.get("daily_symbol_features_full_universe")
    bundle_premarket = frames.get("premarket_features_full_universe")
    if not isinstance(bundle_daily, pd.DataFrame) or not isinstance(bundle_premarket, pd.DataFrame):
        raise FileNotFoundError("Bundle fallback is missing daily_symbol_features_full_universe or premarket_features_full_universe")

    bundle_diagnostics = frames.get("symbol_day_diagnostics")
    warnings.append("Fell back to the latest manifest-backed export bundle because exact-named exports were unavailable.")
    return (
        _normalize_frame(bundle_daily),
        _normalize_frame(bundle_premarket),
        _normalize_frame(bundle_diagnostics if isinstance(bundle_diagnostics, pd.DataFrame) else pd.DataFrame()),
        {
            "source": "bundle",
            "manifest_path": str(payload["manifest_path"]),
            "fallback_reason": ", ".join(fallback_reason_parts),
            "manifest": payload["manifest"],
        },
        warnings,
    )


def _compute_filter_funnel(frame: pd.DataFrame, cfg: LongDipConfig) -> list[dict[str, Any]]:
    if frame.empty or "trade_date" not in frame.columns:
        return []

    latest_trade_date = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date.dropna().max()
    if latest_trade_date is None:
        return []
    current = frame.loc[frame["trade_date"] == latest_trade_date].copy()
    steps: list[tuple[str, str, pd.Series]] = [
        ("selected_top20pct", "True", current.get("selected_top20pct", pd.Series(True, index=current.index)).fillna(False).astype(bool)),
        ("is_eligible", "True", current.get("is_eligible", pd.Series(True, index=current.index)).fillna(True).astype(bool)),
        ("premarket_gap_pct", f">= {cfg.min_gap_pct:.1f}", pd.to_numeric(current.get("prev_close_to_premarket_pct"), errors="coerce") >= float(cfg.min_gap_pct)),
        (
            "premarket_dollar_volume",
            f">= {cfg.min_premarket_dollar_volume:,.0f}",
            pd.to_numeric(current.get("premarket_dollar_volume"), errors="coerce") >= float(cfg.min_premarket_dollar_volume),
        ),
        (
            "premarket_volume",
            f">= {int(cfg.min_premarket_volume):,}",
            pd.to_numeric(current.get("premarket_volume"), errors="coerce") >= int(cfg.min_premarket_volume),
        ),
        (
            "premarket_trade_count",
            f">= {int(cfg.min_premarket_trade_count):,}",
            pd.to_numeric(current.get("premarket_trade_count"), errors="coerce") >= int(cfg.min_premarket_trade_count),
        ),
        (
            "premarket_active_seconds",
            f">= {int(cfg.min_premarket_active_seconds):,}",
            pd.to_numeric(current.get("premarket_active_seconds"), errors="coerce") >= int(cfg.min_premarket_active_seconds),
        ),
    ]

    funnel = [{"filter": "Total symbols", "threshold": "n/a", "remaining": int(len(current))}]
    for name, threshold, mask in steps:
        current = current.loc[mask.fillna(False)].copy()
        funnel.append({"filter": name, "threshold": threshold, "remaining": int(len(current))})
    return funnel


def _format_rank_change(previous_rank: Any, current_rank: Any) -> str:
    previous = pd.to_numeric(pd.Series([previous_rank]), errors="coerce").iloc[0]
    current = pd.to_numeric(pd.Series([current_rank]), errors="coerce").iloc[0]
    if pd.isna(current):
        return "n/a"
    if pd.isna(previous):
        return "new"
    delta = int(previous) - int(current)
    if delta == 0:
        return "flat"
    if delta > 0:
        return f"up {delta}"
    return f"down {abs(delta)}"


def _attach_previous_day_rank_context(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()

    enriched = frame.sort_values(["trade_date", "watchlist_rank", "symbol"]).reset_index(drop=True).copy()
    history = enriched[["trade_date", "symbol", "watchlist_rank"]].rename(columns={"watchlist_rank": "previous_watchlist_rank"})
    history = history.sort_values(["symbol", "trade_date"]).reset_index(drop=True)
    history["next_trade_date"] = history.groupby("symbol")["trade_date"].shift(-1)
    history = history.dropna(subset=["next_trade_date"])
    history["next_trade_date"] = pd.to_datetime(history["next_trade_date"], errors="coerce").dt.date
    enriched = enriched.merge(
        history[["symbol", "next_trade_date", "previous_watchlist_rank"]],
        left_on=["symbol", "trade_date"],
        right_on=["symbol", "next_trade_date"],
        how="left",
    ).drop(columns=["next_trade_date"])
    enriched["watchlist_rank_delta"] = pd.to_numeric(enriched["previous_watchlist_rank"], errors="coerce") - pd.to_numeric(enriched["watchlist_rank"], errors="coerce")
    enriched["watchlist_rank_change"] = [
        _format_rank_change(previous_rank, current_rank)
        for previous_rank, current_rank in zip(enriched["previous_watchlist_rank"], enriched["watchlist_rank"], strict=False)
    ]
    return enriched


def _build_watchlist_table(daily: pd.DataFrame, premarket: pd.DataFrame, diagnostics: pd.DataFrame, cfg: LongDipConfig) -> tuple[pd.DataFrame, pd.DataFrame, list[dict[str, Any]], dict[str, Any]]:
    merged = daily.copy()
    if merged.empty:
        empty = pd.DataFrame()
        return empty, empty, [], {"profile_name": "standard", "profile_reason": "no_daily_rows", "premarket_symbols": 0}

    premarket_subset = premarket.copy()
    if not premarket_subset.empty:
        merged = merged.merge(premarket_subset, on=["trade_date", "symbol"], how="left", suffixes=("", "_premarket"))
    if not diagnostics.empty:
        diagnostics_subset = diagnostics.drop_duplicates(subset=["trade_date", "symbol"])
        merged = merged.merge(diagnostics_subset, on=["trade_date", "symbol"], how="left", suffixes=("", "_diagnostic"))

    merged["selected_top20pct"] = merged.get("selected_top20pct", pd.Series(True, index=merged.index)).fillna(False).astype(bool)
    merged["is_eligible"] = merged.get("is_eligible", pd.Series(True, index=merged.index)).fillna(True).astype(bool)
    merged["has_premarket_data"] = merged.get("has_premarket_data", pd.Series(False, index=merged.index)).fillna(False).astype(bool)
    merged["premarket_volume"] = pd.to_numeric(merged.get("premarket_volume"), errors="coerce").fillna(0.0)
    merged["premarket_trade_count"] = pd.to_numeric(merged.get("premarket_trade_count"), errors="coerce").fillna(0.0)
    merged["premarket_active_seconds"] = pd.to_numeric(
        merged.get("premarket_active_seconds", pd.Series(0.0, index=merged.index)),
        errors="coerce",
    ).fillna(0.0)
    merged["prev_close_to_premarket_pct"] = pd.to_numeric(merged.get("prev_close_to_premarket_pct"), errors="coerce")
    merged["premarket_last"] = pd.to_numeric(merged.get("premarket_last"), errors="coerce")
    if "premarket_dollar_volume" not in merged.columns:
        merged["premarket_dollar_volume"] = merged["premarket_last"] * merged["premarket_volume"]
    else:
        merged["premarket_dollar_volume"] = pd.to_numeric(merged.get("premarket_dollar_volume"), errors="coerce")

    funnel = _compute_filter_funnel(merged, cfg)

    filtered = merged.loc[merged["selected_top20pct"]].copy()
    filtered = filtered.loc[filtered["is_eligible"]].copy()
    filtered = filtered.loc[pd.to_numeric(filtered["prev_close_to_premarket_pct"], errors="coerce") >= float(cfg.min_gap_pct)].copy()
    filtered = filtered.loc[pd.to_numeric(filtered["premarket_dollar_volume"], errors="coerce") >= float(cfg.min_premarket_dollar_volume)].copy()
    filtered = filtered.loc[pd.to_numeric(filtered["premarket_volume"], errors="coerce") >= int(cfg.min_premarket_volume)].copy()
    filtered = filtered.loc[pd.to_numeric(filtered["premarket_trade_count"], errors="coerce") >= int(cfg.min_premarket_trade_count)].copy()
    filtered = filtered.loc[pd.to_numeric(filtered["premarket_active_seconds"], errors="coerce") >= int(cfg.min_premarket_active_seconds)].copy()

    if filtered.empty:
        empty = pd.DataFrame(columns=list(merged.columns) + ["watchlist_rank", "previous_watchlist_rank", "watchlist_rank_delta", "watchlist_rank_change"])
        profile = {
            "profile_name": "standard",
            "profile_reason": "configured_thresholds",
            "premarket_symbols": int(merged.get("has_premarket_data", pd.Series(dtype=bool)).sum()),
        }
        return empty, empty, funnel, profile

    ranking_columns = [column for column in ["trade_date", "rank_within_trade_date", "window_range_pct", "window_return_pct", "premarket_dollar_volume", "symbol"] if column in filtered.columns]
    ascending = [True, True, False, False, False, True][: len(ranking_columns)]
    ranked = filtered.sort_values(ranking_columns, ascending=ascending).reset_index(drop=True)
    ranked["watchlist_rank"] = ranked.groupby("trade_date").cumcount() + 1
    ranked = ranked.loc[ranked["watchlist_rank"] <= int(cfg.top_n)].copy()
    ranked["watchlist_rank"] = ranked["watchlist_rank"].astype(int)
    ranked = _attach_previous_day_rank_context(ranked)

    latest_trade_date = ranked["trade_date"].dropna().max()
    active = ranked.loc[ranked["trade_date"] == latest_trade_date].sort_values(["watchlist_rank", "symbol"]).reset_index(drop=True)
    ranked = ranked.sort_values(["trade_date", "watchlist_rank", "symbol"]).reset_index(drop=True)
    profile = {
        "profile_name": "standard",
        "profile_reason": "configured_thresholds",
        "premarket_symbols": int(merged.get("has_premarket_data", pd.Series(dtype=bool)).sum()),
    }
    return ranked, active, ([] if not active.empty else funnel), profile


def generate_watchlist_result(*, export_dir: Path, cfg: LongDipConfig) -> WatchlistResult:
    daily, premarket, diagnostics, source_metadata, warnings = _load_watchlist_inputs(export_dir)
    watchlist_table, active_watchlist_table, filter_funnel, filter_profile = _build_watchlist_table(daily, premarket, diagnostics, cfg)
    latest_trade_date = None
    if not daily.empty and "trade_date" in daily.columns:
        latest_trade_date = pd.to_datetime(daily["trade_date"], errors="coerce").dt.date.max()
    source_data_fetched_at = _resolve_source_data_fetched_at(
        [daily, premarket, diagnostics],
        source_metadata.get("manifest") if isinstance(source_metadata, dict) else None,
    )
    if source_data_fetched_at is None and isinstance(source_metadata, dict):
        source_data_fetched_at = source_metadata.get("source_data_fetched_at")
    if active_watchlist_table.empty:
        warnings = [*warnings, "No symbols matched the configured Long-Dip filters for the latest trade date."]
    config_snapshot = asdict(cfg)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_data_fetched_at": source_data_fetched_at,
        "trade_date": latest_trade_date.isoformat() if latest_trade_date else None,
        "watchlist_table": watchlist_table,
        "active_watchlist_table": active_watchlist_table,
        "summary_table": active_watchlist_table.copy(),
        "latest_trade_date_table": active_watchlist_table.copy(),
        "full_history_table": watchlist_table.copy(),
        "filter_funnel": filter_funnel,
        "filter_profile": filter_profile,
        "warnings": warnings,
        "config_snapshot": config_snapshot,
        "requested_config_snapshot": config_snapshot,
        "source_metadata": source_metadata,
    }