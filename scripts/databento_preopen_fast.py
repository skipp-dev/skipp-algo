from __future__ import annotations

import argparse
import json
import os
import sys
import warnings
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from databento_volatility_screener import (
    US_EASTERN_TZ,
    _exclusive_ohlcv_1s_end,
    _extract_unresolved_symbols_from_warning_messages,
    _iter_symbol_batches,
    _make_databento_client,
    _safe_float,
    _store_to_frame,
    normalize_symbol_for_databento,
)
from scripts.databento_production_export import (
    DAILY_SYMBOL_FEATURE_COLUMNS,
    PREMARKET_FEATURE_COLUMNS,
    SYMBOL_DAY_DIAGNOSTIC_COLUMNS,
)
from scripts.load_databento_export_bundle import load_export_bundle


DEFAULT_EXPORT_DIR = Path.home() / "Downloads"
DEFAULT_FAST_SCOPE_MIN_DAYS = 5
DEFAULT_FAST_SCOPE_MAX_DAYS = 15
FAST_SCOPE_CALIBRATION_DAYS = (5, 7, 10, 12, 15)


def _normalize_trade_date(frame: pd.DataFrame) -> pd.DataFrame:
    normalized = frame.copy()
    normalized["trade_date"] = pd.to_datetime(normalized["trade_date"], errors="coerce").dt.date
    if "symbol" in normalized.columns:
        normalized["symbol"] = normalized["symbol"].astype(str).map(normalize_symbol_for_databento)
    return normalized


