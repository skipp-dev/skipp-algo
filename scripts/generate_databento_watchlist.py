from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, TypedDict, cast

import pandas as pd

from strategy_config import (
    LONG_DIP_DEFAULTS,
    LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_ENTRY_EARLY_DIP_MAX_SECONDS,
    LONG_DIP_ENTRY_EARLY_DIP_MIN_PCT,
    LONG_DIP_ENTRY_OPEN30_VOLUME_MIN,
    LONG_DIP_ENTRY_RECLAIM_MAX_SECONDS,
    LONG_DIP_MAX_GAP_PCT,
    LONG_DIP_MIN_GAP_PCT,
    LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS,
    LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME,
    LONG_DIP_MIN_PREMARKET_TRADE_COUNT,
    LONG_DIP_MIN_PREMARKET_VOLUME,
    LONG_DIP_MIN_PREVIOUS_CLOSE,
    LONG_DIP_POSITION_BUDGET_USD,
    LONG_DIP_TOP_N,
)
from scripts.load_databento_export_bundle import load_export_bundle


US_EASTERN_TZ = __import__("zoneinfo").ZoneInfo("America/New_York")


@dataclass(frozen=True)
class LongDipConfig:
    top_n: int = LONG_DIP_TOP_N
    min_gap_pct: float = LONG_DIP_MIN_GAP_PCT
    max_gap_pct: float = LONG_DIP_MAX_GAP_PCT
    min_previous_close: float = LONG_DIP_MIN_PREVIOUS_CLOSE
    min_premarket_dollar_volume: float = LONG_DIP_MIN_PREMARKET_DOLLAR_VOLUME
    min_premarket_volume: int = LONG_DIP_MIN_PREMARKET_VOLUME
    min_premarket_trade_count: int = LONG_DIP_MIN_PREMARKET_TRADE_COUNT
    min_premarket_active_seconds: int = LONG_DIP_MIN_PREMARKET_ACTIVE_SECONDS
    position_budget_usd: float = LONG_DIP_POSITION_BUDGET_USD


@dataclass(frozen=True)
class EntryLevel:
    tag: str
    limit_price: float
    quantity: int
    take_profit_price: float
    stop_loss_price: float
    trailing_stop_anchor_price: float


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
    out = frame.copy()
    if "trade_date" in out.columns:
        out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
    if "symbol" in out.columns:
        out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    return out


def _load_latest_manifest(export_dir: Path) -> tuple[dict[str, Any] | None, Path | None]:
    manifests = sorted(export_dir.glob("*_manifest.json"), key=lambda item: item.stat().st_mtime)
    if not manifests:
        return None, None
    manifest_path = manifests[-1]
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload, manifest_path
    except Exception:
        return None, manifest_path
    return None, manifest_path


def _resolve_source_data_fetched_at(frames: list[pd.DataFrame], manifest: dict[str, Any] | None) -> str | None:
    for frame in frames:
        for column in ("source_data_fetched_at", "premarket_fetched_at", "daily_bars_fetched_at"):
            if column in frame.columns:
                values = frame[column].dropna().astype(str)
                if not values.empty:
                    return str(values.iloc[-1])
    if manifest:
        for key in ("source_data_fetched_at", "premarket_fetched_at", "export_generated_at", "exported_at"):
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
    manifest, manifest_path = _load_latest_manifest(export_dir)

    if daily is not None and premarket is not None:
        exact_paths = [path for path in (daily_path, premarket_path, diagnostics_path) if path.exists()]
        exact_source_data_fetched_at = (
            datetime.fromtimestamp(max(path.stat().st_mtime for path in exact_paths), tz=UTC).isoformat(timespec="seconds")
            if exact_paths
            else None
        )
        metadata: dict[str, Any] = {
            "source": "exact_named",
            "paths": [str(daily_path), str(premarket_path)],
            "manifest": manifest or {},
            "source_data_fetched_at": exact_source_data_fetched_at,
        }
        if manifest_path is not None:
            metadata["manifest_path"] = str(manifest_path)
        return _normalize_frame(daily), _normalize_frame(premarket), _normalize_frame(diagnostics if diagnostics is not None else pd.DataFrame()), metadata, warnings

    payload = load_export_bundle(
        export_dir,
        required_frames=("daily_symbol_features_full_universe", "premarket_features_full_universe"),
        manifest_prefix="databento_volatility_production_",
    )
    frames = payload["frames"]
    bundle_daily = frames.get("daily_symbol_features_full_universe")
    bundle_premarket = frames.get("premarket_features_full_universe")
    if not isinstance(bundle_daily, pd.DataFrame) or not isinstance(bundle_premarket, pd.DataFrame):
        raise FileNotFoundError("Bundle fallback is missing daily_symbol_features_full_universe or premarket_features_full_universe")
    warnings.append("Fell back to the latest manifest-backed export bundle because exact-named exports were unavailable.")
    return (
        _normalize_frame(bundle_daily),
        _normalize_frame(bundle_premarket),
        _normalize_frame(frames.get("symbol_day_diagnostics") if isinstance(frames.get("symbol_day_diagnostics"), pd.DataFrame) else pd.DataFrame()),
        {
            "source": "bundle",
            "manifest": payload.get("manifest", {}),
            "manifest_path": str(payload.get("manifest_path", "")),
            "fallback_reason": "daily_symbol_features_full_universe missing_or_corrupt, premarket_features_full_universe missing_or_corrupt",
        },
        warnings,
    )


