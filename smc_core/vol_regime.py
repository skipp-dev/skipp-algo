"""Volatility-regime classification — additive Meta-Domain MVP.

Provides a deterministic regime label derived from price-bar volatility.
The module is *additive*: if data is missing, it degrades gracefully to
``NORMAL`` regime rather than failing.

Integration:
  - Called by ``smc_integration.service`` to enrich ``snapshot.meta``.
  - Consumed by ``smc_core.layering`` to modulate ``global_strength`` / tier.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

VolRegimeLabel = Literal["LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME"]


@dataclass(slots=True, frozen=True)
class VolRegimeResult:
    """Immutable result of the vol-regime classification."""

    label: VolRegimeLabel
    raw_atr_ratio: float  # current ATR / rolling median ATR
    confidence: float     # 0.0–1.0
    bars_used: int


# Thresholds for ATR-ratio → regime label.
_THRESHOLDS: list[tuple[float, VolRegimeLabel]] = [
    (0.5, "LOW_VOL"),
    (1.5, "HIGH_VOL"),
    (2.5, "EXTREME"),
]


def _classify(atr_ratio: float) -> VolRegimeLabel:
    if atr_ratio <= _THRESHOLDS[0][0]:
        return "LOW_VOL"
    if atr_ratio >= _THRESHOLDS[2][0]:
        return "EXTREME"
    if atr_ratio >= _THRESHOLDS[1][0]:
        return "HIGH_VOL"
    return "NORMAL"


def compute_vol_regime(
    bars: pd.DataFrame,
    *,
    atr_period: int = 14,
    lookback: int = 50,
) -> VolRegimeResult:
    """Classify the current volatility regime from OHLC bars.

    Parameters
    ----------
    bars:
        DataFrame with columns ``high``, ``low``, ``close`` (numeric).
    atr_period:
        Number of bars for the ATR calculation.
    lookback:
        Rolling window for the median ATR baseline.

    Returns
    -------
    VolRegimeResult
    """
    if bars.empty or len(bars) < atr_period + 1:
        return VolRegimeResult(label="NORMAL", raw_atr_ratio=1.0, confidence=0.0, bars_used=len(bars))

    df = bars.copy()
    for col in ("high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["high", "low", "close"])

    if len(df) < atr_period + 1:
        return VolRegimeResult(label="NORMAL", raw_atr_ratio=1.0, confidence=0.0, bars_used=len(df))

    # True Range
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    atr = tr.rolling(window=atr_period, min_periods=atr_period).mean()
    atr = atr.dropna()

    if atr.empty:
        return VolRegimeResult(label="NORMAL", raw_atr_ratio=1.0, confidence=0.0, bars_used=len(df))

    current_atr = float(atr.iloc[-1])
    window = min(lookback, len(atr))
    median_atr = float(atr.iloc[-window:].median())

    if median_atr == 0:
        return VolRegimeResult(label="NORMAL", raw_atr_ratio=1.0, confidence=0.0, bars_used=len(df))

    ratio = current_atr / median_atr
    label = _classify(ratio)

    # Confidence increases with available data.
    confidence = min(1.0, len(atr) / lookback)

    return VolRegimeResult(
        label=label,
        raw_atr_ratio=round(ratio, 4),
        confidence=round(confidence, 4),
        bars_used=len(df),
    )
