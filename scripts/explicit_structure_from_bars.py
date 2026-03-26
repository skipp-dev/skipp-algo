from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.explicit_structure_profiles import build_structure_profile
from scripts.smc_price_action_engine import (
    canonical_timeframe,
    normalize_bars,
)

RequiredBarColumns = ("symbol", "timestamp", "open", "high", "low", "close")

_TIMEFRAME_TO_PANDAS_FREQ: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "1H": "1h",
    "4H": "4h",
    "1D": "1D",
}


def _canonical_timeframe(timeframe: str) -> str:
    return canonical_timeframe(timeframe)


def _coerce_bars(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in RequiredBarColumns if column not in df.columns]
    if missing:
        raise ValueError(f"missing required bar columns: {missing}")

    out = df.copy()
    if "volume" not in out.columns:
        out["volume"] = 0.0
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out = normalize_bars(out)
    out["timestamp"] = pd.to_datetime(out["timestamp"], unit="s", utc=True)
    out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    if out.empty:
        raise ValueError("bar frame has no usable rows after coercion")
    return out.sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def resample_bars_to_timeframe(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    canonical_tf = _canonical_timeframe(timeframe)
    freq = _TIMEFRAME_TO_PANDAS_FREQ[canonical_tf]
    bars = _coerce_bars(df)

    parts: list[pd.DataFrame] = []
    for symbol, group in bars.groupby("symbol", sort=False):
        indexed = group.set_index("timestamp").sort_index()
        max_source_ts = indexed.index.max()
        agg = indexed.resample(freq, label="right", closed="right").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        if not agg.empty and pd.notna(max_source_ts):
            # Prevent a partial trailing bucket from being treated as a confirmed bar.
            if pd.Timestamp(agg.index[-1]) > pd.Timestamp(max_source_ts):
                agg = agg.iloc[:-1]
        agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index()
        if agg.empty:
            continue
        agg.insert(0, "symbol", symbol)
        parts.append(agg)

    if not parts:
        return pd.DataFrame(columns=["symbol", "timestamp", "open", "high", "low", "close", "volume"])

    return pd.concat(parts, ignore_index=True).sort_values(["symbol", "timestamp"]).reset_index(drop=True)


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        row_id = str(row.get("id", "")).strip()
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        out.append(row)
    return out


def _prepare_symbol_resampled_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> tuple[pd.DataFrame, str]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        return bars, canonical_tf
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).astype("int64") // 10**9
    return bars, canonical_tf


def build_bos_events_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(bars, symbol=str(symbol), timeframe=canonical_tf, profile="hybrid_default", pivot_lookup=1)
    return _dedupe_by_id(payload.bos)


def build_liquidity_sweeps_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(bars, symbol=str(symbol), timeframe=canonical_tf, profile="hybrid_default", pivot_lookup=1)
    return _dedupe_by_id(payload.liquidity_sweeps)


def build_fvg_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(bars, symbol=str(symbol), timeframe=canonical_tf, profile="hybrid_default", pivot_lookup=1)
    return _dedupe_by_id(payload.fvg)


def build_orderblocks_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(bars, symbol=str(symbol), timeframe=canonical_tf, profile="hybrid_default", pivot_lookup=1)
    return _dedupe_by_id(payload.orderblocks)


def build_explicit_structure_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivot_lookup: int = 1,
    structure_profile: str = "hybrid_default",
) -> dict:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = _coerce_bars(df)
    symbol_name = str(symbol).strip().upper()
    symbol_bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
    if symbol_bars.empty:
        raise ValueError(f"symbol {symbol_name} has no bars in source frame")

    resampled = resample_bars_to_timeframe(symbol_bars, canonical_tf)
    resampled["timestamp"] = pd.to_datetime(resampled["timestamp"], utc=True).astype("int64") // 10**9

    profile_result = build_structure_profile(
        resampled,
        symbol=symbol_name,
        timeframe=canonical_tf,
        profile=structure_profile,
        pivot_lookup=pivot_lookup,
    )

    return {
        "bos": _dedupe_by_id(profile_result.bos),
        "orderblocks": _dedupe_by_id(profile_result.orderblocks),
        "fvg": _dedupe_by_id(profile_result.fvg),
        "liquidity_sweeps": _dedupe_by_id(profile_result.liquidity_sweeps),
        "auxiliary": profile_result.auxiliary,
        "diagnostics": profile_result.diagnostics,
        "producer_debug": {
            "liquidity_levels_count": int(profile_result.diagnostics.get("liquidity_levels_count", 0)),
            "structure_profile": str(structure_profile),
        },
    }


def build_full_structure_from_bars(df: pd.DataFrame, symbol: str, timeframe: str, structure_profile: str = "hybrid_default") -> dict:
    payload = build_explicit_structure_from_bars(
        df,
        symbol=symbol,
        timeframe=timeframe,
        pivot_lookup=1,
        structure_profile=structure_profile,
    )
    return {
        "bos": payload["bos"],
        "orderblocks": payload["orderblocks"],
        "fvg": payload["fvg"],
        "liquidity_sweeps": payload["liquidity_sweeps"],
    }
