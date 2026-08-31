"""Compatibility view of the canonical SMC surface registry.

``scripts.smc_bus_manifest.SURFACE_DEFINITIONS`` owns lifecycle and rollout
truth.  This module preserves the older ENG-WS6-01 matrix API for callers that
still consume its coarse production/operator/experimental/historical classes.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scripts.smc_bus_manifest import SURFACE_DEFINITIONS, SurfaceDefinition


class SurfaceClass(StrEnum):
    PRODUCTION = "production"
    OPERATOR_ONLY = "operator_only"
    EXPERIMENTAL = "experimental"
    HISTORICAL = "historical"


class Audience(StrEnum):
    DESKTOP = "desktop"
    MOBILE = "mobile"
    OPERATOR = "operator"


@dataclass(frozen=True)
class SurfaceEntry:
    name: str
    classification: SurfaceClass
    audience: Audience
    description: str
    is_default: bool = False

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "classification": self.classification.value,
            "audience": self.audience.value,
            "description": self.description,
            "is_default": self.is_default,
        }


def _surface_class(surface: SurfaceDefinition) -> SurfaceClass:
    if surface.lifecycle in ("retired_tombstone", "archived"):
        return SurfaceClass.HISTORICAL
    if (
        surface.lifecycle in ("replacement_pending", "retirement_pending")
        or surface.deployment_mode in ("optional", "shadow")
    ):
        return SurfaceClass.EXPERIMENTAL
    if surface.consumer_role in (
        "alert_companion",
        "exit_companion",
        "overlay_companion",
        "setup_utility",
    ):
        return SurfaceClass.OPERATOR_ONLY
    if surface.surface_role == "internal":
        return SurfaceClass.OPERATOR_ONLY
    return SurfaceClass.PRODUCTION


def _audience(surface: SurfaceDefinition) -> Audience:
    if surface.consumer_role == "mobile_companion":
        return Audience.MOBILE
    if surface.surface_role == "companion_operator_only":
        return Audience.OPERATOR
    if surface.surface_role == "internal":
        return Audience.OPERATOR
    return Audience.DESKTOP


def _description(surface: SurfaceDefinition) -> str:
    if surface.notes:
        return " ".join(surface.notes)
    return f"Compatibility view of canonical registry entry {surface.script_name}."


SURFACE_MATRIX: tuple[SurfaceEntry, ...] = tuple(
    SurfaceEntry(
        name=surface.file,
        classification=_surface_class(surface),
        audience=_audience(surface),
        description=_description(surface),
        is_default=surface.file in (
            "SMC_Decision_Board.pine",
            "SMC_Long_Dip_Mobile.pine",
        ),
    )
    for surface in SURFACE_DEFINITIONS
)

# Historical non-SMC tools are outside the canonical SMC registry, but callers
# of the old ``historical_surfaces()`` helper still expect these three
# references.  Keep them out of SURFACE_MATRIX so the matrix itself remains a
# pure registry projection.
_NON_SMC_HISTORICAL_COMPATIBILITY: tuple[SurfaceEntry, ...] = (
    SurfaceEntry(
        name="CHOCH-Indicator.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historical CHoCH indicator retained outside the SMC product cut.",
    ),
    SurfaceEntry(
        name="CHOCH-Strategy.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historical CHoCH strategy retained outside the SMC product cut.",
    ),
    SurfaceEntry(
        name="QuickALGO.pine",
        classification=SurfaceClass.HISTORICAL,
        audience=Audience.DESKTOP,
        description="Historical QuickALGO indicator retained outside the SMC product cut.",
    ),
)


def production_surfaces() -> tuple[SurfaceEntry, ...]:
    return tuple(
        surface
        for surface in SURFACE_MATRIX
        if surface.classification is SurfaceClass.PRODUCTION
    )


def historical_surfaces() -> tuple[SurfaceEntry, ...]:
    registry_surfaces = tuple(
        surface
        for surface in SURFACE_MATRIX
        if surface.classification is SurfaceClass.HISTORICAL
    )
    return registry_surfaces + _NON_SMC_HISTORICAL_COMPATIBILITY


def default_for(audience: Audience) -> SurfaceEntry | None:
    """Return the single production default for an audience, if any."""
    candidates = [
        surface
        for surface in SURFACE_MATRIX
        if surface.audience is audience
        and surface.classification is SurfaceClass.PRODUCTION
        and surface.is_default
    ]
    if not candidates:
        return None
    return candidates[0]


def render_matrix_markdown() -> str:
    """Render the compatibility matrix as a Markdown table."""
    lines = [
        "# SMC Product-Surface Matrix",
        "",
        "| Surface | Klasse | Audience | Default | Beschreibung |",
        "|---------|--------|----------|:-------:|--------------|",
    ]
    for surface in SURFACE_MATRIX:
        marker = "✓" if surface.is_default else ""
        lines.append(
            f"| `{surface.name}` | {surface.classification.value} | "
            f"{surface.audience.value} | {marker} | {surface.description} |"
        )
    lines.append("")
    return "\n".join(lines)
