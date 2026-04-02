from __future__ import annotations

from typing import Any

import pandas as pd

from smc_core.ids import liquidity_id, sweep_id
from scripts.smc_price_action_engine import canonical_timeframe, normalize_bars


def detect_liquidity_levels(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivot_lookup: int = 1,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    out: list[dict[str, Any]] = []
    window = max(1, int(pivot_lookup))

    if len(bars) < (window * 2 + 1):
        return out

    for i in range(window, len(bars) - window):
        left = bars.iloc[i - window : i]
        mid = bars.iloc[i]
        right = bars.iloc[i + 1 : i + 1 + window]

        if float(mid["high"]) > float(left["high"].max()) and float(mid["high"]) > float(right["high"].max()):
            price = float(mid["high"])
            ts = int(mid["timestamp"])
            out.append(
                {
                    "id": liquidity_id(
                        symbol=str(symbol),
                        timeframe=tf,
                        anchor_ts=float(ts),
                        side="BUY_SIDE",
                        price=price,
                        ticksize=ticksize,
                        asset_class=asset_class,
                        session_tz=session_tz,
                    ),
                    "time": ts,
                    "price": price,
                    "side": "BUY_SIDE",
                    "kind": "PIVOT_HIGH",
                }
            )

        if float(mid["low"]) < float(left["low"].min()) and float(mid["low"]) < float(right["low"].min()):
            price = float(mid["low"])
            ts = int(mid["timestamp"])
            out.append(
                {
                    "id": liquidity_id(
                        symbol=str(symbol),
                        timeframe=tf,
                        anchor_ts=float(ts),
                        side="SELL_SIDE",
                        price=price,
                        ticksize=ticksize,
                        asset_class=asset_class,
                        session_tz=session_tz,
                    ),
                    "time": ts,
                    "price": price,
                    "side": "SELL_SIDE",
                    "kind": "PIVOT_LOW",
                }
            )

    return out


def detect_liquidity_sweeps(
    df: pd.DataFrame,
    liquidity_levels: list[dict],
    symbol: str,
    timeframe: str,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars = normalize_bars(df)
    tf = canonical_timeframe(timeframe)
    out: list[dict[str, Any]] = []

    for level in liquidity_levels:
        level_time = int(level["time"])
        level_price = float(level["price"])
        level_side = str(level["side"])

        for i in range(len(bars)):
            row = bars.iloc[i]
            ts = int(row["timestamp"])
            if ts <= level_time:
                continue

            if level_side == "BUY_SIDE":
                if float(row["high"]) > level_price and float(row["close"]) < level_price:
                    out.append(
                        {
                            "id": sweep_id(
                                symbol=str(symbol),
                                timeframe=tf,
                                anchor_ts=float(ts),
                                side="BUY_SIDE",
                                price=level_price,
                                ticksize=ticksize,
                                asset_class=asset_class,
                                session_tz=session_tz,
                            ),
                            "time": float(ts),
                            "price": level_price,
                            "side": "BUY_SIDE",
                            "source_liquidity_id": str(level.get("id", "")),
                        }
                    )
                    break

            if level_side == "SELL_SIDE":
                if float(row["low"]) < level_price and float(row["close"]) > level_price:
                    out.append(
                        {
                            "id": sweep_id(
                                symbol=str(symbol),
                                timeframe=tf,
                                anchor_ts=float(ts),
                                side="SELL_SIDE",
                                price=level_price,
                                ticksize=ticksize,
                                asset_class=asset_class,
                                session_tz=session_tz,
                            ),
                            "time": float(ts),
                            "price": level_price,
                            "side": "SELL_SIDE",
                            "source_liquidity_id": str(level.get("id", "")),
                        }
                    )
                    break

    dedup: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in out:
        if row["id"] in seen:
            continue
        seen.add(row["id"])
        dedup.append(row)
    return dedup
