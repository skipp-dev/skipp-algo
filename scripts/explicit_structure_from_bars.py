from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.smc_liquidity_engine import detect_liquidity_levels, detect_liquidity_sweeps
from scripts.smc_price_action_engine import (
    canonical_timeframe,
    detect_bos_from_pivots,
    detect_fvg_three_candle,
    detect_orderblocks_two_candle,
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


def build_bos_events_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        return []
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).astype("int64") // 10**9
    events = detect_bos_from_pivots(
        bars,
        symbol=str(symbol),
        timeframe=canonical_tf,
        pivot_lookup=1,
        use_high_low_for_bullish=False,
        use_high_low_for_bearish=False,
    )
    return _dedupe_by_id(events)


def build_liquidity_sweeps_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        return []
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).astype("int64") // 10**9
    levels = detect_liquidity_levels(bars, symbol=str(symbol), timeframe=canonical_tf, pivot_lookup=1)
    sweeps = detect_liquidity_sweeps(bars, levels, symbol=str(symbol), timeframe=canonical_tf)
    if not sweeps:
        # Backward-compatible fallback: treat prior candle highs/lows as candidate liquidity.
        legacy_levels: list[dict[str, Any]] = []
        for i in range(len(bars) - 1):
            row = bars.iloc[i]
            ts = int(row["timestamp"])
            high = float(row["high"])
            low = float(row["low"])
            sym = str(symbol).strip().upper()
            legacy_levels.append(
                {
                    "id": f"liq:{sym}:{canonical_tf}:{ts}:BUY_SIDE:{high:.2f}",
                    "time": ts,
                    "price": high,
                    "side": "BUY_SIDE",
                }
            )
            legacy_levels.append(
                {
                    "id": f"liq:{sym}:{canonical_tf}:{ts}:SELL_SIDE:{low:.2f}",
                    "time": ts,
                    "price": low,
                    "side": "SELL_SIDE",
                }
            )
        sweeps = detect_liquidity_sweeps(bars, legacy_levels, symbol=str(symbol), timeframe=canonical_tf)
    return _dedupe_by_id(sweeps)


def build_fvg_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        return []
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).astype("int64") // 10**9
    events = detect_fvg_three_candle(bars, symbol=str(symbol), timeframe=canonical_tf)
    return _dedupe_by_id(events)


def build_orderblocks_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if bars.empty:
        return []
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True).astype("int64") // 10**9
    events = detect_orderblocks_two_candle(bars, symbol=str(symbol), timeframe=canonical_tf)
    return _dedupe_by_id(events)


def build_explicit_structure_from_bars(df: pd.DataFrame, symbol: str, timeframe: str, pivot_lookup: int = 1) -> dict:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = _coerce_bars(df)
    symbol_name = str(symbol).strip().upper()
    symbol_bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
    if symbol_bars.empty:
        raise ValueError(f"symbol {symbol_name} has no bars in source frame")

    resampled = resample_bars_to_timeframe(symbol_bars, canonical_tf)
    resampled["timestamp"] = pd.to_datetime(resampled["timestamp"], utc=True).astype("int64") // 10**9

    orderblocks = detect_orderblocks_two_candle(resampled, symbol=symbol_name, timeframe=canonical_tf)
    fvg = detect_fvg_three_candle(resampled, symbol=symbol_name, timeframe=canonical_tf)
    bos = detect_bos_from_pivots(
        resampled,
        symbol=symbol_name,
        timeframe=canonical_tf,
        pivot_lookup=pivot_lookup,
        use_high_low_for_bullish=False,
        use_high_low_for_bearish=False,
    )

    liquidity_levels = detect_liquidity_levels(resampled, symbol=symbol_name, timeframe=canonical_tf, pivot_lookup=pivot_lookup)
    liquidity_sweeps = detect_liquidity_sweeps(resampled, liquidity_levels, symbol=symbol_name, timeframe=canonical_tf)

    return {
        "bos": _dedupe_by_id(bos),
        "orderblocks": _dedupe_by_id(orderblocks),
        "fvg": _dedupe_by_id(fvg),
        "liquidity_sweeps": _dedupe_by_id(liquidity_sweeps),
        "producer_debug": {
            "liquidity_levels_count": len(liquidity_levels),
        },
    }


def build_full_structure_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    payload = build_explicit_structure_from_bars(df, symbol=symbol, timeframe=timeframe, pivot_lookup=1)
    return {
        "bos": payload["bos"],
        "orderblocks": payload["orderblocks"],
        "fvg": payload["fvg"],
        "liquidity_sweeps": payload["liquidity_sweeps"],
    }
