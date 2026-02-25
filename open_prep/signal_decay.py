"""Signal Decay — adaptive freshness half-life based on volatility.

Ported from IB_monitoring.py's signal_decay concept.

In high-volatility instruments (high ATR%), signals age faster because
price moves quickly away from entry levels.  In low-vol / large-cap
names, signals remain actionable longer.

The decay uses a true half-life formula:  ``exp(-t * ln(2) / hl)``
so that at ``t = hl`` the value is exactly 0.5 (50%).

Usage::

    from open_prep.signal_decay import adaptive_half_life, adaptive_freshness_decay

    hl = adaptive_half_life(atr_pct=3.5)          # ~420s vs 600s baseline
    score = adaptive_freshness_decay(120.0, atr_pct=3.5)  # 0..1
"""
from __future__ import annotations

import math
import logging

_LN2 = math.log(2)  # ≈ 0.6931

logger = logging.getLogger("open_prep.signal_decay")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_HALF_LIFE_SECONDS: float = 600.0   # 10 min — default for mid-cap
MIN_HALF_LIFE_SECONDS: float = 180.0    # 3 min  — floor for highly volatile
MAX_HALF_LIFE_SECONDS: float = 1200.0   # 20 min — ceiling for blue chips

# ATR% reference points
ATR_PCT_LOW: float = 1.0    # below → max half-life (slow decay)
ATR_PCT_HIGH: float = 5.0   # above → min half-life (fast decay)


def adaptive_half_life(
    atr_pct: float | None = None,
    instrument_class: str | None = None,
) -> float:
    """Compute an adaptive half-life in seconds based on volatility.

    High ATR% → shorter half-life (signals age faster).
    Low  ATR% → longer  half-life (signals stay actionable longer).

    Parameters
    ----------
    atr_pct : float | None
        ATR as percentage of price (ATR / price * 100).
        If None, falls back to instrument_class or base half-life.
    instrument_class : str | None
        ``"penny" / "small_cap" / "mid_cap" / "large_cap"`` — used as
        fallback when atr_pct is unavailable.

    Returns
    -------
    float
        Half-life in seconds, clamped to [MIN, MAX].
    """
    if atr_pct is not None and atr_pct > 0:
        # Linear interpolation: atr_pct in [LOW, HIGH] → half_life in [MAX, MIN]
        if atr_pct <= ATR_PCT_LOW:
            hl = MAX_HALF_LIFE_SECONDS
        elif atr_pct >= ATR_PCT_HIGH:
            hl = MIN_HALF_LIFE_SECONDS
        else:
            ratio = (atr_pct - ATR_PCT_LOW) / (ATR_PCT_HIGH - ATR_PCT_LOW)
            hl = MAX_HALF_LIFE_SECONDS - ratio * (MAX_HALF_LIFE_SECONDS - MIN_HALF_LIFE_SECONDS)
        return max(MIN_HALF_LIFE_SECONDS, min(hl, MAX_HALF_LIFE_SECONDS))

    # Fallback: use instrument class
    _class_defaults: dict[str, float] = {
        "penny": 240.0,       # 4 min — very fast decay
        "small_cap": 420.0,   # 7 min
        "mid_cap": 600.0,     # 10 min (base)
        "large_cap": 900.0,   # 15 min
    }
    if instrument_class and instrument_class in _class_defaults:
        return _class_defaults[instrument_class]

    return BASE_HALF_LIFE_SECONDS


def adaptive_freshness_decay(
    elapsed_seconds: float | None,
    *,
    atr_pct: float | None = None,
    instrument_class: str | None = None,
) -> float:
    """Compute freshness score with adaptive half-life.

    Returns 0..1 where 1 = perfectly fresh.

    Drop-in replacement for ``scorer.freshness_decay_score`` when
    ATR% or instrument_class is available.
    """
    if elapsed_seconds is None:
        return 0.5  # Unknown age → neutral, not dead
    if elapsed_seconds <= 0:
        return 1.0

    hl = adaptive_half_life(atr_pct=atr_pct, instrument_class=instrument_class)
    return math.exp(-elapsed_seconds * _LN2 / hl)


def signal_strength_decay(
    initial_strength: float,
    elapsed_seconds: float,
    *,
    atr_pct: float | None = None,
    instrument_class: str | None = None,
) -> float:
    """Decay an initial signal strength over time.

    Useful for trailing signals or realtime alert freshness.

    Parameters
    ----------
    initial_strength : float
        Original signal strength (e.g. 0.85).
    elapsed_seconds : float
        Time since signal fired.

    Returns
    -------
    float
        Decayed strength, approaching 0.
    """
    decay = adaptive_freshness_decay(
        elapsed_seconds,
        atr_pct=atr_pct,
        instrument_class=instrument_class,
    )
    return initial_strength * decay
