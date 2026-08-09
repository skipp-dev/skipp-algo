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
            "snapshot_age_seconds": 12.0 + day,
            "max_snapshot_age_seconds": 120.0,
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
        "max_abs_quantity_delta": 0.0 if reconciled else 2.0,
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
    assert report["verdict_counts"] == {"allow": 20}
    assert report["latest_snapshot_age_seconds"] == 31.0
    assert report["latest_snapshot_max_age_seconds"] == 120.0
    assert report["latest_reconciliation_max_abs_quantity_delta"] == 0.0
    assert report["latest_reconciliation_reconciled"] is True
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


def test_submission_attempt_requires_a_prior_same_run_portfolio_evaluation() -> None:
    evaluation = _row(0)
    evaluation["ts"] = "2026-08-08T13:28:00+00:00"
    evaluation["phase"] = "paper"
    rows = [
        {
            "ts": "2026-08-08T13:28:00+00:00",
            "phase": "paper",
            "action": "paper_submitted",
        },
        evaluation,
        {
            "ts": "2026-08-08T13:28:00+00:00",
            "phase": "paper",
            "action": "submit_failed",
        },
    ]

    report = summarize_portfolio_shadow(rows)

    assert report["submission_attempt_count"] == 2
    assert report["submission_attempts_without_prior_evaluation"] == 1
    assert report["evidence_complete"] is False


def test_submission_integrity_starts_with_first_portfolio_evaluation() -> None:
    evaluation = _row(0)
    evaluation["ts"] = "2026-08-08T13:28:00+00:00"
    evaluation["phase"] = "paper"
    report = summarize_portfolio_shadow(
        [
            {
                "ts": "2026-08-07T13:28:00+00:00",
                "phase": "paper",
                "action": "paper_submitted",
            },
            evaluation,
            {
                "ts": "2026-08-09T13:28:00+00:00",
                "phase": "paper",
                "action": "paper_submitted",
            },
        ]
    )

    assert report["submission_attempt_count"] == 1
    assert report["submission_attempts_without_prior_evaluation"] == 1


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
    assert report["latest_reconciliation_max_abs_quantity_delta"] == 2.0
    assert report["latest_reconciliation_reconciled"] is False


def test_latest_operational_metrics_are_unknown_without_evidence() -> None:
    report = summarize_portfolio_shadow([])

    assert report["latest_snapshot_age_seconds"] is None
    assert report["latest_snapshot_max_age_seconds"] is None
    assert report["latest_reconciliation_max_abs_quantity_delta"] is None
    assert report["latest_reconciliation_reconciled"] is None
