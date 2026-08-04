"""Fail-closed contracts for the R1 private TradingView rollout.

2026-08-01: the rollout was re-attested after an automated consumer save
overwrote the source attested on 2026-07-29. The re-attestation closed the
source, compile and binding axes at 05:05Z and left FOUR open, because nothing
in those runs reproduced what the attended 2026-07-29 session observed by hand.

All four have since closed, each by its own dated artifact rather than by an
edit to the 05:05Z evidence -- the rollback drill at 17:23Z (run 30710010604)
and the operator's observation of the remaining three at 19:40Z. The registered
evidence still reads ``not_run`` for every one of them and always will; that is
what dating a measurement means.

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
    OPERATOR_OBSERVATION_EVIDENCE,
    PRIOR_EXECUTION_EVIDENCE,
    ROLLBACK_DRILL_EVIDENCE,
    build_rollout_contract,
)


def _evidence() -> dict:
    return json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))


def test_checked_in_rollout_contract_is_current() -> None:
    expected = build_rollout_contract()
    actual = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))

    assert actual == expected
    assert actual["status"] == "authorized_execution_reattested"
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
    # NOT equality against the registered evidence. That artifact is dated: it
    # lists what was open at 05:05:15Z and must keep saying so. The live roster
    # is that list minus the gates a later dated artifact has closed -- so a gate
    # can only leave by acquiring evidence, never by being deleted from a list.
    closed = {entry["gate"] for entry in contract["closedSinceRegisteredEvidence"]}
    assert closed <= set(evidence["openGates"])
    assert set(OPEN_GATES) == set(evidence["openGates"]) - closed

    # The roster is empty now, and an empty roster is the strongest claim this
    # contract makes. It used to be pinned as non-empty, which was the honest
    # assertion while gates were open and becomes a false one the moment they
    # are not. What carries the weight instead: every gate that left must name
    # an artifact that exists and reports passed. Emptying the roster without
    # that is what the pin now prevents.
    for entry in contract["closedSinceRegisteredEvidence"]:
        artifact = DEFAULT_OUTPUT.parents[2] / entry["evidence"]
        assert artifact.exists(), f"{entry['gate']} names evidence that is not in the tree"
        assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "passed"
        assert entry["status"] == "passed"

    assert trading_view["alertConditionInventory"] == "not_run"
    assert trading_view["holdManagerPresent"] == "not_run"
    assert trading_view["forbiddenConcurrentScriptsPresent"] == "not_run"
    assert trading_view["finalInventory"] == "not_run"
    assert trading_view["compileStatusAfterFinalReload"] == "not_run"

    # The producer was never counted, only inferred from resolved BUS parents.
    assert trading_view["suitePresence"] == "inferred"


def test_the_rollback_gate_is_closed_by_a_measurement_not_by_a_deleted_line() -> None:
    """The one gate that left the roster, and what had to exist for it to leave.

    A gate is closed here only when a dated artifact carries a verdict that
    could have come out the other way. The drill removes both companions,
    persists that, crosses a hard reload, and only then reads the layout back --
    so every field below is a reading of what TradingView actually held, not a
    restatement of what the run intended.
    """
    contract = build_rollout_contract()
    drill = json.loads(ROLLBACK_DRILL_EVIDENCE.read_text(encoding="utf-8"))
    verdict = drill["drill"]["verdict"]

    entry = next(
        e for e in contract["closedSinceRegisteredEvidence"]
        if e["gate"] == "rollback drill removing and restoring both companions"
    )
    assert "rollback drill removing and restoring both companions" not in OPEN_GATES
    assert drill["status"] == "passed"
    assert entry["evidence"] == ROLLBACK_DRILL_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    assert entry["run"] == drill["drill"]["run"]

    # Both halves, each across a reload, plus the part that makes it a ROLLBACK
    # rather than a teardown: the producer stayed, alone.
    assert verdict["removalSurvivedReload"] is True
    assert verdict["suiteRemainedPresent"] is True
    assert verdict["suiteOnlyInventoryAfterReload"] == [drill["chart"]["producerName"]]
    assert verdict["companionsRestoredFromSavedScripts"] is True
    assert verdict["finalReloadStatus"] == "passed"
    assert verdict["bindingsRestored"] == _evidence()["tradingView"]["bindingsChecked"]

    # NOT equality. ``remainingOpenGates`` says what was still open at
    # 17:23:24Z, and three gates were -- the operator closed them at 19:40Z.
    # Pinning it to the live roster would force an edit to a dated artifact the
    # first time anything else closed, which is the move this whole file exists
    # to prevent. I wrote that equality four hours ago and it was wrong then
    # too; it only looked right because nothing had moved yet.
    #
    # What must hold instead: the artifact may not UNDERSTATE what was open.
    # Everything it listed is either still open or has since acquired its own
    # dated evidence.
    still_open = set(OPEN_GATES)
    closed_since = {entry["gate"] for entry in contract["closedSinceRegisteredEvidence"]}
    assert still_open <= set(drill["remainingOpenGates"])
    assert set(drill["remainingOpenGates"]) - still_open <= closed_since


def test_the_drill_reading_moves_forward_by_a_new_artifact_never_by_an_edit() -> None:
    """The divergence is deliberate, and it is the whole point of dating evidence.

    On 2026-08-01 the registered evidence was captured at 05:05:15Z, before the
    drill had an implementation, and it records ``rollback: not_run``. The drill
    ran at 17:23:24Z. That artifact still says not_run and must keep saying it.

    The 2026-08-04 re-attestation was captured after the drill, so ``not_run``
    would be false there -- it carries the drill's own dated artifact forward
    instead, and says in the same breath that it did not re-run it. Both
    readings are true of their own date, which is exactly what editing the
    earlier one to agree would have destroyed.
    """
    evidence = _evidence()
    drill = json.loads(ROLLBACK_DRILL_EVIDENCE.read_text(encoding="utf-8"))
    prior = json.loads(PRIOR_EXECUTION_EVIDENCE.read_text(encoding="utf-8"))

    # The artifact captured BEFORE the drill keeps its pre-drill reading, for
    # good. This is the assertion that forbids the edit.
    assert prior["rollback"]["status"] == "not_run"
    assert prior["capturedAt"] < drill["capturedAt"]
    assert "not_run" in drill["supersedesNothing"]

    # The current attestation was captured after the drill, so it may not claim
    # not_run -- and it may not claim to have run it either. It carries the
    # drill's own dated artifact and says so.
    assert evidence["capturedAt"] > drill["capturedAt"]
    assert evidence["rollback"]["status"] == "carried_over"
    assert evidence["rollback"]["evidence"] == ROLLBACK_DRILL_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    assert "NOT re-run" in evidence["rollback"]["justification"]
    assert contract_note_names_the_divergence(build_rollout_contract())


def contract_note_names_the_divergence(contract: dict) -> bool:
    """The contract has to say the two artifacts disagree, or a reader will read
    the older one as current and conclude the gate is still open."""
    return any(
        "not_run" in entry["note"] and "dated measurement" in entry["note"]
        for entry in contract["closedSinceRegisteredEvidence"]
    )


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
    assert prior["capturedAt"].startswith("2026-08-01")
    # Its own pre-drill reading, unedited. The 2026-07-29 artifact it in turn
    # superseded is still in the tree with ITS reading -- the chain is kept, not
    # collapsed onto the newest state.
    assert prior["rollback"]["status"] == "not_run"
    oldest = DEFAULT_OUTPUT.parent / "smc_r1_live_rollout_evidence_2026-07-29.json"
    assert oldest.exists()
    assert json.loads(oldest.read_text(encoding="utf-8"))["rollback"]["status"] == "passed"

    assert evidence["supersedes"] == PRIOR_EXECUTION_EVIDENCE.relative_to(
        DEFAULT_OUTPUT.parents[2]
    ).as_posix()
    # The superseded hash must differ from today's, or the artifact is claiming
    # a supersession that never happened.
    assert superseded != evidence["sources"]["SMC Event Overlay"]["repositorySha256"]


def test_the_operator_observation_carries_what_no_run_reports() -> None:
    """The three fields that made R1 partial, and why they stayed partial.

    The readonly preflight reports source hashes and bindings. It does not read
    the alert-condition selector, does not enumerate the layout, and does not
    look for an error badge after a reload. Those three came from the account
    owner on 2026-07-29 and again on 2026-08-01, with screenshots -- an attended
    observation by design, not a gap waiting for automation.
    """
    observation = json.loads(OPERATOR_OBSERVATION_EVIDENCE.read_text(encoding="utf-8"))
    contract = build_rollout_contract()

    assert observation["status"] == "passed"
    assert observation["alertsCreated"] is False, "the inventory was read, not built"
    assert observation["alertsModified"] is False

    # The named conditions must match the contract's requiredAlerts exactly --
    # em dashes included. They come verbatim from alertcondition(title = ...),
    # so a differing character means the source moved underneath the alert.
    inventory = observation["alertConditionInventory"]
    for target in contract["targets"]:
        assert inventory[target["scriptName"]] == target["requiredAlerts"]

    # A rollback is only a rollback if the rest is untouched; an inventory is
    # only an inventory if it names what must NOT be there.
    layout = observation["layoutInventory"]
    assert layout["holdManagerPresent"] is False
    assert layout["forbiddenConcurrentScriptsPresent"] == []
    assert "SMC Hold Manager" in layout["checkedNames"]
    assert layout["finalInventory"] == contract["layoutContract"]["requiredScripts"]
    # The layout has to BE the Simple Management preset, which is what makes the
    # Hold Manager exclusion meaningful rather than an observation about some
    # other chart that happens to carry three scripts.
    assert contract["layoutContract"]["preset"] in layout["layoutNameConfirmed"]

    assert observation["compileStatusAfterFinalReload"] == "passed"


def test_status_derives_from_execution_state(tmp_path, monkeypatch) -> None:
    """pending im Artefakt => pending im Contract, ohne Code-Edit."""
    import scripts.smc_r1_rollout_contract as contract_mod

    evidence = json.loads(contract_mod.EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    evidence["executionState"] = "pending"
    fake = tmp_path / contract_mod.EXECUTION_EVIDENCE.name
    fake.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(contract_mod, "EXECUTION_EVIDENCE", fake)

    built = contract_mod.build_rollout_contract()
    assert built["status"] == "authorized_execution_pending"
    assert built["executionPerformed"] is False


def test_missing_execution_state_means_executed() -> None:
    """Backward-Kompatibilität: das 2026-08-04-Artefakt hat kein Feld."""
    from scripts.smc_r1_rollout_contract import build_rollout_contract

    built = build_rollout_contract()
    assert built["status"] == "authorized_execution_reattested"
    assert built["executionPerformed"] is True


def test_closed_since_is_scoped_to_the_registered_evidence(tmp_path, monkeypatch) -> None:
    """Einträge für superseded Evidenz fallen ohne Code-Edit heraus."""
    import scripts.smc_r1_rollout_contract as contract_mod

    evidence = json.loads(contract_mod.EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    evidence["executionState"] = "pending"
    evidence["openGates"] = ["mutating consumer save", "post-save verification"]
    fake = tmp_path / "smc_r1_live_rollout_evidence_2026-12-31.json"
    fake.write_text(json.dumps(evidence), encoding="utf-8")
    monkeypatch.setattr(contract_mod, "EXECUTION_EVIDENCE", fake)

    built = contract_mod.build_rollout_contract()
    assert built["closedSinceRegisteredEvidence"] == [], (
        "closures recorded against the superseded artifact must not carry over"
    )


def test_the_repaint_caution_is_disclosed_and_its_unknown_is_named() -> None:
    """TradingView flagged the alerts; the artifact says so rather than omitting it.

    Recording only what confirms the attestation is how an artifact becomes an
    advertisement. The caution appeared on all three scripts, the repository's
    mitigation is real and pinned, and whether the notice is blanket or specific
    was NOT measured -- so it is named as unmeasured instead of resolved by
    plausibility.
    """
    observation = json.loads(OPERATOR_OBSERVATION_EVIDENCE.read_text(encoding="utf-8"))
    caution = observation["observedCaution"]

    assert "repainted" in caution["text"]
    assert len(caution["appearedFor"]) == 3
    # The mitigation must cite the gate, not merely assert one exists.
    assert "barstate.isconfirmed" in caution["repositoryMitigation"]
    assert "test_pine_alert_bar_close_gate.py" in caution["repositoryMitigation"]
    # And the open question must stay open, with the check that would settle it.
    assert "NOT measured" in caution["notDetermined"]
    assert caution["treatment"].startswith("Recorded as a disclosed observation")
