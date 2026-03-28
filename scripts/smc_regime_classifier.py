"""Standalone market-regime classifier for SMC micro-profile generation.

Derived from ``open_prep/regime.py:classify_regime()`` but intentionally
free of any ``open_prep`` dependency so the profile generator can run
without the full open-prep stack.

No global state, no hysteresis — every call is a pure function of its
inputs.
"""
from __future__ import annotations

from typing import Any

# ── VIX thresholds ──────────────────────────────────────────────
VIX_LOW = 15.0
VIX_HIGH = 25.0
VIX_EXTREME = 35.0


def _to_float(val: Any) -> float:
    """Coerce *val* to float, returning 0.0 on failure."""
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


def classify_market_regime(
    vix_level: float | None,
    macro_bias: float,
    sector_performance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify the current market regime.

    Parameters
    ----------
    vix_level:
        Current VIX level.  ``None`` when unavailable — the classifier
        then relies on *macro_bias* and sector breadth only.
    macro_bias:
        Macro bias score, typically in [-1, +1].
    sector_performance:
        Sector rows with at least a ``changesPercentage`` key.

    Returns
    -------
    dict with keys ``regime``, ``vix_level``, ``macro_bias``,
    ``sector_breadth``, ``reasons``.
    """
    sectors = sector_performance or []
    reasons: list[str] = []

    # ── Sector breadth ──────────────────────────────────────────
    positive = [s for s in sectors if _to_float(s.get("changesPercentage")) > 0.0]
    total = len(sectors) or 1
    breadth = len(positive) / total

    leading = [
        s.get("sector", "?")
        for s in sectors
        if _to_float(s.get("changesPercentage")) > 0.5
    ]
    lagging = [
        s.get("sector", "?")
        for s in sectors
        if _to_float(s.get("changesPercentage")) < -0.5
    ]

    # ── Classification ──────────────────────────────────────────
    regime = "NEUTRAL"

    # Strong risk-off signals
    if vix_level is not None and vix_level >= VIX_EXTREME:
        regime = "RISK_OFF"
        reasons.append(f"VIX extreme ({vix_level:.1f} >= {VIX_EXTREME})")
    elif macro_bias <= -0.5:
        regime = "RISK_OFF"
        reasons.append(f"Macro bias strongly negative ({macro_bias:.2f})")
    elif vix_level is not None and vix_level >= VIX_HIGH and macro_bias < 0:
        regime = "RISK_OFF"
        reasons.append(f"VIX elevated ({vix_level:.1f}) + negative bias ({macro_bias:.2f})")

    # Rotation: mixed breadth
    elif 0.3 <= breadth <= 0.7 and len(leading) >= 2 and len(lagging) >= 2:
        regime = "ROTATION"
        reasons.append(
            f"Sector breadth mixed ({breadth:.0%}): "
            f"{len(leading)} leading, {len(lagging)} lagging"
        )

    # Risk-on: broad participation
    elif macro_bias >= 0.3 and breadth >= 0.6:
        regime = "RISK_ON"
        reasons.append(f"Macro bias positive ({macro_bias:.2f}) + broad breadth ({breadth:.0%})")
    elif vix_level is not None and vix_level <= VIX_LOW and macro_bias >= 0:
        regime = "RISK_ON"
        reasons.append(f"VIX low ({vix_level:.1f}) + non-negative bias ({macro_bias:.2f})")
    elif breadth >= 0.75:
        regime = "RISK_ON"
        reasons.append(f"Very broad sector breadth ({breadth:.0%})")

    # Default
    else:
        reasons.append(f"No clear regime signal (bias={macro_bias:.2f}, breadth={breadth:.0%})")

    return {
        "regime": regime,
        "vix_level": vix_level,
        "macro_bias": macro_bias,
        "sector_breadth": round(breadth, 4),
        "reasons": reasons,
    }
