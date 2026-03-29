"""V5.3 Range / Profile Regime — compact contract layer.

Provides range boundaries, volume-profile levels, sentiment, liquidity
distribution, and predictive range bands.  Complements the existing
``smc_range_regime`` module with a tighter, consumer-oriented field set.

All fields safe-default to neutral when inputs are unavailable.

Usage::

    from scripts.smc_range_profile_regime import build_range_profile_regime, DEFAULTS

    rpr = build_range_profile_regime(snapshot=base_snapshot_df)
    enrichment["range_profile_regime"] = rpr
"""
from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# ── Defaults ────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    # Range boundaries
    "RANGE_ACTIVE": False,
    "RANGE_TOP": 0.0,
    "RANGE_BOTTOM": 0.0,
    "RANGE_MID": 0.0,
    "RANGE_WIDTH_ATR": 0.0,
    "RANGE_BREAK_DIRECTION": "NONE",       # NONE | UP | DOWN
    # Volume profile
    "PROFILE_POC": 0.0,
    "PROFILE_VALUE_AREA_TOP": 0.0,
    "PROFILE_VALUE_AREA_BOTTOM": 0.0,
    "PROFILE_VALUE_AREA_ACTIVE": False,
    # Sentiment
    "PROFILE_BULLISH_SENTIMENT": 0.0,
    "PROFILE_BEARISH_SENTIMENT": 0.0,
    "PROFILE_SENTIMENT_BIAS": "NEUTRAL",   # BULL | BEAR | NEUTRAL
    # Liquidity distribution
    "LIQUIDITY_ABOVE_PCT": 0.0,
    "LIQUIDITY_BELOW_PCT": 0.0,
    "LIQUIDITY_IMBALANCE": 0.0,
    # Predictive range bands
    "PRED_RANGE_MID": 0.0,
    "PRED_RANGE_UPPER_1": 0.0,
    "PRED_RANGE_UPPER_2": 0.0,
    "PRED_RANGE_LOWER_1": 0.0,
    "PRED_RANGE_LOWER_2": 0.0,
    "IN_PREDICTIVE_RANGE_EXTREME": False,
}

# ── Thresholds ──────────────────────────────────────────────────

RANGE_ATR_WIDTH_MIN = 0.5       # below this ATR-width → not a real range
BREAKOUT_ATR_MULT = 1.2         # close beyond boundary × ATR = breakout
VALUE_AREA_PCT = 0.70           # 70 % of volume for value area
PRED_SIGMA_1 = 1.0              # ±1σ band
PRED_SIGMA_2 = 2.0              # ±2σ band


