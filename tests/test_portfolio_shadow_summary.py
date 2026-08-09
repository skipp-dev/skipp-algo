from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.summarize_portfolio_shadow import summarize_portfolio_shadow


def _row(day: int, *, reasons=(), candidate_gross_pct: float = 5.0) -> dict:
    return {
        "ts": (datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=day)).isoformat(),
        "action": "portfolio_risk_evaluated",
        "portfolio_risk": {
            "verdict": "allow" if not reasons else "reject",
            "reasons": list(reasons),
            "projection": {
                "candidate_gross_pct": candidate_gross_pct,
                "projected_gross_pct": 10 + day,
                "correlation_coverage_pct": 100,
            },
        },
    }


def _reconciliation(day: int, *, reconciled: bool = True) -> dict:
    return {
        "after_captured_at": (
            datetime(2026, 7, 1, 20, tzinfo=UTC) + timedelta(days=day)
        ).isoformat(),
        "reconciled": reconciled,
    }


def test_report_requires_twenty_clean_sessions() -> None:
    report = summarize_portfolio_shadow(
        (_row(day) for day in range(20)),
        (_reconciliation(day) for day in range(20)),
    )
    assert report["status"] == "ready_for_human_review"
    assert report["promotion"] == "manual_only"
    assert report["schema_version"] == "1.1"
    assert report["sessions_observed"] == 20
    assert report["risk_relevant_sessions_observed"] == 20
    assert report["risk_relevant_decision_count"] == 20
    assert report["evidence_complete"] is True


def test_zero_candidate_sessions_do_not_satisfy_review_evidence() -> None:
    report = summarize_portfolio_shadow(
        (_row(day, candidate_gross_pct=0.0) for day in range(20)),
        (_reconciliation(day) for day in range(20)),
    )
    assert report["status"] == "observing"
    assert report["sessions_observed"] == 20
    assert report["risk_relevant_sessions_observed"] == 0
    assert report["risk_relevant_decision_count"] == 0
    assert report["evidence_complete"] is False


def test_reconciliations_must_cover_the_risk_relevant_session_dates() -> None:
    report = summarize_portfolio_shadow(
        (_row(day) for day in range(20)),
        (_reconciliation(day + 30) for day in range(20)),
    )
    assert report["status"] == "observing"
    assert report["reconciliation_sessions"] == 20
    assert report["risk_relevant_sessions_missing_reconciliation"] == 20


def test_stale_snapshot_keeps_report_observing() -> None:
    rows = [_row(day) for day in range(20)]
    rows[-1] = _row(19, reasons=("snapshot_stale",))
    report = summarize_portfolio_shadow(
        rows,
        (_reconciliation(day) for day in range(20)),
    )
    assert report["status"] == "observing"
    assert report["incomplete_decisions"] == 1


def test_missing_or_failed_reconciliation_prevents_review_ready() -> None:
    rows = [_row(day) for day in range(20)]
    report = summarize_portfolio_shadow(
        rows,
        [_reconciliation(day) for day in range(19)] + [_reconciliation(19, reconciled=False)],
    )
    assert report["status"] == "observing"
    assert report["reconciliation_failures"] == 1