def load_watchlist_inputs(*, bundle: str | Path | None, export_dir: str | Path | None) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if bundle is not None:
        payload = load_export_bundle(
            Path(bundle).expanduser(),
            required_frames=("daily_symbol_features_full_universe", "premarket_features_full_universe"),
        )
        frames = payload["frames"]
        daily = _normalize_frame(frames.get("daily_symbol_features_full_universe", pd.DataFrame()))
        premarket = _normalize_frame(frames.get("premarket_features_full_universe", pd.DataFrame()))
        diagnostics = _normalize_frame(frames.get("symbol_day_diagnostics") if isinstance(frames.get("symbol_day_diagnostics"), pd.DataFrame) else pd.DataFrame())
        metadata = {"source": "bundle", "manifest": payload.get("manifest", {}), "manifest_path": str(payload.get("manifest_path", ""))}
        return daily, premarket, diagnostics, metadata
    if export_dir is None:
        raise ValueError("Either bundle or export_dir must be provided.")
    daily, premarket, diagnostics, metadata, _warnings = _load_watchlist_inputs(Path(export_dir).expanduser())
    return daily, premarket, diagnostics, metadata


def _merge_open_signal_metrics(base: pd.DataFrame, metrics: pd.DataFrame | None) -> pd.DataFrame:
    if metrics is None or metrics.empty:
        return base.copy()
    merged = base.copy().merge(metrics, on=["trade_date", "symbol"], how="left", suffixes=("", "__metric"))
    for column in metrics.columns:
        if column in ("trade_date", "symbol"):
            continue
        metric_column = f"{column}__metric"
        if metric_column in merged.columns:
            if column in merged.columns:
                merged[column] = merged[metric_column].where(merged[metric_column].notna(), merged[column])
            else:
                merged[column] = merged[metric_column]
            merged = merged.drop(columns=[metric_column])
    return merged


def _build_candidate_frame(daily: pd.DataFrame, prem: pd.DataFrame, diagnostics: pd.DataFrame | None, trade_date: date) -> pd.DataFrame:
    d = _normalize_frame(daily)
    p = _normalize_frame(prem)
    d = d.loc[d.get("trade_date").eq(trade_date)].copy() if "trade_date" in d.columns else pd.DataFrame()
    p = p.loc[p.get("trade_date").eq(trade_date)].copy() if "trade_date" in p.columns else pd.DataFrame()
    merged = d.merge(p, on=["trade_date", "symbol"], how="left", suffixes=("", "_premarket")) if not d.empty else d
    if diagnostics is not None and not diagnostics.empty and not merged.empty:
        diag = _normalize_frame(diagnostics)
        diag = diag.loc[diag.get("trade_date").eq(trade_date)].copy() if "trade_date" in diag.columns else pd.DataFrame()
        if not diag.empty:
            merged = merged.merge(diag.drop_duplicates(subset=["trade_date", "symbol"]), on=["trade_date", "symbol"], how="left", suffixes=("", "_diag"))

    if merged.empty:
        return merged
    merged["is_eligible"] = merged.get("is_eligible", pd.Series(True, index=merged.index)).fillna(True).astype(bool)
    merged["previous_close"] = pd.to_numeric(merged.get("previous_close"), errors="coerce")
    merged["premarket_last"] = pd.to_numeric(merged.get("premarket_last"), errors="coerce")
    merged["premarket_last"] = merged["premarket_last"].where(merged["premarket_last"].notna(), merged["previous_close"])
    merged["prev_close_to_premarket_pct"] = pd.to_numeric(merged.get("prev_close_to_premarket_pct"), errors="coerce")
    merged["premarket_volume"] = pd.to_numeric(merged.get("premarket_volume"), errors="coerce").fillna(0.0)
    merged["premarket_trade_count"] = pd.to_numeric(merged.get("premarket_trade_count"), errors="coerce")
    if "premarket_dollar_volume" in merged.columns:
        merged["premarket_dollar_volume"] = pd.to_numeric(merged.get("premarket_dollar_volume"), errors="coerce")
    else:
        merged["premarket_dollar_volume"] = merged["premarket_last"] * merged["premarket_volume"]

    if "premarket_active_seconds" in merged.columns:
        merged["premarket_active_seconds"] = pd.to_numeric(merged.get("premarket_active_seconds"), errors="coerce")
        merged["trade_count_source_used"] = merged.get("premarket_trade_count_source", pd.Series("actual_active_seconds", index=merged.index)).fillna("actual_active_seconds").astype(str)
    else:
        merged["premarket_active_seconds"] = pd.to_numeric(merged.get("premarket_trade_count"), errors="coerce")
        merged["trade_count_source_used"] = "proxy_active_seconds"
    return merged


