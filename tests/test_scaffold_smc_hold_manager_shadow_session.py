"""Fail-closed tests for the R2 shadow session-row scaffold."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.scaffold_smc_hold_manager_shadow_session import (
    OPERATOR_FIELDS,
    scaffold_session,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _observations(sessions: list[dict], *, activation: dict | None) -> dict:
    return {
        "schemaVersion": 1,
        "requirementId": "R2-SHADOW-CUTOVER",
        "activation": activation,
        "sessions": sessions,
        "rollbackDrill": None,
    }


def _activation() -> dict:
    return {"firstEvaluableSessionDate": "2026-07-29"}


def test_scaffolds_identity_constants_and_null_operator_fields() -> None:
    contract = _contract()
    observations = _observations([], activation=_activation())

    result = scaffold_session(contract, observations, "2026-07-29")

    assert result["verdict"] == "scaffolded"
    assert result["activationSequence"] == 1
    row = observations["sessions"][0]
    assert row["sessionDate"] == "2026-07-29"
    assert row["marketTimezone"] == contract["tradingView"]["marketTimezone"]
    assert row["layout"] == contract["tradingView"]["validationLayout"]
    assert row["sourceSha256"] == contract["source"]["sha256"]
    assert row["busSchema"] == contract["tradingView"]["busSchema"]
    for field in OPERATOR_FIELDS:
        assert row[field] is None
    # The delivered side must stay absent for the ledger reconciliation.
    assert "deliveredServerAlerts" not in row


def test_refuses_before_activation_is_recorded() -> None:
    result = scaffold_session(
        _contract(), _observations([], activation=None), "2026-07-29"
    )

    assert result["verdict"] == "refused"
    assert any("activation is not recorded" in b for b in result["blockers"])


def test_refuses_duplicate_and_out_of_order_dates() -> None:
    contract = _contract()
    observations = _observations(
        [{"activationSequence": 1, "sessionDate": "2026-07-30"}],
        activation=_activation(),
    )

    duplicate = scaffold_session(contract, observations, "2026-07-30")
    out_of_order = scaffold_session(contract, observations, "2026-07-29")

    assert duplicate["verdict"] == "refused"
    assert any("already recorded" in b for b in duplicate["blockers"])
    assert out_of_order["verdict"] == "refused"
    assert any("in order" in b for b in out_of_order["blockers"])
    assert len(observations["sessions"]) == 1


def test_refuses_dates_before_first_evaluable_session() -> None:
    result = scaffold_session(
        _contract(), _observations([], activation=_activation()), "2026-07-28"
    )

    assert result["verdict"] == "refused"
    assert any("precedes the first evaluable" in b for b in result["blockers"])


def test_second_session_gets_next_activation_sequence() -> None:
    contract = _contract()
    observations = _observations(
        [{"activationSequence": 1, "sessionDate": "2026-07-29"}],
        activation=_activation(),
    )

    result = scaffold_session(contract, observations, "2026-07-30")

    assert result["verdict"] == "scaffolded"
    assert result["activationSequence"] == 2
    assert observations["sessions"][1]["sessionDate"] == "2026-07-30"
