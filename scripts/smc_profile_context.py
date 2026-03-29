"""V5.2 Profile Context builder.

Aggregates ticker-level microstructure profile characteristics:
volume profile, VWAP relationship, spread regime, session behaviour,
decay characteristics, and per-symbol quality scoring.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_profile_context import build_profile_context, DEFAULTS

    profile = build_profile_context(snapshot=base_snapshot_df)
    enrichment["profile_context"] = profile
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "PROFILE_VOLUME_NODE": "NONE",        # HVN | LVN | POC | NONE
    "PROFILE_VWAP_POSITION": "AT",        # ABOVE | BELOW | AT
    "PROFILE_VWAP_DISTANCE_PCT": 0.0,
    "PROFILE_SPREAD_REGIME": "NORMAL",    # TIGHT | NORMAL | WIDE
    "PROFILE_AVG_SPREAD_BPS": 0.0,
    "PROFILE_SESSION_BIAS": "NEUTRAL",    # BULLISH | BEARISH | NEUTRAL
    "PROFILE_RTH_DOMINANCE_PCT": 0.0,
    "PROFILE_PM_QUALITY": "NORMAL",       # STRONG | NORMAL | WEAK
    "PROFILE_AH_QUALITY": "NORMAL",       # STRONG | NORMAL | WEAK
    "PROFILE_MIDDAY_EFFICIENCY": 0.0,
    "PROFILE_DECAY_HALFLIFE": 0.0,
    "PROFILE_CONSISTENCY": 0.0,           # 0.0–1.0
    "PROFILE_WICKINESS": 0.0,
    "PROFILE_CLEAN_SCORE": 0.0,           # 0.0–1.0
    "PROFILE_RECLAIM_RATE": 0.0,          # 0.0–1.0
    "PROFILE_STOP_HUNT_RATE": 0.0,
    "PROFILE_TICKER_GRADE": "C",          # A | B | C | D
    "PROFILE_CONTEXT_SCORE": 0,           # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────

SPREAD_TIGHT_BPS = 1.5
SPREAD_WIDE_BPS = 5.0
VWAP_AT_THRESHOLD_PCT = 0.1
PM_STRONG_SHARE = 0.20
PM_WEAK_SHARE = 0.05
AH_STRONG_SHARE = 0.15
AH_WEAK_SHARE = 0.03
GRADE_A_CLEAN = 0.90
GRADE_B_CLEAN = 0.75
GRADE_D_CLEAN = 0.50


def build_profile_context(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a profile context block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with profile/quality columns.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        # Volume profile node
        node = str(row.get("profile_volume_node", "")).upper()
        if node in ("HVN", "LVN", "POC"):
            result["PROFILE_VOLUME_NODE"] = node

        # VWAP
        vwap_dist = float(row.get("profile_vwap_distance_pct", 0.0))
        result["PROFILE_VWAP_DISTANCE_PCT"] = round(vwap_dist, 4)
        if vwap_dist > VWAP_AT_THRESHOLD_PCT:
            result["PROFILE_VWAP_POSITION"] = "ABOVE"
        elif vwap_dist < -VWAP_AT_THRESHOLD_PCT:
            result["PROFILE_VWAP_POSITION"] = "BELOW"
        else:
            result["PROFILE_VWAP_POSITION"] = "AT"

        # Spread
        spread = float(row.get("avg_spread_bps_rth_20d", 0.0))
        result["PROFILE_AVG_SPREAD_BPS"] = round(spread, 2)
        if spread <= SPREAD_TIGHT_BPS:
            result["PROFILE_SPREAD_REGIME"] = "TIGHT"
        elif spread >= SPREAD_WIDE_BPS:
            result["PROFILE_SPREAD_REGIME"] = "WIDE"
        else:
            result["PROFILE_SPREAD_REGIME"] = "NORMAL"

        # Session characteristics
        rth_share = float(row.get("rth_active_minutes_share_20d", 0.0))
        result["PROFILE_RTH_DOMINANCE_PCT"] = round(rth_share * 100, 2)

        pm_share = float(row.get("pm_dollar_share_20d", 0.0))
        result["PROFILE_PM_QUALITY"] = _quality_label(pm_share, PM_STRONG_SHARE, PM_WEAK_SHARE)

        ah_share = float(row.get("ah_dollar_share_20d", 0.0))
        result["PROFILE_AH_QUALITY"] = _quality_label(ah_share, AH_STRONG_SHARE, AH_WEAK_SHARE)

        result["PROFILE_MIDDAY_EFFICIENCY"] = round(float(row.get("midday_efficiency_20d", 0.0)), 4)
        result["PROFILE_DECAY_HALFLIFE"] = round(float(row.get("setup_decay_half_life_bars_20d", 0.0)), 2)
        result["PROFILE_CONSISTENCY"] = round(float(row.get("consistency_score_20d", 0.0)), 4)
        result["PROFILE_WICKINESS"] = round(float(row.get("wickiness_20d", 0.0)), 4)
        result["PROFILE_CLEAN_SCORE"] = round(float(row.get("clean_intraday_score_20d", 0.0)), 4)
        result["PROFILE_RECLAIM_RATE"] = round(float(row.get("reclaim_respect_rate_20d", 0.0)), 4)
        result["PROFILE_STOP_HUNT_RATE"] = round(float(row.get("stop_hunt_rate_20d", 0.0)), 4)

        result["PROFILE_SESSION_BIAS"] = _session_bias(row)
        result["PROFILE_TICKER_GRADE"] = _ticker_grade(result)
        result["PROFILE_CONTEXT_SCORE"] = _context_score(result)

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


def _quality_label(share: float, strong_threshold: float, weak_threshold: float) -> str:
    if share >= strong_threshold:
        return "STRONG"
    if share <= weak_threshold:
        return "WEAK"
    return "NORMAL"


def _session_bias(row: dict[str, Any]) -> str:
    open_share = float(row.get("open_30m_dollar_share_20d", 0.0))
    close_share = float(row.get("close_60m_dollar_share_20d", 0.0))
    if open_share > close_share + 0.05:
        return "BULLISH"
    if close_share > open_share + 0.05:
        return "BEARISH"
    return "NEUTRAL"


def _ticker_grade(r: dict[str, Any]) -> str:
    clean = r["PROFILE_CLEAN_SCORE"]
    if clean >= GRADE_A_CLEAN:
        return "A"
    if clean >= GRADE_B_CLEAN:
        return "B"
    if clean >= GRADE_D_CLEAN:
        return "C"
    return "D"


def _context_score(r: dict[str, Any]) -> int:
    score = 0
    if r["PROFILE_TICKER_GRADE"] in ("A", "B"):
        score += 1
    if r["PROFILE_SPREAD_REGIME"] == "TIGHT":
        score += 1
    if r["PROFILE_CONSISTENCY"] >= 0.85:
        score += 1
    if r["PROFILE_RECLAIM_RATE"] >= 0.80:
        score += 1
    if r["PROFILE_PM_QUALITY"] == "STRONG":
        score += 1
    return min(score, 5)
