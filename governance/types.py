"""Shared TypedDicts for the governance package."""
from __future__ import annotations

from typing import Literal, TypedDict

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
Posture = Literal["green", "yellow", "orange", "red"]
BlockerSeverity = Literal["info", "warning", "blocker"]


class Blocker(TypedDict):
    """A single failed gate check."""

    check: str          # e.g. "brier_threshold", "psr_minimum", "psi_drift"
    severity: BlockerSeverity
    # ``observed`` is ``None`` for ``info`` blockers (missing metric);
    # this keeps the Decision JSON-safe under ``allow_nan=False``, which
    # is the policy used by every downstream consumer.
    observed: float | None
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
