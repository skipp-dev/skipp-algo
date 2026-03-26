from __future__ import annotations

from typing import Any, Literal, cast

import pandas as pd

from smc_core.ids import bos_id, fvg_id, ob_id

_TIMEFRAME_CANONICAL: dict[str, str] = {
    "5m": "5m",
    "15m": "15m",
    "1h": "1H",
    "4h": "4H",
    "1d": "1D",
}


REQUIRED_BAR_COLUMNS = ["timestamp", "open", "high", "low", "close", "volume"]


def canonical_timeframe(timeframe: str) -> str:
    key = str(timeframe).strip().lower()
    if key not in _TIMEFRAME_CANONICAL:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    return _TIMEFRAME_CANONICAL[key]


def normalize_bars(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()

    missing = sorted(set(REQUIRED_BAR_COLUMNS).difference(out.columns))
    if missing:
        raise ValueError(f"Missing required bar columns: {missing}")

    if not pd.api.types.is_numeric_dtype(out["timestamp"]):
        out["timestamp"] = pd.to_datetime(out["timestamp"], utc=True, errors="coerce")
        out["timestamp"] = out["timestamp"].astype("int64") // 10**9

    out = out.sort_values("timestamp").reset_index(drop=True)

    for col in ["open", "high", "low", "close", "volume"]:
        out[col] = pd.to_numeric(out[col], errors="coerce")

    out = out.dropna(subset=["timestamp", "open", "high", "low", "close"]).reset_index(drop=True)
    return out


def is_up(row: pd.Series) -> bool:
    return float(row["close"]) > float(row["open"])


def is_down(row: pd.Series) -> bool:
    return float(row["close"]) < float(row["open"])


def detect_pivots(df: pd.DataFrame, pivot_lookup: int = 1) -> pd.DataFrame:
    bars = normalize_bars(df)
    n = int(pivot_lookup)
    if n < 1:
        raise ValueError("pivot_lookup must be >= 1")

    rows: list[dict[str, Any]] = []
    if len(bars) < 2 * n + 1:
        return pd.DataFrame(columns=["index", "timestamp", "price", "kind", "confirmed", "confirmed_at_index"])

    for i in range(n, len(bars) - n):
        high_val = float(bars.iloc[i]["high"])
        low_val = float(bars.iloc[i]["low"])

        is_high = True
        is_low = True
        for j in range(i - n, i + n + 1):
            if j == i:
                continue
            if float(bars.iloc[j]["high"]) >= high_val:
                is_high = False
            if float(bars.iloc[j]["low"]) <= low_val:
                is_low = False

        if is_high:
            rows.append(
                {
                    "index": i,
                    "timestamp": int(bars.iloc[i]["timestamp"]),
                    "price": high_val,
                    "kind": "HIGH",
                    "confirmed": True,
                    "confirmed_at_index": i + n,
                }
            )
        if is_low:
            rows.append(
                {
                    "index": i,
                    "timestamp": int(bars.iloc[i]["timestamp"]),
                    "price": low_val,
                    "kind": "LOW",
                    "confirmed": True,
                    "confirmed_at_index": i + n,
                }
            )

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["index", "timestamp", "price", "kind", "confirmed", "confirmed_at_index"])
    return out.sort_values(["index", "kind"]).reset_index(drop=True)


