"""Summarize portfolio shadow decisions without promoting any limit."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

PORTFOLIO_SHADOW_REPORT_SCHEMA_VERSION = "1.1"
MIN_SHADOW_SESSIONS_FOR_REVIEW = 20


def _decision_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        row
        for row in rows
        if row.get("action") == "portfolio_risk_evaluated"
        and isinstance(row.get("portfolio_risk"), dict)
    ]


def summarize_portfolio_shadow(
    rows: Iterable[dict[str, Any]],
    reconciliations: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    decisions = _decision_rows(rows)
    verdicts: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    sessions: set[str] = set()
    risk_relevant_sessions: set[str] = set()
    risk_relevant_decision_count = 0
    projected_gross: list[float] = []
    correlation_coverage: list[float] = []
    incomplete_decisions = 0
    for row in decisions:
        risk = row["portfolio_risk"]
        verdicts[str(risk.get("verdict", "unknown"))] += 1
        reasons.update(str(item) for item in risk.get("reasons", []))
        raw_ts = row.get("ts")
        session_id = None
        if raw_ts:
            session_id = datetime.fromisoformat(str(raw_ts)).date().isoformat()
            sessions.add(session_id)
        projection = risk.get("projection") or {}
        candidate_gross_pct = float(projection.get("candidate_gross_pct", 0.0))
        if candidate_gross_pct > 0.0:
            risk_relevant_decision_count += 1
            if session_id is not None:
                risk_relevant_sessions.add(session_id)
        projected_gross.append(float(projection.get("projected_gross_pct", 0.0)))
        correlation_coverage.append(float(projection.get("correlation_coverage_pct", 0.0)))
        if any(
            reason in risk.get("reasons", [])
            for reason in (
                "snapshot_stale",
                "snapshot_from_future",
                "snapshot_incomplete",
                "unknown_working_order_role",
            )
        ):
            incomplete_decisions += 1

    reconciliation_rows = tuple(reconciliations)
    reconciliation_sessions = {
        datetime.fromisoformat(str(row["after_captured_at"])).date().isoformat()
        for row in reconciliation_rows
        if row.get("after_captured_at")
    }
    reconciliation_failures = sum(
        not bool(row.get("reconciled", False)) for row in reconciliation_rows
    )
    missing_reconciliation = risk_relevant_sessions - reconciliation_sessions
    review_ready = (
        len(risk_relevant_sessions) >= MIN_SHADOW_SESSIONS_FOR_REVIEW
        and incomplete_decisions == 0
        and risk_relevant_decision_count > 0
        and not missing_reconciliation
        and reconciliation_failures == 0
    )
    return {
        "schema_version": PORTFOLIO_SHADOW_REPORT_SCHEMA_VERSION,
        "status": "ready_for_human_review" if review_ready else "observing",
        "promotion": "manual_only",
        "min_shadow_sessions_for_review": MIN_SHADOW_SESSIONS_FOR_REVIEW,
        "sessions_observed": len(sessions),
        "risk_relevant_sessions_observed": len(risk_relevant_sessions),
        "risk_relevant_decision_count": risk_relevant_decision_count,
        "decision_count": len(decisions),
        "verdict_counts": dict(sorted(verdicts.items())),
        "reason_counts": dict(sorted(reasons.items())),
        "incomplete_decisions": incomplete_decisions,
        "reconciliation_sessions": len(reconciliation_sessions),
        "risk_relevant_sessions_missing_reconciliation": len(missing_reconciliation),
        "reconciliation_failures": reconciliation_failures,
        "max_projected_gross_pct": max(projected_gross, default=0.0),
        "min_correlation_coverage_pct": min(correlation_coverage, default=0.0),
        "evidence_complete": review_ready,
    }


def _load_jsonl(paths: Sequence[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"{path}:{line_number} must contain a JSON object")
            rows.append(payload)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize portfolio shadow evidence.")
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument(
        "--reconciliations",
        nargs="*",
        type=Path,
        default=(),
        help="Portfolio reconciliation JSON reports for the observed sessions.",
    )
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    reconciliation_rows = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in args.reconciliations
    ]
    report = summarize_portfolio_shadow(
        _load_jsonl(args.inputs),
        reconciliation_rows,
    )
    atomic_write_text(
        json.dumps(report, sort_keys=True, indent=2) + "\n",
        args.output,
        fsync=True,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "MIN_SHADOW_SESSIONS_FOR_REVIEW",
    "PORTFOLIO_SHADOW_REPORT_SCHEMA_VERSION",
    "summarize_portfolio_shadow",
]
