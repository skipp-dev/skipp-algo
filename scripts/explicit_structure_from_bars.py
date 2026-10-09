from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from scripts.explicit_structure_detectors import detect_liquidity_sweeps_from_lines
from scripts.explicit_structure_profiles import build_structure_profile, validate_structure_profile
from scripts.smc_price_action_engine import (
    canonical_timeframe,
    coerce_timestamps_to_epoch_seconds,
    normalize_bars,
)
from smc_core.ids import liquidity_id

_LOG = logging.getLogger(__name__)

RequiredBarColumns = ("symbol", "timestamp", "open", "high", "low", "close")

_TIMEFRAME_TO_PANDAS_FREQ: dict[str, str] = {
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
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

    if canonical_tf == "1D":
        # Silent-fallback audit (2026-06-10): this branch used to be an
        # unconditional identity pass-through, silently serving intraday
        # bars as "1D" (mirror image of the #2666 cross-TF aliasing).
        # Keep the identity ONLY for genuinely daily input (≤1 row per
        # symbol/calendar-day — regardless of stamp time, so daily bars
        # stamped at session open are not corrupted); aggregate finer
        # input through the generic bucket path below.
        day_counts = bars.groupby(
            ["symbol", bars["timestamp"].dt.floor("1D")]
        ).size()
        if day_counts.empty or int(day_counts.max()) <= 1:
            return bars[["symbol", "timestamp", "open", "high", "low", "close", "volume"]].reset_index(drop=True)
        _LOG.warning(
            "resample_bars_to_timeframe: source bars are finer than 1D "
            "(max %d rows per symbol/day); aggregating to calendar days — "
            "the trailing partial day is trimmed",
            int(day_counts.max()),
        )

    parts: list[pd.DataFrame] = []
    bucket_offset = pd.tseries.frequencies.to_offset(freq)
    for symbol, group in bars.groupby("symbol", sort=False):
        grouped = group.sort_values("timestamp").copy()
        max_source_ts = grouped["timestamp"].max()
        floored = grouped["timestamp"].dt.floor(freq)
        grouped["bucket_end"] = floored.where(grouped["timestamp"].eq(floored), floored + bucket_offset)
        agg = (
            grouped.groupby("bucket_end", sort=True, dropna=True)
            .agg(
                open=("open", "first"),
                high=("high", "max"),
                low=("low", "min"),
                close=("close", "last"),
                volume=("volume", "sum"),
            )
            .reset_index()
            .rename(columns={"bucket_end": "timestamp"})
        )
        # BAR-CLOSE-EXEMPT: offline batch aggregation script. Reads a finished
        # historical bar series and trims a partial trailing bucket whose end
        # exceeds the source's max timestamp. There is no live trading loop
        # here — the tail-row indexer reads a closed historical bar, not the
        # chart's current candle (system review 2026-04-24 / iloc-guard ledger).
        # NOTE: this comment block intentionally avoids the literal token so
        # the iloc-guard discipline test (which scans a ±2-line window
        # around the pinned hotspot) cannot be satisfied by the comment
        # alone — it must match the real code site below (Copilot review
        # of PR #1942).
        # Prevent a partial trailing bucket from being treated as a confirmed bar.
        if (
            not agg.empty
            and pd.notna(max_source_ts)
            and pd.Timestamp(agg["timestamp"].iloc[-1])
            > pd.Timestamp(max_source_ts)
        ):
            # BAR-CLOSE-EXEMPT: drops the partial trailing bucket detected above.
            agg = agg.iloc[:-1]
        agg = agg.dropna(subset=["open", "high", "low", "close"]).reset_index(drop=True)
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
    bars["timestamp"] = coerce_timestamps_to_epoch_seconds(bars["timestamp"])
    return bars, canonical_tf


def build_bos_events_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(
        bars,
        symbol=str(symbol),
        timeframe=canonical_tf,
        profile="hybrid_default",
        pivot_lookup=1,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    return _dedupe_by_id(payload.bos)


def build_liquidity_sweeps_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(
        bars,
        symbol=str(symbol),
        timeframe=canonical_tf,
        profile="hybrid_default",
        pivot_lookup=1,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    sweeps = _dedupe_by_id(payload.liquidity_sweeps)
    if sweeps:
        return sweeps

    symbol_name = str(symbol).strip().upper()
    # Silent-fallback audit (2026-06-10): make the legacy fallback loud
    # (#2666 lesson) — every emitted line carries source=legacy_high_low,
    # but without this log the engine→legacy downgrade was invisible.
    _LOG.warning(
        "liquidity sweeps: profile engine produced none for %s/%s; "
        "falling back to legacy high/low line detection "
        "(source=legacy_high_low)",
        symbol_name,
        canonical_tf,
    )
    legacy_lines: list[dict[str, Any]] = []
    for i in range(len(bars) - 1):
        row = bars.iloc[i]
        ts = int(row["timestamp"])
        high = float(row["high"])
        low = float(row["low"])
        legacy_lines.append(
            {
                "id": liquidity_id(
                    symbol=symbol_name,
                    timeframe=canonical_tf,
                    anchor_ts=float(ts),
                    side="BUY_SIDE",
                    price=high,
                    ticksize=ticksize,
                    asset_class=asset_class,
                    session_tz=session_tz,
                ),
                "anchor_ts": ts,
                "price": high,
                "side": "BUY_SIDE",
                "source": "legacy_high_low",
                "active": True,
                "consumed": False,
            }
        )
        legacy_lines.append(
            {
                "id": liquidity_id(
                    symbol=symbol_name,
                    timeframe=canonical_tf,
                    anchor_ts=float(ts),
                    side="SELL_SIDE",
                    price=low,
                    ticksize=ticksize,
                    asset_class=asset_class,
                    session_tz=session_tz,
                ),
                "anchor_ts": ts,
                "price": low,
                "side": "SELL_SIDE",
                "source": "legacy_high_low",
                "active": True,
                "consumed": False,
            }
        )

    fallback = detect_liquidity_sweeps_from_lines(
        bars,
        liquidity_lines=legacy_lines,
        symbol=symbol_name,
        timeframe=canonical_tf,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    return _dedupe_by_id(fallback)


def build_fvg_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(
        bars,
        symbol=str(symbol),
        timeframe=canonical_tf,
        profile="hybrid_default",
        pivot_lookup=1,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    return _dedupe_by_id(payload.fvg)


def build_orderblocks_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> list[dict]:
    bars, canonical_tf = _prepare_symbol_resampled_bars(df, symbol=symbol, timeframe=timeframe)
    if bars.empty:
        return []
    payload = build_structure_profile(
        bars,
        symbol=str(symbol),
        timeframe=canonical_tf,
        profile="hybrid_default",
        pivot_lookup=1,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    orderblocks = _dedupe_by_id(payload.orderblocks)
    # Backward-compatible ordering for helper callers that inspect the first zone.
    orderblocks.sort(key=lambda row: (bool(row.get("valid", True)), int(row.get("anchor_ts", 0))), reverse=True)
    return orderblocks


def build_explicit_structure_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    pivot_lookup: int = 1,
    structure_profile: str = "hybrid_default",
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> dict:
    canonical_tf = _canonical_timeframe(timeframe)
    normalized_profile = validate_structure_profile(structure_profile)
    bars = _coerce_bars(df)
    symbol_name = str(symbol).strip().upper()
    symbol_bars = bars.loc[bars["symbol"].eq(symbol_name)].copy()
    if symbol_bars.empty:
        raise ValueError(f"symbol {symbol_name} has no bars in source frame")

    resampled = resample_bars_to_timeframe(symbol_bars, canonical_tf)
    resampled["timestamp"] = coerce_timestamps_to_epoch_seconds(resampled["timestamp"])

    profile_result = build_structure_profile(
        resampled,
        symbol=symbol_name,
        timeframe=canonical_tf,
        profile=normalized_profile,
        pivot_lookup=pivot_lookup,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
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
            "structure_profile_used": normalized_profile,
            "event_logic_version": str(profile_result.diagnostics.get("event_logic_version", "v2")),
        },
    }


def build_full_structure_from_bars(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str,
    structure_profile: str = "hybrid_default",
    *,
    ticksize: float | None = None,
    asset_class: str | None = None,
    session_tz: str | None = None,
) -> dict:
    payload = build_explicit_structure_from_bars(
        df,
        symbol=symbol,
        timeframe=timeframe,
        pivot_lookup=1,
        structure_profile=structure_profile,
        ticksize=ticksize,
        asset_class=asset_class,
        session_tz=session_tz,
    )
    return {
        "bos": payload["bos"],
        "orderblocks": payload["orderblocks"],
        "fvg": payload["fvg"],
        "liquidity_sweeps": payload["liquidity_sweeps"],
    }
