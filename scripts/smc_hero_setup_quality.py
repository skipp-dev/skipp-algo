"""Hero Setup-Quality card (ENG-WS3-04).

Realises ticket ``ENG-WS3-04`` ("Setup-Qualitaetskarte mit Begruendung
bauen") from
``docs/engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md``.

Composes the Hero-level Setup-Quality card as one deterministic product
object — quality tier + why-now + main-risk + family-health summary —
and lifts it into the Pine library so dashboards must read it from the
canonical fields instead of re-classifying raw ensemble scores.

DoD:

* Setup-Qualitaet ist nicht nur ein Rohwert — we expose a
  human-readable tier *and* the reasoning (``why_now`` + ``main_risk``).
* Why now und Main risk sind sichtbar — pinned as own Pine fields.
* Default und Audit nutzen dieselbe Logik — both surfaces read the
  same ``HERO_QUALITY_*`` block.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from collections.abc import Mapping


# ── Tier vocabulary ───────────────────────────────────────────────────


_TIER_VOCAB: tuple[str, ...] = ("excellent", "good", "limited", "avoid")


def all_quality_tiers() -> tuple[str, ...]:
    """Return the four canonical Hero-quality tiers in severity order."""
    return _TIER_VOCAB


# Score thresholds map a normalised ensemble-quality score (0..1) to a
# Hero-readable tier. Boundaries are inclusive on the upper side
# (``score >= threshold``).
_SCORE_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.80, "excellent"),
    (0.60, "good"),
    (0.40, "limited"),
    (0.0, "avoid"),
)


# Translation from the existing ensemble-quality string tier (which
# downstream code has been emitting as 'high' / 'mid' / 'low' / 'na')
# into the new Hero vocabulary.
_ENSEMBLE_TIER_MAP: Mapping[str, str] = {
    "high": "excellent",
    "mid": "good",
    "low": "limited",
    "na": "avoid",
}


def _quality_tier_from_score(score: float) -> str:
    for threshold, tier in _SCORE_THRESHOLDS:
        if score >= threshold:
            return tier
    return "avoid"


def _quality_tier_from_ensemble(eq: Mapping[str, Any]) -> str:
    raw_tier = str(eq.get("tier") or "").lower()
    if raw_tier in _ENSEMBLE_TIER_MAP:
        return _ENSEMBLE_TIER_MAP[raw_tier]
    try:
        score = float(eq.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    return _quality_tier_from_score(score)


# ── Why now / main risk ───────────────────────────────────────────────


def _why_now_from_enrichment(enrichment: Mapping[str, Any], tier: str) -> str:
    """Pick a single why-now sentence; never empty."""
    quality = enrichment.get("hero_quality") or {}
    if isinstance(quality, Mapping):
        text = str(quality.get("why_now") or "").strip()
        if text:
            return text
    eq = enrichment.get("ensemble_quality") or {}
    if isinstance(eq, Mapping):
        text = str(eq.get("why_now") or "").strip()
        if text:
            return text
    if tier in ("excellent", "good"):
        return f"Setup quality {tier} — confluence aligned"
    if tier == "limited":
        return "Mixed confluence — selektiv handeln"
    return "Confluence missing — beobachten"


def _main_risk_from_enrichment(enrichment: Mapping[str, Any], tier: str) -> str:
    """Pick a single main-risk sentence; never empty."""
    quality = enrichment.get("hero_quality") or {}
    if isinstance(quality, Mapping):
        text = str(quality.get("main_risk") or "").strip()
        if text:
            return text
    eq = enrichment.get("ensemble_quality") or {}
    if isinstance(eq, Mapping):
        text = str(eq.get("main_risk") or "").strip()
        if text:
            return text
    # Fall back to the trust-state degradation reason if present — the
    # main risk for a degraded surface is by definition the data state.
    trust = enrichment.get("trust_state") or {}
    if isinstance(trust, Mapping):
        cause = trust.get("cause") or {}
        if isinstance(cause, Mapping):
            description = str(cause.get("description") or "").strip()
            if description:
                return description
    if tier == "excellent":
        return "Position sizing only"
    if tier == "good":
        return "Confluence partial — keep trigger tight"
    if tier == "limited":
        return "Setup edge thin — wait for confirmation"
    return "Setup unsupported — keine Aktion"


def _family_health(enrichment: Mapping[str, Any]) -> str:
    """Compress family scoring into a Hero-readable token."""
    eq = enrichment.get("ensemble_quality") or {}
    if isinstance(eq, Mapping):
        components = eq.get("available_components")
        count: int | None = None
        if isinstance(components, (int, float)):
            count = int(components)
        elif isinstance(components, (list, tuple, set)):
            count = len(components)
        elif isinstance(components, str):
            count = len([s for s in components.split(",") if s.strip()])
        if count is not None:
            if count >= 4:
                return "all_families"
            if count == 3:
                return "three_families"
            if count == 2:
                return "two_families"
            if count == 1:
                return "single_family"
            return "no_families"
    return "unknown"


# ── Result dataclass ──────────────────────────────────────────────────


@dataclass(frozen=True)
class HeroSetupQuality:
    """Hero-level Setup-Quality card."""

    tier: str
    why_now: str
    main_risk: str
    family_health: str

    def as_dict(self) -> dict[str, str]:
        return {
            "tier": self.tier,
            "why_now": self.why_now,
            "main_risk": self.main_risk,
            "family_health": self.family_health,
        }


# ── Derivation ────────────────────────────────────────────────────────


def derive_hero_setup_quality(enrichment: Mapping[str, Any]) -> HeroSetupQuality:
    enr = enrichment or {}
    eq = enr.get("ensemble_quality") or {}
    tier = _quality_tier_from_ensemble(eq if isinstance(eq, Mapping) else {})
    return HeroSetupQuality(
        tier=tier,
        why_now=_why_now_from_enrichment(enr, tier),
        main_risk=_main_risk_from_enrichment(enr, tier),
        family_health=_family_health(enr),
    )


# ── Pine rendering ────────────────────────────────────────────────────


PINE_HERO_QUALITY_FIELDS: tuple[str, ...] = (
    "HERO_QUALITY_TIER",
    "HERO_QUALITY_WHY_NOW",
    "HERO_QUALITY_MAIN_RISK",
    "HERO_QUALITY_FAMILY_HEALTH",
)


def _pine_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def render_hero_setup_quality_block_lines(
    enrichment: Mapping[str, Any],
) -> list[str]:
    quality = derive_hero_setup_quality(enrichment)
    values = quality.as_dict()
    lines: list[str] = ["// ── Hero Setup Quality (ENG-WS3-04) ──"]
    for field, key in zip(
        PINE_HERO_QUALITY_FIELDS,
        ("tier", "why_now", "main_risk", "family_health"), strict=False,
    ):
        lines.append(
            f'export const string {field} = "{_pine_string(values[key])}"'
        )
    return lines


__all__ = [
    "PINE_HERO_QUALITY_FIELDS",
    "HeroSetupQuality",
    "all_quality_tiers",
    "derive_hero_setup_quality",
    "render_hero_setup_quality_block_lines",
]
