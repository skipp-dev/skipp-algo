#!/usr/bin/env python3
"""Evaluate the pre-registered Hold Manager R2 shadow gate fail-closed."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_text

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTRACT = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_contract.json"
)
DEFAULT_OBSERVATIONS = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_observations.json"
)
DEFAULT_OUTPUT = (
    ROOT
    / "artifacts"
    / "governance"
    / "smc_hold_manager_shadow_evidence.json"
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_equal(
    blockers: list[str],
    actual: object,
    expected: object,
    label: str,
) -> None:
    if actual != expected:
        blockers.append(f"{label}: expected {expected!r}, observed {actual!r}")


def _alert_counts(
    row: Mapping[str, Any],
    field: str,
    channels: tuple[str, ...],
    blockers: list[str],
    prefix: str,
) -> dict[str, int]:
    raw = row.get(field)
    if not isinstance(raw, Mapping):
        blockers.append(f"{prefix}.{field}: missing alert-count object")
        return {channel: 0 for channel in channels}

    if set(raw) != set(channels):
        blockers.append(
            f"{prefix}.{field}: channels must exactly match {list(channels)!r}"
        )

    result: dict[str, int] = {}
    for channel in channels:
        value = raw.get(channel)
        if not _is_nonnegative_int(value):
            blockers.append(
                f"{prefix}.{field}.{channel}: expected non-negative integer"
            )
            result[channel] = 0
        else:
            result[channel] = value
    return result


def evaluate_shadow(
    contract: Mapping[str, Any],
    observations: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a deterministic, fail-closed shadow verdict."""

    blockers: list[str] = []
    requirement_id = contract.get("requirementId")
    _require_equal(
        blockers,
        observations.get("requirementId"),
        requirement_id,
        "requirementId",
    )
    _require_equal(
        blockers,
        observations.get("schemaVersion"),
        contract.get("schemaVersion"),
        "schemaVersion",
    )

    activation = observations.get("activation")
    sessions_raw = observations.get("sessions")
    rollback = observations.get("rollbackDrill")
    if not isinstance(sessions_raw, list):
        blockers.append("sessions: expected an array")
        sessions: list[Mapping[str, Any]] = []
    else:
        sessions = [
            row for row in sessions_raw if isinstance(row, Mapping)
        ]
        if len(sessions) != len(sessions_raw):
            blockers.append("sessions: every row must be an object")

    if activation is None:
        if sessions:
            blockers.append("sessions exist before shadow activation")
        if rollback is not None:
            blockers.append("rollback drill exists before shadow activation")
        current_state = contract.get("currentState")
        state = current_state if isinstance(current_state, Mapping) else {}
        setup_gates: list[str] = []
        if state.get("managedSavedScriptRefreshPerformed") is not True:
            setup_gates.append(
                "Obtain separate authorization for the private managed "
                "saved-script refresh."
            )
        if state.get("receiverImplemented") is not True:
            setup_gates.append(
                "Implement and verify the controlled server-alert receiver."
            )
        if state.get("receiverDeployed") is not True:
            setup_gates.append(
                "Obtain separate authorization to publish and deploy the "
                "inactive controlled shadow receiver."
            )
        if state.get("receiverConfigured") is not True:
            setup_gates.append(
                "Configure and verify its secret and persistent empty ledger "
                "under separate authorization."
            )
        if state.get("alertsCreated") is not True:
            setup_gates.append(
                "Obtain separate authorization for controlled alert creation."
            )
        return {
            "schemaVersion": 1,
            "requirementId": requirement_id,
            "verdict": "not_started" if not blockers else "blocked",
            "activationStatus": "not_started",
            "completeSessionCount": 0,
            "observedSessionCount": len(sessions),
            "aggregateExpectedAlerts": {},
            "aggregateDeliveredAlerts": {},
            "blockers": blockers,
            "openGates": [
                *setup_gates,
                "Activate the pre-registered shadow and record every session in order.",
                "Complete the rollback drill after the observation criteria pass.",
            ],
        }

    if not isinstance(activation, Mapping):
        blockers.append("activation: expected an object or null")
        activation = {}

    source = contract["source"]
    trading_view = contract["tradingView"]
    activation_contract = contract["activationRequirements"]
    window = contract["observationWindow"]
    per_session = contract["perSessionRequirements"]
    channels = tuple(activation_contract["holdAlertChannels"])

    _require_equal(
        blockers,
        activation.get("managedScriptStatus"),
        "managed_saved",
        "activation.managedScriptStatus",
    )
    _require_equal(
        blockers,
        activation.get("savedScriptVisibility"),
        activation_contract["managedSavedScriptRefresh"][
            "savedScriptVisibility"
        ],
        "activation.savedScriptVisibility",
    )
    _require_equal(
        blockers,
        activation.get("externalPublicationPerformed"),
        False,
        "activation.externalPublicationPerformed",
    )
    _require_equal(
        blockers,
        activation.get("sourceSha256"),
        source["sha256"],
        "activation.sourceSha256",
    )
    _require_equal(
        blockers,
        activation.get("compileStatus"),
        "passed",
        "activation.compileStatus",
    )
    _require_equal(
        blockers,
        activation.get("bindingStatus"),
        "passed_after_reload",
        "activation.bindingStatus",
    )
    _require_equal(
        blockers,
        activation.get("activeHoldAlertChannels"),
        list(channels),
        "activation.activeHoldAlertChannels",
    )
    _require_equal(
        blockers,
        activation.get("exitSignalActionableAlertsActive"),
        0,
        "activation.exitSignalActionableAlertsActive",
    )
    _require_equal(
        blockers,
        activation.get("strategyActionableExitAlertsActive"),
        0,
        "activation.strategyActionableExitAlertsActive",
    )

    expected_sequence = list(range(1, len(sessions) + 1))
    observed_sequence = [row.get("activationSequence") for row in sessions]
    _require_equal(
        blockers,
        observed_sequence,
        expected_sequence,
        "sessions.activationSequence",
    )
    session_dates = [row.get("sessionDate") for row in sessions]
    if len(session_dates) != len(set(session_dates)):
        blockers.append("sessions.sessionDate: duplicate date")
    for index, session_date in enumerate(session_dates, start=1):
        try:
            date.fromisoformat(session_date)
        except (TypeError, ValueError):
            blockers.append(
                f"sessions[{index}].sessionDate: expected ISO calendar date"
            )

    aggregate_expected = {channel: 0 for channel in channels}
    aggregate_delivered = {channel: 0 for channel in channels}
    complete_sessions = 0
    required_modes = per_session["activeActionableExitModes"]

    for index, row in enumerate(sessions, start=1):
        prefix = f"sessions[{index}]"
        complete = row.get("completeUsMarketSession") is True
        excluded = row.get("exclusionReason") not in (None, "")
        if complete and not excluded:
            complete_sessions += 1
        elif not excluded:
            blockers.append(
                f"{prefix}: incomplete session requires exclusionReason"
            )

        _require_equal(
            blockers,
            row.get("marketTimezone"),
            trading_view["marketTimezone"],
            f"{prefix}.marketTimezone",
        )
        _require_equal(
            blockers,
            row.get("layout"),
            trading_view["validationLayout"],
            f"{prefix}.layout",
        )
        _require_equal(
            blockers,
            row.get("sourceSha256"),
            source["sha256"],
            f"{prefix}.sourceSha256",
        )
        _require_equal(
            blockers,
            row.get("producer"),
            trading_view["producer"],
            f"{prefix}.producer",
        )
        _require_equal(
            blockers,
            row.get("busSchema"),
            trading_view["busSchema"],
            f"{prefix}.busSchema",
        )
        _require_equal(
            blockers,
            row.get("bindingStatus"),
            "passed",
            f"{prefix}.bindingStatus",
        )
        _require_equal(
            blockers,
            row.get("activeActionableExitModes"),
            required_modes,
            f"{prefix}.activeActionableExitModes",
        )
        _require_equal(
            blockers,
            row.get("exitSignalCompared"),
            True,
            f"{prefix}.exitSignalCompared",
        )
        _require_equal(
            blockers,
            row.get("strategyCompared"),
            True,
            f"{prefix}.strategyCompared",
        )

        for field in (
            "runtimeErrorCount",
            "falseExitAlertCount",
            "duplicateActionableExitAlertCount",
            "unclassifiedTransitionDifferenceCount",
        ):
            value = row.get(field)
            if not _is_nonnegative_int(value):
                blockers.append(
                    f"{prefix}.{field}: expected non-negative integer"
                )
            elif value != 0:
                blockers.append(f"{prefix}.{field}: expected 0, observed {value}")

        expected = _alert_counts(
            row, "expectedServerAlerts", channels, blockers, prefix
        )
        delivered = _alert_counts(
            row, "deliveredServerAlerts", channels, blockers, prefix
        )
        # Provenance gate (2026-08-18 Verdrahtungs-Sweep K6): the reconcile
        # exists so the delivered side comes from the receiver ledger instead
        # of manual typing, and it stamps exactly these two fields — but the
        # evaluator never read them, so a hand-typed row passed identically.
        # Enforced BEFORE the first session row lands, so every row of the
        # observation window is provable from row one.
        delivered_source = row.get("deliveredServerAlertsSource")
        if delivered_source != "receiver_ledger":
            blockers.append(
                f"{prefix}.deliveredServerAlertsSource: delivered counts must "
                "be reconciled from the receiver ledger (run "
                "scripts/reconcile_smc_hold_manager_shadow_deliveries.py), "
                f"observed {delivered_source!r}"
            )
        receiver_duplicates = _alert_counts(
            row, "receiverDuplicateDeliveries", channels, blockers, prefix
        )
        for channel in channels:
            if receiver_duplicates[channel] != 0:
                blockers.append(
                    f"{prefix}.{channel}: receiver ledger measured "
                    f"{receiver_duplicates[channel]} duplicate deliveries, "
                    "expected 0"
                )
            if expected[channel] != delivered[channel]:
                blockers.append(
                    f"{prefix}.{channel}: expected server delivery "
                    f"{expected[channel]}, observed {delivered[channel]}"
                )
            if complete and not excluded:
                aggregate_expected[channel] += expected[channel]
                aggregate_delivered[channel] += delivered[channel]

    minimum_sessions = window["minimumCompleteSessions"]
    if complete_sessions < minimum_sessions:
        blockers.append(
            f"complete sessions: need {minimum_sessions}, observed "
            f"{complete_sessions}"
        )
    maximum_sessions = window["maximumSessionsWithoutRequiredEdges"]
    if len(sessions) > maximum_sessions:
        blockers.append(
            f"observation window exceeded {maximum_sessions} sessions"
        )

    for channel, minimum in window["requiredAggregateExpectedEdges"].items():
        if aggregate_expected[channel] < minimum:
            blockers.append(
                f"aggregate {channel}: need at least {minimum} expected edge(s), "
                f"observed {aggregate_expected[channel]}"
            )
    terminal_edges = sum(
        aggregate_expected[channel]
        for channel in window["terminalExitChannels"]
    )
    if terminal_edges < window["requiredAggregateTerminalExitEdges"]:
        blockers.append(
            "aggregate terminal exits: need at least "
            f"{window['requiredAggregateTerminalExitEdges']}, observed "
            f"{terminal_edges}"
        )

    if not isinstance(rollback, Mapping):
        blockers.append("rollbackDrill: missing")
    else:
        for field, expected in contract["rollbackRequirements"].items():
            _require_equal(
                blockers,
                rollback.get(field),
                expected,
                f"rollbackDrill.{field}",
            )

    return {
        "schemaVersion": 1,
        "requirementId": requirement_id,
        "verdict": "passed" if not blockers else "blocked",
        "activationStatus": "active",
        "completeSessionCount": complete_sessions,
        "observedSessionCount": len(sessions),
        "aggregateExpectedAlerts": aggregate_expected,
        "aggregateDeliveredAlerts": aggregate_delivered,
        "blockers": blockers,
        "openGates": [] if not blockers else [
            "Resolve every blocker without changing the pre-registered contract."
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument(
        "--observations", type=Path, default=DEFAULT_OBSERVATIONS
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = evaluate_shadow(
        _load_json(args.contract),
        _load_json(args.observations),
    )
    atomic_write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["verdict"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
