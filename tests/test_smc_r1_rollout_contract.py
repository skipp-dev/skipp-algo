"""Fail-closed contracts for the R1 private TradingView rollout.

2026-08-01: the rollout was re-attested after an automated consumer save
overwrote the source attested on 2026-07-29. The re-attestation closes the
source, compile and binding axes and leaves four axes open, because nothing in
the 2026-08-01 runs reproduces what the attended 2026-07-29 session observed by
hand.

The tests below therefore have two jobs, and the second matters more than the
first: assert what the evidence proves, and make it impossible to close an open
gate without measuring it.
"""

from __future__ import annotations

import json

from scripts.smc_r1_rollout_contract import (
    CONFIG,
    DEFAULT_OUTPUT,
    EXECUTION_EVIDENCE,
    OPEN_GATES,
    PRIOR_EXECUTION_EVIDENCE,
    build_rollout_contract,
)


def _evidence() -> dict:
    return json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))


def test_checked_in_rollout_contract_is_current() -> None:
    expected = build_rollout_contract()
    actual = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["status"] == "authorized_execution_partially_reattested"
    assert actual["executionPerformed"] is True
    assert actual["executionEvidence"] == EXECUTION_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    assert actual["priorExecutionEvidence"] == PRIOR_EXECUTION_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()


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


def test_execution_evidence_attests_the_currently_deployed_sources() -> None:
    """The axis the re-attestation exists to close.

    A source hash equal to the repository's proves only that what is saved on
    TradingView is what this commit holds -- read the open-gate test below
    before treating that as the rollout being complete.
    """
    evidence = _evidence()
    targets = {
        target["scriptName"]: target for target in build_rollout_contract()["targets"]
    }

    for script_name, target in targets.items():
        source = evidence["sources"][script_name]
        assert source["repositorySha256"] == target["sha256"]
        assert source["savedSourceReadbackSha256"] == target["sha256"]
        assert source["compileStatus"] == "passed"
        assert source["compileDiagnostics"] == []


def test_execution_evidence_attests_all_ten_bus_bindings() -> None:
    evidence = _evidence()
    bindings = evidence["tradingView"]["bindings"]
    targets = {
        target["scriptName"]: target for target in build_rollout_contract()["targets"]
    }

    for script_name, target in targets.items():
        attested = bindings[script_name]
        assert sorted(attested) == sorted(target["bindingLabels"])
        for label, parent in attested.items():
            assert parent == f"SMC Long-Dip Suite: {label}"

    assert evidence["tradingView"]["bindingsChecked"] == 10
    assert evidence["tradingView"]["bindingMismatches"] == 0
    assert evidence["tradingView"]["unknownParentRuntimeError"] is False


def test_open_gates_are_named_and_the_evidence_refuses_to_claim_them() -> None:
    """The anti-vacuity pin.

    An open gate that no test ties to a concrete unmeasured field can be closed
    by deleting a line from a list. Each gate below is anchored to the evidence
    field that would have to carry a real measurement instead of ``not_run``,
    so closing a gate requires changing the evidence, not the roster.
    """
    contract = build_rollout_contract()
    evidence = _evidence()
    trading_view = evidence["tradingView"]

    assert contract["openGates"] == list(OPEN_GATES)
    assert contract["openGates"], "R1 has open gates; an empty roster would be a false claim"
    assert evidence["openGates"] == list(OPEN_GATES)

    assert trading_view["alertConditionInventory"] == "not_run"
    assert trading_view["holdManagerPresent"] == "not_run"
    assert trading_view["forbiddenConcurrentScriptsPresent"] == "not_run"
    assert trading_view["finalInventory"] == "not_run"
    assert trading_view["compileStatusAfterFinalReload"] == "not_run"
    assert evidence["rollback"]["status"] == "not_run"

    # The producer was never counted, only inferred from resolved BUS parents.
    assert trading_view["suitePresence"] == "inferred"


def test_carried_over_replay_requires_the_exit_signal_source_to_be_unchanged() -> None:
    """The replay artifact may be reused only while its subject has not moved.

    The 2026-07-29 replay covers SMC Exit Signal. Carrying it forward is honest
    exactly as long as that source is byte-identical to the version it was
    measured against; the moment Exit Signal changes, the carry-over becomes a
    claim about a source nobody replayed.
    """
    evidence = _evidence()
    prior = json.loads(PRIOR_EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    replay = evidence["replay"]

    if replay["status"] == "carried_over":
        assert (
            evidence["sources"]["SMC Exit Signal"]["repositorySha256"]
            == prior["sources"]["SMC Exit Signal"]["repositorySha256"]
        ), "Exit Signal moved, so the 2026-07-29 replay no longer describes it"
        assert replay["evidence"] == prior["replay"]["evidence"]
        assert replay["passedLogicalCases"] == prior["replay"]["passedLogicalCases"]


def test_the_superseded_dated_evidence_is_kept_verbatim() -> None:
    """A dated measurement is never rewritten to match the present.

    The 2026-07-29 artifact attests an Event Overlay source that no longer
    exists on TradingView. That is the point: it records what was true that day.
    Editing its hash to today's value would turn a measurement into a
    fabrication and would silently erase the fact that an automated save
    overwrote an attested source.
    """
    prior = json.loads(PRIOR_EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    evidence = _evidence()

    superseded = evidence["reattestationTrigger"]["attestedEventOverlaySha256"]
    assert prior["sources"]["SMC Event Overlay"]["repositorySha256"] == superseded
    assert prior["sources"]["SMC Event Overlay"]["savedSourceReadbackSha256"] == superseded
    assert prior["capturedAt"].startswith("2026-07-29")
    assert prior["rollback"]["status"] == "passed"

    assert evidence["supersedes"] == PRIOR_EXECUTION_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    # The superseded hash must differ from today's, or the artifact is claiming
    # a supersession that never happened.
    assert superseded != evidence["sources"]["SMC Event Overlay"]["repositorySha256"]
