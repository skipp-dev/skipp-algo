"""Executable claim guards for the R0-R8 Pine migration traceability matrix."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.smc_bus_manifest import SURFACE_DEFINITIONS
from scripts.smc_r1_rollout_contract import OPEN_GATES as R1_OPEN_GATES

ROOT = Path(__file__).resolve().parents[1]
TRACE_PATH = (
    ROOT
    / "artifacts"
    / "governance"
    / "pine_extended_migration_traceability.json"
)
PLAN_PATH = ROOT / "docs" / "SMC_EXTENDED_PINE_ARCHITECTURE_AND_ROLLOUT_2026-07-26.md"


def _trace() -> dict:
    return json.loads(TRACE_PATH.read_text(encoding="utf-8"))


def _derived_phase_status(requirements: list[dict]) -> str:
    statuses = {requirement["status"] for requirement in requirements}
    if statuses == {"complete"}:
        return "complete"
    if statuses == {"not_started"}:
        return "not_started"
    return "in_progress"


def test_traceability_covers_every_phase_and_requirement_id_once() -> None:
    trace = _trace()
    phases = trace["phases"]
    requirements = [
        requirement
        for phase in phases
        for requirement in phase["requirements"]
    ]

    assert trace["schemaVersion"] == 1
    assert trace["plan"] == PLAN_PATH.relative_to(ROOT).as_posix()
    assert [phase["id"] for phase in phases] == [f"R{i}" for i in range(9)]
    ids = [requirement["id"] for requirement in requirements]
    assert len(ids) == len(set(ids))
    assert all(requirement["description"] for requirement in requirements)


def test_phase_status_is_derived_from_requirement_status_not_prose() -> None:
    allowed_requirement_statuses = {"complete", "partial", "not_started"}
    trace = _trace()

    for phase in trace["phases"]:
        requirements = phase["requirements"]
        assert requirements
        assert {
            requirement["status"]
            for requirement in requirements
        } <= allowed_requirement_statuses
        assert phase["status"] == _derived_phase_status(requirements)


def test_completed_requirements_have_existing_repository_evidence() -> None:
    trace = _trace()

    for phase in trace["phases"]:
        for requirement in phase["requirements"]:
            if requirement["status"] != "complete":
                continue
            assert requirement["evidence"], requirement["id"]
            assert requirement["openGates"] == [], requirement["id"]
            missing = [
                path
                for path in requirement["evidence"]
                if not (ROOT / path).exists()
            ]
            assert missing == [], (
                f"{requirement['id']} claims complete with missing evidence: "
                f"{missing}"
            )


def test_r1_traceability_cannot_disagree_with_the_r1_contract() -> None:
    """Two artifacts describing one rollout must not drift apart.

    Before 2026-08-01 this matrix carried R1-LIVE-ROLLOUT as complete with no
    open gates while the R1 contract had just grown four. Nothing tied them
    together, so the stale one -- the one that reads "complete" -- would have
    stayed authoritative to anyone reading the matrix instead of the contract.
    """
    trace = _trace()
    requirement = next(
        item
        for phase in trace["phases"]
        for item in phase["requirements"]
        if item["id"] == "R1-LIVE-ROLLOUT"
    )

    assert requirement["openGates"] == list(R1_OPEN_GATES)
    assert (requirement["status"] == "complete") == (not R1_OPEN_GATES)
    assert (
        "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-01.json"
        in requirement["evidence"]
    )
    # The superseded artifact stays cited: it is what the current evidence
    # supersedes, and dropping it would hide that a re-attestation happened.
    assert (
        "artifacts/governance/smc_r1_live_rollout_evidence_2026-07-29.json"
        in requirement["evidence"]
    )


def test_open_requirements_name_their_remaining_gate() -> None:
    trace = _trace()

    for phase in trace["phases"]:
        for requirement in phase["requirements"]:
            if requirement["status"] == "complete":
                continue
            assert requirement["openGates"], (
                f"{requirement['id']} is open but has no explicit gate"
            )


def test_live_claims_follow_the_surface_rollout_state() -> None:
    trace = _trace()
    requirements = {
        requirement["id"]: requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
    }
    surfaces = {surface.file: surface for surface in SURFACE_DEFINITIONS}

    # 2026-08-01: an automated consumer save overwrote the Event Overlay source
    # attested on 2026-07-29, so the rollout was re-attested against what three
    # runs actually measured. Sources, compile and the ten bindings closed at
    # 05:05Z; four axes the attended session had observed by hand did not, and
    # were carried as open gates. All four closed the same day -- the rollback
    # drill by run 30710010604 at 17:23Z, the three observation axes by the
    # account owner reading the live layout at 19:40Z. The surfaces were
    # "deployed" throughout: what was partial was the evidence, never the
    # deployment, which is why nothing about them changes here.
    assert requirements["R1-LIVE-ROLLOUT"]["status"] == "complete"
    assert requirements["R1-LIVE-ROLLOUT"]["openGates"] == []
    # 2026-07-28 22:41Z: R2 shadow observation window opened (partial) — the
    # surface itself stays a planned rollout until the window and rollback
    # drill pass; "partial" must never silently become "complete" here.
    assert requirements["R2-SHADOW-CUTOVER"]["status"] == "partial"
    for file in ("SMC_Event_Overlay.pine", "SMC_Exit_Signal.pine"):
        assert surfaces[file].rollout_state == "deployed"
    assert surfaces["SMC_Hold_Manager.pine"].rollout_state == "planned"


def test_r2_reconstruction_claim_is_pinned_to_runtime_contract() -> None:
    trace = _trace()
    requirements = {
        requirement["id"]: requirement
        for phase in trace["phases"]
        for requirement in phase["requirements"]
    }

    reconstruction = requirements["R2-RECONSTRUCTION"]
    assert reconstruction["status"] == "complete"
    assert reconstruction["evidence"] == [
        "SMC_Hold_Manager.pine",
        "tests/test_smc_hold_manager.py",
    ]
    assert reconstruction["openGates"] == []


def test_r4_tracks_local_sources_without_claiming_shadow_completion() -> None:
    trace = _trace()
    r4 = next(phase for phase in trace["phases"] if phase["id"] == "R4")

    assert r4["status"] == "in_progress"
    assert (ROOT / "SMC_Context_Bus.pine").exists()
    assert (ROOT / "SMC_Context_Overlay.pine").exists()
    requirements = {item["id"]: item for item in r4["requirements"]}
    assert requirements["R4-BUS"]["status"] == "partial"
    assert requirements["R4-OVERLAY"]["status"] == "partial"
    assert requirements["R4-BUS"]["openGates"]
    assert requirements["R4-OVERLAY"]["openGates"]
