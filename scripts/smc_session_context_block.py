"""V5.2 Session Context Block builder.

Derives session-aware context fields (killzone detection, session MSS/FVG
flags, direction bias) from timestamp and structural signals.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_session_context_block import build_session_context_block, DEFAULTS

    session = build_session_context_block(snapshot=base_snapshot_df)
    enrichment["session_context"] = session
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timezone
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Session definitions (UTC) ───────────────────────────────────

SESSIONS = {
    "ASIA":   (time(0, 0), time(8, 0)),
    "LONDON": (time(7, 0), time(15, 30)),
    "NY_AM":  (time(13, 30), time(17, 0)),
    "NY_PM":  (time(17, 0), time(20, 0)),
}

KILLZONES = {
    "ASIA_KZ":   (time(0, 0), time(4, 0)),
    "LONDON_KZ": (time(7, 0), time(10, 0)),
    "NY_KZ":     (time(13, 30), time(16, 0)),
}

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SESSION_CONTEXT": "NONE",
    "IN_KILLZONE": False,
    "SESSION_MSS_BULL": False,
    "SESSION_MSS_BEAR": False,
    "SESSION_STRUCTURE_STATE": "NEUTRAL",
    "SESSION_FVG_BULL_ACTIVE": False,
    "SESSION_FVG_BEAR_ACTIVE": False,
    "SESSION_BPR_ACTIVE": False,
    "SESSION_RANGE_TOP": 0.0,
    "SESSION_RANGE_BOTTOM": 0.0,
    "SESSION_MEAN": 0.0,
    "SESSION_VWAP": 0.0,
    "SESSION_TARGET_BULL": 0.0,
    "SESSION_TARGET_BEAR": 0.0,
    "SESSION_DIRECTION_BIAS": "NEUTRAL",
    "SESSION_CONTEXT_SCORE": 0,
}


def build_session_context_block(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    timestamp: datetime | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a session context block.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with session-related signal columns.
    symbol : str
        Ticker to filter in snapshot.
    timestamp : datetime, optional
        Current UTC time for session classification.
        Falls back to ``datetime.now(UTC)`` when not provided.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    ts = timestamp or datetime.now(timezone.utc)
    current_time = ts.time() if hasattr(ts, "time") else time(0, 0)

    result["SESSION_CONTEXT"] = _classify_session(current_time)
    result["IN_KILLZONE"] = _in_killzone(current_time)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        result["SESSION_MSS_BULL"] = bool(row.get("session_mss_bull", False))
        result["SESSION_MSS_BEAR"] = bool(row.get("session_mss_bear", False))
        result["SESSION_STRUCTURE_STATE"] = str(row.get("session_structure_state", "NEUTRAL"))
        result["SESSION_FVG_BULL_ACTIVE"] = bool(row.get("session_fvg_bull_active", False))
        result["SESSION_FVG_BEAR_ACTIVE"] = bool(row.get("session_fvg_bear_active", False))
        result["SESSION_BPR_ACTIVE"] = bool(row.get("session_bpr_active", False))
        result["SESSION_RANGE_TOP"] = float(row.get("session_range_top", 0.0))
        result["SESSION_RANGE_BOTTOM"] = float(row.get("session_range_bottom", 0.0))
        result["SESSION_MEAN"] = float(row.get("session_mean", 0.0))
        result["SESSION_VWAP"] = float(row.get("session_vwap", 0.0))
        result["SESSION_TARGET_BULL"] = float(row.get("session_target_bull", 0.0))
        result["SESSION_TARGET_BEAR"] = float(row.get("session_target_bear", 0.0))

    result["SESSION_DIRECTION_BIAS"] = _direction_bias(result)
    result["SESSION_CONTEXT_SCORE"] = _context_score(result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Helpers ─────────────────────────────────────────────────────


def _resolve_row(df: pd.DataFrame | None, symbol: str) -> dict[str, Any] | None:
    if df is None or df.empty:
        return None
    if symbol and "symbol" in df.columns:
        match = df.loc[df["symbol"] == symbol]
        if not match.empty:
            return match.iloc[0].to_dict()
    if len(df) == 1:
        return df.iloc[0].to_dict()
    return None


def _classify_session(t: time) -> str:
    # Check in reverse order so more specific/later sessions win
    # over broader ones (e.g. NY_AM over LONDON overlap).
    for name in reversed(SESSIONS):
        start, end = SESSIONS[name]
        if start <= end:
            if start <= t < end:
                return name
        else:
            if t >= start or t < end:
                return name
    return "NONE"


def _in_killzone(t: time) -> bool:
    for start, end in KILLZONES.values():
        if start <= end:
            if start <= t < end:
                return True
        else:
            if t >= start or t < end:
                return True
    return False


def _direction_bias(r: dict[str, Any]) -> str:
    bull = 0
    bear = 0
    if r["SESSION_MSS_BULL"]:
        bull += 2
    if r["SESSION_MSS_BEAR"]:
        bear += 2
    if r["SESSION_FVG_BULL_ACTIVE"]:
        bull += 1
    if r["SESSION_FVG_BEAR_ACTIVE"]:
        bear += 1
    if r["SESSION_TARGET_BULL"] > 0:
        bull += 1
    if r["SESSION_TARGET_BEAR"] > 0:
        bear += 1
    if bull > bear:
        return "BULLISH"
    if bear > bull:
        return "BEARISH"
    return "NEUTRAL"


def _context_score(r: dict[str, Any]) -> int:
    score = 0
    if r["SESSION_CONTEXT"] != "NONE":
        score += 1
    if r["IN_KILLZONE"]:
        score += 1
    if r["SESSION_MSS_BULL"] or r["SESSION_MSS_BEAR"]:
        score += 1
    if r["SESSION_FVG_BULL_ACTIVE"] or r["SESSION_FVG_BEAR_ACTIVE"]:
        score += 1
    if r["SESSION_DIRECTION_BIAS"] != "NEUTRAL":
        score += 1
    if r["SESSION_STRUCTURE_STATE"] != "NEUTRAL":
        score += 1
    if r["SESSION_BPR_ACTIVE"]:
        score += 1
    return min(score, 7)
