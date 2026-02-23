from __future__ import annotations

from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    """Safely parse numeric-like values to float with default fallback."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
