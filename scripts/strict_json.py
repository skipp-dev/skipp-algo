from __future__ import annotations

import json
import math
import numbers
from decimal import Decimal
from typing import Any


def sanitize_for_strict_json(value: Any) -> Any:
    """Recursively replace non-finite floats with ``None``.

    This keeps artifact payloads JSON-standard-compliant under
    ``json.dumps(..., allow_nan=False)`` without hiding schema shape:
    metric keys remain present, but NaN/Inf sentinel values become ``null``.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Decimal):
        return float(value) if value.is_finite() else None
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        item = float(value)
        return item if math.isfinite(item) else None
    if isinstance(value, dict):
        return {key: sanitize_for_strict_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_for_strict_json(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_for_strict_json(item) for item in value]
    return value


def dumps_strict_json(
    value: Any,
    *,
    indent: int | None = None,
    sort_keys: bool = False,
) -> str:
    """Render a payload as strict JSON after sanitizing non-finite floats."""
    return json.dumps(
        sanitize_for_strict_json(value),
        indent=indent,
        sort_keys=sort_keys,
        allow_nan=False,
    )
