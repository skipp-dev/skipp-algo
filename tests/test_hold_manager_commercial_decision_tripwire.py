"""The Hold-Manager commercial decision cannot drift past its window.

2026-08-16, weekly commercial review: the Hold Manager sits outside the
product family (no ``SMC_PRODUCT_IDENTITY.md`` entry, ``rollout_state:
planned``) while carrying a full governance chain — a design partner cannot
tell what they are buying. The operator decided the same day: the commercial
yes/no is taken AT THE END of the shadow observation window, not before,
because the window's evidence is the decision input — and it is taken THEN,
not whenever someone remembers. A deadline that lives only in prose is the
promise form the forward-promises rule forbids, so this file is the
mechanism.

The trigger is two-sided, data first:

* the observation window completes (``completeSessionCount`` reaches the
  contract's ``minimumCompleteSessions``, computed by the SAME evaluator the
  governance chain runs, not re-derived here), or
* the recorded due date passes (the window can stall — sessions not recorded
  keep the data trigger silent forever, which is exactly how decisions rot).

Both sides of the date comparison are delivered: ``dueBy`` is data in the
decision record, and every branch below is exercised with dates DERIVED from
it — the ambient clock is borrowed in exactly one place, the repository
state test, which is the tripwire itself. Once the decision is recorded the
pending branch retires and the record must carry the decision honestly.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.evaluate_smc_hold_manager_shadow import evaluate_shadow

ROOT = Path(__file__).resolve().parents[1]
DECISION_PATH = (
    ROOT / "docs" / "commercial" / "HOLD_MANAGER_COMMERCIAL_DECISION.json"
)
CONTRACT_PATH = (
    ROOT / "artifacts" / "governance" / "smc_hold_manager_shadow_contract.json"
)
OBSERVATIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_observations.json"
)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _verify(
    today: date,
    complete_sessions: int,
    minimum_sessions: int,
    record: dict[str, Any],
) -> None:
    due_by = date.fromisoformat(record["dueBy"])
    status = record["status"]
    if status == "pending":
        if record["decision"] is not None or record["decidedAt"] is not None:
            raise AssertionError(
                "the record says pending but carries a decision -- record it "
                "properly (status=decided) instead of half-writing it"
            )
        if complete_sessions >= minimum_sessions:
            raise AssertionError(
                "the shadow observation window has delivered its "
                f"{minimum_sessions} complete sessions -- the Hold-Manager "
                "commercial decision is due NOW: record it in "
                "docs/commercial/HOLD_MANAGER_COMMERCIAL_DECISION.json in "
                "this PR (commercial -> identity + claims registry + tier; "
                "internal -> conclude the shadow and cap the effort)"
            )
        if today > due_by:
            raise AssertionError(
                f"the due date {due_by.isoformat()} passed with the decision "
                "still pending -- the window stalled or nobody recorded it; "
                "either record the decision or move dueBy DELIBERATELY with "
                "a dated justification in the same commit"
            )
        return
    if status == "decided":
        if record["decision"] not in record["options"]:
            raise AssertionError(
                "the recorded decision names no known option -- it must be "
                "one of " + ", ".join(sorted(record["options"]))
            )
        # Constructing the date validates the format; the value is history.
        date.fromisoformat(record["decidedAt"])
        return
    raise AssertionError(f"unknown decision status {status!r}")


def _window_state() -> tuple[int, int]:
    contract = _load(CONTRACT_PATH)
    report = evaluate_shadow(contract, _load(OBSERVATIONS_PATH))
    return (
        int(report["completeSessionCount"]),
        int(contract["observationWindow"]["minimumCompleteSessions"]),
    )


def test_the_repository_state_holds() -> None:
    """The tripwire: green only while pending is legitimately pending.

    The single deliberate ambient-clock read in this file -- a deadline that
    never consults the calendar is not a deadline.
    """
    complete_sessions, minimum_sessions = _window_state()

    _verify(
        datetime.now(tz=UTC).date(),
        complete_sessions,
        minimum_sessions,
        _load(DECISION_PATH),
    )


def test_a_completed_window_demands_the_decision() -> None:
    record = _load(DECISION_PATH)
    _complete, minimum_sessions = _window_state()
    due = date.fromisoformat(record["dueBy"])

    pending = {**record, "status": "pending", "decision": None, "decidedAt": None}
    with pytest.raises(AssertionError, match="due NOW"):
        _verify(due, minimum_sessions, minimum_sessions, pending)


def test_a_passed_due_date_demands_the_decision() -> None:
    record = _load(DECISION_PATH)
    due = date.fromisoformat(record["dueBy"])

    pending = {**record, "status": "pending", "decision": None, "decidedAt": None}
    with pytest.raises(AssertionError, match="passed with the decision"):
        _verify(due + timedelta(days=1), 0, 5, pending)


def test_the_sleeping_state_is_green_on_both_trigger_edges() -> None:
    """One session short at the due date itself: legitimately pending."""
    record = _load(DECISION_PATH)
    due = date.fromisoformat(record["dueBy"])

    pending = {**record, "status": "pending", "decision": None, "decidedAt": None}
    _verify(due, 4, 5, pending)


def test_a_recorded_decision_is_the_executable_exit() -> None:
    record = _load(DECISION_PATH)
    due = date.fromisoformat(record["dueBy"])

    for option in record["options"]:
        decided = {
            **record,
            "status": "decided",
            "decision": option,
            "decidedAt": due.isoformat(),
        }
        _verify(due + timedelta(days=30), 5, 5, decided)


def test_dishonest_records_are_refused() -> None:
    record = _load(DECISION_PATH)
    due = date.fromisoformat(record["dueBy"])

    half_written = {**record, "status": "pending", "decision": "internal"}
    with pytest.raises(AssertionError, match="half-writing"):
        _verify(due, 0, 5, half_written)

    unknown_option = {
        **record,
        "status": "decided",
        "decision": "maybe_later",
        "decidedAt": due.isoformat(),
    }
    with pytest.raises(AssertionError, match="no known option"):
        _verify(due, 5, 5, unknown_option)

    unknown_status = {**record, "status": "postponed"}
    with pytest.raises(AssertionError, match="unknown decision status"):
        _verify(due, 0, 5, unknown_status)
