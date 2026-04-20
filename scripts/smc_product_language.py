"""Shared product-language glossary (ENG-WS6-03).

A single source of truth for the product-facing core terms used in
the Hero surface, the release-gate report and the post-release
validation. Keeping the surface, the release-gate output and the
validation report on the same words is what makes the product feel
coherent.

DoD:
- dieselben Kernbegriffe werden konsistent verwendet,
- Default-Surface und Release-Berichte sprechen dieselbe Produkt-
  sprache,
- interne Terminologie tritt in der Nutzerlage zurueck.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductTerm:
    key: str          # internal key (used inside python helpers)
    user_label: str   # what the user reads in the surface
    user_label_de: str
    description: str  # what the term promises to communicate

    def as_dict(self) -> dict:
        return {
            "key": self.key,
            "user_label": self.user_label,
            "user_label_de": self.user_label_de,
            "description": self.description,
        }


# Core product vocabulary. Used by Hero surface (Action / Quality /
# Trust / Risk / Main blocker) and by the release-gate + post-release
# validation reports.
PRODUCT_GLOSSARY: tuple[ProductTerm, ...] = (
    ProductTerm(
        key="action",
        user_label="Action",
        user_label_de="Aktion",
        description="Empfohlene naechste Aktion (ENTER, WAIT, SKIP, AVOID).",
    ),
    ProductTerm(
        key="quality",
        user_label="Setup Quality",
        user_label_de="Setup-Qualitaet",
        description="Tier-Bewertung des aktuellen Setups (A/B/C/D).",
    ),
    ProductTerm(
        key="trust",
        user_label="Trust",
        user_label_de="Vertrauen",
        description="Vertrauenslevel der Datenlage (high/mid/low).",
    ),
    ProductTerm(
        key="risk",
        user_label="Risk",
        user_label_de="Risiko",
        description="Hauptrisiko-Faktor des aktuellen Setups.",
    ),
    ProductTerm(
        key="main_blocker",
        user_label="Main blocker",
        user_label_de="Hauptblocker",
        description="Haupthindernis, das einen besseren Tier verhindert.",
    ),
    ProductTerm(
        key="freshness",
        user_label="Freshness",
        user_label_de="Datenfrische",
        description="Frische der zugrundeliegenden Datenlage.",
    ),
    ProductTerm(
        key="degradation",
        user_label="Degradation",
        user_label_de="Degradation",
        description="Aktive Action-Degradation (none/soft/hard).",
    ),
)


def term(key: str) -> ProductTerm:
    """Lookup a term by its internal key. Raises if unknown."""
    for t in PRODUCT_GLOSSARY:
        if t.key == key:
            return t
    raise KeyError(f"unknown product term {key!r}")


def user_label(key: str, *, locale: str = "en") -> str:
    """Return the user-facing label for ``key`` in the given locale."""
    t = term(key)
    return t.user_label_de if locale == "de" else t.user_label


# Internal jargon that must NEVER appear in user-facing copy. The
# release-gate renderer and the post-release validator can use this
# list to lint their outgoing strings.
INTERNAL_JARGON: frozenset[str] = frozenset({
    "BUS_v2",
    "PACK_state",
    "ensemble_score",
    "calibrated_brier",
    "calibrated_ece",
    "feature_importance",
    "ScorerWeightUpdate",
    "smc_micro_profiles_generated",
})


def lint_user_copy(text: str) -> list[str]:
    """Return the internal-jargon tokens leaking into ``text``.

    Empty list means the copy speaks the product language only.
    DoD: 'interne Terminologie tritt in der Nutzerlage zurueck'.
    """
    if not text:
        return []
    found: list[str] = []
    for token in INTERNAL_JARGON:
        if token in text:
            found.append(token)
    return sorted(found)