def detect_bos_from_pivots(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivot_lookup: int = 1,
    use_high_low_for_bullish: bool = False,
    use_high_low_for_bearish: bool = False,
) -> list[dict]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    pivots = detect_pivots(bars, pivot_lookup=pivot_lookup)

    by_confirm_idx: dict[int, list[dict[str, Any]]] = {}
    for row in pivots.to_dict("records"):
        by_confirm_idx.setdefault(int(row["confirmed_at_index"]), []).append(row)

    last_pivot_high: dict[str, Any] | None = None
    last_pivot_low: dict[str, Any] | None = None
    structure_dir: str | None = None
    out: list[dict[str, Any]] = []

    for i in range(len(bars)):
        for pivot in by_confirm_idx.get(i, []):
            if str(pivot["kind"]).upper() == "HIGH":
                last_pivot_high = pivot
            else:
                last_pivot_low = pivot

        if i == 0:
            continue

        row = bars.iloc[i]
        prev = bars.iloc[i - 1]

        if last_pivot_high is not None:
            cur_val = float(row["high"]) if use_high_low_for_bullish else float(row["close"])
            prev_val = float(prev["high"]) if use_high_low_for_bullish else float(prev["close"])
            level = float(last_pivot_high["price"])

            crossed_up = prev_val <= level and cur_val > level
            if crossed_up:
                kind = cast(Literal["BOS", "CHOCH"], "CHOCH" if structure_dir == "DOWN" else "BOS")
                structure_dir = "UP"
                ts = float(row["timestamp"])
                out.append(
                    {
                        "id": bos_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, kind=kind, dir="UP", price=level),
                        "time": ts,
                        "price": level,
                        "kind": kind,
                        "dir": "UP",
                        "source": "pivot_break",
                    }
                )

        if last_pivot_low is not None:
            cur_val = float(row["low"]) if use_high_low_for_bearish else float(row["close"])
            prev_val = float(prev["low"]) if use_high_low_for_bearish else float(prev["close"])
            level = float(last_pivot_low["price"])

            crossed_down = prev_val >= level and cur_val < level
            if crossed_down:
                kind = cast(Literal["BOS", "CHOCH"], "CHOCH" if structure_dir == "UP" else "BOS")
                structure_dir = "DOWN"
                ts = float(row["timestamp"])
                out.append(
                    {
                        "id": bos_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, kind=kind, dir="DOWN", price=level),
                        "time": ts,
                        "price": level,
                        "kind": kind,
                        "dir": "DOWN",
                        "source": "pivot_break",
                    }
                )

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        dedup.append(row)
    return dedup


