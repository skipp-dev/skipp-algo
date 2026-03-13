from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from scripts.bullish_quality_config import (
    BullishQualityConfig,
    BullishQualityScannerResult,
    build_default_bullish_quality_config,
)


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


def load_bullish_quality_inputs(export_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    return (
        _read_exact_named_frame(export_dir, "premarket_window_features_full_universe"),
        _read_exact_named_frame(export_dir, "daily_symbol_features_full_universe"),
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
    ranked = ranked.sort_values(
        ["trade_date", "window_tag", "window_quality_score", "window_dollar_volume", "symbol"],
        ascending=[True, True, False, False, True],
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


def _latest_window_table(ranked: pd.DataFrame, cfg: BullishQualityConfig) -> pd.DataFrame:
    if ranked.empty:
        return ranked.copy()
    latest_trade_date = ranked["trade_date"].dropna().max()
    preferred_tag = cfg.window_definitions[-1].tag if cfg.window_definitions else None
    latest = ranked.loc[ranked["trade_date"] == latest_trade_date].copy()
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
    window_features, daily_features = load_bullish_quality_inputs(export_dir)
    window_features = _normalize_trade_date(window_features)
    if window_features.empty:
        warnings.append("No premarket window feature rows were available.")
        empty = _empty_window_feature_table()
        return BullishQualityScannerResult(
            generated_at=datetime.now(UTC).isoformat(timespec="seconds"),
            trade_date=None,
            source_data_fetched_at=None,
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
    source_data_fetched_at = _resolve_source_data_fetched_at(window_features)
    diagnostics = _build_filter_diagnostics(window_features, ranked)
    latest_window = _latest_window_table(ranked, resolved_cfg)

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
        trade_date=latest_trade_date,
        source_data_fetched_at=source_data_fetched_at,
        config_snapshot={**asdict(resolved_cfg), "window_definitions": [asdict(item) for item in resolved_cfg.window_definitions]},
        rankings_table=rankings_table,
        latest_window_table=latest_window_table,
        filter_diagnostics_table=diagnostics,
        window_feature_table=window_feature_table,
        warnings=warnings,
    )