def build_filter_funnel(*, daily: pd.DataFrame, prem: pd.DataFrame, cfg: LongDipConfig, trade_date: date) -> list[dict[str, Any]]:
    frame = _build_candidate_frame(daily, prem, None, trade_date)
    if frame.empty:
        return []
    current = frame.copy()
    funnel = [{"filter": "Total symbols", "threshold": "n/a", "remaining": int(len(current))}]

    def _apply(name: str, threshold: str, mask: pd.Series) -> None:
        nonlocal current
        current = current.loc[mask.fillna(False)].copy()
        funnel.append({"filter": name, "threshold": threshold, "remaining": int(len(current))})

    _apply("is_eligible", "True", current["is_eligible"])
    _apply("premarket_gap_pct", f">= {cfg.min_gap_pct:.1f}", pd.to_numeric(current["prev_close_to_premarket_pct"], errors="coerce") >= float(cfg.min_gap_pct))
    _apply("premarket_dollar_volume", f">= {cfg.min_premarket_dollar_volume:,.0f}", pd.to_numeric(current["premarket_dollar_volume"], errors="coerce") >= float(cfg.min_premarket_dollar_volume))
    _apply("premarket_volume", f">= {int(cfg.min_premarket_volume):,}", pd.to_numeric(current["premarket_volume"], errors="coerce") >= int(cfg.min_premarket_volume))

    trade_count = pd.to_numeric(current.get("premarket_trade_count"), errors="coerce")
    if trade_count.isna().all():
        funnel.append({"filter": "premarket_trade_count", "threshold": "skipped (no data)", "remaining": int(len(current))})
    else:
        _apply("premarket_trade_count", f">= {int(cfg.min_premarket_trade_count):,}", trade_count >= int(cfg.min_premarket_trade_count))
    return funnel


def build_preopen_long_candidates(*, daily: pd.DataFrame, prem: pd.DataFrame, cfg: LongDipConfig, trade_date: date, diagnostics: pd.DataFrame | None = None) -> pd.DataFrame:
    frame = _build_candidate_frame(daily, prem, diagnostics, trade_date)
    if frame.empty:
        return frame
    current = frame.loc[frame["is_eligible"]].copy()
    current = current.loc[pd.to_numeric(current["previous_close"], errors="coerce") >= float(cfg.min_previous_close)].copy()
    current = current.loc[pd.to_numeric(current["prev_close_to_premarket_pct"], errors="coerce") >= float(cfg.min_gap_pct)].copy()
    current = current.loc[pd.to_numeric(current["prev_close_to_premarket_pct"], errors="coerce") <= float(cfg.max_gap_pct)].copy()
    current = current.loc[pd.to_numeric(current["premarket_dollar_volume"], errors="coerce") >= float(cfg.min_premarket_dollar_volume)].copy()
    current = current.loc[pd.to_numeric(current["premarket_volume"], errors="coerce") >= int(cfg.min_premarket_volume)].copy()
    current = current.loc[pd.to_numeric(current["premarket_trade_count"], errors="coerce").fillna(0.0) >= int(cfg.min_premarket_trade_count)].copy()
    current = current.loc[pd.to_numeric(current["premarket_active_seconds"], errors="coerce").fillna(0.0) >= int(cfg.min_premarket_active_seconds)].copy()

    if current.empty:
        return current
    sort_cols = [col for col in ["trade_date", "prev_close_to_premarket_pct", "premarket_dollar_volume", "symbol"] if col in current.columns]
    ascending = [True, False, False, True][: len(sort_cols)]
    ranked = current.sort_values(sort_cols, ascending=ascending).reset_index(drop=True)
    ranked["watchlist_rank"] = ranked.groupby("trade_date").cumcount() + 1
    ranked = ranked.loc[ranked["watchlist_rank"] <= int(cfg.top_n)].copy()
    ranked["watchlist_rank"] = ranked["watchlist_rank"].astype(int)
    return ranked


