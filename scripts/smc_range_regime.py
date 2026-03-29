"""V5.3 Range / Profile Regime builder.

Detects whether the instrument is in a ranging, trending, or breakout
regime and quantifies range boundaries plus basic volume-profile levels.

Answers *"is this a range day or a trend day?"* — a question that
fundamentally alters trade management (fade vs follow).

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_range_regime import build_range_regime, DEFAULTS

    rng = build_range_regime(snapshot=base_snapshot_df)
    enrichment["range_regime"] = rng
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "RANGE_REGIME": "UNKNOWN",             # TRENDING | RANGING | BREAKOUT | UNKNOWN
    "RANGE_WIDTH_PCT": 0.0,
    "RANGE_POSITION": "MID",               # HIGH | MID | LOW
    "RANGE_HIGH": 0.0,
    "RANGE_LOW": 0.0,
    "RANGE_DURATION_BARS": 0,
    "RANGE_VPOC_LEVEL": 0.0,
    "RANGE_VAH_LEVEL": 0.0,
    "RANGE_VAL_LEVEL": 0.0,
    "RANGE_BALANCE_STATE": "BALANCED",     # BALANCED | IMBALANCED_UP | IMBALANCED_DOWN
    "RANGE_REGIME_SCORE": 0,               # 0–5
}

# ── Thresholds ──────────────────────────────────────────────────────

RANGE_WIDTH_THRESHOLD = 2.0    # % — width below this counts as "ranging"
TREND_SLOPE_THRESHOLD = 0.3    # % per bar — above this is trending
BREAKOUT_ATR_MULT = 1.5        # close beyond range boundary × ATR = breakout
VALUE_AREA_PCT = 0.70          # 70% of volume for VAH/VAL


def build_range_regime(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a range/profile regime block from a base snapshot.

    Parameters
    ----------
    snapshot : DataFrame, optional
        OHLCV bars for range detection.
    symbol : str
        Optional symbol filter.
    overrides : dict, optional
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict matching the range regime contract (11 fields).
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        df = snapshot.copy()
        if symbol and "symbol" in df.columns:
            df = df[df["symbol"] == symbol]

        if not df.empty:
            result = _derive_regime(df, result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


def _derive_regime(df: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    """Derive range regime from OHLCV bars."""
    for col in ("high", "low", "close", "open"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if not {"high", "low", "close"}.issubset(df.columns):
        return result

    df = df.dropna(subset=["high", "low", "close"]).reset_index(drop=True)
    if len(df) < 3:
        return result

    highs = df["high"].astype(float)
    lows = df["low"].astype(float)
    closes = df["close"].astype(float)

    # Use all-bar range for output fields
    range_high = float(highs.max())
    range_low = float(lows.min())
    mid_price = (range_high + range_low) / 2 if (range_high + range_low) > 0 else 1.0

    result["RANGE_HIGH"] = range_high
    result["RANGE_LOW"] = range_low

    # Prior-bar range (excl last) for breakout detection
    prior_high = float(highs.iloc[:-1].max())
    prior_low = float(lows.iloc[:-1].min())

    # Range width as % of mid-price
    range_width_pct = (range_high - range_low) / mid_price * 100 if mid_price > 0 else 0.0
    result["RANGE_WIDTH_PCT"] = round(range_width_pct, 4)

    # Current position in range
    last_close = float(closes.iloc[-1])
    if range_high > range_low:
        position_ratio = (last_close - range_low) / (range_high - range_low)
        if position_ratio >= 0.67:
            result["RANGE_POSITION"] = "HIGH"
        elif position_ratio <= 0.33:
            result["RANGE_POSITION"] = "LOW"
        else:
            result["RANGE_POSITION"] = "MID"

    # Trend slope (linear regression on closes)
    n = len(closes)
    x = np.arange(n, dtype=float)
    slope = float(np.polyfit(x, closes.values, 1)[0]) if n >= 2 else 0.0
    slope_pct_per_bar = abs(slope) / mid_price * 100 if mid_price > 0 else 0.0

    # ATR (simple, excluding last bar to avoid breakout bar skewing)
    tr_vals = []
    for i in range(1, len(df) - 1):
        h = float(highs.iloc[i])
        lo = float(lows.iloc[i])
        pc = float(closes.iloc[i - 1])
        tr_vals.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    atr = float(np.mean(tr_vals)) if tr_vals else 0.0

    # Regime classification — breakout uses prior-bar range + ATR
    breakout_threshold = prior_high + atr * BREAKOUT_ATR_MULT if atr > 0 else prior_high
    breakdown_threshold = prior_low - atr * BREAKOUT_ATR_MULT if atr > 0 else prior_low

    if last_close > breakout_threshold or last_close < breakdown_threshold:
        result["RANGE_REGIME"] = "BREAKOUT"
    elif slope_pct_per_bar >= TREND_SLOPE_THRESHOLD:
        result["RANGE_REGIME"] = "TRENDING"
    elif range_width_pct <= RANGE_WIDTH_THRESHOLD:
        result["RANGE_REGIME"] = "RANGING"
    else:
        result["RANGE_REGIME"] = "RANGING"

    # Range duration: count consecutive bars within the range (from the end)
    duration = 0
    for i in range(len(df) - 1, -1, -1):
        bar_h = float(highs.iloc[i])
        bar_l = float(lows.iloc[i])
        if bar_l >= range_low and bar_h <= range_high:
            duration += 1
        else:
            break
    result["RANGE_DURATION_BARS"] = duration

    # Volume profile (VPOC, VAH, VAL)
    if "volume" in df.columns:
        volumes = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float)
        if float(volumes.sum()) > 0:
            _compute_volume_profile(closes, volumes, result)

    # Balance state
    if slope > 0 and slope_pct_per_bar >= TREND_SLOPE_THRESHOLD / 2:
        result["RANGE_BALANCE_STATE"] = "IMBALANCED_UP"
    elif slope < 0 and slope_pct_per_bar >= TREND_SLOPE_THRESHOLD / 2:
        result["RANGE_BALANCE_STATE"] = "IMBALANCED_DOWN"
    else:
        result["RANGE_BALANCE_STATE"] = "BALANCED"

    # Regime score
    result["RANGE_REGIME_SCORE"] = _regime_score(result, slope_pct_per_bar)

    return result


def _compute_volume_profile(
    closes: pd.Series, volumes: pd.Series, result: dict[str, Any]
) -> None:
    """Simple volume-at-price profile for VPOC, VAH, VAL."""
    price_min = float(closes.min())
    price_max = float(closes.max())
    if price_max <= price_min:
        return

    n_bins = max(10, len(closes))
    bins = np.linspace(price_min, price_max, n_bins + 1)
    bin_volumes = np.zeros(n_bins)

    for price, vol in zip(closes.values, volumes.values):
        idx = int((float(price) - price_min) / (price_max - price_min) * (n_bins - 1))
        idx = min(max(idx, 0), n_bins - 1)
        bin_volumes[idx] += float(vol)

    total_vol = float(bin_volumes.sum())
    if total_vol <= 0:
        return

    # VPOC: bin with highest volume
    vpoc_idx = int(np.argmax(bin_volumes))
    result["RANGE_VPOC_LEVEL"] = round(float((bins[vpoc_idx] + bins[vpoc_idx + 1]) / 2), 4)

    # VAH/VAL: 70% of volume centered on VPOC
    sorted_indices = np.argsort(bin_volumes)[::-1]
    cum_vol = 0.0
    va_indices: list[int] = []
    for idx in sorted_indices:
        cum_vol += bin_volumes[idx]
        va_indices.append(int(idx))
        if cum_vol / total_vol >= VALUE_AREA_PCT:
            break

    va_min_idx = min(va_indices)
    va_max_idx = max(va_indices)
    result["RANGE_VAH_LEVEL"] = round(float(bins[va_max_idx + 1]), 4)
    result["RANGE_VAL_LEVEL"] = round(float(bins[va_min_idx]), 4)


def _regime_score(r: dict[str, Any], slope_pct: float) -> int:
    """Compute regime clarity/confidence score (0–5)."""
    score = 0
    if r["RANGE_REGIME"] != "UNKNOWN":
        score += 1
    if r["RANGE_WIDTH_PCT"] > 0:
        score += 1
    if r["RANGE_POSITION"] != "MID":
        score += 1
    if r["RANGE_BALANCE_STATE"] != "BALANCED":
        score += 1
    if slope_pct >= TREND_SLOPE_THRESHOLD:
        score += 1
    return min(score, 5)
