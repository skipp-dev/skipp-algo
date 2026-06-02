from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from scripts.smc_price_action_engine import normalize_bars

DEFAULT_TZ = "America/New_York"
DEFAULT_SESSIONS = [
    ("ASIA", "20:00", "00:00"),
    ("LONDON", "02:00", "05:00"),
    ("NY_AM", "09:30", "11:00"),
    ("NY_LUNCH", "12:00", "13:00"),
    ("NY_PM", "13:30", "16:00"),
]


def _parse_hhmm(raw: str) -> time:
    hh, mm = str(raw).split(":")
    return time(hour=int(hh), minute=int(mm))


def _in_session(local_dt: datetime, start: time, end: time) -> bool:
    local_t = local_dt.timetz().replace(tzinfo=None)
    if start < end:
        return start <= local_t < end
    return local_t >= start or local_t < end


def _session_date(local_dt: datetime, start: time, end: time) -> str:
    if start < end:
        return str(local_dt.date())
    local_t = local_dt.timetz().replace(tzinfo=None)
    if local_t >= start:
        return str(local_dt.date())
    return str((local_dt - pd.Timedelta(days=1)).date())


def build_session_ranges(df: pd.DataFrame, timezone: str = DEFAULT_TZ, sessions: list[tuple[str, str, str]] | None = None) -> list[dict]:
    bars = normalize_bars(df)
    if bars.empty:
        return []

    tz = ZoneInfo(timezone)
    session_defs = sessions or DEFAULT_SESSIONS
    ts_local = pd.to_datetime(bars["timestamp"], unit="s", utc=True).dt.tz_convert(tz)
    bars = bars.copy()
    bars["_dt_local"] = ts_local

    out: list[dict] = []
    for name, start_raw, end_raw in session_defs:
        start = _parse_hhmm(start_raw)
        end = _parse_hhmm(end_raw)

        scoped = bars[bars["_dt_local"].apply(lambda dt, _s=start, _e=end: _in_session(dt, _s, _e))].copy()
        if scoped.empty:
            continue

        scoped["_session_date"] = scoped["_dt_local"].apply(lambda dt, _s=start, _e=end: _session_date(dt, _s, _e))
        for session_date, group in scoped.groupby("_session_date"):
            high = float(group["high"].max())
            low = float(group["low"].min())
            out.append(
                {
                    "session": name,
                    "date": str(session_date),
                    "start_ts": int(group["timestamp"].min()),
                    "end_ts": int(group["timestamp"].max()),
                    "high": high,
                    "low": low,
                    "mid": (high + low) / 2.0,
                    "range": high - low,
                }
            )

    return sorted(out, key=lambda row: (row["date"], row["session"]))


def build_session_pivots(session_ranges: list[dict]) -> list[dict]:
    out: list[dict] = []
    for row in session_ranges:
        out.append(
            {
                "session": row["session"],
                "date": row["date"],
                "high": row["high"],
                "low": row["low"],
                "mid": row["mid"],
                "range": row["range"],
            }
        )
    return out


def build_ipda_operating_range(df: pd.DataFrame, timeframe: str) -> dict:
    bars = normalize_bars(df)
    if bars.empty:
        return {
            "selected_htf": "D",
            "range_high": None,
            "range_low": None,
            "range_25": None,
            "range_50": None,
            "range_75": None,
        }

    tf = str(timeframe).strip()
    if tf in {"5m", "15m", "1H", "4H"}:
        selected_htf = "D"
    elif tf == "1D":
        selected_htf = "W"
    else:
        selected_htf = "D"

    highs = pd.to_numeric(bars["high"], errors="coerce")
    lows = pd.to_numeric(bars["low"], errors="coerce")
    range_high = float(highs.max())
    range_low = float(lows.min())
    width = max(0.0, range_high - range_low)

    return {
        "selected_htf": selected_htf,
        "range_high": range_high,
        "range_low": range_low,
        "range_25": range_low + 0.25 * width,
        "range_50": range_low + 0.50 * width,
        "range_75": range_low + 0.75 * width,
    }


def compute_htf_fvg_bias(df: pd.DataFrame) -> dict:
    bars = normalize_bars(df)
    if len(bars) < 3:
        return {"counter": 0, "bias": "NEUTRAL"}

    counter = 0
    for i in range(2, len(bars)):
        left = bars.iloc[i - 2]
        cur = bars.iloc[i]

        bullish = float(cur["low"]) > float(left["high"])
        bearish = float(cur["high"]) < float(left["low"])

        if bullish:
            if counter < 0:
                counter = 0
            counter += 1
        elif bearish:
            if counter > 0:
                counter = 0
            counter -= 1

    if counter > 0:
        bias = "BULLISH"
    elif counter < 0:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"
    return {"counter": int(counter), "bias": bias}


def compute_broken_fractal_signals(df: pd.DataFrame) -> list[dict]:
    bars = normalize_bars(df)
    n = len(bars)
    if n < 5:
        return []

    # Vectorized rewrite of the original O(n^2) double loop. The hot path was
    # ~n^2 pandas `.iloc[j]` scalar lookups (Arrow-backed rows cost ~tens of us
    # each). We pull the columns into numpy once and replace the inner "first
    # future close that breaks the fractal level" scan with a C-level slice
    # search. Output is byte-for-byte identical to the previous implementation.
    high = bars["high"].to_numpy(dtype=float)
    low = bars["low"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float)
    ts = bars["timestamp"].to_numpy(dtype="int64")

    out: list[dict] = []

    for i in range(1, n - 3):
        pivot_high = high[i]
        pivot_low = low[i]
        is_high_fractal = pivot_high > high[i - 1] and pivot_high > high[i + 1]
        is_low_fractal = pivot_low < low[i - 1] and pivot_low < low[i + 1]
        if not (is_high_fractal or is_low_fractal):
            continue

        seg = close[i + 2 :]

        jh: int | None = None
        if is_high_fractal:
            hits = np.flatnonzero(seg > pivot_high)
            if hits.size:
                jh = i + 2 + int(hits[0])

        jl: int | None = None
        if is_low_fractal:
            hits = np.flatnonzero(seg < pivot_low)
            if hits.size:
                jl = i + 2 + int(hits[0])

        # The original loop checked the high condition before the low condition
        # at each bar, so whichever break fires at the earliest bar wins. Both
        # cannot fire on the same bar (close can't exceed pivot_high and fall
        # below pivot_low simultaneously when pivot_high > pivot_low).
        if jh is not None and (jl is None or jh < jl):
            out.append(
                {
                    "side": "BULLISH",
                    "anchor_ts": int(ts[i]),
                    "trigger_ts": int(ts[jh]),
                    "level": float(pivot_high),
                    "zone_high": float(pivot_high),
                    "zone_low": float(low[i]),
                }
            )
        elif jl is not None:
            out.append(
                {
                    "side": "BEARISH",
                    "anchor_ts": int(ts[i]),
                    "trigger_ts": int(ts[jl]),
                    "level": float(pivot_low),
                    "zone_high": float(high[i]),
                    "zone_low": float(pivot_low),
                }
            )

    return out
