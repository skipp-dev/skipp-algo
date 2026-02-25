from __future__ import annotations

import math
from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    """Safely parse numeric-like values to float with default fallback.

    Returns *default* for ``None``, non-numeric strings, **and** ``NaN``
    values so that downstream arithmetic never silently propagates NaN.
    """
    try:
        f = float(value)
        return default if math.isnan(f) else f
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Shared screening constants (used by screen.py and scorer.py)
# ---------------------------------------------------------------------------
MIN_PRICE_THRESHOLD: float = 5.0
"""Hard floor — reject any candidate priced below this."""

SEVERE_GAP_DOWN_THRESHOLD: float = -8.0
"""Gap-down percentage that triggers the *severe gap-down* filter."""