def _resolve_full_history_bundle_input(bundle: str | Path | None, export_dir: Path) -> str | Path:
    candidate = Path(bundle).expanduser() if bundle is not None else export_dir
    if candidate.is_file():
        return candidate
    if candidate.is_dir():
        manifests = sorted(
            candidate.glob("databento_volatility_production_*_manifest.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        if manifests:
            return manifests[0]
    return candidate


def _resolve_target_trade_date(completed_trade_days: list[date], *, now_utc: datetime | None = None) -> date:
    if not completed_trade_days:
        raise ValueError("completed_trade_days must not be empty")
    now_et = (now_utc or datetime.now(UTC)).astimezone(US_EASTERN_TZ)
    latest_completed = max(completed_trade_days)
    return now_et.date() if now_et.date() > latest_completed else latest_completed


def _target_scope_symbol_count(*, now_utc: datetime | None = None) -> int:
    now_et = (now_utc or datetime.now(UTC)).astimezone(US_EASTERN_TZ)
    current_time = now_et.time()
    if current_time < time(8, 30):
        return 3200
    if current_time < time(9, 0):
        return 2800
    if current_time < time(9, 20):
        return 2400
    return 2100


def _recent_scope_symbol_counts(daily_features: pd.DataFrame) -> dict[int, int]:
    normalized = _normalize_trade_date(daily_features)
    normalized = normalized[normalized["symbol"].astype(str).ne("")].copy()
    selected = normalized[normalized["selected_top20pct"] == True].copy()
    if selected.empty:
        return {int(days): 0 for days in FAST_SCOPE_CALIBRATION_DAYS}
    completed_days = sorted(selected["trade_date"].dropna().unique().tolist())
    counts: dict[int, int] = {}
    for days in FAST_SCOPE_CALIBRATION_DAYS:
        if not completed_days:
            counts[int(days)] = 0
            continue
        scope_trade_days = set(completed_days[-min(int(days), len(completed_days)):])
        counts[int(days)] = int(selected[selected["trade_date"].isin(scope_trade_days)]["symbol"].nunique())
    return counts


def _choose_scope_days(
    daily_features: pd.DataFrame,
    *,
    min_scope_days: int = DEFAULT_FAST_SCOPE_MIN_DAYS,
    max_scope_days: int = DEFAULT_FAST_SCOPE_MAX_DAYS,
    target_symbol_count: int | None = None,
    now_utc: datetime | None = None,
) -> tuple[int, int]:
    if min_scope_days <= 0:
        raise ValueError(f"min_scope_days must be > 0, got {min_scope_days}")
    if max_scope_days < min_scope_days:
        raise ValueError(f"max_scope_days must be >= min_scope_days, got {max_scope_days} < {min_scope_days}")

    normalized = _normalize_trade_date(daily_features)
    normalized = normalized[normalized["symbol"].astype(str).ne("")].copy()
    selected = normalized[normalized["selected_top20pct"] == True].copy()
    if selected.empty:
        return min_scope_days, 0

    completed_days = sorted(selected["trade_date"].dropna().unique().tolist())
    if not completed_days:
        return min_scope_days, 0

    desired_symbol_count = target_symbol_count if target_symbol_count is not None else _target_scope_symbol_count(now_utc=now_utc)
    chosen_days = min(min_scope_days, len(completed_days))
    chosen_symbols = 0
    for candidate_days in range(min_scope_days, min(max_scope_days, len(completed_days)) + 1):
        scope_trade_days = set(completed_days[-candidate_days:])
        symbol_count = int(selected[selected["trade_date"].isin(scope_trade_days)]["symbol"].nunique())
        chosen_days = candidate_days
        chosen_symbols = symbol_count
        if symbol_count >= desired_symbol_count:
            break
    return chosen_days, chosen_symbols


def _select_recent_scope_symbols(daily_features: pd.DataFrame, *, scope_days: int) -> pd.DataFrame:
    if scope_days <= 0:
        raise ValueError(f"scope_days must be > 0, got {scope_days}")
    normalized = _normalize_trade_date(daily_features)
    normalized = normalized[normalized["symbol"].astype(str).ne("")].copy()
    if normalized.empty:
        return normalized.iloc[0:0].copy()

    selected = normalized[normalized["selected_top20pct"] == True].copy()
    if selected.empty:
        return normalized.iloc[0:0].copy()

    completed_days = sorted(selected["trade_date"].dropna().unique().tolist())
    scope_trade_days = set(completed_days[-scope_days:])
    scope_symbols = set(selected.loc[selected["trade_date"].isin(scope_trade_days), "symbol"].tolist())
    if not scope_symbols:
        return normalized.iloc[0:0].copy()

    latest_rows = (
        normalized[normalized["symbol"].isin(scope_symbols)]
        .sort_values(["symbol", "trade_date"])
        .groupby("symbol", as_index=False)
        .tail(1)
        .reset_index(drop=True)
    )
    latest_rows["selected_top20pct"] = True
    latest_rows["is_eligible"] = True
    latest_rows["eligibility_reason"] = "historical_selected_top20pct_scope"
    return latest_rows


def _build_current_daily_features(
    scope_rows: pd.DataFrame,
    daily_bars: pd.DataFrame,
    *,
    target_trade_date: date,
) -> pd.DataFrame:
    if scope_rows.empty:
        return pd.DataFrame(columns=DAILY_SYMBOL_FEATURE_COLUMNS)

    daily_bars_norm = _normalize_trade_date(daily_bars)
    latest_completed_trade_date = max(daily_bars_norm["trade_date"].dropna().tolist())
    latest_closes = (
        daily_bars_norm[daily_bars_norm["trade_date"] == latest_completed_trade_date][["symbol", "close"]]
        .rename(columns={"close": "previous_close"})
        .drop_duplicates(subset=["symbol"])
    )

    current = scope_rows.copy()
    current["trade_date"] = target_trade_date
    current = current.drop(columns=[column for column in ["previous_close"] if column in current.columns])
    current = current.merge(latest_closes, on="symbol", how="left")
    current["has_daily_bars"] = current["previous_close"].notna()
    current["has_intraday"] = False
    current["selected_top20pct"] = True
    current["is_eligible"] = current["previous_close"].notna()
    current["eligibility_reason"] = np.where(
        current["previous_close"].notna(),
        "historical_selected_top20pct_scope",
        "missing_latest_close",
    )

    for column in DAILY_SYMBOL_FEATURE_COLUMNS:
        if column not in current.columns:
            if column in {"trade_date", "symbol", "exchange", "asset_type", "eligibility_reason"}:
                current[column] = ""
            elif column in {
                "is_eligible",
                "selected_top20pct",
                "has_reference_data",
                "has_fundamentals",
                "has_daily_bars",
                "has_intraday",
                "has_market_cap",
            }:
                current[column] = False
            else:
                current[column] = np.nan

    current["symbol"] = current["symbol"].astype(str).map(normalize_symbol_for_databento)
    current = current[current["symbol"].astype(str).ne("")].copy()
    current = current.sort_values(["trade_date", "symbol"]).reset_index(drop=True)
    return current[DAILY_SYMBOL_FEATURE_COLUMNS]


def _aggregate_current_premarket_features(
    frame: pd.DataFrame,
    previous_close_by_symbol: dict[str, float | None],
    *,
    target_trade_date: date,
) -> pd.DataFrame:
    expected = pd.DataFrame(
        {
            "trade_date": [target_trade_date for _ in previous_close_by_symbol],
            "symbol": list(previous_close_by_symbol.keys()),
            "previous_close": [previous_close_by_symbol[symbol] for symbol in previous_close_by_symbol],
        }
    )
    if frame.empty:
        out = expected.copy()
        out["has_premarket_data"] = False
        for column in PREMARKET_FEATURE_COLUMNS:
            if column not in out.columns:
                out[column] = np.nan if column not in {"trade_date", "symbol", "has_premarket_data"} else out.get(column)
        out["has_premarket_data"] = False
        return out[PREMARKET_FEATURE_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)

    detail = frame.copy()
    detail["symbol"] = detail["symbol"].astype(str).map(normalize_symbol_for_databento)
    detail = detail[detail["symbol"].astype(str).isin(expected["symbol"])].copy()
    if detail.empty:
        return _aggregate_current_premarket_features(pd.DataFrame(), previous_close_by_symbol, target_trade_date=target_trade_date)

    detail["ts"] = pd.to_datetime(detail["ts"], errors="coerce", utc=True)
    detail = detail.dropna(subset=["ts", "symbol"]).sort_values(["symbol", "ts"]).reset_index(drop=True)
    trade_count_source = None
    for column in ["trade_count", "count", "n_trades", "num_trades"]:
        if column in detail.columns:
            trade_count_source = column
            break

    metrics: list[dict[str, object]] = []
    for symbol, group in detail.groupby("symbol", sort=False):
        ordered = group.sort_values("ts")
        volume = pd.to_numeric(ordered["volume"], errors="coerce").fillna(0.0)
        close = pd.to_numeric(ordered["close"], errors="coerce")
        total_volume = float(volume.sum())
        dollar_volume = float((close.fillna(0.0) * volume).sum())
        metrics.append(
            {
                "trade_date": target_trade_date,
                "symbol": symbol,
                "premarket_open": pd.to_numeric(ordered["open"], errors="coerce").iloc[0],
                "premarket_high": pd.to_numeric(ordered["high"], errors="coerce").max(),
                "premarket_low": pd.to_numeric(ordered["low"], errors="coerce").min(),
                "premarket_last": close.iloc[-1],
                "premarket_vwap": (dollar_volume / total_volume) if total_volume > 0 else np.nan,
                "premarket_volume": total_volume,
                "premarket_dollar_volume": dollar_volume,
                "premarket_trade_count": float(pd.to_numeric(ordered[trade_count_source], errors="coerce").sum()) if trade_count_source else np.nan,
                "premarket_seconds": int(len(ordered)),
            }
        )

    out = expected.merge(pd.DataFrame(metrics), on=["trade_date", "symbol"], how="left")
    out["has_premarket_data"] = out["premarket_seconds"].fillna(0).astype(int) > 0
    out["premarket_to_open_pct"] = np.nan
    out["prev_close_to_premarket_pct"] = np.where(
        pd.to_numeric(out["previous_close"], errors="coerce") > 0,
        ((pd.to_numeric(out["premarket_last"], errors="coerce") / pd.to_numeric(out["previous_close"], errors="coerce")) - 1.0) * 100.0,
        np.nan,
    )
    for column in PREMARKET_FEATURE_COLUMNS:
        if column not in out.columns:
            out[column] = np.nan if column not in {"trade_date", "symbol", "has_premarket_data"} else out.get(column)
    return out[PREMARKET_FEATURE_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _build_current_diagnostics(daily_current: pd.DataFrame) -> pd.DataFrame:
    if daily_current.empty:
        return pd.DataFrame(columns=SYMBOL_DAY_DIAGNOSTIC_COLUMNS)

    diagnostics = pd.DataFrame(
        {
            "trade_date": daily_current["trade_date"],
            "symbol": daily_current["symbol"],
            "present_in_raw_universe": True,
            "present_after_reference_join": True,
            "present_after_fundamentals_join": daily_current["has_fundamentals"].fillna(False).astype(bool),
            "present_after_daily_filter": daily_current["has_daily_bars"].fillna(False).astype(bool),
            "present_after_intraday_filter": False,
            "present_in_eligible": daily_current["is_eligible"].fillna(False).astype(bool),
            "selected_top20pct": True,
            "excluded_step": "preopen_fast_scope",
            "excluded_reason": "historical_selected_top20pct_scope",
            "exchange": daily_current["exchange"],
            "asset_type": daily_current["asset_type"],
            "has_reference_data": daily_current["has_reference_data"].fillna(False).astype(bool),
            "has_fundamentals": daily_current["has_fundamentals"].fillna(False).astype(bool),
            "has_daily_bars": daily_current["has_daily_bars"].fillna(False).astype(bool),
            "has_intraday": False,
            "has_market_cap": daily_current["has_market_cap"].fillna(False).astype(bool),
            "is_supported_by_databento": True,
        }
    )
    return diagnostics[SYMBOL_DAY_DIAGNOSTIC_COLUMNS].sort_values(["trade_date", "symbol"]).reset_index(drop=True)


def _write_fast_outputs(
    export_dir: Path,
    *,
    daily_current: pd.DataFrame,
    premarket_current: pd.DataFrame,
    diagnostics_current: pd.DataFrame,
    manifest: dict[str, Any],
) -> dict[str, Path]:
    export_dir.mkdir(parents=True, exist_ok=True)
    basename = manifest["basename"]
    manifest_path = export_dir / f"{basename}_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=True, default=str), encoding="utf-8")

    outputs = {
        "manifest": manifest_path,
        "daily": export_dir / "daily_symbol_features_full_universe.parquet",
        "premarket": export_dir / "premarket_features_full_universe.parquet",
        "diagnostics": export_dir / "symbol_day_diagnostics.parquet",
    }
    daily_current.to_parquet(outputs["daily"], index=False)
    premarket_current.to_parquet(outputs["premarket"], index=False)
    diagnostics_current.to_parquet(outputs["diagnostics"], index=False)
    return outputs


def run_preopen_fast_refresh(
    *,
    databento_api_key: str,
    dataset: str,
    export_dir: str | Path | None = None,
    bundle: str | Path | None = None,
    scope_days: int | None = None,
) -> dict[str, Any]:
    resolved_export_dir = Path(export_dir).expanduser() if export_dir is not None else DEFAULT_EXPORT_DIR
    bundle_input = _resolve_full_history_bundle_input(bundle, resolved_export_dir)
    payload = load_export_bundle(bundle_input)
    frames = payload["frames"]

    daily_features = _normalize_trade_date(frames["daily_symbol_features_full_universe"])
    scope_calibration = _recent_scope_symbol_counts(daily_features)
    daily_bars = _normalize_trade_date(frames["daily_bars"])
    completed_trade_days = sorted(daily_bars["trade_date"].dropna().unique().tolist())
    if not completed_trade_days:
        raise ValueError("No completed trade days found in baseline bundle")

    target_trade_date = _resolve_target_trade_date(completed_trade_days)
    if scope_days is None or int(scope_days) <= 0:
        resolved_scope_days, resolved_scope_symbol_count = _choose_scope_days(daily_features)
    else:
        resolved_scope_days = int(scope_days)
        resolved_scope_symbol_count = 0
    scope_rows = _select_recent_scope_symbols(daily_features, scope_days=resolved_scope_days)
    if scope_rows.empty:
        raise ValueError("No reduced scope symbols found from selected_top20pct history")

    daily_current = _build_current_daily_features(scope_rows, daily_bars, target_trade_date=target_trade_date)
    symbols = sorted(daily_current["symbol"].dropna().astype(str).unique().tolist())
    if resolved_scope_symbol_count <= 0:
        resolved_scope_symbol_count = int(len(symbols))
    previous_close_by_symbol = {
        row.symbol: _safe_float(row.previous_close)
        for row in daily_current[["symbol", "previous_close"]].drop_duplicates(subset=["symbol"]).itertuples(index=False)
    }

    premarket_start_utc = datetime.combine(target_trade_date, time(8, 0), tzinfo=US_EASTERN_TZ).astimezone(UTC)
    regular_open_utc = datetime.combine(target_trade_date, time(9, 30), tzinfo=US_EASTERN_TZ).astimezone(UTC)
    fetch_end_utc = min(datetime.now(UTC), regular_open_utc - pd.Timedelta(seconds=1).to_pytimedelta())

    client = _make_databento_client(databento_api_key)
    batch_frames: list[pd.DataFrame] = []
    unresolved_symbols: set[str] = set()
    if fetch_end_utc >= premarket_start_utc:
        for symbols_batch in _iter_symbol_batches(symbols):
            try:
                with warnings.catch_warnings(record=True) as caught_warnings:
                    warnings.simplefilter("always")
                    store = client.timeseries.get_range(
                        dataset=dataset,
                        symbols=symbols_batch,
                        schema="ohlcv-1s",
                        start=premarket_start_utc.isoformat(),
                        end=_exclusive_ohlcv_1s_end(fetch_end_utc).isoformat(),
                    )
                frame = _store_to_frame(store, context="run_preopen_fast_refresh")
                unresolved_symbols.update(
                    _extract_unresolved_symbols_from_warning_messages([str(item.message) for item in caught_warnings])
                )
            except Exception:
                continue
            if frame.empty:
                continue
            batch_frames.append(frame)

    premarket_raw = pd.concat(batch_frames, ignore_index=True) if batch_frames else pd.DataFrame()
    premarket_current = _aggregate_current_premarket_features(
        premarket_raw,
        previous_close_by_symbol,
        target_trade_date=target_trade_date,
    )
    diagnostics_current = _build_current_diagnostics(daily_current)

    exported_at = datetime.now(UTC).isoformat(timespec="seconds")
    basename = f"databento_preopen_fast_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    manifest = {
        "basename": basename,
        "export_generated_at": exported_at,
        "exported_at": exported_at,
        "premarket_fetched_at": exported_at,
        "dataset": dataset,
        "mode": "preopen_fast_reduced_scope",
        "scope_days": int(resolved_scope_days),
        "scope_days_mode": "auto" if scope_days is None or int(scope_days) <= 0 else "manual",
        "scope_symbol_count": int(len(symbols)),
        "scope_symbol_count_target": int(_target_scope_symbol_count()),
        "scope_symbol_count_resolved": int(resolved_scope_symbol_count),
        "scope_symbol_count_calibration": scope_calibration,
        "target_trade_date": target_trade_date.isoformat(),
        "trade_dates_covered": [target_trade_date.isoformat()],
        "baseline_manifest_path": str(payload["manifest_path"]),
        "baseline_bundle_prefix": payload["base_prefix"],
        "unresolved_symbols": sorted(unresolved_symbols),
    }
    outputs = _write_fast_outputs(
        resolved_export_dir,
        daily_current=daily_current,
        premarket_current=premarket_current,
        diagnostics_current=diagnostics_current,
        manifest=manifest,
    )

    return {
        "manifest": manifest,
        "paths": outputs,
        "daily_current": daily_current,
        "premarket_current": premarket_current,
        "diagnostics_current": diagnostics_current,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a reduced-scope pre-open refresh from the latest full-history Databento bundle.")
    parser.add_argument("--dataset", default=os.getenv("DATABENTO_DATASET", "DBEQ.BASIC"))
    parser.add_argument("--export-dir", default=str(DEFAULT_EXPORT_DIR))
    parser.add_argument("--bundle", default=None, help="Optional bundle directory or manifest path for the baseline full-history export.")
    parser.add_argument("--scope-days", type=int, default=0, help="Use symbols selected_top20pct in the last N completed trade days. Use 0 for adaptive auto mode.")
    return parser


def main() -> int:
    load_dotenv()
    args = _build_parser().parse_args()
    databento_api_key = os.getenv("DATABENTO_API_KEY")
    if not databento_api_key:
        print(json.dumps({"error": "DATABENTO_API_KEY missing"}, indent=2, ensure_ascii=True))
        return 2

    result = run_preopen_fast_refresh(
        databento_api_key=databento_api_key,
        dataset=args.dataset,
        export_dir=args.export_dir,
        bundle=args.bundle,
        scope_days=None if int(args.scope_days) <= 0 else int(args.scope_days),
    )
    print(
        json.dumps(
            {
                "manifest": result["manifest"],
                "paths": {key: str(value) for key, value in result["paths"].items()},
                "daily_rows": int(len(result["daily_current"])),
                "premarket_rows": int(len(result["premarket_current"])),
            },
            indent=2,
            ensure_ascii=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())