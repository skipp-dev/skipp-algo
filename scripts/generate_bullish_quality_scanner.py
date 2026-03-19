from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from newsstack_fmp._market_cal import is_us_equity_trading_day
from scripts.bullish_quality_config import (
    BullishQualityConfig,
    BullishQualityScannerResult,
    build_default_bullish_quality_config,
)
from scripts.load_databento_export_bundle import load_export_bundle


def _empty_window_feature_table() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "symbol",
            "window_tag",
            "window_quality_score",
            "quality_rank_within_window",
            "quality_selected_top_n",
            "passes_quality_filter",
            "quality_filter_reason",
        ]
    )


def _read_exact_named_frame(export_dir: Path, name: str) -> pd.DataFrame:
    path = export_dir / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"Missing export artifact: {path}")
    return pd.read_parquet(path)


def load_bullish_quality_inputs(export_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, list[str], dict[str, Any] | None]:
    warnings: list[str] = []
    try:
        return (
            _read_exact_named_frame(export_dir, "premarket_window_features_full_universe"),
            _read_exact_named_frame(export_dir, "daily_symbol_features_full_universe"),
            warnings,
            None,
        )
    except Exception:
        payload = load_export_bundle(
            export_dir,
            required_frames=("premarket_window_features_full_universe", "daily_symbol_features_full_universe"),
            manifest_prefix="databento_volatility_production_",
        )
        frames = payload["frames"]
        warnings.append("Fell back to the latest manifest-backed production bundle because exact-named bullish-quality inputs were unavailable.")
        return (
            frames["premarket_window_features_full_universe"],
            frames["daily_symbol_features_full_universe"],
            warnings,
            payload.get("manifest") if isinstance(payload.get("manifest"), dict) else None,
        )


