from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from smc_core.ids import bos_id, fvg_id, ob_id, sweep_id

RequiredBarColumns = ("symbol", "timestamp", "open", "high", "low", "close")

_TIMEFRAME_CANONICAL: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}

_TIMEFRAME_TO_PANDAS_FREQ: dict[str, str] = {
    "5m": "5min",
    "15m": "15min",
    "1H": "1h",
    "4H": "4h",
    "1D": "1D",
}


@dataclass(frozen=True)
class StructureBuildConfig:
    swing_lookback: int = 6
    ob_search_back: int = 12
    ob_atr_window: int = 14
    ob_atr_mult: float = 1.4
    ob_body_ratio_min: float = 0.55


def _canonical_timeframe(timeframe: str) -> str:
    normalized = str(timeframe).strip()
    if not normalized:
        raise ValueError("timeframe must not be empty")
    key = normalized.lower()
    if key not in _TIMEFRAME_CANONICAL:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return _TIMEFRAME_CANONICAL[key]


def _coerce_bars(df: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in RequiredBarColumns if column not in df.columns]
    if missing:
        raise ValueError(f"missing required bar columns: {missing}")

    out = df.copy()
    out["symbol"] = out["symbol"].astype(str).str.strip().str.upper()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
    for column in ("open", "high", "low", "close"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    if "volume" in out.columns:
        out["volume"] = pd.to_numeric(out["volume"], errors="coerce").fillna(0.0)
    else:
        out["volume"] = 0.0

    out = out.dropna(subset=["symbol", "timestamp", "open", "high", "low", "close"]).copy()
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
        agg = indexed.resample(freq, label="right", closed="right").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
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
    config = StructureBuildConfig()
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if len(bars) <= config.swing_lookback:
        return []

    highs = bars["high"].tolist()
    lows = bars["low"].tolist()
    closes = bars["close"].tolist()
    timestamps = bars["timestamp"].tolist()

    events: list[dict[str, Any]] = []
    trend = 0
    for idx in range(config.swing_lookback, len(bars)):
        prior_high = max(highs[idx - config.swing_lookback:idx])
        prior_low = min(lows[idx - config.swing_lookback:idx])
        close_price = float(closes[idx])
        ts = float(pd.Timestamp(timestamps[idx]).timestamp())

        if close_price > float(prior_high):
            kind: Literal["BOS", "CHOCH"] = "BOS" if trend >= 0 else "CHOCH"
            direction: Literal["UP", "DOWN"] = "UP"
            events.append(
                {
                    "id": bos_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=ts, kind=kind, dir=direction, price=close_price),
                    "time": ts,
                    "price": close_price,
                    "kind": kind,
                    "dir": direction,
                }
            )
            trend = 1
        elif close_price < float(prior_low):
            kind = "BOS" if trend <= 0 else "CHOCH"
            direction = "DOWN"
            events.append(
                {
                    "id": bos_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=ts, kind=kind, dir=direction, price=close_price),
                    "time": ts,
                    "price": close_price,
                    "kind": kind,
                    "dir": direction,
                }
            )
            trend = -1

    return _dedupe_by_id(events)


def build_liquidity_sweeps_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    config = StructureBuildConfig()
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy()
    if len(bars) <= config.swing_lookback:
        return []

    events: list[dict[str, Any]] = []
    highs = bars["high"].tolist()
    lows = bars["low"].tolist()
    closes = bars["close"].tolist()
    timestamps = bars["timestamp"].tolist()

    for idx in range(config.swing_lookback, len(bars)):
        prior_high = max(highs[idx - config.swing_lookback:idx])
        prior_low = min(lows[idx - config.swing_lookback:idx])
        bar_high = float(highs[idx])
        bar_low = float(lows[idx])
        bar_close = float(closes[idx])
        ts = float(pd.Timestamp(timestamps[idx]).timestamp())

        if bar_high > float(prior_high) and bar_close < float(prior_high):
            price = float(prior_high)
            side: Literal["BUY_SIDE", "SELL_SIDE"] = "BUY_SIDE"
            events.append(
                {
                    "id": sweep_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=ts, side=side, price=price),
                    "time": ts,
                    "price": price,
                    "side": side,
                }
            )
        if bar_low < float(prior_low) and bar_close > float(prior_low):
            price = float(prior_low)
            side = "SELL_SIDE"
            events.append(
                {
                    "id": sweep_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=ts, side=side, price=price),
                    "time": ts,
                    "price": price,
                    "side": side,
                }
            )

    return _dedupe_by_id(events)


