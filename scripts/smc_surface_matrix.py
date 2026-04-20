"""Supported product-surface matrix (ENG-WS6-01).

Defines which surfaces are PRODUCTION, OPERATOR_ONLY, EXPERIMENTAL
or HISTORICAL. Until now historical variants were implicitly
co-equal; this matrix promotes a single production default per
audience and makes the rest visibly subordinate.

DoD:
- Surface-Matrix ist dokumentiert,
- produktive Default-Pfade sind eindeutig,
- historische Varianten sind nicht mehr implizit gleichrangig.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SurfaceClass(str, Enum):
    PRODUCTION = "production"
    OPERATOR_ONLY = "operator_only"
    EXPERIMENTAL = "experimental"
    HISTORICAL = "historical"


class Audience(str, Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    OPERATOR = "operator"


@dataclass(frozen=True)
class SurfaceEntry:
    name: str            # filename (e.g. SMC_Dashboard.pine)
    classification: SurfaceClass
    audience: Audience
    description: str
    is_default: bool = False  # true iff this is THE default for its audience

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "classification": self.classification.value,
            "audience": self.audience.value,
            "description": self.description,
            "is_default": self.is_default,
        }


# The single source of truth. Order is presentation order in docs.
SURFACE_MATRIX: tuple[SurfaceEntry, ...] = (
    SurfaceEntry(
        name="SMC_Dashboard.pine",
        classification=SurfaceClass.PRODUCTION,
        audience=Audience.DESKTOP,
        description="Hauptdashboard mit Hero-Surface (Market Mode, "
                    "Setup Quality, Action) — Produktivnutzer-Default.",
        is_default=True,
    ),
    SurfaceEntry(
        name="SMC_Mobile_Dashboard.pine",
        classification=SurfaceClass.PRODUCTION,
        audience=Audience.MOBILE,
        description="Mobile Hero-Surface — Mobil-Default.",
        is_default=True,
    ),
    SurfaceEntry(
        name="SMC_Setup_Check.pine",
        classification=SurfaceClass.OPERATOR_ONLY,
        audience=Audience.OPERATOR,
        description="Operator-Diagnose: Setup-Check fuer Engine-Zustand.",
    ),
    SurfaceEntry(
        name="SMC_TV_Bridge.pine",
        classification=SurfaceClass.OPERATOR_ONLY,
        audience=Audience.OPERATOR,
        description="Operator-Bridge fuer TradingView-Integration.",
    ),
    SurfaceEntry(
        name="SMC_Event_Overlay.pine",
        classification=SurfaceClass.OPERATOR_ONLY,
        audience=Audience.OPERATOR,
        description="Operator-Overlay fuer Event-Inspektion.",
    ),
    SurfaceEntry(
        name="SMC_Orderflow_Overlay.pine",
        classification=SurfaceClass.EXPERIMENTAL,
        audience=Audience.DESKTOP,
        description="Experimentelles Orderflow-Overlay — nicht produktiv.",
    ),
    SurfaceEntry(
        name="CHOCH-Indicator.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historische CHoCH-Variante — fuer Referenz, nicht "
                    "produktiv genutzt.",
    ),
    SurfaceEntry(
        name="CHOCH-Strategy.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historische CHoCH-Strategie — fuer Referenz.",
    ),
    SurfaceEntry(
        name="QuickALGO.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historischer QuickALGO-Indikator.",
    ),
)


def production_surfaces() -> tuple[SurfaceEntry, ...]:
    return tuple(s for s in SURFACE_MATRIX
                 if s.classification is SurfaceClass.PRODUCTION)


def historical_surfaces() -> tuple[SurfaceEntry, ...]:
    return tuple(s for s in SURFACE_MATRIX
                 if s.classification is SurfaceClass.HISTORICAL)


def default_for(audience: Audience) -> SurfaceEntry | None:
    """Return THE production default for a given audience, if any."""
    candidates = [s for s in SURFACE_MATRIX
                  if s.audience is audience
                  and s.classification is SurfaceClass.PRODUCTION
                  and s.is_default]
    if not candidates:
        return None
    return candidates[0]


def render_matrix_markdown() -> str:
    """Render the surface matrix as a Markdown table."""
    lines = [
        "# SMC Product-Surface Matrix",
        "",
        "| Surface | Klasse | Audience | Default | Beschreibung |",
        "|---------|--------|----------|:-------:|--------------|",
    ]
    for s in SURFACE_MATRIX:
        marker = "✓" if s.is_default else ""
        lines.append(
            f"| `{s.name}` | {s.classification.value} | "
            f"{s.audience.value} | {marker} | {s.description} |"
        )
    lines.append("")
    return "\n".join(lines)
