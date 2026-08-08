from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scripts.summarize_portfolio_shadow import summarize_portfolio_shadow


def _row(day: int, *, reasons=()) -> dict:
    return {
        "ts": (datetime(2026, 7, 1, tzinfo=UTC) + timedelta(days=day)).isoformat(),
        "action": "portfolio_risk_evaluated",
        "portfolio_risk": {
            "verdict": "allow" if not reasons else "reject",
            "reasons": list(reasons),
            "projection": {
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
    assert report["sessions_observed"] == 20
    assert report["evidence_complete"] is True


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
