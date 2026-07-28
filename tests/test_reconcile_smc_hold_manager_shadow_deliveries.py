"""Fail-closed tests for the receiver-ledger -> observations reconciliation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

from scripts.reconcile_smc_hold_manager_shadow_deliveries import (
    reconcile_deliveries,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)
CHANNELS = (
    "HM_ENTRY",
    "HM_T1",
    "HM_T2",
    "HM_STOP",
    "HM_TIMESTOP",
    "HM_EXIT_ANY",
)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _counts(**overrides: int) -> dict[str, int]:
    return {**dict.fromkeys(CHANNELS, 0), **overrides}


def _state(sessions: list[dict] | None) -> dict:
    return {
        "schemaVersion": 1,
        "requirementId": "R2-SHADOW-CUTOVER",
        "marketTimezone": "America/New_York",
        "sessions": sessions,
    }


def _session_state(session_date: str, **unique: int) -> dict:
    return {
        "sessionDate": session_date,
        "uniqueByChannel": _counts(**unique),
        "duplicatesByChannel": _counts(),
    }


def _observations(sessions: list[dict]) -> dict:
    return {
        "schemaVersion": 1,
        "requirementId": "R2-SHADOW-CUTOVER",
        "activation": None,
        "sessions": sessions,
        "rollbackDrill": None,
    }


def test_fills_delivered_counts_from_receiver_ledger() -> None:
    observations = _observations(
        [
            {"sessionDate": "2026-07-30"},
            {"sessionDate": "2026-07-31"},
        ]
    )
    state = _state(
        [_session_state("2026-07-30", HM_ENTRY=2, HM_EXIT_ANY=1)]
    )

    result = reconcile_deliveries(_contract(), state, observations)

    assert result["verdict"] == "reconciled"
    assert result["blockers"] == []
    assert result["sessionsFilled"] == 2
    assert observations["sessions"][0]["deliveredServerAlerts"] == _counts(
        HM_ENTRY=2, HM_EXIT_ANY=1
    )
    assert observations["sessions"][0]["deliveredServerAlertsSource"] == (
        "receiver_ledger"
    )
    # A recorded session without receiver events is a legitimate zero-delivery
    # session, not an error.
    assert observations["sessions"][1]["deliveredServerAlerts"] == _counts()


def test_conflicting_manual_claim_blocks_instead_of_overwriting() -> None:
    observations = _observations(
        [
            {
                "sessionDate": "2026-07-30",
                "deliveredServerAlerts": _counts(HM_ENTRY=3),
            }
        ]
    )
    state = _state([_session_state("2026-07-30", HM_ENTRY=2)])
    before = copy.deepcopy(observations)

    result = reconcile_deliveries(_contract(), state, observations)

    assert result["verdict"] == "blocked"
    assert any("conflicts with receiver ledger" in b for b in result["blockers"])
    assert observations["sessions"][0]["deliveredServerAlerts"] == (
        before["sessions"][0]["deliveredServerAlerts"]
    )


def test_matching_prefilled_row_is_confirmed_idempotently() -> None:
    observations = _observations(
        [
            {
                "sessionDate": "2026-07-30",
                "deliveredServerAlerts": _counts(HM_ENTRY=2),
            }
        ]
    )
    state = _state([_session_state("2026-07-30", HM_ENTRY=2)])

    result = reconcile_deliveries(_contract(), state, observations)

    assert result["verdict"] == "reconciled"
    assert result["sessionsConfirmed"] == 1
    assert result["sessionsFilled"] == 0


def test_unrecorded_receiver_session_blocks() -> None:
    observations = _observations([{"sessionDate": "2026-07-30"}])
    state = _state(
        [
            _session_state("2026-07-30", HM_ENTRY=1),
            _session_state("2026-07-31", HM_STOP=1),
        ]
    )

    result = reconcile_deliveries(_contract(), state, observations)

    assert result["verdict"] == "blocked"
    assert any("2026-07-31" in b and "record or exclude" in b for b in result["blockers"])


def test_state_without_session_breakdown_blocks() -> None:
    state = _state(None)
    state.pop("sessions")

    result = reconcile_deliveries(
        _contract(), state, _observations([{"sessionDate": "2026-07-30"}])
    )

    assert result["verdict"] == "blocked"
    assert any("must be redeployed" in b for b in result["blockers"])


def test_channel_set_mismatch_blocks() -> None:
    session = _session_state("2026-07-30")
    session["uniqueByChannel"].pop("HM_STOP")

    result = reconcile_deliveries(
        _contract(),
        _state([session]),
        _observations([{"sessionDate": "2026-07-30"}]),
    )

    assert result["verdict"] == "blocked"
    assert any("must exactly match" in b for b in result["blockers"])


def test_market_timezone_mismatch_blocks() -> None:
    state = _state([])
    state["marketTimezone"] = "UTC"

    result = reconcile_deliveries(_contract(), state, _observations([]))

    assert result["verdict"] == "blocked"
    assert any("state.marketTimezone" in b for b in result["blockers"])
