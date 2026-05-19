"""Shared TypedDicts for the governance package."""
from __future__ import annotations

from typing import Literal, TypedDict, Union

EventFamily = Literal["BOS", "OB", "FVG", "SWEEP"]
Posture = Literal["green", "yellow", "orange", "red"]
BlockerSeverity = Literal["info", "warning", "blocker"]

ProvenanceValue = Union[str, int, float, bool]

# F-008 (2026-05-18): closed inventory of check names that
# ``PromotionGate.evaluate()`` may emit on a Blocker. Dashboard / report
# consumers parse these strings, so renaming any of them is a contract
# break. ``provenance.<key>`` is a prefix; the per-key suffix comes from
# ``REQUIRED_PROVENANCE_KEYS`` in ``governance.promotion_gate``.
#
# Pinned by ``tests/test_promotion_gate_check_name_inventory.py``: any new
# check name MUST be added here in the same commit that emits it.
BLOCKER_CHECK_NAMES: frozenset[str] = frozenset({
    "brier_threshold",
    "ece_threshold",
    "fdr_significance",
    "psr_minimum",
    "mintrl_horizon",
    "psi_drift",
    "live_vs_wf_ratio",
    "suspicious_too_good",
    "regime_degraded",
    "psi_slope_threshold",
    "conformal_coverage",
})
BLOCKER_CHECK_NAME_PREFIXES: tuple[str, ...] = ("provenance.",)


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
