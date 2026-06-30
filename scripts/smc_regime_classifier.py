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

PE_CHEAP = 15.0
PE_EXPENSIVE = 25.0
MAX_PE_ADJUSTMENT = 0.2


def _to_float(val: Any) -> float:
    """Coerce *val* to float, returning 0.0 on failure or NaN.

    NaN is treated as a failed coercion (no usable signal) rather than a
    valid number: a NaN macro_bias / sector change must not survive into the
    classifier, where ``_clamp`` would otherwise silently turn it into +1.0
    (max bullish) and flip the regime.
    """
    try:
        f = float(val)
    except (TypeError, ValueError):
        return 0.0
    return f if f == f else 0.0  # NaN check


def _clamp(value: float, low: float, high: float) -> float:
    # NaN is "no signal", not a high score: clamp it to ``low`` instead of
    # letting ``max(low, min(high, nan))`` silently return ``high`` (NaN
    # compares False to everything, so ``min(high, nan)`` returns ``high``).
    f = float(value)
    if f != f:  # NaN
        return low
    return max(low, min(high, f))


def _market_pe_modifier(market_pe_forward: float | None) -> tuple[float, str]:
    if market_pe_forward is None or market_pe_forward <= 0:
        return 0.0, "UNKNOWN"
    if market_pe_forward > PE_EXPENSIVE:
        penalty = -0.1 * (market_pe_forward - PE_EXPENSIVE) / 10.0
        return max(penalty, -MAX_PE_ADJUSTMENT), "EXPENSIVE"
    if market_pe_forward < PE_CHEAP:
        boost = 0.1 * (PE_CHEAP - market_pe_forward) / 5.0
        return min(boost, MAX_PE_ADJUSTMENT), "CHEAP"
    return 0.0, "FAIR"


def classify_market_regime(
    vix_level: float | None,
    macro_bias: float,
    sector_performance: list[dict[str, Any]] | None = None,
    market_pe_forward: float | None = None,
    yield_curve_inverted: bool = False,
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
    yield_curve_inverted:
        If *True*, the 2Y-10Y spread is negative — adds a +0.2 RISK_OFF
        bias (i.e. reduces the macro bias by 0.2).

    Returns
    -------
    dict with keys ``regime``, ``vix_level``, ``macro_bias``,
    ``macro_bias_raw``, ``macro_bias_pe_adjustment``,
    ``macro_bias_yield_curve_adjustment``,
    ``market_pe_forward``, ``market_pe_regime``, ``sector_breadth``,
    ``yield_curve_inverted``, ``reasons``.
    """
    sectors = sector_performance or []
    reasons: list[str] = []
    macro_bias_raw = _to_float(macro_bias)
    macro_bias_pe_adjustment, market_pe_regime = _market_pe_modifier(market_pe_forward)
    macro_bias_yc_adjustment = -0.2 if yield_curve_inverted else 0.0
    adjusted_macro_bias = _clamp(
        macro_bias_raw + macro_bias_pe_adjustment + macro_bias_yc_adjustment, -1.0, 1.0
    )

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
    elif adjusted_macro_bias <= -0.5:
        regime = "RISK_OFF"
        reasons.append(f"Macro bias strongly negative ({adjusted_macro_bias:.2f})")
    elif vix_level is not None and vix_level >= VIX_HIGH and adjusted_macro_bias < 0:
        regime = "RISK_OFF"
        reasons.append(f"VIX elevated ({vix_level:.1f}) + negative bias ({adjusted_macro_bias:.2f})")

    # Rotation: mixed breadth
    elif 0.3 <= breadth <= 0.7 and len(leading) >= 2 and len(lagging) >= 2:
        regime = "ROTATION"
        reasons.append(
            f"Sector breadth mixed ({breadth:.0%}): "
            f"{len(leading)} leading, {len(lagging)} lagging"
        )

    # Risk-on: broad participation
    elif adjusted_macro_bias >= 0.3 and breadth >= 0.6:
        regime = "RISK_ON"
        reasons.append(f"Macro bias positive ({adjusted_macro_bias:.2f}) + broad breadth ({breadth:.0%})")
    elif vix_level is not None and vix_level <= VIX_LOW and adjusted_macro_bias >= 0:
        regime = "RISK_ON"
        reasons.append(f"VIX low ({vix_level:.1f}) + non-negative bias ({adjusted_macro_bias:.2f})")
    elif breadth >= 0.75:
        regime = "RISK_ON"
        reasons.append(f"Very broad sector breadth ({breadth:.0%})")

    # Default
    else:
        reasons.append(f"No clear regime signal (bias={adjusted_macro_bias:.2f}, breadth={breadth:.0%})")

    if market_pe_forward is not None and market_pe_regime != "UNKNOWN":
        reasons.append(
            f"Valuation modifier {macro_bias_pe_adjustment:+.2f} "
            f"({market_pe_regime.lower()} market PE {market_pe_forward:.1f})"
        )

    if yield_curve_inverted:
        reasons.append("Yield curve inverted (2Y > 10Y) — RISK_OFF bias +0.2")

    return {
        "regime": regime,
        "vix_level": vix_level,
        "macro_bias": round(adjusted_macro_bias, 4),
        "macro_bias_raw": round(macro_bias_raw, 4),
        "macro_bias_pe_adjustment": round(macro_bias_pe_adjustment, 4),
        "macro_bias_yield_curve_adjustment": round(macro_bias_yc_adjustment, 4),
        "market_pe_forward": round(float(market_pe_forward), 4) if market_pe_forward is not None else None,
        "market_pe_regime": market_pe_regime,
        "sector_breadth": round(breadth, 4),
        "yield_curve_inverted": yield_curve_inverted,
        "reasons": reasons,
    }
