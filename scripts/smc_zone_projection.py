"""V5.2 Zone Projection builder (DTFX-style zone context).

Projects expected zone behaviour forward: target zones, retest
expectation, trap risk, spread quality, and projection scoring.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_zone_projection import build_zone_projection, DEFAULTS

    proj = build_zone_projection(snapshot=base_snapshot_df)
    enrichment["zone_projection"] = proj
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "ZONE_PROJ_TARGET_BULL": 0.0,
    "ZONE_PROJ_TARGET_BEAR": 0.0,
    "ZONE_PROJ_RETEST_EXPECTED": False,
    "ZONE_PROJ_TRAP_RISK": "NONE",     # NONE | LOW | MEDIUM | HIGH
    "ZONE_PROJ_SPREAD_QUALITY": "NORMAL",  # TIGHT | NORMAL | WIDE
    "ZONE_PROJ_HTF_ALIGNED": False,
    "ZONE_PROJ_BIAS": "NEUTRAL",       # BULLISH | BEARISH | NEUTRAL
    "ZONE_PROJ_CONFIDENCE": 0,         # 0–5
    "ZONE_PROJ_DECAY_BARS": 0,         # bars since zone formation
    "ZONE_PROJ_SCORE": 0,              # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────

SPREAD_WIDE_BPS = 5.0        # spread above this = WIDE
SPREAD_TIGHT_BPS = 1.5       # spread below this = TIGHT
DECAY_STALE_BARS = 30        # OB older than this is stale
TRAP_RISK_SWEEP_DEPTH = 0.3  # depth threshold for trap risk


def build_zone_projection(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a zone projection block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with projection-related columns.
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    row = _resolve_row(snapshot, symbol)
    if row is not None:
        result["ZONE_PROJ_TARGET_BULL"] = float(row.get("zone_proj_target_bull", 0.0))
        result["ZONE_PROJ_TARGET_BEAR"] = float(row.get("zone_proj_target_bear", 0.0))
        result["ZONE_PROJ_RETEST_EXPECTED"] = bool(row.get("zone_proj_retest_expected", False))
        result["ZONE_PROJ_TRAP_RISK"] = _classify_trap_risk(row)
        result["ZONE_PROJ_SPREAD_QUALITY"] = _classify_spread(row)
        result["ZONE_PROJ_HTF_ALIGNED"] = bool(row.get("zone_proj_htf_aligned", False))
        result["ZONE_PROJ_DECAY_BARS"] = max(0, int(row.get("zone_proj_decay_bars", 0)))

        result["ZONE_PROJ_BIAS"] = _compute_bias(result)
        result["ZONE_PROJ_CONFIDENCE"] = _clamp(int(row.get("zone_proj_confidence", 0)), 0, 5)
        result["ZONE_PROJ_SCORE"] = _compute_score(result)

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


def _clamp(val: int, lo: int, hi: int) -> int:
    return max(lo, min(val, hi))


def _classify_trap_risk(row: dict[str, Any]) -> str:
    explicit = str(row.get("zone_proj_trap_risk", "")).upper()
    if explicit in ("LOW", "MEDIUM", "HIGH"):
        return explicit
    depth = float(row.get("zone_proj_sweep_depth", 0))
    if depth >= TRAP_RISK_SWEEP_DEPTH * 2:
        return "HIGH"
    if depth >= TRAP_RISK_SWEEP_DEPTH:
        return "MEDIUM"
    if depth > 0:
        return "LOW"
    return "NONE"


def _classify_spread(row: dict[str, Any]) -> str:
    spread = float(row.get("zone_proj_spread_bps", 2.5))
    if spread <= SPREAD_TIGHT_BPS:
        return "TIGHT"
    if spread >= SPREAD_WIDE_BPS:
        return "WIDE"
    return "NORMAL"


def _compute_bias(r: dict[str, Any]) -> str:
    bull = 0
    bear = 0
    if r["ZONE_PROJ_TARGET_BULL"] > 0:
        bull += 1
    if r["ZONE_PROJ_TARGET_BEAR"] > 0:
        bear += 1
    if r["ZONE_PROJ_HTF_ALIGNED"]:
        bull += 1
    if r["ZONE_PROJ_TRAP_RISK"] in ("MEDIUM", "HIGH"):
        bear += 1
    if bull > bear:
        return "BULLISH"
    if bear > bull:
        return "BEARISH"
    return "NEUTRAL"


def _compute_score(r: dict[str, Any]) -> int:
    score = 0
    if r["ZONE_PROJ_TARGET_BULL"] > 0 or r["ZONE_PROJ_TARGET_BEAR"] > 0:
        score += 1
    if r["ZONE_PROJ_HTF_ALIGNED"]:
        score += 1
    if r["ZONE_PROJ_SPREAD_QUALITY"] == "TIGHT":
        score += 1
    if r["ZONE_PROJ_TRAP_RISK"] == "NONE":
        score += 1
    if r["ZONE_PROJ_CONFIDENCE"] >= 3:
        score += 1
    return min(score, 5)