def build_preanchor_seed_candidates(*, daily: pd.DataFrame, diagnostics: pd.DataFrame | None, cfg: LongDipConfig, trade_date: date) -> pd.DataFrame:
    frame = _normalize_frame(daily)
    if frame.empty:
        return frame
    current = frame.loc[frame.get("trade_date").eq(trade_date)].copy() if "trade_date" in frame.columns else pd.DataFrame()
    if current.empty:
        return current
    scope_col = "selected_top20pct_0400" if "selected_top20pct_0400" in current.columns else "selected_top20pct"
    mask = current.get(scope_col, pd.Series(False, index=current.index)).fillna(False).astype(bool)
    seeded = current.loc[mask].copy()
    if seeded.empty:
        return seeded
    seeded["candidate_basis"] = "pre_anchor_historical_seed"
    seeded["premarket_last"] = pd.to_numeric(seeded.get("premarket_last"), errors="coerce")
    seeded["premarket_last"] = seeded["premarket_last"].where(seeded["premarket_last"].notna(), pd.to_numeric(seeded.get("previous_close"), errors="coerce"))
    sort_cols = [col for col in ["focus_0400_open_30s_volume", "window_range_pct", "symbol"] if col in seeded.columns]
    ascending = [False, False, True][: len(sort_cols)]
    if sort_cols:
        seeded = seeded.sort_values(sort_cols, ascending=ascending)
    seeded = seeded.reset_index(drop=True)
    seeded["watchlist_rank"] = seeded.groupby("trade_date").cumcount() + 1
    return seeded.loc[seeded["watchlist_rank"] <= int(cfg.top_n)].copy()


