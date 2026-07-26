"""Legacy file-lifecycle compatibility view (ENG-WS6-04).

SMC product files are classified through the canonical registry exposed by
``scripts.smc_surface_matrix``.  The override table is intentionally limited
to non-SMC Pine files that live outside that registry.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from scripts.smc_surface_matrix import SURFACE_MATRIX, SurfaceClass


class FileLifecycle(StrEnum):
    PRODUCTION = "production"
    OPERATOR_ONLY = "operator_only"
    EXPERIMENTAL = "experimental"
    LEGACY = "legacy"
    UNCLASSIFIED = "unclassified"


# Exact non-SMC filenames that are intentionally outside SURFACE_DEFINITIONS.
# SMC entries must never be added here: their lifecycle belongs in the
# canonical registry and flows through SURFACE_MATRIX.
EXPLICIT_OVERRIDES: dict[str, FileLifecycle] = {
    "BFI-Reversal.pine": FileLifecycle.EXPERIMENTAL,
    "Breakout_Finder_Intelligent.pine": FileLifecycle.EXPERIMENTAL,
    "REV-BUY.pine": FileLifecycle.EXPERIMENTAL,
    "REV-Ladder.pine": FileLifecycle.EXPERIMENTAL,
    "REV-Ladder-CHoCH.pine": FileLifecycle.EXPERIMENTAL,
    "BTC 3m EV Scalper BALANCED (Harmonized).pine": FileLifecycle.EXPERIMENTAL,
    "test_div.pine": FileLifecycle.EXPERIMENTAL,
    "CHOCH-Base_Indikator.pine": FileLifecycle.LEGACY,
    "CHOCH-Base_Strategy.pine": FileLifecycle.LEGACY,
    "CHOCH-Indicator.pine": FileLifecycle.LEGACY,
    "CHOCH-Strategy.pine": FileLifecycle.LEGACY,
    "CHoCH.pine": FileLifecycle.LEGACY,
    "QuickALGO.pine": FileLifecycle.LEGACY,
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
      1. SURFACE_MATRIX (compatibility projection of the canonical registry).
      2. EXPLICIT_OVERRIDES for non-SMC files.
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
