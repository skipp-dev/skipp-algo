"""Phase 0 (Edge-Validation Roadmap) — frozen edge-hypothesis register.

The X2 ``PromotionGate`` already enforces statistical thresholds (PSR,
MinTRL, FDR-q, PSI-drift, conformal coverage). What was missing is a
*pre-registered, falsifiable* claim per ``EventFamily`` so that a passing
gate run can be checked against a hypothesis that was frozen **before**
the forward test — closing the door on HARKing / p-hacking.

This module is that register. ``governance/edge_hypotheses.json`` is the
**static, hand-curated** inventory: exactly one entry per gate
``EventFamily``. The companion test
``tests/test_edge_hypotheses_frozen.py`` enforces:
- every ``EventFamily`` from :mod:`governance.types` has exactly one entry
- ``primary_metric`` is a metric the gate actually consumes
- required fields are present and well-typed (incl. a frozen date)

Like :mod:`governance.alpha_ledger`, adding or changing a hypothesis is an
intentional governance act that goes through the JSON file plus PR review;
there is deliberately no production code path that mutates it at runtime.

Roadmap pointer: Edge-Validation Roadmap, Phase 0 / story EV-01.
"""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict, get_args

from governance.types import EventFamily

DEFAULT_HYPOTHESES_PATH = Path(__file__).resolve().parent / "edge_hypotheses.json"

# Metrics the gate actually consumes (mirror of the numeric FamilyMetrics
# fields read by ``scripts/run_promotion_gate.py``). A ``primary_metric``
# outside this set could never be falsified by a real gate run.
ALLOWED_PRIMARY_METRICS: frozenset[str] = frozenset({
    "brier",
    "ece",
    "fdr_pvalue",
    "psr",
    "mintrl_years",
    "psi",
    "live_brier",
    "walkforward_brier",
    "psi_slope",
    "conformal_coverage",
    "conformal_target",
})

REQUIRED_FIELDS: tuple[str, ...] = (
    "family",
    "h0",
    "h1",
    "primary_metric",
    "min_sample_n",
    "benchmark",
    "frozen_at",
    "rationale",
)


class EdgeHypothesis(TypedDict):
    family: str
    h0: str
    h1: str
    primary_metric: str
    min_sample_n: int
    benchmark: str
    frozen_at: str
    rationale: str


def _load(path: Path) -> list[EdgeHypothesis]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(
            f"edge_hypotheses.json must be a JSON array, got {type(raw).__name__}"
        )
    return [EdgeHypothesis(**item) for item in raw]


def list_hypotheses(path: Path | None = None) -> list[EdgeHypothesis]:
    """Return current frozen hypotheses from disk."""
    return _load(path or DEFAULT_HYPOTHESES_PATH)


def get_hypothesis(
    family: str, *, path: Path | None = None
) -> EdgeHypothesis:
    """Return the single frozen hypothesis for *family*.

    Raises ``KeyError`` if no hypothesis is registered for the family.
    """
    for hyp in list_hypotheses(path):
        if hyp["family"] == family:
            return hyp
    raise KeyError(f"no edge hypothesis registered for family {family!r}")


def validate(items: Iterable[EdgeHypothesis] | None = None) -> list[EdgeHypothesis]:
    """Validate the register against the gate contract.

    Checks (raising ``ValueError`` on the first violation):
    - every gate ``EventFamily`` has exactly one entry
    - no entry references an unknown family
    - all ``REQUIRED_FIELDS`` are present
    - ``primary_metric`` is consumed by the gate
    - ``min_sample_n`` is a positive integer

    Returns the validated list on success.
    """
    hyps = list(items) if items is not None else list_hypotheses()
    valid_families = set(get_args(EventFamily))

    seen: dict[str, int] = {}
    for hyp in hyps:
        missing = [f for f in REQUIRED_FIELDS if f not in hyp]
        if missing:
            raise ValueError(
                f"hypothesis {hyp.get('family')!r} missing fields: {missing}"
            )
        family = hyp["family"]
        if family not in valid_families:
            raise ValueError(
                f"unknown family {family!r}; expected one of {sorted(valid_families)}"
            )
        if hyp["primary_metric"] not in ALLOWED_PRIMARY_METRICS:
            raise ValueError(
                f"family {family!r}: primary_metric {hyp['primary_metric']!r} "
                f"is not a gate-consumed metric"
            )
        n = hyp["min_sample_n"]
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            raise ValueError(
                f"family {family!r}: min_sample_n must be a positive int, got {n!r}"
            )
        seen[family] = seen.get(family, 0) + 1

    duplicates = sorted(f for f, c in seen.items() if c > 1)
    if duplicates:
        raise ValueError(f"duplicate hypotheses for families: {duplicates}")
    uncovered = sorted(valid_families - set(seen))
    if uncovered:
        raise ValueError(f"no edge hypothesis registered for families: {uncovered}")
    return hyps


__all__ = [
    "ALLOWED_PRIMARY_METRICS",
    "DEFAULT_HYPOTHESES_PATH",
    "REQUIRED_FIELDS",
    "EdgeHypothesis",
    "get_hypothesis",
    "list_hypotheses",
    "validate",
]