def build_fvg_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy().reset_index(drop=True)
    if len(bars) < 3:
        return []

    events: list[dict[str, Any]] = []
    for idx in range(1, len(bars) - 1):
        prev_bar = bars.iloc[idx - 1]
        next_bar = bars.iloc[idx + 1]
        anchor_bar = bars.iloc[idx]
        anchor_ts = float(pd.Timestamp(anchor_bar["timestamp"]).timestamp())

        prev_high = float(prev_bar["high"])
        prev_low = float(prev_bar["low"])
        next_high = float(next_bar["high"])
        next_low = float(next_bar["low"])

        if prev_high < next_low:
            low = prev_high
            high = next_low
            direction: Literal["BULL", "BEAR"] = "BULL"
            events.append(
                {
                    "id": fvg_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=anchor_ts, dir=direction, low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": direction,
                    "valid": True,
                }
            )
        if prev_low > next_high:
            low = next_high
            high = prev_low
            direction = "BEAR"
            events.append(
                {
                    "id": fvg_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=anchor_ts, dir=direction, low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": direction,
                    "valid": True,
                }
            )

    return _dedupe_by_id(events)


def build_orderblocks_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    config = StructureBuildConfig()
    canonical_tf = _canonical_timeframe(timeframe)
    bars = resample_bars_to_timeframe(df, canonical_tf)
    bars = bars.loc[bars["symbol"].eq(str(symbol).strip().upper())].copy().reset_index(drop=True)
    if len(bars) < max(config.ob_atr_window + 2, 8):
        return []

    bars["true_range"] = (bars["high"] - bars["low"]).abs()
    bars["atr"] = bars["true_range"].rolling(config.ob_atr_window, min_periods=config.ob_atr_window).mean()
    body = (bars["close"] - bars["open"]).abs()
    bars["body_ratio"] = body / bars["true_range"].replace(0.0, pd.NA)

    events: list[dict[str, Any]] = []
    for idx in range(config.ob_atr_window, len(bars)):
        row = bars.iloc[idx]
        atr = float(row["atr"]) if pd.notna(row["atr"]) else 0.0
        tr = float(row["true_range"]) if pd.notna(row["true_range"]) else 0.0
        body_ratio = float(row["body_ratio"]) if pd.notna(row["body_ratio"]) else 0.0

        if atr <= 0.0:
            continue
        is_displacement = tr > (config.ob_atr_mult * atr) and body_ratio >= config.ob_body_ratio_min
        if not is_displacement:
            continue

        is_bull_impulse = float(row["close"]) > float(row["open"])
        is_bear_impulse = float(row["close"]) < float(row["open"])
        if not (is_bull_impulse or is_bear_impulse):
            continue

        search_start = max(0, idx - config.ob_search_back)
        prior = bars.iloc[search_start:idx].copy()
        if prior.empty:
            continue

        if is_bull_impulse:
            candidates = prior.loc[prior["close"] < prior["open"]]
            direction: Literal["BULL", "BEAR"] = "BULL"
        else:
            candidates = prior.loc[prior["close"] > prior["open"]]
            direction = "BEAR"

        if candidates.empty:
            continue
        candle = candidates.iloc[-1]
        low = float(candle["low"])
        high = float(candle["high"])
        anchor_ts = float(pd.Timestamp(candle["timestamp"]).timestamp())

        events.append(
            {
                "id": ob_id(symbol=str(symbol), timeframe=canonical_tf, anchor_ts=anchor_ts, dir=direction, low=low, high=high),
                "low": low,
                "high": high,
                "dir": direction,
                "valid": True,
            }
        )

    return _dedupe_by_id(events)


def build_full_structure_from_bars(df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    canonical_tf = _canonical_timeframe(timeframe)
    bars = _coerce_bars(df)
    symbol_name = str(symbol).strip().upper()
    symbol_bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
    if symbol_bars.empty:
        raise ValueError(f"symbol {symbol_name} has no bars in source frame")

    return {
        "bos": build_bos_events_from_bars(symbol_bars, symbol=symbol_name, timeframe=canonical_tf),
        "orderblocks": build_orderblocks_from_bars(symbol_bars, symbol=symbol_name, timeframe=canonical_tf),
        "fvg": build_fvg_from_bars(symbol_bars, symbol=symbol_name, timeframe=canonical_tf),
        "liquidity_sweeps": build_liquidity_sweeps_from_bars(symbol_bars, symbol=symbol_name, timeframe=canonical_tf),
    }
