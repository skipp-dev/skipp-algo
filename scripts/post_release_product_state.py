"""Post-release product-state validation (ENG-WS5-04).

After release we must verify the visible product, not only the build.
This module produces a structured verdict over the three hero state
families (Market Mode, Setup Quality, Action) plus the Trust state.

DoD:
- Validation berichtet ueber sichtbare Produktzustandspaare,
- Nutzerkritische Pfade sind nach Release explizit abgesichert,
- Fehlerbilder referenzieren Produktfunktionen statt nur technische Schritte.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, StrEnum
from collections.abc import Mapping


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIPPED = "skipped"


# Required keys per surface — each pair maps a product function to
# the underlying hero/trust field that must be populated.
HERO_MARKET_REQUIRED = ("regime", "bias", "session", "trust", "freshness")
HERO_QUALITY_REQUIRED = ("tier", "why_now", "main_risk", "family_health")
HERO_ACTION_REQUIRED = ("verb", "verb_de", "reason", "degradation", "quality")
TRUST_REQUIRED = ("trust", "freshness", "trust_reason")


@dataclass(frozen=True)
class StateCheck:
    surface: str          # product surface: "Market Mode" / "Setup Quality" / ...
    field: str            # underlying hero / trust field
    status: CheckStatus
    product_function: str  # what a user sees if this check fails
    detail: str = ""

    def as_dict(self) -> dict:
        return {
            "surface": self.surface,
            "field": self.field,
            "status": self.status.value,
            "product_function": self.product_function,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class ValidationReport:
    overall_status: CheckStatus
    checks: tuple[StateCheck, ...] = field(default_factory=tuple)
    summary: str = ""

    def as_dict(self) -> dict:
        return {
            "overall_status": self.overall_status.value,
            "checks": [c.as_dict() for c in self.checks],
            "summary": self.summary,
            "failures": [c.as_dict() for c in self.checks
                         if c.status is CheckStatus.FAIL],
        }


# Map (surface, field) -> the user-visible product function the check
# protects. Keeping this here ensures failure messages reference
# product behaviour, not technical pipeline steps.
_PRODUCT_FUNCTION: dict[tuple[str, str], str] = {
    ("Market Mode", "regime"): "Hero zeigt das aktuelle Marktregime",
    ("Market Mode", "bias"): "Hero kommuniziert die Richtungs-Bias",
    ("Market Mode", "session"): "Hero zeigt die aktive Session",
    ("Market Mode", "trust"): "Hero zeigt das Trust-Level fuer das Marktbild",
    ("Market Mode", "freshness"): "Hero zeigt die Datenfrische fuer das Marktbild",

    ("Setup Quality", "tier"): "Hero benennt das Setup-Tier",
    ("Setup Quality", "why_now"): "Hero erklaert, warum das Setup jetzt zaehlt",
    ("Setup Quality", "main_risk"): "Hero benennt das Hauptrisiko des Setups",
    ("Setup Quality", "family_health"): "Hero zeigt die Strukturfamilien-Gesundheit",

    ("Action", "verb"): "Hero zeigt die empfohlene Aktion",
    ("Action", "verb_de"): "Hero zeigt die empfohlene Aktion auf Deutsch",
    ("Action", "reason"): "Hero begruendet die Aktion",
    ("Action", "degradation"): "Hero zeigt aktive Action-Degradation",
    ("Action", "quality"): "Hero zeigt die Aktionsqualitaet",

    ("Trust", "trust"): "Trust-Badge ist sichtbar",
    ("Trust", "freshness"): "Freshness-Badge ist sichtbar",
    ("Trust", "trust_reason"): "Trust-Begruendung ist verfuegbar",
}


def _check_surface(
    surface: str,
    payload: Mapping[str, object],
    required: tuple[str, ...],
) -> list[StateCheck]:
    out: list[StateCheck] = []
    for field_name in required:
        function = _PRODUCT_FUNCTION.get((surface, field_name),
                                         f"{surface} feld {field_name}")
        if field_name not in payload:
            out.append(StateCheck(
                surface=surface, field=field_name,
                status=CheckStatus.FAIL,
                product_function=function,
                detail=f"Feld {field_name!r} fehlt — {function} bricht.",
            ))
            continue
        value = payload[field_name]
        if value is None or (isinstance(value, str) and not value.strip()):
            out.append(StateCheck(
                surface=surface, field=field_name,
                status=CheckStatus.FAIL,
                product_function=function,
                detail=f"Feld {field_name!r} leer — {function} bricht.",
            ))
            continue
        out.append(StateCheck(
            surface=surface, field=field_name,
            status=CheckStatus.PASS,
            product_function=function,
            detail=f"{function}: ok",
        ))
    return out


def validate_post_release(
    *,
    market_mode: Mapping[str, object] | None,
    setup_quality: Mapping[str, object] | None,
    action: Mapping[str, object] | None,
    trust: Mapping[str, object] | None,
) -> ValidationReport:
    """Build the post-release validation report.

    Each surface argument may be ``None`` if the upstream collector
    could not provide it — those checks then surface as SKIPPED so
    the validation log still pinpoints the missing user path.
    """
    checks: list[StateCheck] = []

    surface_payloads = [
        ("Market Mode", market_mode, HERO_MARKET_REQUIRED),
        ("Setup Quality", setup_quality, HERO_QUALITY_REQUIRED),
        ("Action", action, HERO_ACTION_REQUIRED),
        ("Trust", trust, TRUST_REQUIRED),
    ]

    for surface, payload, required in surface_payloads:
        if payload is None:
            for field_name in required:
                function = _PRODUCT_FUNCTION.get(
                    (surface, field_name),
                    f"{surface} feld {field_name}",
                )
                checks.append(StateCheck(
                    surface=surface, field=field_name,
                    status=CheckStatus.SKIPPED,
                    product_function=function,
                    detail=f"{surface} payload nicht verfuegbar — "
                           f"{function} kann nicht geprueft werden.",
                ))
            continue
        checks.extend(_check_surface(surface, payload, required))

    failed = [c for c in checks if c.status is CheckStatus.FAIL]
    skipped = [c for c in checks if c.status is CheckStatus.SKIPPED]

    if failed:
        overall = CheckStatus.FAIL
        summary = (
            f"{len(failed)} sichtbare(r) Produktzustand(staende) gebrochen: "
            + "; ".join(f"{c.surface}/{c.field} → {c.product_function}"
                        for c in failed)
        )
    elif skipped and not [c for c in checks if c.status is CheckStatus.PASS]:
        overall = CheckStatus.SKIPPED
        summary = "alle Surfaces uebersprungen — keine Validation moeglich"
    else:
        overall = CheckStatus.PASS
        summary = "alle sichtbaren Hero- und Trust-Zustaende sind besetzt"

    return ValidationReport(
        overall_status=overall,
        checks=tuple(checks),
        summary=summary,
    )
