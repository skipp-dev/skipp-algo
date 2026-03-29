"""V5.3 Session-Scoped Structure builder.

Combines session awareness (v5.2 Session Context) with intra-session
structural tracking.  Answers *"what has happened structurally inside
this session?"* — opening-range breaks, intra-session BOS/CHoCH,
PDH/PDL sweeps, and session impulse direction.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_session_structure import build_session_structure, DEFAULTS

    sess = build_session_structure(snapshot=base_snapshot_df, timestamp=now)
    enrichment["session_structure"] = sess
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SESS_HIGH": 0.0,
    "SESS_LOW": 0.0,
    "SESS_OPEN_RANGE_HIGH": 0.0,
    "SESS_OPEN_RANGE_LOW": 0.0,
    "SESS_OPEN_RANGE_BREAK": "NONE",       # NONE | ABOVE | BELOW
    "SESS_IMPULSE_DIR": "NONE",            # NONE | BULL | BEAR
    "SESS_IMPULSE_STRENGTH": 0,            # 0–5
    "SESS_INTRA_BOS_COUNT": 0,
    "SESS_INTRA_CHOCH": False,
    "SESS_PDH": 0.0,
    "SESS_PDL": 0.0,
    "SESS_PDH_SWEPT": False,
    "SESS_PDL_SWEPT": False,
    "SESS_STRUCT_SCORE": 0,                # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────────

OPEN_RANGE_BARS = 5         # first N bars form the opening range
IMPULSE_MIN_PCT = 0.15      # min move % of price for impulse credit


def build_session_structure(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    timestamp: datetime | None = None,
    prev_day_snapshot: pd.DataFrame | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a session-scoped structure block.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Intra-session OHLC bars (current session only).
    symbol : str
        Optional symbol filter.
    timestamp : datetime, optional
        Current UTC time (unused currently but reserved for session gating).
    prev_day_snapshot : DataFrame, optional
        Previous day summary with ``high``/``low`` columns.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.

    Returns
    -------
    dict[str, Any]
        Flat dict matching the session-scoped structure contract (14 fields).
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        df = snapshot.copy()
        if symbol and "symbol" in df.columns:
            df = df[df["symbol"] == symbol]

        if not df.empty:
            result = _derive_session_structure(df, result)

    # PDH / PDL from previous day snapshot
    if prev_day_snapshot is not None and not prev_day_snapshot.empty:
        pdf = prev_day_snapshot
        if symbol and "symbol" in pdf.columns:
            pdf = pdf[pdf["symbol"] == symbol]
        if not pdf.empty:
            row = pdf.iloc[-1]
            result["SESS_PDH"] = float(row.get("high", 0.0))
            result["SESS_PDL"] = float(row.get("low", 0.0))

    # PDH/PDL sweep detection
    if result["SESS_PDH"] > 0 and result["SESS_HIGH"] > 0:
        if result["SESS_HIGH"] > result["SESS_PDH"]:
            result["SESS_PDH_SWEPT"] = True
    if result["SESS_PDL"] > 0 and result["SESS_LOW"] > 0:
        if result["SESS_LOW"] < result["SESS_PDL"]:
            result["SESS_PDL_SWEPT"] = True

    # Composite score
    result["SESS_STRUCT_SCORE"] = _session_score(result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


def _derive_session_structure(
    df: pd.DataFrame, result: dict[str, Any]
) -> dict[str, Any]:
    """Derive session structure from intra-session OHLC bars."""
    for col in ("high", "low", "close", "open"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if not {"high", "low", "close", "open"}.issubset(df.columns):
        return result

    df = df.dropna(subset=["high", "low", "close", "open"]).reset_index(drop=True)
    if len(df) < 1:
        return result

    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    closes = df["close"].astype(float)

    # Session high / low
    result["SESS_HIGH"] = float(highs.max())
    result["SESS_LOW"] = float(lows.min())

    # Opening range (first OPEN_RANGE_BARS bars)
    or_bars = min(OPEN_RANGE_BARS, len(df))
    result["SESS_OPEN_RANGE_HIGH"] = float(highs.iloc[:or_bars].max())
    result["SESS_OPEN_RANGE_LOW"] = float(lows.iloc[:or_bars].min())

    # Opening range break
    last_close = float(closes.iloc[-1])
    if last_close > result["SESS_OPEN_RANGE_HIGH"]:
        result["SESS_OPEN_RANGE_BREAK"] = "ABOVE"
    elif last_close < result["SESS_OPEN_RANGE_LOW"]:
        result["SESS_OPEN_RANGE_BREAK"] = "BELOW"

    # Intra-session BOS / CHoCH (3-bar pivot swing detection)
    if len(df) >= 3:
        swing_highs: list[tuple[int, float]] = []
        swing_lows: list[tuple[int, float]] = []
        for i in range(1, len(df) - 1):
            h = float(highs.iloc[i])
            if h > float(highs.iloc[i - 1]) and h > float(highs.iloc[i + 1]):
                swing_highs.append((i, h))
            lo = float(lows.iloc[i])
            if lo < float(lows.iloc[i - 1]) and lo < float(lows.iloc[i + 1]):
                swing_lows.append((i, lo))

        bos_count = 0
        choch_detected = False

        # BOS: successive swing highs / lows breaking prior levels
        if len(swing_highs) >= 2:
            for j in range(1, len(swing_highs)):
                if swing_highs[j][1] > swing_highs[j - 1][1]:
                    bos_count += 1  # bull BOS
                elif swing_highs[j][1] < swing_highs[j - 1][1]:
                    bos_count += 1  # bear BOS (lower high)

        if len(swing_lows) >= 2:
            for j in range(1, len(swing_lows)):
                if swing_lows[j][1] < swing_lows[j - 1][1]:
                    bos_count += 1  # bear BOS
                elif swing_lows[j][1] > swing_lows[j - 1][1]:
                    bos_count += 1  # bull BOS (higher low)

        # CHoCH: last swing breaks against prior trend
        if swing_highs and swing_lows:
            last_sh = swing_highs[-1]
            last_sl = swing_lows[-1]
            if last_sh[0] > last_sl[0]:
                # Latest event was a swing high — check if close broke below prior swing low
                if last_close < last_sl[1]:
                    choch_detected = True
            else:
                # Latest event was a swing low — check if close broke above prior swing high
                if last_close > last_sh[1]:
                    choch_detected = True

        result["SESS_INTRA_BOS_COUNT"] = bos_count
        result["SESS_INTRA_CHOCH"] = choch_detected

    # Session impulse direction
    if len(df) >= 2:
        first_open = float(df.iloc[0]["open"])
        if first_open > 0:
            move_pct = abs(last_close - first_open) / first_open * 100
            if move_pct >= IMPULSE_MIN_PCT:
                result["SESS_IMPULSE_DIR"] = "BULL" if last_close > first_open else "BEAR"
                # Strength: 1 point per 0.15% move, capped at 5
                result["SESS_IMPULSE_STRENGTH"] = min(
                    int(move_pct / IMPULSE_MIN_PCT), 5
                )

    return result


def _session_score(r: dict[str, Any]) -> int:
    """Compute composite session-structure quality score (0–5)."""
    score = 0
    if r["SESS_OPEN_RANGE_BREAK"] != "NONE":
        score += 1
    if r["SESS_INTRA_BOS_COUNT"] > 0:
        score += 1
    if r["SESS_IMPULSE_DIR"] != "NONE":
        score += 1
    if r["SESS_PDH_SWEPT"] or r["SESS_PDL_SWEPT"]:
        score += 1
    if r["SESS_INTRA_CHOCH"]:
        score += 1
    return min(score, 5)
