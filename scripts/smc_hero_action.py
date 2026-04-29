"""Hero Action recommendation (ENG-WS3-05).

Realises ticket ``ENG-WS3-05`` ("Handlungsempfehlung als primaere
Ausgabe modellieren") from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

The product must explicitly say: **handeln, warten, beobachten, oder
vermeiden** — one primary action per state, in user-readable language,
not just an internal action-state code.

This module composes the canonical Hero-level Action recommendation
from:

* ``ActionDegradation`` (ENG-WS2-04) — the degradation tier from the
  trust state.
* ``HeroSetupQuality`` (ENG-WS3-04) — the reasoned setup quality.

And renders it as a single Pine block so dashboards must read the same
recommendation everywhere (no second classification path).

DoD:

* pro Zustand existiert genau eine primaere Handlung — enforced by
  ``_ACTION_TABLE`` returning exactly one ``HeroAction`` per
  (degradation, quality) pair.
* Action-State ist fuer Nutzer lesbar statt nur intern codiert —
  every action carries a German verb (``handeln`` / ``warten`` /
  ``beobachten`` / ``vermeiden``) and an English verb token.
* Main risk und Hauptblocker widersprechen der Aktion nicht —
  ``HeroAction.reason`` uses the degradation reason (the actual
  blocker) when degraded, and the quality main_risk only when
  trust is healthy.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from scripts.smc_hero_setup_quality import derive_hero_setup_quality
from smc_integration.action_degradation import (
    ActionDegradation,
    derive_action_degradation,
)
from smc_integration.trust_state import (
    TrustState,
    TrustStateAssessment,
    TrustStateCause,
    derive_trust_state,
)

# ── Action vocabulary ─────────────────────────────────────────────────


class _Verb:
    HANDELN = ("act", "handeln")
    WARTEN = ("wait", "warten")
    BEOBACHTEN = ("watch", "beobachten")
    VERMEIDEN = ("avoid", "vermeiden")


_ALLOWED_VERBS: frozenset[str] = frozenset({"act", "wait", "watch", "avoid"})


def all_action_verbs() -> tuple[str, ...]:
    """Return the four canonical Hero action verbs in severity order."""
    return ("act", "wait", "watch", "avoid")


# Mapping table: (degradation tier, quality tier) -> (verb_en, verb_de).
# Reading order: degradation first (it gates everything), then quality.
_ACTION_TABLE: dict[tuple[ActionDegradation, str], tuple[str, str]] = {
    (ActionDegradation.NO_TRADE, "excellent"): _Verb.VERMEIDEN,
    (ActionDegradation.NO_TRADE, "good"): _Verb.VERMEIDEN,
    (ActionDegradation.NO_TRADE, "limited"): _Verb.VERMEIDEN,
    (ActionDegradation.NO_TRADE, "avoid"): _Verb.VERMEIDEN,

    (ActionDegradation.WATCHLIST, "excellent"): _Verb.BEOBACHTEN,
    (ActionDegradation.WATCHLIST, "good"): _Verb.BEOBACHTEN,
    (ActionDegradation.WATCHLIST, "limited"): _Verb.BEOBACHTEN,
    (ActionDegradation.WATCHLIST, "avoid"): _Verb.BEOBACHTEN,

    (ActionDegradation.SELECTIVE, "excellent"): _Verb.HANDELN,
    (ActionDegradation.SELECTIVE, "good"): _Verb.WARTEN,
    (ActionDegradation.SELECTIVE, "limited"): _Verb.BEOBACHTEN,
    (ActionDegradation.SELECTIVE, "avoid"): _Verb.VERMEIDEN,

    (ActionDegradation.NONE, "excellent"): _Verb.HANDELN,
    (ActionDegradation.NONE, "good"): _Verb.HANDELN,
    (ActionDegradation.NONE, "limited"): _Verb.WARTEN,
    (ActionDegradation.NONE, "avoid"): _Verb.BEOBACHTEN,
}


# ── Result dataclass ──────────────────────────────────────────────────


@dataclass(frozen=True)
class HeroAction:
    """The one Hero-level primary action for a snapshot."""

    verb: str            # act / wait / watch / avoid
    verb_de: str         # handeln / warten / beobachten / vermeiden
    reason: str          # one sentence — never empty
    degradation: str     # ActionDegradation tier value
    quality: str         # HeroSetupQuality tier value

    def as_dict(self) -> dict[str, str]:
        return {
            "verb": self.verb,
            "verb_de": self.verb_de,
            "reason": self.reason,
            "degradation": self.degradation,
            "quality": self.quality,
        }


# ── Derivation ────────────────────────────────────────────────────────


def _assessment_from_block(block: Mapping[str, Any]) -> TrustStateAssessment:
    cause_block = block.get("cause") or {}
    cause = TrustStateCause(
        domain=cause_block.get("domain"),
        failure_type=cause_block.get("failure_type"),
        code=cause_block.get("code"),
        description=cause_block.get("description"),
    )
    try:
        state = TrustState(str(block.get("state") or "healthy"))
    except ValueError:
        state = TrustState.HEALTHY
    return TrustStateAssessment(
        state=state,
        action_impact=str(block.get("action_impact") or "ok"),
        cause=cause,
        contributing_alerts=tuple(block.get("contributing_alerts") or ()),
        derived_from_overall_status=str(block.get("derived_from_overall_status") or "ok"),
    )


def derive_hero_action(enrichment: Mapping[str, Any]) -> HeroAction:
    enr = enrichment or {}

    # Degradation: prefer attached block, else derive from trust state
    # (which itself prefers attached trust_state, else derives).
    deg_block = enr.get("action_degradation")
    if isinstance(deg_block, Mapping) and deg_block.get("tier"):
        try:
            degradation = ActionDegradation(str(deg_block["tier"]))
        except ValueError:
            degradation = ActionDegradation.SELECTIVE
        deg_reason = str(deg_block.get("reason") or "")
    else:
        trust_block = enr.get("trust_state")
        if isinstance(trust_block, Mapping) and trust_block.get("state"):
            assessment = _assessment_from_block(trust_block)
        else:
            assessment = derive_trust_state(enr)
        result = derive_action_degradation(assessment)
        degradation = result.tier
        deg_reason = result.reason

    quality_card = derive_hero_setup_quality(enr)
    quality_tier = quality_card.tier

    verb_en, verb_de = _ACTION_TABLE[(degradation, quality_tier)]

    # Reason composition:
    #  - When degraded, the data state IS the blocker → use deg_reason.
    #  - Otherwise the main risk drives the action language.
    if degradation is not ActionDegradation.NONE and deg_reason:
        reason = deg_reason
    else:
        reason = quality_card.main_risk or quality_card.why_now or "Setup unsupported"

    return HeroAction(
        verb=verb_en,
        verb_de=verb_de,
        reason=reason,
        degradation=degradation.value,
        quality=quality_tier,
    )


# ── Pine rendering ────────────────────────────────────────────────────


PINE_HERO_ACTION_FIELDS: tuple[str, ...] = (
    "HERO_ACTION_VERB",
    "HERO_ACTION_VERB_DE",
    "HERO_ACTION_REASON",
    "HERO_ACTION_DEGRADATION",
    "HERO_ACTION_QUALITY",
)


def _pine_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_hero_action_block_lines(
    enrichment: Mapping[str, Any],
) -> list[str]:
    action = derive_hero_action(enrichment)
    values = action.as_dict()
    lines: list[str] = ["// ── Hero Action (ENG-WS3-05) ──"]
    for field, key in zip(
        PINE_HERO_ACTION_FIELDS,
        ("verb", "verb_de", "reason", "degradation", "quality"), strict=False,
    ):
        lines.append(
            f'export const string {field} = "{_pine_string(values[key])}"'
        )
    return lines


__all__ = [
    "PINE_HERO_ACTION_FIELDS",
    "HeroAction",
    "all_action_verbs",
    "derive_hero_action",
    "render_hero_action_block_lines",
]
