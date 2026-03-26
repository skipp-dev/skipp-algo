from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

DEFAULT_TZ = "America/New_York"
DEFAULT_KILLZONES = [
    ("Asia", "20:00", "00:00"),
    ("London", "02:00", "05:00"),
    ("NY AM", "09:30", "11:00"),
    ("NY Lunch", "12:00", "13:00"),
    ("NY PM", "13:30", "16:00"),
]

DEFAULT_OPENING_LEVELS = ["00:00", "06:00", "10:00", "14:00"]


def _to_local_bars(df: pd.DataFrame, timezone_name: str) -> pd.DataFrame:
    bars = df.copy()
    if not pd.api.types.is_numeric_dtype(bars["timestamp"]):
        bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
        bars["timestamp"] = bars["timestamp"].astype("int64") // 10**9

    ts_utc = pd.to_datetime(bars["timestamp"], unit="s", utc=True)
    bars["_dt_local"] = ts_utc.dt.tz_convert(ZoneInfo(timezone_name))
    bars["_date_local"] = bars["_dt_local"].dt.date

    for col in ["open", "high", "low", "close"]:
        bars[col] = pd.to_numeric(bars[col], errors="coerce")

    return bars.dropna(subset=["timestamp", "open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)


def _parse_hhmm(raw: str) -> time:
    hh, mm = str(raw).split(":")
    return time(hour=int(hh), minute=int(mm))


def _in_session(dt: datetime, start_t: time, end_t: time) -> bool:
    local_t = dt.timetz().replace(tzinfo=None)
    if start_t < end_t:
        return start_t <= local_t < end_t
    return local_t >= start_t or local_t < end_t


def _session_date_for_row(dt: datetime, start_t: time, end_t: time) -> date:
    if start_t < end_t:
        return dt.date()
    # Overnight sessions are keyed by the starting date.
    local_t = dt.timetz().replace(tzinfo=None)
    if local_t >= start_t:
        return dt.date()
    return (dt - timedelta(days=1)).date()


def build_killzones(df: pd.DataFrame, tz: str = DEFAULT_TZ) -> list[dict]:
    bars = _to_local_bars(df, tz)
    out: list[dict] = []

    for session_name, start_hm, end_hm in DEFAULT_KILLZONES:
        start_t = _parse_hhmm(start_hm)
        end_t = _parse_hhmm(end_hm)

        scoped = bars[bars["_dt_local"].apply(lambda x: _in_session(x, start_t, end_t))].copy()
        if scoped.empty:
            continue
        scoped["_session_date"] = scoped["_dt_local"].apply(lambda x: _session_date_for_row(x, start_t, end_t))

        for session_date, group in scoped.groupby("_session_date"):
            high = float(group["high"].max())
            low = float(group["low"].min())
            out.append(
                {
                    "name": session_name,
                    "date": str(session_date),
                    "start_ts": int(group["timestamp"].min()),
                    "end_ts": int(group["timestamp"].max()),
                    "high": high,
                    "low": low,
                    "mid": (high + low) / 2.0,
                    "range": high - low,
                }
            )

    return sorted(out, key=lambda x: (x["date"], x["name"]))


def build_session_pivots(df: pd.DataFrame, tz: str = DEFAULT_TZ) -> list[dict]:
    # Session pivots share the same high/low/mid outputs as killzones.
    return build_killzones(df, tz=tz)


def build_dwm_levels(df: pd.DataFrame) -> dict:
    bars = df.copy()
    if not pd.api.types.is_numeric_dtype(bars["timestamp"]):
        bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
        bars["timestamp"] = bars["timestamp"].astype("int64") // 10**9

    bars["_dt"] = pd.to_datetime(bars["timestamp"], unit="s", utc=True)
    bars["_day"] = bars["_dt"].dt.floor("D")
    bars["_week"] = bars["_dt"].dt.to_period("W").astype(str)
    bars["_month"] = bars["_dt"].dt.to_period("M").astype(str)

    for col in ["open", "high", "low", "close"]:
        bars[col] = pd.to_numeric(bars[col], errors="coerce")

    bars = bars.dropna(subset=["open", "high", "low", "close"]).sort_values("timestamp").reset_index(drop=True)

    result: dict[str, float] = {}

    daily = bars.groupby("_day").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"))
    if len(daily) >= 2:
        result["day_open"] = float(daily.iloc[-1]["open"])
        result["prev_day_high"] = float(daily.iloc[-2]["high"])
        result["prev_day_low"] = float(daily.iloc[-2]["low"])

    weekly = bars.groupby("_week").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"))
    if len(weekly) >= 2:
        result["week_open"] = float(weekly.iloc[-1]["open"])
        result["prev_week_high"] = float(weekly.iloc[-2]["high"])
        result["prev_week_low"] = float(weekly.iloc[-2]["low"])

    monthly = bars.groupby("_month").agg(open=("open", "first"), high=("high", "max"), low=("low", "min"))
    if len(monthly) >= 2:
        result["month_open"] = float(monthly.iloc[-1]["open"])
        result["prev_month_high"] = float(monthly.iloc[-2]["high"])
        result["prev_month_low"] = float(monthly.iloc[-2]["low"])

    return result


def build_opening_levels(df: pd.DataFrame, tz: str = DEFAULT_TZ) -> list[dict]:
    bars = _to_local_bars(df, tz)
    out: list[dict] = []

    for session_date, group in bars.groupby("_date_local"):
        for hm in DEFAULT_OPENING_LEVELS:
            hh, mm = map(int, hm.split(":"))
            picked = group[(group["_dt_local"].dt.hour == hh) & (group["_dt_local"].dt.minute == mm)]
            if picked.empty:
                picked = group[group["_dt_local"] >= datetime.combine(session_date, time(hh, mm), tzinfo=ZoneInfo(tz))]
                if picked.empty:
                    continue
                row = picked.iloc[0]
            else:
                row = picked.iloc[0]

            out.append(
                {
                    "name": hm,
                    "date": str(session_date),
                    "timestamp": int(row["timestamp"]),
                    "price": float(row["open"]),
                }
            )

    return sorted(out, key=lambda x: (x["date"], x["timestamp"], x["name"]))


def build_session_liquidity_context(df: pd.DataFrame, tz: str = DEFAULT_TZ) -> dict:
    return {
        "killzones": build_killzones(df, tz=tz),
        "session_pivots": build_session_pivots(df, tz=tz),
        "dwm_levels": build_dwm_levels(df),
        "opening_levels": build_opening_levels(df, tz=tz),
    }