def _normalize_trade_date(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
    out["symbol"] = out["symbol"].astype(str).str.upper()
    return out


def _resolve_source_data_fetched_at(frame: pd.DataFrame) -> str | None:
    if "source_data_fetched_at" not in frame.columns or frame.empty:
        return None
    values = frame["source_data_fetched_at"].dropna().astype(str)
    return values.iloc[-1] if not values.empty else None


def filter_bullish_quality_candidates(frame: pd.DataFrame, *, cfg: BullishQualityConfig) -> pd.DataFrame:
    filtered = frame.copy()
    filtered["passes_quality_filter"] = filtered["passes_quality_filter"].fillna(False).astype(bool)
    filtered = filtered.loc[filtered["passes_quality_filter"]].copy()
    filtered["window_quality_score"] = pd.to_numeric(filtered["window_quality_score"], errors="coerce")
    return filtered


def rank_bullish_quality_candidates(frame: pd.DataFrame, *, cfg: BullishQualityConfig) -> pd.DataFrame:
    ranked = frame.copy()
    if ranked.empty:
        ranked["quality_rank_within_window"] = pd.Series(dtype="Int64")
        ranked["quality_selected_top_n"] = pd.Series(dtype=bool)
        return ranked

    ranked["window_quality_score"] = pd.to_numeric(ranked["window_quality_score"], errors="coerce")
    ranked["window_dollar_volume"] = pd.to_numeric(ranked.get("window_dollar_volume"), errors="coerce")
    ranked["window_structure_bias_score"] = pd.to_numeric(ranked.get("window_structure_bias_score"), errors="coerce")
    ranked["window_structure_alignment_score"] = pd.to_numeric(ranked.get("window_structure_alignment_score"), errors="coerce")
    ranked = ranked.sort_values(
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
    ).reset_index(drop=True)
    ranked["quality_rank_within_window"] = ranked.groupby(["trade_date", "window_tag"]).cumcount() + 1
    ranked["quality_rank_within_window"] = ranked["quality_rank_within_window"].astype("Int64")
    ranked["quality_selected_top_n"] = ranked["quality_rank_within_window"] <= int(cfg.top_n)
    return ranked


def _build_filter_diagnostics(window_features: pd.DataFrame, ranked: pd.DataFrame) -> pd.DataFrame:
    if window_features.empty:
        return pd.DataFrame(columns=["trade_date", "window_tag", "window_rows", "pass_rows", "top_n_rows"])

    all_rows = (
        window_features.groupby(["trade_date", "window_tag"], dropna=False)
        .size()
        .rename("window_rows")
        .reset_index()
    )
    pass_rows = (
        window_features.loc[window_features["passes_quality_filter"].fillna(False).astype(bool)]
        .groupby(["trade_date", "window_tag"], dropna=False)
        .size()
        .rename("pass_rows")
        .reset_index()
    )
    top_rows = (
        ranked.loc[ranked["quality_selected_top_n"].fillna(False).astype(bool)]
        .groupby(["trade_date", "window_tag"], dropna=False)
        .size()
        .rename("top_n_rows")
        .reset_index()
    )
    diagnostics = all_rows.merge(pass_rows, on=["trade_date", "window_tag"], how="left")
    diagnostics = diagnostics.merge(top_rows, on=["trade_date", "window_tag"], how="left")
    diagnostics[["pass_rows", "top_n_rows"]] = diagnostics[["pass_rows", "top_n_rows"]].fillna(0).astype(int)
    return diagnostics.sort_values(["trade_date", "window_tag"]).reset_index(drop=True)


def _resolve_active_trade_date(preferred_trade_date: date | None, ranked: pd.DataFrame) -> tuple[date | None, bool]:
    if preferred_trade_date is None:
        return None, False
    if ranked.empty or "trade_date" not in ranked.columns:
        return preferred_trade_date, False

    available_trade_dates = ranked["trade_date"].dropna()
    if available_trade_dates.eq(preferred_trade_date).any():
        return preferred_trade_date, False
    if is_us_equity_trading_day(preferred_trade_date):
        return preferred_trade_date, False

    prior_trade_dates = available_trade_dates.loc[available_trade_dates < preferred_trade_date]
    if prior_trade_dates.empty:
        return preferred_trade_date, False
    return prior_trade_dates.max(), True


def _latest_window_table(ranked: pd.DataFrame, cfg: BullishQualityConfig, active_trade_date: date | None = None) -> pd.DataFrame:
    if ranked.empty:
        return ranked.copy()
    latest_trade_date = active_trade_date or ranked["trade_date"].dropna().max()
    preferred_tag = cfg.window_definitions[-1].tag if cfg.window_definitions else None
    latest = ranked.loc[ranked["trade_date"] == latest_trade_date].copy()
    if latest.empty:
        return ranked.iloc[0:0].copy()
    if preferred_tag is not None and latest["window_tag"].eq(preferred_tag).any():
        latest = latest.loc[latest["window_tag"] == preferred_tag].copy()
    else:
        latest = latest.sort_values("window_tag")
        latest = latest.loc[latest["window_tag"] == latest["window_tag"].iloc[-1]].copy()
    latest = latest.loc[latest["quality_selected_top_n"].fillna(False).astype(bool)].copy()
    return latest.sort_values(["quality_rank_within_window", "symbol"]).reset_index(drop=True)


def generate_bullish_quality_scanner_result(
    *,
    export_dir: Path,
    cfg: BullishQualityConfig | None = None,
) -> BullishQualityScannerResult:
    resolved_cfg = cfg or build_default_bullish_quality_config()
    warnings: list[str] = []
    window_features, daily_features, load_warnings, manifest = load_bullish_quality_inputs(export_dir)
    warnings.extend(load_warnings)
    daily_features = _normalize_trade_date(daily_features)
    latest_daily_trade_date = daily_features["trade_date"].dropna().max() if not daily_features.empty else None
    window_features = _normalize_trade_date(window_features)

    # Avoid showing stale rankings when daily context is already on a newer trade date.
    if latest_daily_trade_date is not None and not window_features.empty:
        latest_window_trade_date = window_features["trade_date"].dropna().max()
        if latest_window_trade_date is not None and latest_window_trade_date < latest_daily_trade_date:
            warnings.append(
                "Window features are older than the latest daily trade date; suppressing stale rankings until current-day premarket rows are available."
            )
            window_features = window_features.loc[window_features["trade_date"] == latest_daily_trade_date].copy()

    source_data_fetched_at = _resolve_source_data_fetched_at(window_features)
    if source_data_fetched_at is None and manifest:
        for key in ("source_data_fetched_at", "premarket_fetched_at", "export_generated_at", "exported_at"):
            value = manifest.get(key)
            if value:
                source_data_fetched_at = str(value)
                break

    if window_features.empty:
        warnings.append("No premarket window feature rows were available.")
        empty = _empty_window_feature_table()
        return BullishQualityScannerResult(
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            trade_date=latest_daily_trade_date,
            source_data_fetched_at=source_data_fetched_at,
            config_snapshot={**asdict(resolved_cfg), "window_definitions": [asdict(item) for item in resolved_cfg.window_definitions]},
            rankings_table=empty,
            latest_window_table=empty,
            filter_diagnostics_table=pd.DataFrame(),
            window_feature_table=empty,
            warnings=warnings,
        )

    filtered = filter_bullish_quality_candidates(window_features, cfg=resolved_cfg)
    ranked = rank_bullish_quality_candidates(filtered, cfg=resolved_cfg)
    if ranked.empty:
        warnings.append("No bullish-quality candidates matched the configured filters.")

    latest_trade_date = window_features["trade_date"].dropna().max() if not window_features.empty else None
    diagnostics = _build_filter_diagnostics(window_features, ranked)
    active_trade_date, used_non_trading_fallback = _resolve_active_trade_date(latest_trade_date, ranked)
    used_trading_day_stale_fallback = False
    if latest_trade_date is not None and active_trade_date == latest_trade_date and not ranked.empty:
        ranked_trade_dates = ranked["trade_date"].dropna()
        if not ranked_trade_dates.eq(latest_trade_date).any():
            prior_ranked_trade_dates = ranked_trade_dates.loc[ranked_trade_dates < latest_trade_date]
            if not prior_ranked_trade_dates.empty:
                active_trade_date = prior_ranked_trade_dates.max()
                used_trading_day_stale_fallback = True
    latest_window = _latest_window_table(ranked, resolved_cfg, active_trade_date=active_trade_date)
    if used_non_trading_fallback and latest_trade_date is not None and active_trade_date is not None:
        warnings.append(
            "Latest export trade date "
            f"{latest_trade_date.isoformat()} is a non-trading day without bullish-quality candidates; showing the latest populated trade date "
            f"{active_trade_date.isoformat()}."
        )
    elif used_trading_day_stale_fallback and latest_trade_date is not None and active_trade_date is not None:
        warnings.append(
            "Latest export trade date "
            f"{latest_trade_date.isoformat()} has no bullish-quality candidates yet; showing the latest populated trade date "
            f"{active_trade_date.isoformat()} as a stale previous-session fallback."
        )

    display_columns = [
        "trade_date",
        "symbol",
        "window_tag",
        "quality_rank_within_window",
        "window_quality_score",
        "window_dollar_volume",
        "window_return_pct",
        "window_close_position_pct",
        "quality_filter_reason",
    ]
    rankings_table = ranked[[column for column in display_columns if column in ranked.columns]].copy()
    latest_window_table = latest_window[[column for column in display_columns if column in latest_window.columns]].copy()
    latest_window_table = latest_window_table.rename(columns={"quality_filter_reason": "quality_reason"})
    window_feature_table = window_features.sort_values(["trade_date", "window_tag", "symbol"]).reset_index(drop=True)
    _ = daily_features
    return BullishQualityScannerResult(
        generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
        trade_date=active_trade_date,
        source_data_fetched_at=source_data_fetched_at,
        config_snapshot={**asdict(resolved_cfg), "window_definitions": [asdict(item) for item in resolved_cfg.window_definitions]},
        rankings_table=rankings_table,
        latest_window_table=latest_window_table,
        filter_diagnostics_table=diagnostics,
        window_feature_table=window_feature_table,
        warnings=warnings,
    )