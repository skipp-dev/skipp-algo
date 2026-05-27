"""Hero State Contract — single-source verdichtung for the Decision-First surface.

Consumes already-computed enrichment blocks and produces 7 product-level
fields that Desktop and Mobile dashboards can read without shadow logic.

Hero fields
-----------
HERO_MARKET_MODE   : str   — e.g. "BULLISH", "BEARISH", "NEUTRAL", "RISK_OFF", "UNKNOWN" (sentinel)
HERO_BIAS          : str   — "LONG", "SHORT", "FLAT", "UNKNOWN" (sentinel)
HERO_TRUST         : str   — "healthy", "warmup", "degraded", "stale", "unavailable"
HERO_SETUP_QUALITY : str   — "high", "good", "ok", "low", "unavailable" (sentinel)
HERO_WHY_NOW       : str   — compact catalyst/reason text
HERO_RISK          : str   — dominant risk factor
HERO_ACTION        : str   — "ACTIVE", "WATCH", "AVOID", "BLOCKED"

Waiting-state sentinels (issue #55 / WS3-UI)
--------------------------------------------
The ``UNKNOWN`` (for HERO_MARKET_MODE / HERO_BIAS) and ``unavailable``
(for HERO_SETUP_QUALITY) values are emitted whenever no upstream
enrichment block is available yet (default state). Pine consumers
render these as grey "awaiting first enrichment run" markers, so
users can distinguish "market truly is neutral / bias truly is flat /
setup truly is low" from "we have no data yet".

This is a MAJOR ``library_field_version`` bump from v5.5c → v6.0a
because Pine ``== "NEUTRAL"`` / ``== "FLAT"`` / ``== "low"`` literal
gates change semantics.

Vocabulary pins
---------------
``HERO_TRUST``, ``HERO_SETUP_QUALITY``, and ``HERO_ACTION`` are
exposed as module-level constants and frozensets below. These pin
the exact literals that Pine dashboards compare against. They also
document the cross-vocabulary mappings used by:

- ``smc_integration.trust_state.TrustState`` (canonical 5-state
  trust enum) via :func:`project_trust_state_to_hero`.
- ``scripts.smc_hero_action._ACTION_TABLE`` (Producer-B quality
  vocabulary ``excellent/good/limited/avoid``) via
  :data:`HERO_QUALITY_A_TO_B`.

Boundary-Contract Improvement Plan 2026-04-23, F-2 / F-4 / F-6 /
PR-BC-04 — DO NOT rename these literals without bumping
``library_field_version`` in the generated Pine library.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from smc_integration.trust_state import TrustState


DEFAULTS: dict[str, str] = {
    # Sentinel: "no data yet" — distinct from upstream "NEUTRAL".
    "HERO_MARKET_MODE": "UNKNOWN",
    # Sentinel: "no data yet" — distinct from upstream "FLAT".
    "HERO_BIAS": "UNKNOWN",
    "HERO_TRUST": "unavailable",
    # Sentinel: "no data yet" — distinct from low-tier signal "low".
    "HERO_SETUP_QUALITY": "unavailable",
    "HERO_WHY_NOW": "",
    "HERO_RISK": "",
    "HERO_ACTION": "WATCH",
}


# ── HERO_TRUST vocabulary (F-2, PR-BC-04) ─────────────────────────────
#
# Hero-local trust vocabulary — SUPERSET of the canonical ``TrustState``
# enum (see ``smc_integration.trust_state.TrustState`` for the 5-state
# enum). Mapping ``TrustState`` → ``HERO_TRUST``:
#
#   TrustState.HEALTHY      → "healthy"
#   TrustState.DEGRADED     → "degraded"
#   TrustState.STALE        → "stale"
#   TrustState.WATCH_ONLY   → "degraded"   # Hero collapses (info loss)
#   TrustState.UNAVAILABLE  → "unavailable"
#
# ``"warmup"`` is Hero-local (no ``TrustState`` counterpart) — it
# signals an aging freshness signal before full degradation. Pine
# dashboards render it as amber (T2).
#
# Pine-boundary contract: ``SMC_Dashboard.pine:1753,1768,1774`` and
# ``SMC_Mobile_Dashboard.pine:50,55`` compare this value to lowercase
# literals. DO NOT rename without bumping ``library_field_version``.
HERO_TRUST_HEALTHY: str = "healthy"
HERO_TRUST_WARMUP: str = "warmup"
HERO_TRUST_DEGRADED: str = "degraded"
HERO_TRUST_STALE: str = "stale"
HERO_TRUST_UNAVAILABLE: str = "unavailable"

HERO_TRUST_VOCAB: frozenset[str] = frozenset({
    HERO_TRUST_HEALTHY,
    HERO_TRUST_WARMUP,
    HERO_TRUST_DEGRADED,
    HERO_TRUST_STALE,
    HERO_TRUST_UNAVAILABLE,
})


# ── HERO_SETUP_QUALITY vocabulary (F-4, PR-BC-04) ─────────────────────
#
# Producer-A vocabulary (live Pine consumer, passthrough of
# ``SIGNAL_QUALITY_TIER``):
#
#   "high"   — top-tier setup, maximum confidence
#   "good"   — standard setup
#   "ok"     — marginal (minimum for ACTIVE)
#   "low"    — below threshold (default; WATCH/AVOID)
#
# Producer-B (``scripts/smc_hero_setup_quality.py`` +
# ``_ACTION_TABLE`` in ``scripts/smc_hero_action.py``) emits a
# parallel 4-tier ``excellent/good/limited/avoid`` vocabulary on the
# RESERVED field ``HERO_QUALITY_TIER`` — reconciliation is planned
# for a WS3-UI follow-up. ``HERO_QUALITY_A_TO_B`` declares the bridge
# so the convergence is trivial.
HERO_SETUP_QUALITY_HIGH: str = "high"
HERO_SETUP_QUALITY_GOOD: str = "good"
HERO_SETUP_QUALITY_OK: str = "ok"
HERO_SETUP_QUALITY_LOW: str = "low"
# Waiting-state sentinel (#55) — "no enrichment run yet", distinct from "low".
HERO_SETUP_QUALITY_UNAVAILABLE: str = "unavailable"

HERO_SETUP_QUALITY_VOCAB: frozenset[str] = frozenset({
    HERO_SETUP_QUALITY_HIGH,
    HERO_SETUP_QUALITY_GOOD,
    HERO_SETUP_QUALITY_OK,
    HERO_SETUP_QUALITY_LOW,
    HERO_SETUP_QUALITY_UNAVAILABLE,
})

HERO_QUALITY_A_TO_B: dict[str, str] = {
    HERO_SETUP_QUALITY_HIGH: "excellent",
    HERO_SETUP_QUALITY_GOOD: "good",
    HERO_SETUP_QUALITY_OK: "limited",
    HERO_SETUP_QUALITY_LOW: "avoid",
    # Waiting-state sentinel maps to Producer-B's "avoid" \u2014 semantically
    # "no data yet" is closer to \u201edon't act\u201c than to any active tier.
    HERO_SETUP_QUALITY_UNAVAILABLE: "avoid",
}


# ── HERO_ACTION vocabulary (F-6 docs, PR-BC-04) ───────────────────────
#
# Producer-A vocabulary — live Pine consumer (``SMC_Dashboard.pine``
# ~line 1728, read-passthrough, no literal gate today). The parallel
# reserved field ``HERO_ACTION_VERB`` uses a lowercase verb vocabulary
# (``act/wait/watch/avoid`` + DE variants) — reconciliation is
# deferred to a WS3 ticket.
HERO_ACTION_ACTIVE: str = "ACTIVE"
HERO_ACTION_WATCH: str = "WATCH"
HERO_ACTION_AVOID: str = "AVOID"
HERO_ACTION_BLOCKED: str = "BLOCKED"

HERO_ACTION_VOCAB: frozenset[str] = frozenset({
    HERO_ACTION_ACTIVE,
    HERO_ACTION_WATCH,
    HERO_ACTION_AVOID,
    HERO_ACTION_BLOCKED,
})


# ── HERO_BIAS vocabulary (PR-AUDIT-2026-04-24, ADR-0006) ───────────────
#
# Producer-A vocabulary — emitted by :func:`_derive_bias`, consumed by
# Pine generated library (``smc_micro_profiles_generated.pine``) via
# ``scripts/generate_smc_micro_profiles.py:1047`` as a const string.
#
# Pine boundary contract: this is a 3-state directional bias.
# DO NOT rename without bumping ``library_field_version`` in the
# generated Pine library (ADR-0006 §3).
HERO_BIAS_LONG: str = "LONG"
HERO_BIAS_SHORT: str = "SHORT"
HERO_BIAS_FLAT: str = "FLAT"
# Waiting-state sentinel (#55) — "no enrichment run yet", distinct from "FLAT".
HERO_BIAS_UNKNOWN: str = "UNKNOWN"

HERO_BIAS_VOCAB: frozenset[str] = frozenset({
    HERO_BIAS_LONG,
    HERO_BIAS_SHORT,
    HERO_BIAS_FLAT,
    HERO_BIAS_UNKNOWN,
})


# ── HERO_MARKET_MODE vocabulary (PR-AUDIT-2026-04-24, ADR-0006) ──────────
#
# Producer-A vocabulary — passthrough of the upstream ``regime`` field
# (see ``scripts/smc_hero_market_mode.py::_regime_label``). Pine
# consumers (``SMC_Mobile_Dashboard.pine`` Mobile context block,
# ``SMC_Dashboard.pine`` Hero block) compare against the literals
# ``"BULLISH"``, ``"BEARISH"``, ``"NEUTRAL"``, ``"RISK_OFF"``; ``"UNKNOWN"``
# is the waiting-state sentinel emitted when no enrichment run has yet
# produced a regime (#55). ``"NEUTRAL"`` is substantive (resolved-neutral).
#
# This vocab is NORMATIVE for downstream Pine consumers but NOT
# enforced at write time — ``_regime_label`` will pass through any
# UPPERCASE string from upstream. Adding a new value here forces a
# parallel Pine-side branch update (ADR-0006 §2).
HERO_MARKET_MODE_BULLISH: str = "BULLISH"
HERO_MARKET_MODE_BEARISH: str = "BEARISH"
HERO_MARKET_MODE_NEUTRAL: str = "NEUTRAL"
HERO_MARKET_MODE_RISK_OFF: str = "RISK_OFF"
# Waiting-state sentinel (#55) — "no enrichment run yet", distinct from "NEUTRAL".
HERO_MARKET_MODE_UNKNOWN: str = "UNKNOWN"

HERO_MARKET_MODE_VOCAB: frozenset[str] = frozenset({
    HERO_MARKET_MODE_BULLISH,
    HERO_MARKET_MODE_BEARISH,
    HERO_MARKET_MODE_NEUTRAL,
    HERO_MARKET_MODE_RISK_OFF,
    HERO_MARKET_MODE_UNKNOWN,
})


# ── HERO_RISK vocabulary (PR-AUDIT-2026-04-24, ADR-0006 §"Out of scope") ─────
#
# Producer-A vocabulary — emitted by :func:`_derive_risk`, exported as
# Pine const ``HERO_RISK`` via
# ``scripts/generate_smc_micro_profiles.py:1051``. Pine consumer
# ``SMC_Dashboard.pine:1769`` uses the EMPTY-STRING sentinel
# (``mp.HERO_RISK != "" ? ...``) to gate the blocker badge — the empty
# string IS part of the contract and MUST NOT be normalised to e.g.
# ``"NONE"`` without a Pine-side migration + library_field_version bump.
#
# Tests asserting ``result["HERO_RISK"] == ""`` (e.g.
# ``tests/test_smc_hero_state.py:100``,
# ``tests/test_smc_pine_evidence_fixtures.py:100``) document the
# sentinel-as-contract.
HERO_RISK_NONE: str = ""  # sentinel: "no dominant risk" — Pine-gated by `!= ""`.
HERO_RISK_DATA_STALE: str = "DATA_STALE"
HERO_RISK_EVENT_RISK: str = "EVENT_RISK"
HERO_RISK_VOLATILITY: str = "VOLATILITY"
HERO_RISK_PROVIDER_GAPS: str = "PROVIDER_GAPS"

HERO_RISK_VOCAB: frozenset[str] = frozenset({
    HERO_RISK_NONE,
    HERO_RISK_DATA_STALE,
    HERO_RISK_EVENT_RISK,
    HERO_RISK_VOLATILITY,
    HERO_RISK_PROVIDER_GAPS,
})


def project_trust_state_to_hero(state: TrustState) -> str:
    """Translate a canonical ``TrustState`` into the Hero-local vocab.

    Single source of truth for the ``WATCH_ONLY`` → ``"degraded"``
    collapse. Used when ``TrustStateAssessment`` is wired into Hero
    (ENG-WS2-03). Keep the mapping here so the information-loss point
    is obvious and testable.
    """
    from smc_integration.trust_state import TrustState

    return {
        TrustState.HEALTHY: HERO_TRUST_HEALTHY,
        TrustState.DEGRADED: HERO_TRUST_DEGRADED,
        TrustState.STALE: HERO_TRUST_STALE,
        TrustState.WATCH_ONLY: HERO_TRUST_DEGRADED,
        TrustState.UNAVAILABLE: HERO_TRUST_UNAVAILABLE,
    }[state]


def _derive_trust(
    *,
    signal_freshness: str,
    stale_providers: str,
    ensemble_tier: str,
) -> str:
    """Map existing freshness and provider health into a product trust class."""
    stale_count = len([s for s in stale_providers.split(",") if s.strip()])

    if signal_freshness == "stale" and stale_count >= 2:
        return HERO_TRUST_UNAVAILABLE
    if signal_freshness == "stale":
        return HERO_TRUST_STALE
    if stale_count >= 2 or ensemble_tier == "low":
        return HERO_TRUST_DEGRADED
    if signal_freshness == "aging":
        return HERO_TRUST_WARMUP
    return HERO_TRUST_HEALTHY


def _derive_bias(*, regime: str, trade_state: str) -> str:
    """Translate regime + trade_state into a directional bias.

    Returns one of :data:`HERO_BIAS_VOCAB` (``LONG`` / ``SHORT`` /
    ``FLAT``). See ADR-0006 for the vocabulary contract.
    """
    if trade_state in ("BLOCKED", "AVOID"):
        return HERO_BIAS_FLAT
    if regime == HERO_MARKET_MODE_BULLISH:
        return HERO_BIAS_LONG
    if regime in (HERO_MARKET_MODE_BEARISH, HERO_MARKET_MODE_RISK_OFF):
        return HERO_BIAS_SHORT
    return HERO_BIAS_FLAT


def _derive_action(*, trade_state: str, trust: str) -> str:
    """Map trade state and trust into a product action.

    Returns one of :data:`HERO_ACTION_VOCAB`. See ADR-0006 for the
    vocabulary contract.
    """
    if trust in (HERO_TRUST_UNAVAILABLE, HERO_TRUST_STALE):
        return HERO_ACTION_WATCH
    if trade_state == "BLOCKED":
        return HERO_ACTION_BLOCKED
    if trade_state == "AVOID":
        return HERO_ACTION_AVOID
    if trade_state == "WATCH":
        return HERO_ACTION_WATCH
    return HERO_ACTION_ACTIVE


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
    """Identify the dominant risk factor.

    Returns one of :data:`HERO_RISK_VOCAB`. The empty-string sentinel
    :data:`HERO_RISK_NONE` is part of the Pine boundary contract
    (``SMC_Dashboard.pine:1769`` uses ``mp.HERO_RISK != ""`` as a gate)
    and MUST be preserved.
    """
    if trust in (HERO_TRUST_UNAVAILABLE, HERO_TRUST_STALE):
        return HERO_RISK_DATA_STALE
    if event_risk_level in ("HIGH", "CRITICAL"):
        return HERO_RISK_EVENT_RISK
    if vol_regime in ("EXTREME", "HIGH_VOL"):
        return HERO_RISK_VOLATILITY
    stale_count = len([s for s in stale_providers.split(",") if s.strip()])
    if stale_count >= 2:
        return HERO_RISK_PROVIDER_GAPS
    return HERO_RISK_NONE


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
