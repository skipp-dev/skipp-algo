from __future__ import annotations

from typing import Any

import pandas as pd

from smc_core.ids import fvg_id, ob_id, sweep_id
from scripts.smc_price_action_engine import canonical_timeframe, detect_bos_from_pivots, normalize_bars


def _is_up(open_price: float, close_price: float) -> bool:
    return float(close_price) > float(open_price)


def _is_down(open_price: float, close_price: float) -> bool:
    return float(close_price) < float(open_price)


def _dedupe_by_id(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        row_id = str(row.get("id", "")).strip()
        if not row_id or row_id in seen:
            continue
        seen.add(row_id)
        out.append(row)
    return out


def detect_orderblocks_makuchaku(df: pd.DataFrame, symbol: str, timeframe: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    symbol_name = str(symbol).strip().upper()

    out: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for i in range(1, len(bars)):
        prev = bars.iloc[i - 1]
        cur = bars.iloc[i]

        prev_open = float(prev["open"])
        prev_close = float(prev["close"])
        prev_high = float(prev["high"])
        prev_low = float(prev["low"])
        cur_open = float(cur["open"])
        cur_close = float(cur["close"])
        cur_high = float(cur["high"])
        cur_low = float(cur["low"])
        cur_ts = float(cur["timestamp"])
        prev_ts = int(prev["timestamp"])

        if _is_down(prev_open, prev_close) and _is_up(cur_open, cur_close) and cur_close > prev_high:
            low = float(min(prev_low, cur_low))
            high = float(prev_high)
            zone_id = ob_id(symbol=symbol_name, timeframe=tf, anchor_ts=cur_ts, dir="BULL", low=low, high=high)
            valid = True
            mitigated = False
            mitigated_ts: int | None = None
            for j in range(i + 1, len(bars)):
                probe = bars.iloc[j]
                probe_close = float(probe["close"])
                probe_low = float(probe["low"])
                probe_ts = int(probe["timestamp"])
                if not mitigated and probe_low <= high and probe_low >= low:
                    mitigated = True
                    mitigated_ts = probe_ts
                if probe_close < low:
                    valid = False
                    break
            out.append(
                {
                    "id": zone_id,
                    "low": low,
                    "high": high,
                    "dir": "BULL",
                    "valid": valid,
                    "anchor_ts": int(cur_ts),
                    "source": "makuchaku_ob",
                }
            )
            diagnostics.append(
                {
                    "id": zone_id,
                    "kind": "ORDERBLOCK",
                    "mitigated": mitigated,
                    "mitigated_ts": mitigated_ts,
                    "invalidation_rule": "close_below_low",
                    "left_anchor_ts": prev_ts,
                }
            )

        if _is_up(prev_open, prev_close) and _is_down(cur_open, cur_close) and cur_close < prev_low:
            high = float(max(prev_high, cur_high))
            low = float(prev_low)
            zone_id = ob_id(symbol=symbol_name, timeframe=tf, anchor_ts=cur_ts, dir="BEAR", low=low, high=high)
            valid = True
            mitigated = False
            mitigated_ts: int | None = None
            for j in range(i + 1, len(bars)):
                probe = bars.iloc[j]
                probe_close = float(probe["close"])
                probe_high = float(probe["high"])
                probe_ts = int(probe["timestamp"])
                if not mitigated and probe_high >= low and probe_high <= high:
                    mitigated = True
                    mitigated_ts = probe_ts
                if probe_close > high:
                    valid = False
                    break
            out.append(
                {
                    "id": zone_id,
                    "low": low,
                    "high": high,
                    "dir": "BEAR",
                    "valid": valid,
                    "anchor_ts": int(cur_ts),
                    "source": "makuchaku_ob",
                }
            )
            diagnostics.append(
                {
                    "id": zone_id,
                    "kind": "ORDERBLOCK",
                    "mitigated": mitigated,
                    "mitigated_ts": mitigated_ts,
                    "invalidation_rule": "close_above_high",
                    "left_anchor_ts": prev_ts,
                }
            )

    return _dedupe_by_id(out), diagnostics


def detect_fvg_classic(df: pd.DataFrame, symbol: str, timeframe: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    symbol_name = str(symbol).strip().upper()

    out: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []

    for i in range(2, len(bars)):
        b2 = bars.iloc[i - 2]
        b0 = bars.iloc[i]

        b2_high = float(b2["high"])
        b2_low = float(b2["low"])
        b0_high = float(b0["high"])
        b0_low = float(b0["low"])
        anchor_ts = float(b0["timestamp"])

        if b0_low > b2_high:
            low = b2_high
            high = b0_low
            zone_id = fvg_id(symbol=symbol_name, timeframe=tf, anchor_ts=anchor_ts, dir="BULL", low=low, high=high)
            mitigated = False
            mitigated_ts: int | None = None
            valid = True
            for j in range(i + 1, len(bars)):
                probe = bars.iloc[j]
                probe_low = float(probe["low"])
                probe_close = float(probe["close"])
                probe_ts = int(probe["timestamp"])
                if not mitigated and probe_low <= high and probe_low >= low:
                    mitigated = True
                    mitigated_ts = probe_ts
                if probe_close < low:
                    valid = False
                    break
            out.append(
                {
                    "id": zone_id,
                    "low": low,
                    "high": high,
                    "dir": "BULL",
                    "valid": valid,
                    "anchor_ts": int(anchor_ts),
                    "source": "classic_fvg",
                }
            )
            diagnostics.append(
                {
                    "id": zone_id,
                    "kind": "FVG",
                    "mitigated": mitigated,
                    "mitigated_ts": mitigated_ts,
                    "is_structure_breaking": False,
                    "break_reference": None,
                }
            )

        if b0_high < b2_low:
            low = b0_high
            high = b2_low
            zone_id = fvg_id(symbol=symbol_name, timeframe=tf, anchor_ts=anchor_ts, dir="BEAR", low=low, high=high)
            mitigated = False
            mitigated_ts: int | None = None
            valid = True
            for j in range(i + 1, len(bars)):
                probe = bars.iloc[j]
                probe_high = float(probe["high"])
                probe_close = float(probe["close"])
                probe_ts = int(probe["timestamp"])
                if not mitigated and probe_high >= low and probe_high <= high:
                    mitigated = True
                    mitigated_ts = probe_ts
                if probe_close > high:
                    valid = False
                    break
            out.append(
                {
                    "id": zone_id,
                    "low": low,
                    "high": high,
                    "dir": "BEAR",
                    "valid": valid,
                    "anchor_ts": int(anchor_ts),
                    "source": "classic_fvg",
                }
            )
            diagnostics.append(
                {
                    "id": zone_id,
                    "kind": "FVG",
                    "mitigated": mitigated,
                    "mitigated_ts": mitigated_ts,
                    "is_structure_breaking": False,
                    "break_reference": None,
                }
            )

    return _dedupe_by_id(out), diagnostics


def detect_liquidity_lines_pivot3(df: pd.DataFrame, symbol: str, timeframe: str) -> list[dict[str, Any]]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    symbol_name = str(symbol).strip().upper()

    out: list[dict[str, Any]] = []

    for i in range(0, len(bars) - 2):
        left = bars.iloc[i]
        mid = bars.iloc[i + 1]
        right = bars.iloc[i + 2]

        if float(mid["high"]) > float(left["high"]) and float(mid["high"]) > float(right["high"]):
            price = float(mid["high"])
            ts = int(mid["timestamp"])
            out.append(
                {
                    "id": f"liq:{symbol_name}:{tf}:{ts}:BUY_SIDE:{price:.2f}",
                    "side": "BUY_SIDE",
                    "price": price,
                    "anchor_ts": ts,
                    "source": "pivot3",
                    "active": True,
                    "consumed": False,
                }
            )

        if float(mid["low"]) < float(left["low"]) and float(mid["low"]) < float(right["low"]):
            price = float(mid["low"])
            ts = int(mid["timestamp"])
            out.append(
                {
                    "id": f"liq:{symbol_name}:{tf}:{ts}:SELL_SIDE:{price:.2f}",
                    "side": "SELL_SIDE",
                    "price": price,
                    "anchor_ts": ts,
                    "source": "pivot3",
                    "active": True,
                    "consumed": False,
                }
            )

    return _dedupe_by_id(out)


def detect_liquidity_sweeps_from_lines(df: pd.DataFrame, liquidity_lines: list[dict[str, Any]], symbol: str, timeframe: str) -> list[dict[str, Any]]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    symbol_name = str(symbol).strip().upper()

    out: list[dict[str, Any]] = []
    consumed_lines: set[str] = set()

    sorted_lines = sorted(liquidity_lines, key=lambda row: (int(row.get("anchor_ts", 0)), str(row.get("id", ""))))
    for line in sorted_lines:
        line_id = str(line.get("id", "")).strip()
        if not line_id:
            continue

        side = str(line.get("side", "")).upper()
        price = float(line.get("price", 0.0))
        anchor_ts = int(line.get("anchor_ts", 0))

        for i in range(len(bars)):
            row = bars.iloc[i]
            ts = int(row["timestamp"])
            if ts <= anchor_ts:
                continue

            sell_side_sweep = side == "SELL_SIDE" and float(row["low"]) < price and float(row["close"]) > price
            buy_side_sweep = side == "BUY_SIDE" and float(row["high"]) > price and float(row["close"]) < price

            if sell_side_sweep:
                out.append(
                    {
                        "id": sweep_id(symbol=symbol_name, timeframe=tf, anchor_ts=float(ts), side="SELL_SIDE", price=price),
                        "time": float(ts),
                        "price": price,
                        "side": "SELL_SIDE",
                        "source_liquidity_id": line_id,
                        "source": "pivot3_close_back",
                    }
                )
                consumed_lines.add(line_id)
                break

            if buy_side_sweep:
                out.append(
                    {
                        "id": sweep_id(symbol=symbol_name, timeframe=tf, anchor_ts=float(ts), side="BUY_SIDE", price=price),
                        "time": float(ts),
                        "price": price,
                        "side": "BUY_SIDE",
                        "source_liquidity_id": line_id,
                        "source": "pivot3_close_back",
                    }
                )
                consumed_lines.add(line_id)
                break

    for line in liquidity_lines:
        if str(line.get("id", "")) in consumed_lines:
            line["consumed"] = True
            line["active"] = False

    return _dedupe_by_id(out)


def detect_bos_choch_events(df: pd.DataFrame, symbol: str, timeframe: str, pivot_lookup: int = 1) -> list[dict[str, Any]]:
    return detect_bos_from_pivots(
        df,
        symbol=symbol,
        timeframe=timeframe,
        pivot_lookup=pivot_lookup,
        use_high_low_for_bullish=False,
        use_high_low_for_bearish=False,
    )
