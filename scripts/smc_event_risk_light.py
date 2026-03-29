"""V5.5 Event Risk Light adapter.

Reduces the broad v5.0 event-risk surface to 7 user-facing fields.
Internal fields remain available in the full ``event_risk`` block
but are not part of the v5.5 lean contract.

Usage::

    from scripts.smc_event_risk_light import build_event_risk_light, DEFAULTS

    light = build_event_risk_light(event_risk=enrichment.get("event_risk", {}))
    enrichment["event_risk_light"] = light
"""
from __future__ import annotations

from typing import Any

# ── Defaults ────────────────────────────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "EVENT_WINDOW_STATE": "CLEAR",
    "EVENT_RISK_LEVEL": "NONE",
    "NEXT_EVENT_NAME": "",
    "NEXT_EVENT_TIME": "",
    "MARKET_EVENT_BLOCKED": False,
    "SYMBOL_EVENT_BLOCKED": False,
    "EVENT_PROVIDER_STATUS": "ok",
}

# Fields from the broad block that are internal/deprecated in v5.5
DEPRECATED_INTERNAL_FIELDS = [
    "NEXT_EVENT_CLASS",
    "NEXT_EVENT_IMPACT",
    "EVENT_RESTRICT_BEFORE_MIN",
    "EVENT_RESTRICT_AFTER_MIN",
    "EVENT_COOLDOWN_ACTIVE",
    "EARNINGS_SOON_TICKERS",
    "HIGH_RISK_EVENT_TICKERS",
]


def build_event_risk_light(
    *,
    event_risk: dict[str, Any] | None = None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract the v5.5 lean event-risk surface from the full block.

    Parameters
    ----------
    event_risk : dict | None
        Full event-risk block from :func:`build_event_risk`.
    overrides : dict | None
        Manual field overrides.

    Returns
    -------
    dict[str, Any]
        Flat dict with 7 lean fields.
    """
    result = dict(DEFAULTS)
    er = event_risk or {}

    for key in DEFAULTS:
        if key in er:
            result[key] = er[key]

    if overrides:
        for key, value in overrides.items():
            if key in result:
                result[key] = value

    return result
