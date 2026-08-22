"""The supersession gate may only ever skip a run that a newer run repeats.

Context 2026-08-22: 14+ pending tv-save runs starved 19h behind ~2h publishes
in the shared tradingview-session group while both TV drift alerts burned.
Same-EVENT runs are interchangeable — a workflow_run save rebuilds on current
main, a schedule verify re-reads everything — but across kinds they are NOT:
the bot-dispatched 18:50Z run that day was verify-only, and a verify never
repeats a save's effect. Dispatch runs carry inputs (operator intent,
re-attestation branches) and take part in neither direction.
"""

from __future__ import annotations

from scripts.tv_save_supersession_gate import decide


def _run(number: int, *, status: str = "queued", event: str = "workflow_run") -> dict:
    return {"run_number": number, "status": status, "event": event}


def test_stale_chain_save_abdicates_to_the_newest_queued_chain_save() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_run",
        runs=[_run(100), _run(101), _run(103), _run(102)],
    )
    assert verdict == 103, "must name the newest superseding run"


def test_the_newest_run_of_a_kind_never_abdicates() -> None:
    verdict = decide(
        own_run_number=103,
        own_event="workflow_run",
        runs=[_run(100), _run(101), _run(102), _run(103)],
    )
    assert verdict is None, "someone must always do the real save"


def test_a_schedule_verify_never_supersedes_a_chain_save() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_run",
        runs=[_run(105, event="schedule"), _run(106, event="schedule")],
    )
    assert verdict is None, "a read-only verify does not repeat a save's effect"


def test_a_chain_save_never_supersedes_a_schedule_verify() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="schedule",
        runs=[_run(105, event="workflow_run")],
    )
    assert verdict is None, "the daily read-only look must still happen"


def test_a_stale_schedule_verify_abdicates_to_a_newer_schedule_verify() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="schedule",
        runs=[_run(105, event="schedule")],
    )
    assert verdict == 105


def test_completed_newer_runs_do_not_supersede() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_run",
        runs=[_run(101, status="completed"), _run(102, status="completed")],
    )
    assert verdict is None, "a finished run refreshes nothing anymore"


def test_dispatch_runs_never_abdicate() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_dispatch",
        runs=[_run(105), _run(106, event="workflow_dispatch")],
    )
    assert verdict is None, "dispatch inputs are not repeated by anyone"


def test_dispatch_runs_never_supersede() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_run",
        runs=[_run(105, event="workflow_dispatch")],
    )
    assert verdict is None


def test_unreadable_rows_fail_open_per_row() -> None:
    verdict = decide(
        own_run_number=100,
        own_event="workflow_run",
        runs=[{"run_number": "not-a-number"}, {"status": "queued"}, _run(90)],
    )
    assert verdict is None, "garbage rows must never abdicate a run"
