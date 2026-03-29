"""V5.1 Compression / ATR Regime builder.

Derives squeeze-state and ATR-regime fields from volatility metrics
in the base snapshot.  Concepts: compression → normal → expansion → exhaustion.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_compression_regime import build_compression_regime, DEFAULTS

    comp = build_compression_regime(snapshot=base_snapshot_df)
    enrichment["compression_regime"] = comp
"""
from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "SQUEEZE_ON": False,
    "SQUEEZE_RELEASED": False,
    "SQUEEZE_MOMENTUM_BIAS": "NEUTRAL",  # BULLISH | BEARISH | NEUTRAL
    "ATR_REGIME": "NORMAL",              # COMPRESSION | NORMAL | EXPANSION | EXHAUSTION
    "ATR_RATIO": 1.0,
}

# ── Thresholds (configurable, stable) ──────────────────────────────

ATR_COMPRESSION_UPPER = 0.7   # ATR ratio below this → COMPRESSION
ATR_EXPANSION_LOWER = 1.4     # ATR ratio above this → EXPANSION
ATR_EXHAUSTION_LOWER = 2.2    # ATR ratio above this → EXHAUSTION
BB_INSIDE_KC_THRESHOLD = 0.85 # BB width / KC width below this → squeeze on


def build_compression_regime(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compression/ATR regime block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with columns: ``atr_14``, ``atr_14_20d_mean``,
        ``bb_width``, ``kc_width``, ``bb_width_prev``, ``kc_width_prev``,
        ``momentum_value`` (or ``squeeze_momentum``).
        If None or empty, returns safe defaults.
    symbol : str
        Ticker to look up in the snapshot.
    overrides : dict, optional
        Manual overrides — flat merge, last wins.

    Returns
    -------
    dict
        Flat dict matching DEFAULTS keys.
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        row = _resolve_row(snapshot, symbol)
        if row is not None:
            # ATR ratio
            atr_now = float(row.get("atr_14", 0))
            atr_mean = float(row.get("atr_14_20d_mean", 0))
            result["ATR_RATIO"] = _safe_ratio(atr_now, atr_mean)

            # ATR regime classification
            result["ATR_REGIME"] = _classify_atr_regime(result["ATR_RATIO"])

            # Squeeze detection: BB inside Keltner Channel
            bb_width = float(row.get("bb_width", 0))
            kc_width = float(row.get("kc_width", 0))
            bb_prev = float(row.get("bb_width_prev", 0))
            kc_prev = float(row.get("kc_width_prev", 0))

            current_squeeze = _is_squeeze(bb_width, kc_width)
            prev_squeeze = _is_squeeze(bb_prev, kc_prev)

            result["SQUEEZE_ON"] = current_squeeze
            result["SQUEEZE_RELEASED"] = prev_squeeze and not current_squeeze

            # Momentum bias during/after squeeze
            momentum = float(row.get("momentum_value", 0) or row.get("squeeze_momentum", 0))
            if momentum > 0:
                result["SQUEEZE_MOMENTUM_BIAS"] = "BULLISH"
            elif momentum < 0:
                result["SQUEEZE_MOMENTUM_BIAS"] = "BEARISH"
            else:
                result["SQUEEZE_MOMENTUM_BIAS"] = "NEUTRAL"

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_row(df: pd.DataFrame, symbol: str) -> dict[str, Any] | None:
    if symbol and "symbol" in df.columns:
        match = df.loc[df["symbol"] == symbol]
        if not match.empty:
            return match.iloc[0].to_dict()
    if len(df) == 1:
        return df.iloc[0].to_dict()
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    num = float(numerator or 0)
    den = float(denominator or 0)
    if den <= 0:
        return 1.0
    return round(num / den, 4)


def _is_squeeze(bb_width: float, kc_width: float) -> bool:
    """Bollinger Band inside Keltner Channel → squeeze."""
    if kc_width <= 0:
        return False
    return (bb_width / kc_width) < BB_INSIDE_KC_THRESHOLD


def _classify_atr_regime(atr_ratio: float) -> str:
    """Classify ATR regime from ratio of current to 20d mean."""
    if atr_ratio >= ATR_EXHAUSTION_LOWER:
        return "EXHAUSTION"
    if atr_ratio >= ATR_EXPANSION_LOWER:
        return "EXPANSION"
    if atr_ratio <= ATR_COMPRESSION_UPPER:
        return "COMPRESSION"
    return "NORMAL"
