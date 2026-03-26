from __future__ import annotations

from typing import Any

import pandas as pd

from scripts.smc_price_action_engine import normalize_bars


def compute_fvg_bias_counter(df: pd.DataFrame) -> list[dict]:
    bars = normalize_bars(df)
    counter = 0
    out: list[dict[str, Any]] = []

    for i in range(1, len(bars)):
        bullish = float(bars.iloc[i]["close"]) > float(bars.iloc[i - 1]["high"])
        bearish = float(bars.iloc[i]["close"]) < float(bars.iloc[i - 1]["low"])

        if bullish:
            if counter < 0:
                counter = 0
            counter += 1
        elif bearish:
            if counter > 0:
                counter = 0
            counter -= 1

        out.append(
            {
                "time": int(bars.iloc[i]["timestamp"]),
                "counter": counter,
                "direction": "BULLISH" if counter > 0 else "BEARISH" if counter < 0 else "NEUTRAL",
            }
        )

    return out


def select_ipda_htf(chart_tf: str) -> str:
    normalized = str(chart_tf).strip()
    intraday_short = {"1m", "5m", "15m", "30m", "1H", "2H"}
    intraday_long = {"3H", "4H", "6H", "8H", "12H"}

    if normalized in intraday_short:
        return "D"
    if normalized in intraday_long:
        return "W"
    if normalized == "D":
        return "M"
    if normalized == "W":
        return "6M"
    return "D"


def build_ipda_range(htf_current: dict, htf_prev: dict) -> dict:
    range_high = max(float(htf_current["high"]), float(htf_prev["high"]))
    range_low = min(float(htf_current["low"]), float(htf_prev["low"]))
    width = range_high - range_low

    return {
        "range_high": range_high,
        "range_low": range_low,
        "q25": range_low + 0.25 * width,
        "mid": range_low + 0.50 * width,
        "q75": range_low + 0.75 * width,
        "width": width,
    }


def compute_calendar_boundaries(df: pd.DataFrame) -> dict:
    bars = normalize_bars(df)
    ts = pd.to_datetime(bars["timestamp"], unit="s", utc=True)
    ts_naive = ts.dt.tz_localize(None)

    day_change_idx = ts.dt.floor("D").ne(ts.dt.floor("D").shift())
    week_key = ts_naive.dt.strftime("%G-W%V")
    month_key = ts_naive.dt.strftime("%Y-%m")
    week_change_idx = week_key.ne(week_key.shift())
    month_change_idx = month_key.ne(month_key.shift())

    return {
        "day_boundaries": [int(bars.iloc[i]["timestamp"]) for i in bars.index[day_change_idx].tolist()],
        "week_boundaries": [int(bars.iloc[i]["timestamp"]) for i in bars.index[week_change_idx].tolist()],
        "month_boundaries": [int(bars.iloc[i]["timestamp"]) for i in bars.index[month_change_idx].tolist()],
    }


def build_htf_bias_context(df: pd.DataFrame, timeframe: str, htf_frames: dict[str, pd.DataFrame] | None = None) -> dict:
    bars = normalize_bars(df)
    htf_frames = htf_frames or {}

    bias = compute_fvg_bias_counter(bars)
    selected_htf = select_ipda_htf(timeframe)

    ipda: dict[str, float] | None = None
    frame = htf_frames.get(selected_htf)
    if frame is not None and len(frame) >= 2:
        f = normalize_bars(frame)
        ipda = build_ipda_range(f.iloc[-1].to_dict(), f.iloc[-2].to_dict())

    return {
        "selected_ipda_htf": selected_htf,
        "fvg_bias_counter": bias,
        "ipda_range": ipda,
        "calendar_boundaries": compute_calendar_boundaries(bars),
    }
