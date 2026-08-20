from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scripts.summarize_portfolio_shadow import (
    MIN_SHADOW_SESSIONS_FOR_REVIEW,
    summarize_portfolio_shadow,
)


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


# --- Disposition-Ledger fuer unbehebbar fehlende Reconciliation --------------
# Anlass 2026-08-20: die Sitzung vom 18.8. kann NIE einen Beleg bekommen (TWS war
# beim Reconcile-Lauf unten, der Runner arbeitet nur auf dem heutigen Datum). Ohne
# Ledger steigt der Zaehler monoton, der Alarm feuert dauerhaft und maskiert die
# NAECHSTE echte Luecke.

def _risk_row(session: str) -> dict:
    return {
        "action": "portfolio_risk_evaluated",
        "ts": f"{session}T13:28:00Z",
        "session_id": session,
        "portfolio_risk": {
            "verdict": "reject",
            "reasons": ["projected_open_positions"],
            # risikorelevant ist eine Sitzung genau dann, wenn ein Kandidat
            # ueberhaupt Gross beitragen wuerde (candidate_gross_pct > 0).
            "projection": {
                "candidate_gross_pct": 0.19,
                "projected_gross_pct": 1.48,
                "correlation_coverage_pct": 0.0,
            },
        },
    }


def _recon(session: str) -> dict:
    return {
        "after_captured_at": f"{session}T21:05:00Z",
        "reconciled": True,
        "max_abs_quantity_delta": 0,
    }


def _summary(sessions, reconciled, dispositions=()):
    return summarize_portfolio_shadow(
        [_risk_row(s) for s in sessions],
        [_recon(s) for s in reconciled],
        dispositions,
    )


def test_gap_without_disposition_still_counts():
    r = _summary(["2026-08-12", "2026-08-17", "2026-08-18"], ["2026-08-12", "2026-08-17"])
    assert r["risk_relevant_sessions_missing_reconciliation"] == 1
    assert r["risk_relevant_sessions_dispositioned"] == 0


def test_dispositioned_gap_clears_the_alert_counter():
    r = _summary(
        ["2026-08-12", "2026-08-17", "2026-08-18"], ["2026-08-12", "2026-08-17"],
        [{"session": "2026-08-18", "reason": "TWS down, after-snapshot unobtainable"}],
    )
    assert r["risk_relevant_sessions_missing_reconciliation"] == 0
    assert r["risk_relevant_sessions_dispositioned"] == 1


def test_a_disposition_without_a_reason_is_ignored():
    # Sonst waere ein stiller Waiver moeglich -- ein Eintrag muss sagen WARUM.
    for entry in ({"session": "2026-08-18"}, {"session": "2026-08-18", "reason": "   "}):
        r = _summary(
            ["2026-08-12", "2026-08-17", "2026-08-18"], ["2026-08-12", "2026-08-17"],
            [entry],
        )
        assert r["risk_relevant_sessions_missing_reconciliation"] == 1, entry
        assert r["risk_relevant_sessions_dispositioned"] == 0, entry


def test_a_new_gap_still_fires_while_an_old_one_is_dispositioned():
    # Der Kern: das Ledger darf den Zaehler NICHT blind machen.
    r = _summary(
        ["2026-08-12", "2026-08-17", "2026-08-18", "2026-08-25"],
        ["2026-08-12", "2026-08-17"],
        [{"session": "2026-08-18", "reason": "TWS down"}],
    )
    assert r["risk_relevant_sessions_missing_reconciliation"] == 1
    assert r["risk_relevant_sessions_dispositioned"] == 1


def _enough_sessions(n: int = MIN_SHADOW_SESSIONS_FOR_REVIEW) -> list[str]:
    """Genug Sitzungen, dass NICHT die Mindestzahl das Gate zuhaelt.

    Ohne das ist jeder Test auf `evidence_complete is False` vakuum: er waere
    auch dann gruen, wenn der Luecken-Term gar nicht ausgewertet wird. Genau so
    ueberlebte die erste Fassung dieses Tests ihre eigene Mutationsprobe.
    """
    return [f"2026-07-{day:02d}" for day in range(1, n + 1)]


def test_min_session_count_alone_does_not_hold_the_gate_shut():
    # Positivkontrolle fuer die beiden Tests darunter: ohne Luecke ist das Gate OFFEN.
    sessions = _enough_sessions()
    assert _summary(sessions, sessions)["evidence_complete"] is True


def test_disposition_keeps_review_shut_by_default():
    # blocks_review ist per Default wahr: verlorene Evidenz bleibt fehlende Evidenz.
    sessions = _enough_sessions()
    r = _summary(
        sessions, sessions[:-1],
        [{"session": sessions[-1], "reason": "TWS down, after-snapshot unobtainable"}],
    )
    assert r["risk_relevant_sessions_missing_reconciliation"] == 0  # Alarm ist still
    assert r["risk_relevant_sessions_dispositioned"] == 1
    assert r["evidence_complete"] is False                          # Gate bleibt ZU
    assert r["status"] == "observing"


def test_operator_can_open_the_gate_explicitly():
    # blocks_review=false ist eine ausdrueckliche Entscheidung, kein Nebeneffekt.
    sessions = _enough_sessions()
    r = _summary(
        sessions, sessions[:-1],
        [{"session": sessions[-1], "reason": "TWS down", "blocks_review": False}],
    )
    assert r["evidence_complete"] is True


def test_stale_disposition_is_reported_as_unused():
    r = _summary(
        ["2026-08-12", "2026-08-17"], ["2026-08-12", "2026-08-17"],
        [{"session": "2026-08-18", "reason": "TWS down"}],
    )
    assert r["reconciliation_dispositions_unused"] == 1


def test_shipped_ledger_parses_and_every_entry_carries_a_reason():
    from scripts.summarize_portfolio_shadow import load_dispositions

    entries = load_dispositions(Path("configs/portfolio_reconciliation_dispositions.json"))
    assert entries, "Ledger darf nicht leer sein, solange die 18.8.-Luecke besteht"
    for entry in entries:
        assert str(entry.get("session", "")).strip(), entry
        assert len(str(entry.get("reason", "")).strip()) > 40, entry
        assert str(entry.get("recorded_at", "")).strip(), entry
