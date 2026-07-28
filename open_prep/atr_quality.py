"""Shared safety contract for ATR percentages used by live decisions.

ATR is produced in price units and later normalised by the current price.
Corporate-action scale breaks can therefore turn an otherwise finite ATR into
an impossible percentage. Consumers must fail closed on that condition rather
than creating unreachable outcome barriers or negative display stops.
"""

from __future__ import annotations

import math

MAX_ACTIONABLE_ATR_PCT = 50.0


def actionable_atr_pct(value: object) -> float | None:
    """Return a finite, positive ATR percentage inside the safety contract."""
    try:
        parsed = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(parsed) or parsed <= 0.0 or parsed > MAX_ACTIONABLE_ATR_PCT:
        return None
    return parsed


def atr_pct_from_price_units(atr: object, price: object) -> float | None:
    """Normalise a price-unit ATR and apply :func:`actionable_atr_pct`."""
    try:
        atr_value = float(atr)
        price_value = float(price)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(atr_value) or not math.isfinite(price_value) or price_value <= 0.0:
        return None
    return actionable_atr_pct((atr_value / price_value) * 100.0)
