"""Action-degradation policy (ENG-WS2-04).

Realises ticket ``ENG-WS2-04`` from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``
("Handlung aus Trust und Freshness degradieren").

Maps the canonical product trust state defined in
:mod:`smc_integration.trust_state` (ENG-WS2-01) to a deterministic
**action-degradation tier** so every consumer (Pine dashboard, micro
base snapshot, post-release validation) sees the same product-action
behaviour for the same trust lage.

The four tiers are intentionally few and product-shaped:

- ``NONE``        — full trust, no degradation, all actions allowed.
- ``SELECTIVE``   — advisory-only failures: entries still allowed, the
                    surface should communicate the limitation.
- ``WATCHLIST``   — suppress new entries; existing positions are not
                    auto-managed by the product. Operator should treat
                    the symbol as a watch-only candidate.
- ``NO_TRADE``    — hard-degrade or fully unavailable: no product
                    action is supported at all.

The mapping from :class:`TrustState` is **single-direction and
exhaustive** so no caller needs to invent it twice:

    HEALTHY     → NONE
    DEGRADED    → SELECTIVE
    STALE       → SELECTIVE
    WATCH_ONLY  → WATCHLIST
    UNAVAILABLE → NO_TRADE

The reason text is derived from the cause already surfaced by
:class:`TrustStateAssessment` so the UI can explain *why* the action
was degraded without re-deriving it from raw alerts.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass

from smc_integration.trust_state import (
    TrustState,
    TrustStateAssessment,
)


class ActionDegradation(enum.Enum):
    """Canonical action-degradation tiers (ENG-WS2-04 scope)."""

    NONE = "none"
    SELECTIVE = "selective"
    WATCHLIST = "watchlist"
    NO_TRADE = "no_trade"


# Stable severity order — strongest restriction wins when multiple
# trust lages overlap (the assessment already collapses to one state,
# so this is mostly informational).
_TIER_SEVERITY: tuple[ActionDegradation, ...] = (
    ActionDegradation.NONE,
    ActionDegradation.SELECTIVE,
    ActionDegradation.WATCHLIST,
    ActionDegradation.NO_TRADE,
)


# Single canonical TrustState → ActionDegradation table.
_TRUST_TO_TIER: dict[TrustState, ActionDegradation] = {
    TrustState.HEALTHY: ActionDegradation.NONE,
    TrustState.DEGRADED: ActionDegradation.SELECTIVE,
    TrustState.STALE: ActionDegradation.SELECTIVE,
    TrustState.WATCH_ONLY: ActionDegradation.WATCHLIST,
    TrustState.UNAVAILABLE: ActionDegradation.NO_TRADE,
}


def tier_for_trust_state(state: TrustState) -> ActionDegradation:
    """Return the canonical action-degradation tier for a trust state.

    Defensive default: an unknown enum value (added later) maps to
    ``SELECTIVE`` so a future addition is loud (action visibly
    degraded) rather than silently HEALTHY.
    """
    tier = _TRUST_TO_TIER.get(state)
    if tier is None:
        return ActionDegradation.SELECTIVE
    return tier


@dataclass(frozen=True)
class ActionDegradationResult:
    """Action-degradation decision for a single trust assessment.

    The ``reason`` field is the single human-readable sentence the UI
    should show next to the degraded action ("die UI erklaert, warum
    die Aktion degradiert wurde" — DoD of ENG-WS2-04). It is derived
    from the trust assessment's cause, so there is no duplicate
    derivation in any consumer.
    """

    tier: ActionDegradation
    reason: str
    derived_from_state: TrustState

    def as_dict(self) -> dict[str, str]:
        """Stable JSON-friendly projection (used by exports)."""
        return {
            "tier": self.tier.value,
            "reason": self.reason,
            "derived_from_state": self.derived_from_state.value,
        }


def _build_reason(assessment: TrustStateAssessment, tier: ActionDegradation) -> str:
    """Compose the UI-visible reason string for the chosen tier.

    HEALTHY → empty string (no degradation to explain).
    Otherwise: prefer the cause description; fall back to a synthesised
    sentence built from ``tier + cause.code/domain`` so we never emit
    an empty reason for a degraded tier.
    """
    if tier is ActionDegradation.NONE:
        return ""
    cause = assessment.cause
    description = (cause.description or "").strip()
    if description:
        return description
    code = (cause.code or "").strip()
    domain = (cause.domain or "").strip()
    if code and domain:
        return f"{tier.value}: {domain} {code}"
    if code:
        return f"{tier.value}: {code}"
    if domain:
        return f"{tier.value}: {domain}"
    # Last-resort: name the trust state so the UI is never silent.
    return f"{tier.value}: trust={assessment.state.value}"


def derive_action_degradation(
    assessment: TrustStateAssessment,
) -> ActionDegradationResult:
    """Derive the action-degradation tier + reason for one assessment.

    Pure, deterministic, read-only. The same assessment always yields
    the same result so all consumers (snapshot, Pine library, release
    validation) agree on the action.
    """
    tier = tier_for_trust_state(assessment.state)
    reason = _build_reason(assessment, tier)
    return ActionDegradationResult(
        tier=tier,
        reason=reason,
        derived_from_state=assessment.state,
    )


def all_action_tiers() -> tuple[ActionDegradation, ...]:
    """Stable iteration order over every canonical action-degradation tier."""
    return _TIER_SEVERITY


__all__ = [
    "ActionDegradation",
    "ActionDegradationResult",
    "all_action_tiers",
    "derive_action_degradation",
    "tier_for_trust_state",
]
