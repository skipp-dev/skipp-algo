"""V5.1 Reversal Context builder.

Derives a reversal-confidence context block from higher-timeframe
structure, divergence signals, and confluence checks.  This is a
confidence / context layer — it does NOT replace the SMC engine.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_reversal_context import build_reversal_context, DEFAULTS

    rev = build_reversal_context(snapshot=base_snapshot_df)
    enrichment["reversal_context"] = rev
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "REVERSAL_CONTEXT_ACTIVE": False,
    "SETUP_SCORE": 0,           # 0–5: composite setup quality
    "CONFIRM_SCORE": 0,         # 0–5: confirmation strength
    "FOLLOW_THROUGH_SCORE": 0,  # 0–5: post-confirm continuation quality
    "HTF_STRUCTURE_OK": False,
    "HTF_BULLISH_PATTERN": False,
    "HTF_BEARISH_PATTERN": False,
    "HTF_BULLISH_DIVERGENCE": False,
    "HTF_BEARISH_DIVERGENCE": False,
    "FVG_CONFIRM_OK": False,
    "VWAP_HOLD_OK": False,
    "RETRACE_OK": False,
}

# ── Score thresholds ────────────────────────────────────────────────

SETUP_ACTIVE_THRESHOLD = 2     # setup_score >= this → context active
CONFIRM_STRONG_THRESHOLD = 3   # confirm_score >= this → strong confirm
RETRACE_MAX_PCT = 61.8         # Fibonacci — max retrace depth allowed


def build_reversal_context(
    *,
    snapshot: pd.DataFrame | None = None,
    signals: dict[str, Any] | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a reversal context block.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with HTF structure columns.
    signals : dict, optional
        Explicit signal dict with boolean/numeric keys matching
        DEFAULTS (e.g. from a Pine or external signal source).
    symbol : str
        Ticker to filter in snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.
    """
    result = dict(DEFAULTS)

    sig = signals or {}
    if snapshot is not None and not snapshot.empty:
        sig = _extract_signals_from_snapshot(snapshot, symbol, sig)

    if sig:
        # HTF structure booleans
        result["HTF_STRUCTURE_OK"] = bool(sig.get("htf_structure_ok", False))
        result["HTF_BULLISH_PATTERN"] = bool(sig.get("htf_bullish_pattern", False))
        result["HTF_BEARISH_PATTERN"] = bool(sig.get("htf_bearish_pattern", False))
        result["HTF_BULLISH_DIVERGENCE"] = bool(sig.get("htf_bullish_divergence", False))
        result["HTF_BEARISH_DIVERGENCE"] = bool(sig.get("htf_bearish_divergence", False))

        # Confluence checks
        result["FVG_CONFIRM_OK"] = bool(sig.get("fvg_confirm_ok", False))
        result["VWAP_HOLD_OK"] = bool(sig.get("vwap_hold_ok", False))

        # Retrace check
        retrace_pct = float(sig.get("retrace_pct", 100.0))
        result["RETRACE_OK"] = retrace_pct <= RETRACE_MAX_PCT

        # Score computation
        result["SETUP_SCORE"] = _compute_setup_score(result)
        result["CONFIRM_SCORE"] = _compute_confirm_score(result, sig)
        result["FOLLOW_THROUGH_SCORE"] = _compute_follow_through_score(result, sig)

        # Reversal context active if setup is good enough
        result["REVERSAL_CONTEXT_ACTIVE"] = (
            result["SETUP_SCORE"] >= SETUP_ACTIVE_THRESHOLD
        )

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Score helpers ───────────────────────────────────────────────────


def _compute_setup_score(r: dict[str, Any]) -> int:
    """Setup score: count of boolean confluence factors (0–5)."""
    score = 0
    if r["HTF_STRUCTURE_OK"]:
        score += 1
    if r["HTF_BULLISH_PATTERN"] or r["HTF_BEARISH_PATTERN"]:
        score += 1
    if r["HTF_BULLISH_DIVERGENCE"] or r["HTF_BEARISH_DIVERGENCE"]:
        score += 1
    if r["FVG_CONFIRM_OK"]:
        score += 1
    if r["RETRACE_OK"]:
        score += 1
    return min(score, 5)


def _compute_confirm_score(r: dict[str, Any], sig: dict[str, Any]) -> int:
    """Confirmation score: quality of the confirmation signal (0–5)."""
    score = 0
    if r["FVG_CONFIRM_OK"]:
        score += 1
    if r["VWAP_HOLD_OK"]:
        score += 1
    if r["RETRACE_OK"]:
        score += 1
    if bool(sig.get("volume_confirm", False)):
        score += 1
    if bool(sig.get("close_strength_ok", False)):
        score += 1
    return min(score, 5)


def _compute_follow_through_score(r: dict[str, Any], sig: dict[str, Any]) -> int:
    """Follow-through score: post-confirm continuation quality (0–5)."""
    score = 0
    if r["HTF_STRUCTURE_OK"]:
        score += 1
    if r["VWAP_HOLD_OK"]:
        score += 1
    if bool(sig.get("momentum_positive", False)):
        score += 1
    if bool(sig.get("higher_low_formed", False)):
        score += 1
    if bool(sig.get("volume_follow_through", False)):
        score += 1
    return min(score, 5)


# ── Snapshot extraction ─────────────────────────────────────────────


def _extract_signals_from_snapshot(
    df: pd.DataFrame, symbol: str, existing: dict[str, Any]
) -> dict[str, Any]:
    """Merge snapshot columns into signal dict."""
    sig = dict(existing)
    row = None
    if symbol and "symbol" in df.columns:
        match = df.loc[df["symbol"] == symbol]
        if not match.empty:
            row = match.iloc[0]
    elif len(df) == 1:
        row = df.iloc[0]

    if row is not None:
        # Map snapshot columns to signal keys
        col_map = {
            "htf_structure_ok": "htf_structure_ok",
            "htf_bullish_pattern": "htf_bullish_pattern",
            "htf_bearish_pattern": "htf_bearish_pattern",
            "htf_bullish_divergence": "htf_bullish_divergence",
            "htf_bearish_divergence": "htf_bearish_divergence",
            "fvg_confirm_ok": "fvg_confirm_ok",
            "vwap_hold_ok": "vwap_hold_ok",
            "retrace_pct": "retrace_pct",
            "volume_confirm": "volume_confirm",
            "close_strength_ok": "close_strength_ok",
            "momentum_positive": "momentum_positive",
            "higher_low_formed": "higher_low_formed",
            "volume_follow_through": "volume_follow_through",
        }
        for col, key in col_map.items():
            if col in row.index and key not in sig:
                sig[key] = row[col]

    return sig
