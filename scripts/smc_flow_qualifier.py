"""V5.1 Flow Qualifier builder.

Derives a flat flow-qualification block from microstructure base data
(volume, trade count, average trade size) to produce Pine-compatible
scalar fields for relative volume, relative activity, delta proxy,
and ATS (Average Trade Size) regime analysis.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_flow_qualifier import build_flow_qualifier, DEFAULTS

    flow = build_flow_qualifier(snapshot=base_snapshot_df)
    enrichment["flow_qualifier"] = flow
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "REL_VOL": 1.0,
    "REL_ACTIVITY": 1.0,
    "REL_SIZE": 1.0,
    "DELTA_PROXY_PCT": 0.0,
    "FLOW_LONG_OK": True,
    "FLOW_SHORT_OK": True,
    "ATS_VALUE": 0.0,
    "ATS_CHANGE_PCT": 0.0,
    "ATS_ZSCORE": 0.0,
    "ATS_STATE": "NEUTRAL",
    "ATS_SPIKE_UP": False,
    "ATS_SPIKE_DOWN": False,
    "ATS_BULLISH_SEQUENCE": False,
    "ATS_BEARISH_SEQUENCE": False,
}

# ── Thresholds (configurable, stable) ──────────────────────────────

REL_VOL_STRONG = 1.5       # volume ratio above which flow is notable
REL_VOL_WEAK = 0.5         # volume ratio below which flow is suspect
ATS_SPIKE_Z = 2.0          # z-score threshold for ATS spike detection
ATS_CHANGE_STRONG = 15.0   # ATS % change considered significant
ATS_SEQUENCE_LEN = 3       # consecutive bars needed for sequence
DELTA_STRONG_PCT = 10.0    # delta proxy % to block counter-flow


def build_flow_qualifier(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a flow qualifier block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        Base snapshot with columns like ``volume_today``,
        ``volume_avg_20d``, ``trade_count_today``,
        ``trade_count_avg_20d``, ``avg_trade_size``,
        ``avg_trade_size_20d_mean``, ``avg_trade_size_20d_std``,
        ``close_change_pct``, ``buy_volume_pct``.
        If None or empty, returns safe defaults.
    symbol : str
        Ticker to look up in the snapshot. If empty, uses
        universe-level aggregates.
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
            result["REL_VOL"] = _safe_ratio(
                row.get("volume_today", 0),
                row.get("volume_avg_20d", 0),
            )
            result["REL_ACTIVITY"] = _safe_ratio(
                row.get("trade_count_today", 0),
                row.get("trade_count_avg_20d", 0),
            )
            result["REL_SIZE"] = _safe_ratio(
                row.get("avg_trade_size", 0),
                row.get("avg_trade_size_20d_mean", 0),
            )

            # Delta proxy: buy_volume_pct mapped to signed %
            buy_pct = float(row.get("buy_volume_pct", 50.0))
            result["DELTA_PROXY_PCT"] = round((buy_pct - 50.0) * 2.0, 2)

            # ATS analysis
            ats_now = float(row.get("avg_trade_size", 0))
            ats_mean = float(row.get("avg_trade_size_20d_mean", 0))
            ats_std = float(row.get("avg_trade_size_20d_std", 0))

            result["ATS_VALUE"] = round(ats_now, 2)
            result["ATS_CHANGE_PCT"] = _safe_change_pct(ats_now, ats_mean)
            result["ATS_ZSCORE"] = _safe_zscore(ats_now, ats_mean, ats_std)

            result["ATS_STATE"] = _classify_ats_state(
                result["ATS_ZSCORE"], result["ATS_CHANGE_PCT"]
            )
            result["ATS_SPIKE_UP"] = result["ATS_ZSCORE"] >= ATS_SPIKE_Z
            result["ATS_SPIKE_DOWN"] = result["ATS_ZSCORE"] <= -ATS_SPIKE_Z

            # Sequence detection from historical columns
            result["ATS_BULLISH_SEQUENCE"] = _detect_sequence(
                row, "ats_rising_streak", ATS_SEQUENCE_LEN
            )
            result["ATS_BEARISH_SEQUENCE"] = _detect_sequence(
                row, "ats_falling_streak", ATS_SEQUENCE_LEN
            )

            # Flow direction gates
            delta = result["DELTA_PROXY_PCT"]
            rel_vol = result["REL_VOL"]
            result["FLOW_LONG_OK"] = not (
                delta < -DELTA_STRONG_PCT and rel_vol > REL_VOL_STRONG
            )
            result["FLOW_SHORT_OK"] = not (
                delta > DELTA_STRONG_PCT and rel_vol > REL_VOL_STRONG
            )

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


# ── Helpers ─────────────────────────────────────────────────────────


def _resolve_row(df: pd.DataFrame, symbol: str) -> dict[str, Any] | None:
    """Extract a single row dict from the snapshot."""
    if symbol and "symbol" in df.columns:
        match = df.loc[df["symbol"] == symbol]
        if not match.empty:
            return match.iloc[0].to_dict()
    # Fallback: use first row or mean of numeric columns
    if len(df) == 1:
        return df.iloc[0].to_dict()
    return None


def _safe_ratio(numerator: float, denominator: float) -> float:
    """Return ratio or 1.0 when denominator is zero/missing."""
    num = float(numerator or 0)
    den = float(denominator or 0)
    if den <= 0:
        return 1.0
    return round(num / den, 4)


def _safe_change_pct(current: float, baseline: float) -> float:
    """Percentage change, safe on zero baseline."""
    if baseline <= 0:
        return 0.0
    return round(((current - baseline) / baseline) * 100.0, 2)


def _safe_zscore(value: float, mean: float, std: float) -> float:
    """Z-score, safe on zero std."""
    if std <= 0:
        return 0.0
    return round((value - mean) / std, 4)


def _classify_ats_state(zscore: float, change_pct: float) -> str:
    """Classify ATS into one of four states."""
    if zscore >= ATS_SPIKE_Z:
        return "SPIKE_UP"
    if zscore <= -ATS_SPIKE_Z:
        return "SPIKE_DOWN"
    if abs(change_pct) > ATS_CHANGE_STRONG:
        return "ELEVATED" if change_pct > 0 else "DEPRESSED"
    return "NEUTRAL"


def _detect_sequence(
    row: dict[str, Any], column: str, min_len: int
) -> bool:
    """Check if a streak column indicates a sequence of min_len."""
    val = row.get(column, 0)
    try:
        return int(val) >= min_len
    except (TypeError, ValueError):
        return False
