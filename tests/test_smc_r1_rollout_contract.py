"""Fail-closed contracts for the pending R1 private TradingView rollout."""

from __future__ import annotations

import json

from scripts.smc_r1_rollout_contract import (
    CONFIG,
    DEFAULT_OUTPUT,
    EXECUTION_EVIDENCE,
    build_rollout_contract,
)


def test_checked_in_rollout_contract_is_current_and_completed() -> None:
    expected = build_rollout_contract()
    actual = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["status"] == "authorized_execution_completed"
    assert actual["executionPerformed"] is True
    assert actual["executionEvidence"] == EXECUTION_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    assert actual["openGates"] == []


def test_rollout_contract_has_the_exact_r1_binding_surfaces() -> None:
    payload = build_rollout_contract()
    targets = {target["scriptName"]: target for target in payload["targets"]}

    assert targets["SMC Event Overlay"]["bindingLabels"] == ["BUS LeanPackA"]
    assert targets["SMC Event Overlay"]["libraryPin"]["version"] > 0
    assert len(targets["SMC Exit Signal"]["bindingLabels"]) == 9
    assert payload["layoutContract"]["actionableExitMode"] == "exit_signal"
    assert payload["layoutContract"]["forbiddenConcurrentActionableExitMode"] == "hold_manager"


def test_preflight_scope_is_private_and_fail_closed_for_missing_saved_scripts() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    payload = build_rollout_contract()

    assert config == {"productCutScope": "smcR1Companions"}
    assert "--execution-mode mutating" in payload["preflight"]["command"]
    assert any(
        "registered immutable execution evidence" in rule
        for rule in payload["claimPolicy"]
    )


def test_execution_evidence_closes_every_r1_live_gate() -> None:
    evidence = json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    targets = {
        target["scriptName"]: target for target in build_rollout_contract()["targets"]
    }

    for script_name, target in targets.items():
        source = evidence["sources"][script_name]
        assert source["repositorySha256"] == target["sha256"]
        assert source["savedSourceReadbackSha256"] == target["sha256"]
        assert source["compileStatus"] == "passed"
        assert source["compileDiagnostics"] == []

    tradingview = evidence["tradingView"]
    assert tradingview["layout"] == "SMC Simple Management R1"
    assert tradingview["finalInventory"] == [
        "SMC Long-Dip Suite",
        "SMC Exit Signal",
        "SMC Event Overlay",
    ]
    assert tradingview["forbiddenConcurrentScriptsPresent"] == []
    assert tradingview["holdManagerPresent"] is False
    assert tradingview["bindingStatusAfterFinalReload"] == "passed"
    assert tradingview["alertsCreated"] is False
    assert tradingview["alertsModified"] is False
    assert evidence["rollback"]["status"] == "passed"
    assert evidence["rollback"]["suiteOnlyInventoryAfterReload"] == [
        "SMC Long-Dip Suite"
    ]
    assert evidence["rollback"]["finalInventoryRestored"] is True
