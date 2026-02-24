"""Market regime classifier.

Detects risk-on / risk-off / rotation regimes from macro bias, VIX level,
and sector breadth.  Each regime produces a recommended weight adjustment
factor that the scorer can apply.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from open_prep.utils import to_float

logger = logging.getLogger("open_prep.regime")


# ---------------------------------------------------------------------------
# Regime enum values
# ---------------------------------------------------------------------------
REGIME_RISK_ON = "RISK_ON"
REGIME_RISK_OFF = "RISK_OFF"
REGIME_ROTATION = "ROTATION"
REGIME_NEUTRAL = "NEUTRAL"

# ---------------------------------------------------------------------------
# VIX thresholds
# ---------------------------------------------------------------------------
VIX_LOW = 15.0
VIX_HIGH = 25.0
VIX_EXTREME = 35.0


@dataclass
class RegimeSnapshot:
    """Immutable snapshot of the current market regime."""

    regime: str  # RISK_ON | RISK_OFF | ROTATION | NEUTRAL
    vix_level: float | None
    macro_bias: float
    sector_breadth: float  # fraction of sectors positive (0..1)
    leading_sectors: list[str]
    lagging_sectors: list[str]
    weight_adjustments: dict[str, float]  # multiplier per score component
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "regime": self.regime,
            "vix_level": self.vix_level,
            "macro_bias": round(self.macro_bias, 4),
            "sector_breadth": round(self.sector_breadth, 4),
            "leading_sectors": self.leading_sectors,
            "lagging_sectors": self.lagging_sectors,
            "weight_adjustments": {k: round(v, 4) for k, v in self.weight_adjustments.items()},
            "reasons": self.reasons,
        }


# ---------------------------------------------------------------------------
# Weight adjustment profiles per regime
# ---------------------------------------------------------------------------

# Multipliers applied to the base weights in the scorer
_WEIGHT_ADJ_RISK_ON: dict[str, float] = {
    "gap": 1.2,
    "gap_sector_relative": 0.8,
    "rvol": 1.1,
    "macro": 1.3,
    "momentum_z": 1.1,
    "earnings_bmo": 1.2,
    "ext_hours": 1.0,
    "freshness_decay": 0.8,
    "risk_off_penalty_multiplier": 0.5,
}

_WEIGHT_ADJ_RISK_OFF: dict[str, float] = {
    "gap": 0.5,
    "gap_sector_relative": 0.5,
    "rvol": 0.8,
    "macro": 1.5,
    "momentum_z": 0.6,
    "earnings_bmo": 0.8,
    "ext_hours": 0.7,
    "freshness_decay": 1.3,
    "risk_off_penalty_multiplier": 2.0,
    "liquidity_penalty": 2.0,
}

_WEIGHT_ADJ_ROTATION: dict[str, float] = {
    "gap": 0.7,
    "gap_sector_relative": 1.8,  # Sector-relative matters much more
    "rvol": 1.0,
    "macro": 0.8,
    "momentum_z": 1.3,
    "earnings_bmo": 1.0,
    "ext_hours": 1.0,
    "freshness_decay": 1.0,
}

_WEIGHT_ADJ_NEUTRAL: dict[str, float] = {}  # No adjustments


def classify_regime(
    *,
    macro_bias: float,
    vix_level: float | None = None,
    sector_performance: list[dict[str, Any]] | None = None,
) -> RegimeSnapshot:
    """Classify the current market regime.

    Parameters
    ----------
    macro_bias : float
        Current macro bias score from -1 to +1.
    vix_level : float | None
        Current VIX level. If unavailable, regime relies on macro bias
        and sector breadth only.
    sector_performance : list[dict]
        Sector performance rows with ``sector`` and ``changesPercentage``.
    """
    sectors = sector_performance or []
    reasons: list[str] = []

    # --- Sector breadth ---
    positive_sectors = [s for s in sectors if to_float(s.get("changesPercentage")) > 0.0]
    negative_sectors = [s for s in sectors if to_float(s.get("changesPercentage")) < 0.0]
    total = len(sectors) or 1
    breadth = len(positive_sectors) / total

    leading = [s.get("sector", "?") for s in sectors if to_float(s.get("changesPercentage")) > 0.5]
    lagging = [s.get("sector", "?") for s in sectors if to_float(s.get("changesPercentage")) < -0.5]

    # --- Classification logic ---
    regime = REGIME_NEUTRAL
    vix = vix_level

    # Strong risk-off signals
    if vix is not None and vix >= VIX_EXTREME:
        regime = REGIME_RISK_OFF
        reasons.append(f"VIX extreme ({vix:.1f} >= {VIX_EXTREME})")
    elif macro_bias <= -0.5:
        regime = REGIME_RISK_OFF
        reasons.append(f"Macro bias strongly negative ({macro_bias:.2f})")
    elif vix is not None and vix >= VIX_HIGH and macro_bias < 0:
        regime = REGIME_RISK_OFF
        reasons.append(f"VIX elevated ({vix:.1f}) + negative bias ({macro_bias:.2f})")

    # Rotation: mixed breadth, not clearly risk-on or risk-off
    elif 0.3 <= breadth <= 0.7 and len(leading) >= 2 and len(lagging) >= 2:
        regime = REGIME_ROTATION
        reasons.append(f"Sector breadth mixed ({breadth:.0%}): {len(leading)} leading, {len(lagging)} lagging")

    # Risk-on: broad participation
    elif macro_bias >= 0.3 and breadth >= 0.6:
        regime = REGIME_RISK_ON
        reasons.append(f"Macro bias positive ({macro_bias:.2f}) + broad breadth ({breadth:.0%})")
    elif vix is not None and vix <= VIX_LOW and macro_bias >= 0:
        regime = REGIME_RISK_ON
        reasons.append(f"VIX low ({vix:.1f}) + non-negative bias ({macro_bias:.2f})")
    elif breadth >= 0.75:
        regime = REGIME_RISK_ON
        reasons.append(f"Very broad sector breadth ({breadth:.0%})")

    # Default: NEUTRAL
    else:
        reasons.append(f"No clear regime signal (bias={macro_bias:.2f}, breadth={breadth:.0%})")

    # Select weight adjustments
    adj_map = {
        REGIME_RISK_ON: _WEIGHT_ADJ_RISK_ON,
        REGIME_RISK_OFF: _WEIGHT_ADJ_RISK_OFF,
        REGIME_ROTATION: _WEIGHT_ADJ_ROTATION,
        REGIME_NEUTRAL: _WEIGHT_ADJ_NEUTRAL,
    }

    return RegimeSnapshot(
        regime=regime,
        vix_level=vix,
        macro_bias=macro_bias,
        sector_breadth=breadth,
        leading_sectors=leading,
        lagging_sectors=lagging,
        weight_adjustments=adj_map.get(regime, {}),
        reasons=reasons,
    )


def apply_regime_adjustments(
    base_weights: dict[str, float],
    regime: RegimeSnapshot,
) -> dict[str, float]:
    """Return a copy of base_weights multiplied by regime adjustments."""
    adjusted = dict(base_weights)
    for key, multiplier in regime.weight_adjustments.items():
        if key in adjusted:
            adjusted[key] = adjusted[key] * multiplier
    return adjusted
