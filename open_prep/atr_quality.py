"""Shared safety contract for ATR percentages used by live decisions.

ATR is smoothed as relative true range and converted back to current price
units for compatibility. Corporate-action boundaries still require an explicit
history reset: the split bar itself is not market volatility. Consumers also
fail closed on implausible percentages rather than creating unreachable
outcome barriers or negative display stops.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

MAX_ACTIONABLE_ATR_PCT = 50.0
MAX_CONTINUOUS_CLOSE_RATIO = 4.0


def _row_date(row: dict[str, Any]) -> date | None:
    raw_value = row.get("date")
    if raw_value is None:
        raw_value = row.get("datetime")
    raw = str(raw_value or "").strip()[:10]
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def homogeneous_price_history(
    rows: list[dict[str, Any]],
    *,
    split_dates: set[date] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Return the latest continuous-price segment and its boundary reason.

    A corporate-action date is authoritative.  The close-ratio fallback catches
    missing provider calendar rows and deliberately treats a >=4x overnight
    scale change as a new feature era.  The boundary row stays in the result,
    but consumers see no pre-boundary close, so the split gap itself cannot
    enter ATR, momentum, RSI, EMA, ADX, Bollinger or breakout calculations.
    """
    dated: list[tuple[date, dict[str, Any], float]] = []
    for row in rows:
        day = _row_date(row)
        try:
            close = float(row.get("close"))
        except (TypeError, ValueError, OverflowError):
            continue
        if day is not None and math.isfinite(close) and close > 0.0:
            dated.append((day, row, close))
    dated.sort(key=lambda item: item[0])
    if not dated:
        return [], None

    boundary_index = 0
    reason: str | None = None
    known = split_dates or set()
    latest_split = max((day for day in known if day <= dated[-1][0]), default=None)
    if latest_split is not None:
        for index, (day, _, _) in enumerate(dated):
            if day >= latest_split:
                boundary_index = index
                reason = "corporate_action"
                break

    for index in range(max(boundary_index + 1, 1), len(dated)):
        ratio = dated[index][2] / dated[index - 1][2]
        if ratio >= MAX_CONTINUOUS_CLOSE_RATIO or ratio <= 1.0 / MAX_CONTINUOUS_CLOSE_RATIO:
            boundary_index = index
            reason = "close_scale_break"

    return [row for _, row, _ in dated[boundary_index:]], reason


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
