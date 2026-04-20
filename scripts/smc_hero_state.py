"""Hero State Contract — single-source verdichtung for the Decision-First surface.

Consumes already-computed enrichment blocks and produces 7 product-level
fields that Desktop and Mobile dashboards can read without shadow logic.

Hero fields
-----------
HERO_MARKET_MODE   : str   — e.g. "BULLISH", "BEARISH", "NEUTRAL", "RISK_OFF"
HERO_BIAS          : str   — "LONG", "SHORT", "FLAT"
HERO_TRUST         : str   — "healthy", "warmup", "degraded", "stale", "unavailable"
HERO_SETUP_QUALITY : str   — "high", "good", "ok", "low"
HERO_WHY_NOW       : str   — compact catalyst/reason text
HERO_RISK          : str   — dominant risk factor
HERO_ACTION        : str   — "ACTIVE", "WATCH", "AVOID", "BLOCKED"
"""
from __future__ import annotations

from typing import Any


DEFAULTS: dict[str, str] = {
    "HERO_MARKET_MODE": "NEUTRAL",
    "HERO_BIAS": "FLAT",
    "HERO_TRUST": "unavailable",
    "HERO_SETUP_QUALITY": "low",
    "HERO_WHY_NOW": "",
    "HERO_RISK": "",
    "HERO_ACTION": "WATCH",
}


def _derive_trust(
    *,
    signal_freshness: str,
    stale_providers: str,
    ensemble_tier: str,
) -> str:
    """Map existing freshness and provider health into a product trust class."""
    stale_count = len([s for s in stale_providers.split(",") if s.strip()])

    if signal_freshness == "stale" and stale_count >= 2:
        return "unavailable"
    if signal_freshness == "stale":
        return "stale"
    if stale_count >= 2 or ensemble_tier == "low":
        return "degraded"
    if signal_freshness == "aging":
        return "warmup"
    return "healthy"


def _derive_bias(*, regime: str, trade_state: str) -> str:
    """Translate regime + trade_state into a directional bias."""
    if trade_state in ("BLOCKED", "AVOID"):
        return "FLAT"
    if regime in ("BULLISH",):
        return "LONG"
    if regime in ("BEARISH", "RISK_OFF"):
        return "SHORT"
    return "FLAT"


def _derive_action(*, trade_state: str, trust: str) -> str:
    """Map trade state and trust into a product action."""
    if trust in ("unavailable", "stale"):
        return "WATCH"
    if trade_state == "BLOCKED":
        return "BLOCKED"
    if trade_state == "AVOID":
        return "AVOID"
    if trade_state == "WATCH":
        return "WATCH"
    return "ACTIVE"


def _derive_why_now(
    *,
    zone_catalyst: str,
    zone_reason: str,
    high_impact_macro: bool,
    macro_event_name: str,
) -> str:
    """Build a compact catalyst text from available enrichment data."""
    parts: list[str] = []
    if high_impact_macro and macro_event_name:
        parts.append(macro_event_name)
    if zone_catalyst and zone_catalyst not in ("NONE", "none", ""):
        parts.append(zone_catalyst)
    if not parts and zone_reason and zone_reason not in ("NONE", "none", ""):
        parts.append(zone_reason)
    return " | ".join(parts[:2]) if parts else ""


def _derive_risk(
    *,
    stale_providers: str,
    event_risk_level: str,
    vol_regime: str,
    trust: str,
) -> str:
    """Identify the dominant risk factor."""
    if trust in ("unavailable", "stale"):
        return "DATA_STALE"
    if event_risk_level in ("HIGH", "CRITICAL"):
        return "EVENT_RISK"
    if vol_regime in ("EXTREME", "HIGH_VOL"):
        return "VOLATILITY"
    stale_count = len([s for s in stale_providers.split(",") if s.strip()])
    if stale_count >= 2:
        return "PROVIDER_GAPS"
    return ""


def build_hero_state(enrichment: dict[str, Any]) -> dict[str, str]:
    """Build the hero state contract from a fully-populated enrichment dict.

    Returns a flat dict with exactly the 7 hero fields.
    """
    regime_block = enrichment.get("regime") or {}
    layering = enrichment.get("layering") or {}
    providers = enrichment.get("providers") or {}
    signal_quality = enrichment.get("signal_quality") or {}
    ensemble_quality = enrichment.get("ensemble_quality") or {}
    calendar = enrichment.get("calendar") or {}
    zone_priority = enrichment.get("zone_priority") or {}
    event_risk = enrichment.get("event_risk") or enrichment.get("event_risk_light") or {}
    vol_regime = enrichment.get("volatility_regime") or {}

    regime = str(regime_block.get("regime", "NEUTRAL"))
    trade_state = str(layering.get("trade_state", "ALLOWED"))
    signal_freshness = str(signal_quality.get("SIGNAL_FRESHNESS", "stale"))
    stale_providers = str(providers.get("stale_providers", ""))
    ensemble_tier = str(ensemble_quality.get("tier", "low"))

    trust = _derive_trust(
        signal_freshness=signal_freshness,
        stale_providers=stale_providers,
        ensemble_tier=ensemble_tier,
    )

    return {
        "HERO_MARKET_MODE": regime,
        "HERO_BIAS": _derive_bias(regime=regime, trade_state=trade_state),
        "HERO_TRUST": trust,
        "HERO_SETUP_QUALITY": str(signal_quality.get("SIGNAL_QUALITY_TIER", "low")),
        "HERO_WHY_NOW": _derive_why_now(
            zone_catalyst=str(zone_priority.get("ZONE_PRIORITY_CATALYST", "")),
            zone_reason=str(zone_priority.get("ZONE_PRIORITY_REASON", "")),
            high_impact_macro=bool(calendar.get("high_impact_macro_today", False)),
            macro_event_name=str(calendar.get("macro_event_name", "")),
        ),
        "HERO_RISK": _derive_risk(
            stale_providers=stale_providers,
            event_risk_level=str(event_risk.get("EVENT_RISK_LEVEL", "NONE")),
            vol_regime=str(vol_regime.get("label", "NORMAL")),
            trust=trust,
        ),
        "HERO_ACTION": _derive_action(trade_state=trade_state, trust=trust),
    }