def build_range_profile_regime(
    *,
    snapshot: pd.DataFrame | None = None,
    symbol: str = "",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a range / profile regime block.

    Parameters
    ----------
    snapshot : DataFrame, optional
        OHLCV bars.
    symbol : str
        Optional symbol filter.
    overrides : dict, optional
        Manual field overrides.
    """
    result = dict(DEFAULTS)

    if snapshot is not None and not snapshot.empty:
        df = snapshot.copy()
        if symbol and "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
        if not df.empty:
            result = _derive(df, result)

    if overrides:
        for key, val in overrides.items():
            if key in DEFAULTS:
                result[key] = val

    return result


def _derive(df: pd.DataFrame, result: dict[str, Any]) -> dict[str, Any]:
    """Derive all 22 fields from OHLCV data."""
    for col in ("high", "low", "close", "open", "volume"):
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

    range_top = float(highs.max())
    range_bottom = float(lows.min())
    range_mid = (range_top + range_bottom) / 2 if (range_top + range_bottom) > 0 else 0.0

    result["RANGE_TOP"] = round(range_top, 4)
    result["RANGE_BOTTOM"] = round(range_bottom, 4)
    result["RANGE_MID"] = round(range_mid, 4)

    # ATR
    atr = _atr(highs, lows, closes)

    # Range width in ATR units
    range_width = range_top - range_bottom
    result["RANGE_WIDTH_ATR"] = round(range_width / atr, 4) if atr > 0 else 0.0

    # Active range?
    result["RANGE_ACTIVE"] = result["RANGE_WIDTH_ATR"] >= RANGE_ATR_WIDTH_MIN

    # Breakout detection
    last_close = float(closes.iloc[-1])
    prior_high = float(highs.iloc[:-1].max())
    prior_low = float(lows.iloc[:-1].min())
    breakout_up = prior_high + atr * BREAKOUT_ATR_MULT
    breakout_down = prior_low - atr * BREAKOUT_ATR_MULT

    if last_close > breakout_up:
        result["RANGE_BREAK_DIRECTION"] = "UP"
    elif last_close < breakout_down:
        result["RANGE_BREAK_DIRECTION"] = "DOWN"
    else:
        result["RANGE_BREAK_DIRECTION"] = "NONE"

    # Volume profile
    has_volume = "volume" in df.columns
    volumes = pd.to_numeric(df["volume"], errors="coerce").fillna(0).astype(float) if has_volume else pd.Series(dtype=float)
    total_vol = float(volumes.sum()) if has_volume else 0.0

    if total_vol > 0:
        _compute_profile(closes, volumes, result)

    # Sentiment
    _compute_sentiment(closes, result)

    # Liquidity distribution
    if total_vol > 0:
        _compute_liquidity(closes, volumes, result)

    # Predictive range bands
    _compute_predictive_bands(closes, atr, result)

    return result


def _atr(highs: pd.Series, lows: pd.Series, closes: pd.Series) -> float:
    """Simple ATR from full bar set."""
    n = len(closes)
    if n < 2:
        return float(highs.iloc[0] - lows.iloc[0]) if n == 1 else 0.0
    tr_vals = []
    for i in range(1, n):
        h = float(highs.iloc[i])
        lo = float(lows.iloc[i])
        pc = float(closes.iloc[i - 1])
        tr_vals.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return float(np.mean(tr_vals)) if tr_vals else 0.0


def _compute_profile(
    closes: pd.Series, volumes: pd.Series, result: dict[str, Any]
) -> None:
    """Volume-at-price profile → POC, VAH, VAL."""
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

    vpoc_idx = int(np.argmax(bin_volumes))
    result["PROFILE_POC"] = round(float((bins[vpoc_idx] + bins[vpoc_idx + 1]) / 2), 4)

    # Value area — 70 % of volume centred on VPOC
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
    result["PROFILE_VALUE_AREA_TOP"] = round(float(bins[va_max_idx + 1]), 4)
    result["PROFILE_VALUE_AREA_BOTTOM"] = round(float(bins[va_min_idx]), 4)

    # Active = last close is within the value area
    last_close = float(closes.iloc[-1])
    result["PROFILE_VALUE_AREA_ACTIVE"] = (
        result["PROFILE_VALUE_AREA_BOTTOM"] <= last_close <= result["PROFILE_VALUE_AREA_TOP"]
    )


def _compute_sentiment(closes: pd.Series, result: dict[str, Any]) -> None:
    """Bull/bear sentiment from close-to-close changes."""
    if len(closes) < 2:
        return
    changes = closes.diff().dropna()
    total = len(changes)
    if total == 0:
        return
    bull_count = int((changes > 0).sum())
    bear_count = int((changes < 0).sum())
    result["PROFILE_BULLISH_SENTIMENT"] = round(bull_count / total, 4)
    result["PROFILE_BEARISH_SENTIMENT"] = round(bear_count / total, 4)
    if bull_count > bear_count:
        result["PROFILE_SENTIMENT_BIAS"] = "BULL"
    elif bear_count > bull_count:
        result["PROFILE_SENTIMENT_BIAS"] = "BEAR"
    else:
        result["PROFILE_SENTIMENT_BIAS"] = "NEUTRAL"


def _compute_liquidity(
    closes: pd.Series, volumes: pd.Series, result: dict[str, Any]
) -> None:
    """Liquidity distribution above/below the current close."""
    last_close = float(closes.iloc[-1])
    total_vol = float(volumes.sum())
    if total_vol <= 0:
        return

    above_vol = float(volumes[closes > last_close].sum())
    below_vol = float(volumes[closes < last_close].sum())

    above_pct = round(above_vol / total_vol * 100, 4)
    below_pct = round(below_vol / total_vol * 100, 4)
    result["LIQUIDITY_ABOVE_PCT"] = above_pct
    result["LIQUIDITY_BELOW_PCT"] = below_pct
    result["LIQUIDITY_IMBALANCE"] = round(above_pct - below_pct, 4)


def _compute_predictive_bands(
    closes: pd.Series, atr: float, result: dict[str, Any]
) -> None:
    """Predictive range bands from recent mean ± σ of ATR."""
    if len(closes) < 2 or atr <= 0:
        return

    last_close = float(closes.iloc[-1])
    # Use recent mean as the predictive centre
    recent = closes.tail(min(20, len(closes)))
    pred_mid = float(recent.mean())

    result["PRED_RANGE_MID"] = round(pred_mid, 4)
    result["PRED_RANGE_UPPER_1"] = round(pred_mid + atr * PRED_SIGMA_1, 4)
    result["PRED_RANGE_UPPER_2"] = round(pred_mid + atr * PRED_SIGMA_2, 4)
    result["PRED_RANGE_LOWER_1"] = round(pred_mid - atr * PRED_SIGMA_1, 4)
    result["PRED_RANGE_LOWER_2"] = round(pred_mid - atr * PRED_SIGMA_2, 4)

    result["IN_PREDICTIVE_RANGE_EXTREME"] = (
        last_close >= result["PRED_RANGE_UPPER_2"]
        or last_close <= result["PRED_RANGE_LOWER_2"]
    )
