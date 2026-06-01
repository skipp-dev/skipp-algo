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

Verdict = Literal["edge_supported", "no_edge", "inconclusive", "not_evaluated"]


class FamilyVerdict(TypedDict):
    """Honest, pre-registration-checked verdict for one family."""

    family: str
    verdict: Verdict
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

    if promoted:
        if measured and sample_adequate:
            base["verdict"] = "edge_supported"
        else:
            base["verdict"] = "inconclusive"
            base["notes"].append(
                "gate promoted but pre-registration check failed; "
                "edge claim withheld"
            )
    else:
        if measured and sample_adequate:
            base["verdict"] = "no_edge"
        else:
            base["verdict"] = "inconclusive"
            if measured and not sample_adequate:
                base["notes"].append(
                    "gate did not promote but pre-registered sample size "
                    "not met; no_edge claim withheld"
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