def build_daily_watchlists(*, daily: pd.DataFrame, prem: pd.DataFrame, diagnostics: pd.DataFrame | None, cfg: LongDipConfig) -> pd.DataFrame:
    normalized_daily = _normalize_frame(daily)
    if normalized_daily.empty or "trade_date" not in normalized_daily.columns:
        return pd.DataFrame()
    trade_dates = sorted(item for item in normalized_daily["trade_date"].dropna().unique().tolist())
    frames: list[pd.DataFrame] = []
    for trade_date in trade_dates:
        candidates = build_preopen_long_candidates(daily=normalized_daily, prem=prem, cfg=cfg, trade_date=trade_date, diagnostics=diagnostics)
        if not candidates.empty:
            frames.append(candidates)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def compute_entry_ladder(premarket_last: float, cfg: LongDipConfig) -> list[EntryLevel]:
    base_price = float(premarket_last)
    levels = [
        ("L1", 0.995, 0.25),
        ("L2", 0.990, 0.35),
        ("L3", 0.985, 0.40),
    ]
    out: list[EntryLevel] = []
    for tag, price_mult, budget_weight in levels:
        limit_price = round(base_price * price_mult, 2)
        quantity = int((float(cfg.position_budget_usd) * budget_weight) // max(limit_price, 0.01))
        out.append(
            EntryLevel(
                tag=tag,
                limit_price=limit_price,
                quantity=quantity,
                take_profit_price=round(limit_price * 1.02, 4),
                stop_loss_price=round(limit_price * 0.984, 4),
                trailing_stop_anchor_price=round(limit_price * 0.99, 4),
            )
        )
    return out


def expand_candidate_trade_plan(candidates: pd.DataFrame, cfg: LongDipConfig) -> pd.DataFrame:
    expanded = candidates.copy()
    if expanded.empty:
        return expanded
    for idx, row in expanded.iterrows():
        levels = compute_entry_ladder(float(row.get("premarket_last", 0.0) or 0.0), cfg)
        for level in levels:
            level_key = level.tag.lower()
            expanded.loc[idx, f"{level_key}_limit_buy"] = level.limit_price
            expanded.loc[idx, f"{level_key}_quantity"] = level.quantity
            expanded.loc[idx, f"{level_key}_take_profit"] = level.take_profit_price
            expanded.loc[idx, f"{level_key}_stop_loss"] = level.stop_loss_price
    return expanded


def _resolve_manifest_reference_time_et(manifest: dict[str, Any] | None) -> datetime | None:
    if not manifest:
        return None
    for key in ("source_data_fetched_at", "premarket_fetched_at", "export_generated_at", "exported_at"):
        value = manifest.get(key)
        if not value:
            continue
        ts = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.notna(ts):
            return cast(datetime, ts.to_pydatetime()).astimezone(US_EASTERN_TZ)
    return None


def _build_effective_profile(
    cfg: LongDipConfig,
    *,
    premarket_symbol_count: int,
    manifest: dict[str, Any] | None,
    has_proxy_activity_counts: bool,
) -> tuple[LongDipConfig, dict[str, Any], bool]:
    profile_name = "standard"
    profile_reason = "configured_thresholds"
    pre_anchor_seed = False
    effective_cfg = cfg

    manifest_et = _resolve_manifest_reference_time_et(manifest)
    anchor_raw = (manifest or {}).get("premarket_anchor_et") or "04:00:00"
    anchor_parts = [int(part) for part in str(anchor_raw).split(":")[:2] if str(part).isdigit()]
    anchor_time = time(anchor_parts[0], anchor_parts[1]) if len(anchor_parts) == 2 else time(4, 0)

    if manifest_et is not None and manifest_et.time() < anchor_time and premarket_symbol_count == 0:
        profile_name = "pre_anchor_seeded"
        profile_reason = "premarket_not_started"
        pre_anchor_seed = True
    elif premarket_symbol_count <= 1:
        profile_name = "sparse_premarket"
        profile_reason = "premarket_symbols_too_low"
        effective_cfg = LongDipConfig(
            **{**asdict(cfg), "min_gap_pct": max(1.0, cfg.min_gap_pct), "min_premarket_dollar_volume": 1000.0, "min_premarket_volume": 100}
        )
    elif manifest_et is not None and manifest_et.time() < time(9, 30):
        profile_name = "early_premarket"
        profile_reason = "early_session"
        early_trade_count_floor = 0 if has_proxy_activity_counts else max(120, cfg.min_premarket_trade_count)
        effective_cfg = LongDipConfig(
            **{
                **asdict(cfg),
                "min_gap_pct": max(2.0, cfg.min_gap_pct),
                "min_premarket_dollar_volume": max(1000.0, cfg.min_premarket_dollar_volume),
                "min_premarket_volume": max(100, cfg.min_premarket_volume),
                "min_premarket_trade_count": early_trade_count_floor,
                "min_premarket_active_seconds": min(LONG_DIP_EARLY_MIN_PREMARKET_ACTIVE_SECONDS, 30),
            }
        )

    profile = {"profile_name": profile_name, "profile_reason": profile_reason, "premarket_symbols": int(premarket_symbol_count)}
    return effective_cfg, profile, pre_anchor_seed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Databento long-dip watchlist from exported parquet artifacts.")
    parser.add_argument("--export-dir", default="~/Downloads")
    parser.add_argument("--top-n", type=int, default=LONG_DIP_DEFAULTS["top_n"])
    parser.add_argument("--min-gap-pct", type=float, default=LONG_DIP_DEFAULTS["min_gap_pct"])
    parser.add_argument("--max-gap-pct", type=float, default=LONG_DIP_DEFAULTS["max_gap_pct"])
    parser.add_argument("--min-previous-close", type=float, default=LONG_DIP_DEFAULTS["min_previous_close"])
    parser.add_argument("--min-premarket-dollar-volume", type=float, default=LONG_DIP_DEFAULTS["min_premarket_dollar_volume"])
    parser.add_argument("--min-premarket-volume", type=int, default=LONG_DIP_DEFAULTS["min_premarket_volume"])
    parser.add_argument("--min-premarket-trade-count", type=int, default=LONG_DIP_DEFAULTS["min_premarket_trade_count"])
    parser.add_argument("--min-premarket-active-seconds", type=int, default=LONG_DIP_DEFAULTS["min_premarket_active_seconds"])
    parser.add_argument("--position-budget-usd", type=float, default=LONG_DIP_DEFAULTS["position_budget_usd"])
    parser.add_argument("--position-budget-eur", type=float, dest="position_budget_usd")
    return parser


def generate_watchlist_result(*, export_dir: Path, cfg: LongDipConfig) -> WatchlistResult:
    if int(cfg.top_n) <= 0:
        raise ValueError("top_n must be > 0")

    daily, premarket, diagnostics, source_metadata, warnings = _load_watchlist_inputs(export_dir)
    manifest = source_metadata.get("manifest") if isinstance(source_metadata, dict) else None
    if isinstance(manifest, dict):
        exported_at = manifest.get("export_generated_at") or manifest.get("exported_at")
        if exported_at:
            source_metadata["export_generated_at"] = str(exported_at)

    latest_trade_date = None
    if not daily.empty and "trade_date" in daily.columns:
        latest_trade_date = pd.to_datetime(daily["trade_date"], errors="coerce").dt.date.max()

    premarket_symbols = 0
    has_proxy_activity_counts = False
    if latest_trade_date is not None and not premarket.empty and "trade_date" in premarket.columns:
        premarket_latest = premarket.loc[pd.to_datetime(premarket["trade_date"], errors="coerce").dt.date.eq(latest_trade_date)].copy()
        if "has_premarket_data" in premarket_latest.columns:
            premarket_symbols = int(pd.Series(premarket_latest["has_premarket_data"]).fillna(False).astype(bool).sum())
        if "premarket_trade_count_source" in premarket_latest.columns:
            has_proxy_activity_counts = premarket_latest["premarket_trade_count_source"].astype(str).eq("proxy_active_seconds").any()

    effective_cfg, filter_profile, use_pre_anchor_seed = _build_effective_profile(
        cfg,
        premarket_symbol_count=premarket_symbols,
        manifest=manifest,
        has_proxy_activity_counts=has_proxy_activity_counts,
    )

    if use_pre_anchor_seed and latest_trade_date is not None:
        watchlist_table = build_preanchor_seed_candidates(daily=daily, diagnostics=diagnostics, cfg=effective_cfg, trade_date=latest_trade_date)
        if not watchlist_table.empty:
            warnings.append(
                "Live premarket data is not available yet. Showing provisional pre-anchor candidates from the historical selected_top20pct_0400 scope."
            )
        filter_funnel: list[dict[str, Any]] = []
    else:
        watchlist_table = build_daily_watchlists(daily=daily, prem=premarket, diagnostics=diagnostics, cfg=effective_cfg)
        filter_funnel = []
        if latest_trade_date is not None:
            filter_funnel = build_filter_funnel(daily=daily, prem=premarket, cfg=effective_cfg, trade_date=latest_trade_date)

        if watchlist_table.empty and filter_profile.get("profile_name") == "early_premarket":
            relaxed_cfg = LongDipConfig(
                **{
                    **asdict(effective_cfg),
                    "min_premarket_dollar_volume": 1000.0,
                    "min_premarket_volume": 100,
                    "min_premarket_trade_count": 0,
                    "min_premarket_active_seconds": 60,
                }
            )
            relaxed = build_daily_watchlists(daily=daily, prem=premarket, diagnostics=diagnostics, cfg=relaxed_cfg)
            if not relaxed.empty:
                watchlist_table = relaxed
                effective_cfg = relaxed_cfg
                filter_profile = {
                    **filter_profile,
                    "profile_name": "liquidity_relaxed",
                    "relaxed_bottleneck": "premarket_volume",
                }
                filter_funnel = []

    active_watchlist_table = pd.DataFrame()
    if not watchlist_table.empty and latest_trade_date is not None and "trade_date" in watchlist_table.columns:
        active_watchlist_table = watchlist_table.loc[pd.to_datetime(watchlist_table["trade_date"], errors="coerce").dt.date.eq(latest_trade_date)].copy()

    source_data_fetched_at = _resolve_source_data_fetched_at([daily, premarket, diagnostics], manifest if isinstance(manifest, dict) else None)
    if source_data_fetched_at is None and isinstance(source_metadata, dict):
        source_data_fetched_at = source_metadata.get("source_data_fetched_at")

    if active_watchlist_table.empty and not use_pre_anchor_seed:
        warnings.append("No symbols matched the configured Long-Dip filters for the latest trade date.")

    if not watchlist_table.empty:
        filter_funnel = []

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
        "config_snapshot": asdict(effective_cfg),
        "requested_config_snapshot": asdict(cfg),
        "source_metadata": source_metadata,
    }
