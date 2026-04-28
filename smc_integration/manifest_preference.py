"""Manifest-preferred artifact resolution policy (ENG-WS5-01).

Production discovery paths must always prefer manifest-backed
artifacts over local scratch files. This module formalises that
policy as a pure helper so provider_health, structure_audit and the
pre-release artifact refresh script can converge on a single,
auditable decision rule.

Source taxonomy
---------------
* ``manifest`` — declared by the release manifest; production-truth.
* ``shadow``   — declared by a shadow/staging manifest; not production.
* ``scratch``  — local file with no manifest backing; never wins over
                 a manifest-backed artifact.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from collections.abc import Iterable


class ArtifactSource(str, Enum):
    MANIFEST = "manifest"
    SHADOW = "shadow"
    SCRATCH = "scratch"


# Source priority — higher wins. Manifest must always beat scratch.
_PRIORITY: dict[ArtifactSource, int] = {
    ArtifactSource.MANIFEST: 100,
    ArtifactSource.SHADOW: 50,
    ArtifactSource.SCRATCH: 0,
}


@dataclass(frozen=True)
class ArtifactCandidate:
    path: Path
    source: ArtifactSource
    label: str = ""

    @property
    def priority(self) -> int:
        return _PRIORITY[self.source]


@dataclass(frozen=True)
class ResolutionResult:
    chosen: ArtifactCandidate | None
    rejected: tuple[ArtifactCandidate, ...] = field(default_factory=tuple)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "chosen_path": str(self.chosen.path) if self.chosen else None,
            "chosen_source": self.chosen.source.value if self.chosen else None,
            "chosen_label": self.chosen.label if self.chosen else "",
            "rejected": [
                {"path": str(c.path), "source": c.source.value, "label": c.label}
                for c in self.rejected
            ],
            "reason": self.reason,
        }


def resolve_preferred(
    candidates: Iterable[ArtifactCandidate],
) -> ResolutionResult:
    """Pick the highest-priority candidate.

    DoD: 'produktive Pfade bevorzugen manifest-backed Artefakte';
    'lokale Scratch-Artefakte koennen die produktive Sicht nicht mehr
    unbemerkt ueberlagern'; 'Fehlermeldungen erklaeren die gewaehlte
    Quelle nachvollziehbar'.
    """
    items = list(candidates)
    if not items:
        return ResolutionResult(chosen=None, rejected=(), reason="no candidates")

    # Stable order: priority desc, then original order. Path strings
    # are NOT used as tie-breakers so a manifest entry beats a scratch
    # entry even when the scratch path sorts higher.
    indexed = sorted(
        enumerate(items),
        key=lambda x: (-x[1].priority, x[0]),
    )
    chosen_idx, chosen = indexed[0]
    rejected = tuple(c for i, c in indexed[1:])

    if chosen.source is ArtifactSource.SCRATCH and len(items) == 1:
        reason = (
            f"only scratch candidate available at {chosen.path}; "
            "no manifest-backed artifact found"
        )
    elif chosen.source is ArtifactSource.MANIFEST:
        scratch_overridden = [c for c in rejected
                              if c.source is ArtifactSource.SCRATCH]
        if scratch_overridden:
            reason = (
                f"chose manifest artifact {chosen.path}; ignored "
                f"{len(scratch_overridden)} scratch candidate(s) — "
                "manifest beats local scratch"
            )
        else:
            reason = f"chose manifest artifact {chosen.path}"
    elif chosen.source is ArtifactSource.SHADOW:
        reason = (
            f"chose shadow artifact {chosen.path}; "
            "no manifest-backed artifact available"
        )
    else:
        reason = f"chose {chosen.source.value} artifact {chosen.path}"

    return ResolutionResult(chosen=chosen, rejected=rejected, reason=reason)
