"""EV-08 honest family verdict: gate decisions vs frozen hypotheses.

The :class:`~governance.promotion_gate.PromotionGate` answers a *statistical*
question per family ("did the measured metrics clear the thresholds?"). The
frozen edge-hypothesis register (:mod:`governance.edge_hypotheses`, EV-01)
records the *pre-registered, falsifiable* claim per family. EV-08 joins the
two and renders an honest verdict that closes the door on HARKing /
p-hacking by refusing to call an edge unless **all** of the following hold:

  1. the gate actually promoted the family,
  2. the metric the hypothesis pre-registered as ``primary_metric`` was
     genuinely *measured* (not a "not yet measured" info-blocker), and
  3. the pre-registered minimum sample size ``min_sample_n`` was met by the
     observed return count.

A family the gate promoted but that fails (2) or (3) is reported as
``inconclusive`` — never as a supported edge. This is the load-bearing
honesty rule: the gate's "promoted" flag alone is *not* sufficient to claim
a pre-registered edge.

Per ADR-0015 the verdict is a **two-tier** taxonomy that refuses to let a
secondary calibration diagnostic veto the primary edge proof:

  * ``edge_supported`` (tier 1) — the pre-registered edge is supported: the
    primary metric was measured, the sample is adequate, no edge-failure
    blocker fired, and the integrity/provenance guards were measured and
    clear. Brier/ECE calibration blockers do *not* gate this tier. When the
    edge metrics are strong but an integrity guard is merely *unmeasured*
    (strict-provenance ``info``), the verdict is ``inconclusive`` — the edge
    cannot be certified without the guards — never ``no_edge``.
  * ``risk_sizeable`` (tier 2, a boolean field, strictly stronger) — tier 1
    **and** the calibration checks (``brier_threshold`` / ``brier_ci_upper``
    / ``ece_threshold``) also clear, so the family's probabilities are sharp
    enough to size and risk-manage. This equals the gate's full ``promoted``
    decision on a measured, adequately-powered family.

No threshold is changed by this taxonomy; the calibration checks are mapped
to the tier they evidence (sizing) instead of vetoing edge recognition.

This module fabricates nothing. It reads a promotion-decisions report (as
produced by ``scripts/run_promotion_gate.py``) plus the frozen register and
emits one verdict per registered family.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal, TypedDict

from governance.edge_hypotheses import EdgeHypothesis, list_hypotheses

# Decision.metrics key carrying the realized return count (EV-06b puts
# ``n_returns`` into FamilyMetrics.extras; the gate re-exports extras under
# an ``extra.`` prefix in Decision.metrics).
_OBSERVED_N_METRIC_KEY = "extra.n_returns"

# ADR-0015: the gate blocker ``check`` names that evidence *calibration for
# sizing* (tier-2 ``risk_sizeable``) rather than the *edge proof* (tier-1
# ``edge_supported``). A family blocked only by these still clears tier 1.
_CALIBRATION_CHECKS = frozenset({
    "brier_threshold",
    "brier_ci_upper",
    "ece_threshold",
})

Verdict = Literal["edge_supported", "no_edge", "inconclusive", "not_evaluated"]


class FamilyVerdict(TypedDict):
    """Honest, pre-registration-checked verdict for one family."""

    family: str
    verdict: Verdict
    risk_sizeable: bool | None
    promoted: bool | None
    primary_metric: str
    primary_metric_measured: bool
    primary_metric_value: float | None
    min_sample_n: int
    observed_n: int | None
    sample_adequate: bool | None
    h0: str
    h1: str
    benchmark: str
    blocker_checks: list[str]
    notes: list[str]


def _decision_index(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    decisions = report.get("decisions")
    if not isinstance(decisions, list):
        raise ValueError("report missing a 'decisions' list")
    index: dict[str, Mapping[str, Any]] = {}
    for decision in decisions:
        if not isinstance(decision, Mapping) or "family" not in decision:
            raise ValueError("each decision must be a mapping with a 'family'")
        family = str(decision["family"])
        if family in index:
            raise ValueError(f"duplicate decision for family {family!r}")
        index[family] = decision
    return index


def _observed_n(metrics: Mapping[str, Any]) -> int | None:
    raw = metrics.get(_OBSERVED_N_METRIC_KEY)
    if raw is None:
        return None
    return int(float(raw))


def _build_one(
    hypothesis: EdgeHypothesis, decision: Mapping[str, Any] | None
) -> FamilyVerdict:
    family = hypothesis["family"]
    primary_metric = hypothesis["primary_metric"]
    min_sample_n = int(hypothesis["min_sample_n"])

    base: FamilyVerdict = {
        "family": family,
        "verdict": "not_evaluated",
        "risk_sizeable": None,
        "promoted": None,
        "primary_metric": primary_metric,
        "primary_metric_measured": False,
        "primary_metric_value": None,
        "min_sample_n": min_sample_n,
        "observed_n": None,
        "sample_adequate": None,
        "h0": hypothesis["h0"],
        "h1": hypothesis["h1"],
        "benchmark": hypothesis["benchmark"],
        "blocker_checks": [],
        "notes": [],
    }

    if decision is None:
        base["notes"].append("no gate decision present for this family")
        return base

    promoted = bool(decision.get("promoted", False))
    metrics = decision.get("metrics") or {}
    blockers = decision.get("blockers") or []
    blocker_checks = [
        str(b.get("check"))
        for b in blockers
        if isinstance(b, Mapping) and b.get("severity") == "blocker"
    ]

    # ADR-0015: split the *promotion-preventing* blockers by severity AND
    # concern. A hard ``blocker`` is a measured failure; an ``info`` blocker
    # is an *unmeasured* guard (strict-provenance "not yet measured"), which
    # cannot certify an edge but is not itself a failure. A ``warning`` never
    # prevents promotion and is excluded.
    #
    # Concern matters as much as severity: the calibration checks evidence
    # tier-2 sizing only, so neither a *measured* calibration failure nor an
    # *unmeasured* calibration check may veto tier-1 ``edge_supported`` (they
    # withhold ``risk_sizeable`` instead). Only the non-calibration guards
    # gate tier 1.
    hard_blocking = {
        str(b.get("check"))
        for b in blockers
        if isinstance(b, Mapping) and b.get("severity") == "blocker"
    }
    unmeasured = {
        str(b.get("check"))
        for b in blockers
        if isinstance(b, Mapping) and b.get("severity") == "info"
    }
    # Tier-1 gating: a genuine edge failure (hard, non-calibration).
    edge_hard_blocking = sorted(hard_blocking - _CALIBRATION_CHECKS)
    # Tier-1 gating: a non-calibration guard the gate could not yet measure.
    unmeasured_guards = sorted(unmeasured - _CALIBRATION_CHECKS)
    # Tier-2 gating: calibration that either failed (measured) or is not yet
    # measured. Either state withholds sizing but never vetoes the edge proof.
    calibration_blocking = sorted((hard_blocking | unmeasured) & _CALIBRATION_CHECKS)

    # The gate only writes a metric label into ``metrics`` when it was
    # genuinely measured; a None metric surfaces as an info-blocker instead.
    measured = primary_metric in metrics
    primary_value = float(metrics[primary_metric]) if measured else None

    observed_n = _observed_n(metrics)
    sample_adequate = observed_n is not None and observed_n >= min_sample_n

    base["promoted"] = promoted
    base["primary_metric_measured"] = measured
    base["primary_metric_value"] = primary_value
    base["observed_n"] = observed_n
    base["sample_adequate"] = sample_adequate
    base["blocker_checks"] = blocker_checks

    if not measured:
        base["notes"].append(
            f"primary metric {primary_metric!r} was not measured by the gate"
        )
    if observed_n is None:
        base["notes"].append("observed sample size not reported in metrics")
    elif not sample_adequate:
        base["notes"].append(
            f"observed_n={observed_n} below pre-registered min_sample_n={min_sample_n}"
        )

    # ADR-0015 two-tier verdict. The order of checks is load-bearing:
    #   1. a genuine *edge-failure* hard blocker -> no_edge,
    #   2. else an *unmeasured* non-calibration guard -> inconclusive
    #      (strong edge metrics cannot be certified without the guards),
    #   3. else tier-1 edge_supported; tier-2 risk_sizeable additionally
    #      requires the calibration checks (brier/ece) to be measured and
    #      clear.
    if measured and sample_adequate:
        if edge_hard_blocking:
            base["verdict"] = "no_edge"
            base["risk_sizeable"] = False
        elif unmeasured_guards:
            base["verdict"] = "inconclusive"
            base["risk_sizeable"] = False
            base["notes"].append(
                "edge metrics clear but guards "
                f"{unmeasured_guards} not yet measured; edge certification "
                "withheld (ADR-0015 tier-1 requires these measured)"
            )
        else:
            base["verdict"] = "edge_supported"
            base["risk_sizeable"] = not calibration_blocking
            if calibration_blocking:
                base["notes"].append(
                    "tier-1 edge_supported: primary edge metrics and "
                    "non-calibration guards clear; tier-2 risk_sizeable "
                    f"withheld \u2014 calibration checks {calibration_blocking} "
                    "not measured-and-clear (ADR-0015)"
                )
    else:
        base["verdict"] = "inconclusive"
        base["risk_sizeable"] = False
        if measured and not sample_adequate:
            if edge_hard_blocking:
                base["notes"].append(
                    "gate did not promote but pre-registered sample size "
                    "not met; no_edge claim withheld"
                )
            else:
                base["notes"].append(
                    "edge metrics clear but pre-registered sample size "
                    "not met; edge claim withheld"
                )

    return base


def build_verdicts(
    report: Mapping[str, Any], *, hypotheses_path: Path | None = None
) -> list[FamilyVerdict]:
    """Render one honest verdict per *registered* family.

    Iterates the frozen hypothesis register (not the report) so that a
    family with no gate decision is surfaced as ``not_evaluated`` rather
    than silently dropped.
    """
    decisions = _decision_index(report)
    verdicts: list[FamilyVerdict] = []
    for hypothesis in list_hypotheses(hypotheses_path):
        decision = decisions.get(hypothesis["family"])
        verdicts.append(_build_one(hypothesis, decision))
    return verdicts


def verdict_summary(verdicts: Sequence[FamilyVerdict]) -> dict[str, int]:
    """Count verdicts by outcome (stable key order, zero-filled)."""
    counts = {
        "edge_supported": 0,
        "no_edge": 0,
        "inconclusive": 0,
        "not_evaluated": 0,
    }
    for v in verdicts:
        counts[v["verdict"]] += 1
    return counts


def build_verdict_report(
    report: Mapping[str, Any], *, hypotheses_path: Path | None = None
) -> dict[str, Any]:
    """Assemble the full verdict report (verdicts + summary)."""
    verdicts = build_verdicts(report, hypotheses_path=hypotheses_path)
    return {
        "generated_from": report.get("generated_at"),
        "gate_schema_version": report.get("gate_schema_version"),
        "summary": verdict_summary(verdicts),
        "risk_sizeable_count": sum(1 for v in verdicts if v["risk_sizeable"] is True),
        "verdicts": verdicts,
    }


def _has_contradiction(verdicts: Sequence[FamilyVerdict]) -> bool:
    """True if the gate promoted a family the verdict could not support.

    This is the case that must not pass CI silently: a green gate run that
    fails the pre-registration cross-check (unmeasured primary metric or an
    underpowered sample).
    """
    return any(
        v["promoted"] is True and v["verdict"] != "edge_supported" for v in verdicts
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Render honest per-family verdicts by joining a promotion-decisions "
            "report with the frozen edge-hypothesis register (EV-08)."
        )
    )
    parser.add_argument(
        "--report",
        required=True,
        help="Path to a promotion-decisions report JSON (run_promotion_gate output).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional path to write the verdict report JSON. Prints to stdout if omitted.",
    )
    parser.add_argument(
        "--hypotheses",
        default=None,
        help="Optional override path to edge_hypotheses.json.",
    )
    args = parser.parse_args(argv)

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    hypotheses_path = Path(args.hypotheses) if args.hypotheses else None
    verdict_report = build_verdict_report(report, hypotheses_path=hypotheses_path)

    payload = json.dumps(verdict_report, indent=2, sort_keys=False, allow_nan=False)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)

    return 3 if _has_contradiction(verdict_report["verdicts"]) else 0


__all__ = [
    "FamilyVerdict",
    "Verdict",
    "build_verdict_report",
    "build_verdicts",
    "main",
    "verdict_summary",
]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
