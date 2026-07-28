"""Fail-closed contract tests for Hold Manager R2 shadow evaluation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts.evaluate_smc_hold_manager_shadow import evaluate_shadow
from scripts.smc_hold_manager_replay import (
    HARNESS_LIBRARY_PIN,
    freeze_library_pin,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)
OBSERVATIONS_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_observations.json"
)
RECEIVER_EVIDENCE_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_receiver_railway_2026-07-28.json"
)
TRACE_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "pine_extended_migration_traceability.json"
)
SOURCE_PATH = ROOT / "SMC_Hold_Manager.pine"
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


def _activation(contract: dict) -> dict:
    return {
        "managedScriptStatus": "managed_saved",
        "savedScriptVisibility": "private",
        "externalPublicationPerformed": False,
        "sourceSha256": contract["source"]["sha256"],
        "compileStatus": "passed",
        "bindingStatus": "passed_after_reload",
        "activeHoldAlertChannels": list(CHANNELS),
        "exitSignalActionableAlertsActive": 0,
        "strategyActionableExitAlertsActive": 0,
    }


def _counts(**overrides: int) -> dict[str, int]:
    result = dict.fromkeys(CHANNELS, 0)
    result.update(overrides)
    return result


def _session(contract: dict, sequence: int) -> dict:
    expected = (
        _counts(HM_ENTRY=1, HM_STOP=1, HM_EXIT_ANY=1)
        if sequence == 1
        else _counts()
    )
    return {
        "activationSequence": sequence,
        "sessionDate": f"2026-08-{sequence:02d}",
        "completeUsMarketSession": True,
        "exclusionReason": None,
        "marketTimezone": "America/New_York",
        "layout": contract["tradingView"]["validationLayout"],
        "sourceSha256": contract["source"]["sha256"],
        "producer": contract["tradingView"]["producer"],
        "busSchema": 7001,
        "bindingStatus": "passed",
        "activeActionableExitModes": ["hold_manager"],
        "exitSignalCompared": True,
        "strategyCompared": True,
        "runtimeErrorCount": 0,
        "falseExitAlertCount": 0,
        "duplicateActionableExitAlertCount": 0,
        "unclassifiedTransitionDifferenceCount": 0,
        "expectedServerAlerts": expected,
        "deliveredServerAlerts": copy.deepcopy(expected),
    }


def _rollback() -> dict:
    return {
        "result": "passed",
        "holdAlertsDisabledBeforeRemoval": True,
        "exitSignalReenabledBeforeHoldDisabled": True,
        "suiteUnchanged": True,
        "busSchemaUnchanged": True,
        "restoredLayoutSaved": True,
        "restoredBindingStatus": "passed_after_reload",
    }


def _passing_observations(contract: dict) -> dict:
    return {
        "schemaVersion": 1,
        "requirementId": "R2-SHADOW-CUTOVER",
        "activation": _activation(contract),
        "sessions": [_session(contract, index) for index in range(1, 6)],
        "rollbackDrill": _rollback(),
    }


def test_checked_in_shadow_state_is_explicitly_not_started() -> None:
    contract = _contract()
    observations = json.loads(
        OBSERVATIONS_PATH.read_text(encoding="utf-8")
    )

    result = evaluate_shadow(contract, observations)

    assert result["verdict"] == "not_started"
    assert result["activationStatus"] == "not_started"
    assert result["completeSessionCount"] == 0
    assert result["blockers"] == []
    # 2026-07-29: the six alerts exist (operator-attested, see
    # smc_hold_manager_shadow_alerts_2026-07-28.json), so the alert-creation
    # gate is closed; activation + rollback remain the only open gates.
    assert result["openGates"] == [
        "Activate the pre-registered shadow and record every session in order.",
        "Complete the rollback drill after the observation criteria pass.",
    ]


def test_contract_is_source_pinned_private_and_pre_registered() -> None:
    contract = _contract()
    import hashlib

    normalized_source = freeze_library_pin(
        SOURCE_PATH.read_text(encoding="utf-8")
    )
    actual_hash = hashlib.sha256(normalized_source.encode()).hexdigest()

    assert contract["status"] == "not_started"
    assert contract["readinessStatus"] == (
        "alerts_created_receiver_inactive"  # 2026-07-29: six alerts attested
    )
    assert contract["source"]["sha256"] == actual_hash
    assert contract["source"]["hashMode"] == (
        "micro_profile_library_pin_frozen"
    )
    assert contract["source"]["frozenMicroProfileLibraryPin"] == (
        HARNESS_LIBRARY_PIN
    )
    refresh = contract["activationRequirements"]["managedSavedScriptRefresh"]
    assert refresh["savedScriptVisibility"] == "private"
    assert refresh["externalPublicationRequired"] is False
    assert refresh["externalPublicationAllowed"] is False
    assert contract["activationRequirements"]["requiresSeparateAuthorization"]
    assert contract["observationWindow"]["minimumCompleteSessions"] == 5
    assert contract["currentState"][
        "managedSavedScriptRefreshPerformed"
    ] is True
    assert contract["currentState"]["receiverImplemented"] is True
    assert contract["currentState"]["receiverDeployed"] is True
    assert contract["currentState"]["receiverConfigured"] is True
    # 2026-07-29: flipped to True — six alerts operator-attested, see
    # smc_hold_manager_shadow_alerts_2026-07-28.json.
    assert contract["currentState"]["alertsCreated"] is True
    assert contract["currentState"]["alertsCreatedEvidence"] == (
        "artifacts/governance/smc_hold_manager_shadow_alerts_2026-07-28.json"
    )
    assert contract["currentState"]["shadowObservationStarted"] is False
    assert contract["currentState"]["isolatedPreflightStatus"] == (
        "passed_visible_browser_fallback"
    )
    assert contract["observationWindow"][
        "maximumSessionsWithoutRequiredEdges"
    ] == 10
    assert contract["perSessionRequirements"][
        "activeActionableExitModes"
    ] == ["hold_manager"]


def test_inactive_receiver_evidence_is_redacted_persistent_and_empty() -> None:
    evidence = json.loads(RECEIVER_EVIDENCE_PATH.read_text(encoding="utf-8"))
    token = evidence["configuration"]["webhookToken"]
    ledger = evidence["configuration"]["ledger"]
    state = evidence["verification"]["state"]

    assert evidence["result"] == "passed_inactive_receiver_ready"
    assert token == {
        "configured": True,
        "length": 64,
        "valueRecorded": False,
        "transport": "json_body_authToken",
    }
    assert ledger["path"] == "/app/data/smc-hold-manager-shadow.sqlite3"
    assert ledger["parentExists"] is True
    assert ledger["parentWritable"] is True
    assert ledger["fileExists"] is False
    assert ledger["initialization"] == "lazy_on_first_accepted_event"
    assert state["accepting"] is False
    assert state["uniqueEvents"] == 0
    assert state["deliveryAttempts"] == 0
    assert state["duplicateDeliveries"] == 0
    assert set(state["uniqueByChannel"]) == set(CHANNELS)
    assert set(state["uniqueByChannel"].values()) == {0}
    assert state["lastReceivedAt"] is None
    assert evidence["safety"]["alertsCreated"] is False
    assert evidence["safety"]["shadowObservationStarted"] is False


def test_five_complete_sessions_with_delivery_and_rollback_pass() -> None:
    contract = _contract()

    result = evaluate_shadow(contract, _passing_observations(contract))

    assert result["verdict"] == "passed"
    assert result["completeSessionCount"] == 5
    assert result["aggregateExpectedAlerts"] == (
        result["aggregateDeliveredAlerts"]
    )
    assert result["blockers"] == []
    assert result["openGates"] == []


@pytest.mark.parametrize(
    ("mutate", "blocker_fragment"),
    [
        (
            lambda payload: payload["sessions"].pop(),
            "complete sessions",
        ),
        (
            lambda payload: payload["sessions"][0][
                "deliveredServerAlerts"
            ].update(HM_EXIT_ANY=0),
            "expected server delivery",
        ),
        (
            lambda payload: payload["sessions"][0].update(
                duplicateActionableExitAlertCount=1
            ),
            "duplicateActionableExitAlertCount",
        ),
        (
            lambda payload: payload["sessions"][0].update(
                unclassifiedTransitionDifferenceCount=1
            ),
            "unclassifiedTransitionDifferenceCount",
        ),
        (
            lambda payload: payload["sessions"][0].update(
                activeActionableExitModes=["hold_manager", "exit_signal"]
            ),
            "activeActionableExitModes",
        ),
        (
            lambda payload: payload.update(rollbackDrill=None),
            "rollbackDrill",
        ),
        (
            lambda payload: payload["activation"].update(
                externalPublicationPerformed=True
            ),
            "activation.externalPublicationPerformed",
        ),
    ],
)
def test_shadow_gate_fails_closed(
    mutate,
    blocker_fragment: str,
) -> None:
    contract = _contract()
    observations = _passing_observations(contract)
    mutate(observations)

    result = evaluate_shadow(contract, observations)

    assert result["verdict"] == "blocked"
    assert any(
        blocker_fragment in blocker for blocker in result["blockers"]
    )


def test_session_sequence_cannot_be_cherry_picked() -> None:
    contract = _contract()
    observations = _passing_observations(contract)
    observations["sessions"][2]["activationSequence"] = 4

    result = evaluate_shadow(contract, observations)

    assert result["verdict"] == "blocked"
    assert any(
        "sessions.activationSequence" in blocker
        for blocker in result["blockers"]
    )


def test_excluded_session_edges_do_not_satisfy_promotion_minimums() -> None:
    contract = _contract()
    observations = _passing_observations(contract)
    first = observations["sessions"][0]
    first["completeUsMarketSession"] = False
    first["exclusionReason"] = "exchange-wide closure"
    observations["sessions"].append(_session(contract, 6))
    observations["sessions"][-1]["expectedServerAlerts"] = _counts()
    observations["sessions"][-1]["deliveredServerAlerts"] = _counts()

    result = evaluate_shadow(contract, observations)

    assert result["verdict"] == "blocked"
    assert result["completeSessionCount"] == 5
    assert result["aggregateExpectedAlerts"]["HM_ENTRY"] == 0
    assert any(
        "aggregate HM_ENTRY" in blocker for blocker in result["blockers"]
    )


def test_invalid_session_date_blocks_promotion() -> None:
    contract = _contract()
    observations = _passing_observations(contract)
    observations["sessions"][0]["sessionDate"] = "2026-02-30"

    result = evaluate_shadow(contract, observations)

    assert result["verdict"] == "blocked"
    assert any(
        "expected ISO calendar date" in blocker
        for blocker in result["blockers"]
    )


def test_traceability_keeps_shadow_not_started_with_readiness_evidence() -> None:
    trace = json.loads(TRACE_PATH.read_text(encoding="utf-8"))
    requirement = next(
        requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
        if requirement["id"] == "R2-SHADOW-CUTOVER"
    )

    assert requirement["status"] == "not_started"
    assert requirement["evidence"] == [
        (
            "artifacts/governance/"
            "smc_hold_manager_tradingview_preconditions_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_contract.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_observations.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_evidence.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_preflight_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_receiver_railway_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_alerts_2026-07-28.json"
        ),
        (
            "artifacts/governance/"
            "smc_hold_manager_shadow_alert_templates.json"
        ),
        "automation/tradingview/preflight-hold-manager-shadow.json",
        "automation/tradingview/lib/tv_validation_model.ts",
        "services/live_overlay_daemon/hold_manager_shadow_receiver.py",
        "services/live_overlay_daemon/README.md",
        "services/live_overlay_daemon/OPS.md",
        "scripts/smc_bus_manifest.py",
        "artifacts/tradingview/smc_product_cut_manifest.json",
        "scripts/evaluate_smc_hold_manager_shadow.py",
        "scripts/reconcile_smc_hold_manager_shadow_deliveries.py",
        "tests/test_hold_manager_shadow_receiver.py",
        "tests/test_evaluate_smc_hold_manager_shadow.py",
        "tests/test_reconcile_smc_hold_manager_shadow_deliveries.py",
        "tests/test_smc_bus_manifest_contract.py",
        "tests/test_smc_product_cut_manifest.py",
    ]
    assert requirement["openGates"]
