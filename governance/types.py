"""Shared TypedDicts for the governance package."""
from __future__ import annotations

from typing import Literal, TypedDict

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
Posture = Literal["green", "yellow", "orange", "red"]
BlockerSeverity = Literal["info", "warning", "blocker"]


class Blocker(TypedDict):
    """A single failed gate check."""

    check: str          # e.g. "brier_threshold", "psr_minIS", "psi_drift"
    severity: BlockerSeverity
    observed: float
    threshold: float
    message: str


class Decision(TypedDict):
    """Aggregated promotion decision for one event family."""

    schema_version: int
    family: EventFamily
    promoted: bool
    posture: Posture
    blockers: list[Blocker]
    metrics: dict[str, float]