def detect_orderblocks_two_candle(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    out: list[dict[str, Any]] = []

    for i in range(1, len(bars)):
        prev = bars.iloc[i - 1]
        cur = bars.iloc[i]

        if is_down(prev) and is_up(cur) and float(cur["close"]) > float(prev["high"]):
            low = float(min(prev["low"], cur["low"]))
            high = float(prev["high"])
            ts = float(cur["timestamp"])
            out.append(
                {
                    "id": ob_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, dir="BULL", low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": "BULL",
                    "valid": True,
                    "anchor_ts": int(ts),
                    "source": "two_candle_displacement",
                }
            )

        if is_up(prev) and is_down(cur) and float(cur["close"]) < float(prev["low"]):
            low = float(prev["low"])
            high = float(max(prev["high"], cur["high"]))
            ts = float(cur["timestamp"])
            out.append(
                {
                    "id": ob_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, dir="BEAR", low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": "BEAR",
                    "valid": True,
                    "anchor_ts": int(ts),
                    "source": "two_candle_displacement",
                }
            )

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        dedup.append(row)
    return dedup


def detect_fvg_three_candle(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    out: list[dict[str, Any]] = []

    for i in range(2, len(bars)):
        left = bars.iloc[i - 2]
        cur = bars.iloc[i]

        if float(cur["low"]) > float(left["high"]):
            low = float(left["high"])
            high = float(cur["low"])
            ts = float(cur["timestamp"])
            out.append(
                {
                    "id": fvg_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, dir="BULL", low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": "BULL",
                    "valid": True,
                    "anchor_ts": int(ts),
                    "source": "three_candle_gap",
                }
            )

        if float(cur["high"]) < float(left["low"]):
            low = float(cur["high"])
            high = float(left["low"])
            ts = float(cur["timestamp"])
            out.append(
                {
                    "id": fvg_id(symbol=str(symbol), timeframe=tf, anchor_ts=ts, dir="BEAR", low=low, high=high),
                    "low": low,
                    "high": high,
                    "dir": "BEAR",
                    "valid": True,
                    "anchor_ts": int(ts),
                    "source": "three_candle_gap",
                }
            )

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        dedup.append(row)
    return dedup


def detect_structure_breaking_fvg(df: pd.DataFrame, pivot_lookup: int = 1) -> list[dict]:
    bars = normalize_bars(df)
    pivots = detect_pivots(bars, pivot_lookup=pivot_lookup)
    by_confirm_idx: dict[int, list[dict[str, Any]]] = {}
    for row in pivots.to_dict("records"):
        by_confirm_idx.setdefault(int(row["confirmed_at_index"]), []).append(row)

    last_top: float | None = None
    last_bottom: float | None = None
    out: list[dict[str, Any]] = []

    for i in range(len(bars)):
        for pivot in by_confirm_idx.get(i, []):
            if str(pivot["kind"]).upper() == "HIGH":
                last_top = float(pivot["price"])
            else:
                last_bottom = float(pivot["price"])

        if i < 2:
            continue

        left = bars.iloc[i - 2]
        mid = bars.iloc[i - 1]
        cur = bars.iloc[i]

        bullish_fvg = float(cur["low"]) > float(left["high"])
        bearish_fvg = float(cur["high"]) < float(left["low"])

        if bullish_fvg and last_top is not None:
            if float(mid["close"]) > last_top and float(mid["low"]) < last_top and float(left["high"]) < last_top and float(cur["low"]) > last_top:
                out.append(
                    {
                        "time": int(cur["timestamp"]),
                        "dir": "BULL",
                        "kind": "STRUCTURE_BREAKING_FVG",
                        "level": float(last_top),
                    }
                )

        if bearish_fvg and last_bottom is not None:
            if float(mid["close"]) < last_bottom and float(mid["high"]) > last_bottom and float(left["low"]) > last_bottom and float(cur["high"]) < last_bottom:
                out.append(
                    {
                        "time": int(cur["timestamp"]),
                        "dir": "BEAR",
                        "kind": "STRUCTURE_BREAKING_FVG",
                        "level": float(last_bottom),
                    }
                )

    return out


def detect_high_volume_bars(df: pd.DataFrame, ema_period: int = 12, multiplier: float = 1.5) -> list[dict]:
    bars = normalize_bars(df)
    vol_ema = bars["volume"].ewm(span=int(ema_period), adjust=False).mean()

    out: list[dict[str, Any]] = []
    for i in range(len(bars)):
        volume = float(bars.iloc[i]["volume"])
        ema_val = float(vol_ema.iloc[i])
        if volume > multiplier * ema_val:
            out.append(
                {
                    "time": int(bars.iloc[i]["timestamp"]),
                    "dir": "BULL" if float(bars.iloc[i]["close"]) > float(bars.iloc[i]["open"]) else "BEAR",
                    "kind": "HVB",
                    "volume": volume,
                    "volume_ema": ema_val,
                }
            )
    return out


def detect_ob_fvg_stack(df: pd.DataFrame) -> list[dict]:
    bars = normalize_bars(df)
    out: list[dict[str, Any]] = []

    for i in range(2, len(bars)):
        prev2 = bars.iloc[i - 2]
        prev1 = bars.iloc[i - 1]
        cur = bars.iloc[i]

        ob_up = is_down(prev2) and is_up(prev1) and float(prev1["close"]) > float(prev2["high"])
        ob_down = is_up(prev2) and is_down(prev1) and float(prev1["close"]) < float(prev2["low"])

        fvg_up = float(cur["low"]) > float(prev2["high"])
        fvg_down = float(cur["high"]) < float(prev2["low"])

        if ob_up and fvg_up:
            out.append({"time": int(cur["timestamp"]), "dir": "BULL", "kind": "OB_FVG_STACK"})
        if ob_down and fvg_down:
            out.append({"time": int(cur["timestamp"]), "dir": "BEAR", "kind": "OB_FVG_STACK"})

    return out


def build_price_action_structure_v2(df: pd.DataFrame, symbol: str, timeframe: str) -> dict:
    bars = normalize_bars(df)

    structure = {
        "bos": detect_bos_from_pivots(bars, symbol=symbol, timeframe=timeframe, pivot_lookup=1),
        "orderblocks": detect_orderblocks_two_candle(bars, symbol=symbol, timeframe=timeframe),
        "fvg": detect_fvg_three_candle(bars, symbol=symbol, timeframe=timeframe),
    }

    qualifiers = {
        "structure_breaking_fvg": detect_structure_breaking_fvg(bars, pivot_lookup=1),
        "high_volume_bars": detect_high_volume_bars(bars, ema_period=12, multiplier=1.5),
        "ob_fvg_stack": detect_ob_fvg_stack(bars),
    }

    return {
        "structure": structure,
        "qualifiers": qualifiers,
    }
