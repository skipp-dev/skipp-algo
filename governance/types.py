"""Shared TypedDicts for the governance package."""
from __future__ import annotations

from typing import Literal, TypedDict, Union

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
Posture = Literal["green", "yellow", "orange", "red"]
BlockerSeverity = Literal["info", "warning", "blocker"]

ProvenanceValue = Union[str, int, float, bool]


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
    """Aggregated promotion decision for one event family.

    ``provenance`` was added at schema_version=2 (Sprint W1.a) to carry
    non-numeric hardening metadata (e.g. ``wf_scheme``, ``bootstrap_method``,
    ``psr_method``). Stays an empty dict for legacy callers.
    """

    schema_version: int
    family: EventFamily
    promoted: bool
    posture: Posture
    blockers: list[Blocker]
    metrics: dict[str, float]
    provenance: dict[str, ProvenanceValue]
