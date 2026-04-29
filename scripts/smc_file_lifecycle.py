"""Legacy / Experimental classification for product files (ENG-WS6-04).

Builds on the surface matrix (WS6-01). Where WS6-01 declares the
class for top-level product surfaces, this module classifies every
Pine file in the workspace so later cleanup steps can act surgically
instead of broadly.

DoD:
- Legacy- und Experimental-Dateien sind explizit markiert,
- die Produktidentitaet wird dadurch nicht mehr verwaessert,
- spaetere Cleanup-Schritte koennen gezielt statt breit erfolgen.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum

from scripts.smc_surface_matrix import SURFACE_MATRIX, SurfaceClass


class FileLifecycle(StrEnum):
    PRODUCTION = "production"
    OPERATOR_ONLY = "operator_only"
    EXPERIMENTAL = "experimental"
    LEGACY = "legacy"
    UNCLASSIFIED = "unclassified"


# Explicit overrides for files that are NOT in SURFACE_MATRIX but
# still need a clear lifecycle classification. Keys are exact
# filenames (basename); use this to mark scratch / single-purpose
# Pine files.
EXPLICIT_OVERRIDES: dict[str, FileLifecycle] = {
    # Hero/Engine production-adjacent helpers.
    "SMC_Core_Engine.pine": FileLifecycle.PRODUCTION,
    "SMC_Structure_Context.pine": FileLifecycle.PRODUCTION,
    "SMC_Liquidity_Context.pine": FileLifecycle.PRODUCTION,
    "SMC_Liquidity_Structure.pine": FileLifecycle.PRODUCTION,
    "SMC_Imbalance_Context.pine": FileLifecycle.PRODUCTION,
    "SMC_Profile_Context.pine": FileLifecycle.PRODUCTION,
    "SMC_Session_Context.pine": FileLifecycle.PRODUCTION,
    "SMC_HTF_Confluence.pine": FileLifecycle.PRODUCTION,
    "SMC_Long_Strategy.pine": FileLifecycle.PRODUCTION,
    # Operator-facing helpers not in SURFACE_MATRIX.
    # (SMC_Setup_Check / SMC_TV_Bridge / SMC_Event_Overlay are already
    # in SURFACE_MATRIX.)
    # Experimental.
    "BFI-Reversal.pine": FileLifecycle.EXPERIMENTAL,
    "Breakout_Finder_Intelligent.pine": FileLifecycle.EXPERIMENTAL,
    "REV-BUY.pine": FileLifecycle.EXPERIMENTAL,
    "REV-Ladder.pine": FileLifecycle.EXPERIMENTAL,
    "REV-Ladder-CHoCH.pine": FileLifecycle.EXPERIMENTAL,
    "BTC 3m EV Scalper BALANCED (Harmonized).pine": FileLifecycle.EXPERIMENTAL,
    "test_div.pine": FileLifecycle.EXPERIMENTAL,
    # Legacy CHoCH/QuickALGO family — non-matrix entries only.
    # (CHOCH-Indicator / CHOCH-Strategy / QuickALGO are in SURFACE_MATRIX.)
    "CHOCH-Base_Indikator.pine": FileLifecycle.LEGACY,
    "CHOCH-Base_Strategy.pine": FileLifecycle.LEGACY,
    "CHoCH.pine": FileLifecycle.LEGACY,
    "SkippALGO_Confluence.pine": FileLifecycle.LEGACY,
}


def _from_surface_class(cls: SurfaceClass) -> FileLifecycle:
    return {
        SurfaceClass.PRODUCTION: FileLifecycle.PRODUCTION,
        SurfaceClass.OPERATOR_ONLY: FileLifecycle.OPERATOR_ONLY,
        SurfaceClass.EXPERIMENTAL: FileLifecycle.EXPERIMENTAL,
        SurfaceClass.HISTORICAL: FileLifecycle.LEGACY,
    }[cls]


def classify_file(filename: str) -> FileLifecycle:
    """Return the lifecycle classification for a given Pine filename.

    Resolution order:
      1. SURFACE_MATRIX (top-level product surfaces).
      2. EXPLICIT_OVERRIDES.
      3. UNCLASSIFIED — flagged so later cleanup steps see the gap.
    """
    for entry in SURFACE_MATRIX:
        if entry.name == filename:
            return _from_surface_class(entry.classification)
    if filename in EXPLICIT_OVERRIDES:
        return EXPLICIT_OVERRIDES[filename]
    return FileLifecycle.UNCLASSIFIED


@dataclass(frozen=True)
class ClassificationResult:
    filename: str
    lifecycle: FileLifecycle

    @property
    def is_legacy(self) -> bool:
        return self.lifecycle is FileLifecycle.LEGACY

    @property
    def is_experimental(self) -> bool:
        return self.lifecycle is FileLifecycle.EXPERIMENTAL

    @property
    def is_user_facing_production(self) -> bool:
        return self.lifecycle is FileLifecycle.PRODUCTION

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "lifecycle": self.lifecycle.value,
            "is_legacy": self.is_legacy,
            "is_experimental": self.is_experimental,
            "is_user_facing_production": self.is_user_facing_production,
        }


def classify_files(filenames: list[str]) -> list[ClassificationResult]:
    return [ClassificationResult(filename=f, lifecycle=classify_file(f))
            for f in filenames]
