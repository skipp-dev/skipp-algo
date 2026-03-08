from __future__ import annotations

import math
import os
import sys
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import (
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
    rank_top_fraction_per_day,
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
    "sector",
    "industry",
    "market_cap",
    "rank_within_trade_date",
    "eligible_count_for_trade_date",
    "take_n_for_trade_date",
    "selected_top20pct",
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

    try:
        rows = FMPClient(fmp_api_key).get_profile_bulk()
    except Exception:
        rows = []
    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "company_name_profile",
                "exchange_profile",
                "sector_profile",
                "industry_profile",
                "market_cap_profile",
                "asset_type_profile",
                "has_fundamental_row",
            ]
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "company_name_profile",
                "exchange_profile",
                "sector_profile",
                "industry_profile",
                "market_cap_profile",
                "asset_type_profile",
                "has_fundamental_row",
            ]
        )

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
    if use_file_cache and not out.empty:
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
        dollar_volume = float((close.fillna(0.0) * volume).sum())
        total_volume = float(volume.sum())
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
                "premarket_trade_count": float(pd.to_numeric(ordered["trade_count"], errors="coerce").sum()) if trade_count_available else np.nan,
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
    lookback_days: int = 30,
    top_fraction: float = 0.20,
    ranking_metric: str = "window_range_pct",
    display_timezone: str = "Europe/Berlin",
    window_start: time | None = None,
    window_end: time | None = None,
    premarket_anchor_et: time = time(8, 0),
    min_market_cap: float = 0.0,
    cache_dir: Path | None = None,
    export_dir: Path | None = None,
    use_file_cache: bool = True,
    force_refresh: bool = False,
) -> dict[str, Any]:
    if not databento_api_key:
        raise ValueError("Databento API key is required.")
    if not 0 < top_fraction <= 1:
        raise ValueError("top_fraction must be between 0 and 1")

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
    summary = build_summary_table(ranked, raw_universe)
    if summary.empty:
        raise RuntimeError("No ranked results were returned for the production export run")

    full_universe_second_detail_raw = collect_full_universe_open_window_second_detail(
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
    second_detail_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")
    premarket_features_full_universe = _build_premarket_features_full_universe_export(
        full_universe_second_detail_open,
        daily_symbol_features_full_universe,
    )
    premarket_fetched_at = datetime.now(UTC).isoformat(timespec="seconds")

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
        "selected_symbol_detail_scope": "selected_top_ranked_symbol_day_only",
        "internal_timezone": display_timezone,
        "session_documentation": "full_universe_second_detail_open spans from the premarket anchor (08:00:00 ET) through 15:35:59 Europe/Berlin; session is labeled as premarket before 09:30 ET and regular from 09:30 ET onward",
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
        "premarket_price_anchor_rule": "last_ohlcv_1s_close in [08:00:00 ET, regular_open) for the trade date",
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
        },
        additional_parquet_targets={
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "premarket_features_full_universe": premarket_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
        },
        cost_estimate=cost_estimate,
        unsupported_symbols=unsupported,
        manifest=manifest,
    )

    exact_named_paths = _write_exact_named_exports(
        resolved_export_dir,
        {
            "daily_symbol_features_full_universe": daily_symbol_features_full_universe,
            "full_universe_second_detail_open": full_universe_second_detail_open,
            "premarket_features_full_universe": premarket_features_full_universe,
            "symbol_day_diagnostics": symbol_day_diagnostics,
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
    dataset = choose_default_dataset(available, requested_dataset=os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"))
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
        premarket_anchor_et=time(8, 0),
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