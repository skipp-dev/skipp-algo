"""Chain properties for the R1 evidence supersession line.

Until 2026-08-04 the current attestation was a hard-coded filename inside
``scripts/smc_r1_rollout_contract.py`` and the supersession story lived in
tests that named each artifact's date by hand. That worked while supersession
was a rare, hand-driven event; it cannot carry an automated re-attestation
chain, where every library-pin bump appends a new artifact (the deliberate
re-attestation PR that ``hold_r1_attested_sources`` defers to).

``artifacts/governance/smc_r1_evidence_chain.json`` is the mechanical
replacement: an append-only index of every evidence artifact in supersession
order, each entry carrying the SHA-256 of the artifact at registration time.
The contract derives ``EXECUTION_EVIDENCE`` (head) and
``PRIOR_EXECUTION_EVIDENCE`` (its predecessor) from the chain instead of
naming files.

The properties below replace the dated narratives wholesale:

* **Byte-freezing subsumes every "keeps its reading" assertion.** The old
  tests pinned that 2026-08-01 keeps ``rollback: not_run`` and 2026-07-29
  keeps ``passed``. Those are single instances of one rule -- a dated
  measurement is never rewritten -- and the SHA-256 pin enforces that rule
  for every artifact at once, including ones the chain gains later.
* **Linkage and ordering** make the supersession line itself checkable:
  every non-root artifact names its predecessor, capture times strictly
  increase, and the index misses nothing that exists in the tree.
* **Head currency** stays where it always was:
  ``test_execution_evidence_attests_the_currently_deployed_sources`` in
  ``test_smc_r1_rollout_contract.py`` asserts the head attests the checked-out
  sources; here we only assert the contract really registers the chain head.
"""

from __future__ import annotations

import hashlib
import json
from itertools import pairwise

from scripts.smc_r1_rollout_contract import (
    EVIDENCE_CHAIN_INDEX,
    EXECUTION_EVIDENCE,
    PRIOR_EXECUTION_EVIDENCE,
    ROOT,
    load_evidence_chain,
)

GOVERNANCE = ROOT / "artifacts" / "governance"


def _chain() -> list[dict]:
    return load_evidence_chain()


def test_chain_index_registers_every_evidence_artifact_in_the_tree() -> None:
    """No artifact outside the index, no index entry without an artifact.

    An evidence file the chain does not know is an attestation nothing
    derives from -- invisible to the contract and to these properties. An
    index entry without a file is a claim with no measurement behind it.
    """
    chain = _chain()
    indexed = {entry["path"] for entry in chain}
    on_disk = {
        p.relative_to(ROOT).as_posix()
        for p in GOVERNANCE.glob("smc_r1_live_rollout_evidence_*.json")
    }
    assert indexed == on_disk


def test_chain_artifacts_are_frozen_byte_exact() -> None:
    """A dated measurement is never rewritten to match the present.

    This is the one rule the old dated tests each asserted a single instance
    of (2026-08-01 keeps ``not_run``, 2026-07-29 keeps ``passed``). Pinning
    the registered SHA-256 enforces it for every artifact at once: editing any
    superseded artifact -- or the head, after registration -- turns a
    measurement into a fabrication and fails here.
    """
    for entry in _chain():
        digest = hashlib.sha256((ROOT / entry["path"]).read_bytes()).hexdigest()
        assert digest == entry["sha256"], (
            f"{entry['path']} no longer matches its registered SHA-256. "
            "Evidence artifacts are append-only: a new reading gets a NEW "
            "dated artifact appended to the chain, never an edit."
        )


def test_chain_is_linked_by_supersedes_and_capture_time_increases() -> None:
    """Each artifact names its predecessor; time only moves forward.

    The root (2026-07-29) supersedes nothing. Every later artifact must name
    exactly the previous chain entry -- an artifact that skips its predecessor
    would silently orphan the readings in between.
    """
    chain = _chain()
    assert len(chain) >= 3, "the seeded chain (07-29, 08-01, 08-04) is the floor"

    artifacts = [
        json.loads((ROOT / entry["path"]).read_text(encoding="utf-8"))
        for entry in chain
    ]

    assert "supersedes" not in artifacts[0] or artifacts[0]["supersedes"] is None
    for prev_entry, artifact in zip(chain, artifacts[1:]):
        assert artifact["supersedes"] == prev_entry["path"]

    captured = [entry["capturedAt"] for entry in chain]
    assert captured == sorted(captured)
    assert len(set(captured)) == len(captured), "capture times must strictly increase"
    for entry, artifact in zip(chain, artifacts):
        assert artifact["capturedAt"] == entry["capturedAt"]


def test_contract_registers_the_chain_head_and_its_predecessor() -> None:
    """The contract derives its evidence paths from the chain, never by name.

    The hard-coded filename was the reason every supersession needed a code
    change; deriving both paths from the index is what makes appending an
    artifact sufficient.
    """
    chain = _chain()
    assert ROOT / chain[-1]["path"] == EXECUTION_EVIDENCE
    assert ROOT / chain[-2]["path"] == PRIOR_EXECUTION_EVIDENCE
    assert EVIDENCE_CHAIN_INDEX.is_file()


def test_a_pre_drill_artifact_keeps_not_run_and_later_ones_carry_the_drill() -> None:
    """The drill divergence, as a chain rule instead of two dated stories.

    The rollback drill has exactly one dated artifact
    (``smc_r1_rollback_drill_2026-08-01.json``, 17:23:24Z). Any evidence
    captured BEFORE it that recorded ``not_run`` keeps that reading (enforced
    byte-exact above); any evidence captured AFTER it may claim neither
    ``not_run`` (false by then) nor a re-run that never happened -- it carries
    the drill's artifact and says so.
    """
    drill_path = GOVERNANCE / "smc_r1_rollback_drill_2026-08-01.json"
    drill = json.loads(drill_path.read_text(encoding="utf-8"))

    for entry in _chain():
        artifact = json.loads((ROOT / entry["path"]).read_text(encoding="utf-8"))
        rollback = artifact["rollback"]
        if entry["capturedAt"] <= drill["capturedAt"]:
            assert rollback["status"] in ("not_run", "passed"), (
                f"{entry['path']} predates the drill and may only carry its "
                "own attended reading or not_run"
            )
        else:
            assert rollback["status"] == "carried_over"
            assert rollback["evidence"] == drill_path.relative_to(ROOT).as_posix()
            assert "NOT re-run" in rollback["justification"]


def test_a_carried_over_replay_requires_its_subject_unchanged_link_by_link() -> None:
    """Replay carry-over is only honest while Exit Signal has not moved.

    Enforced per link: wherever an artifact carries the replay forward, its
    Exit Signal hash must equal its predecessor's. With every artifact frozen
    byte-exact, the per-link rule gives the transitive guarantee back to the
    artifact that actually measured the replay.
    """
    chain = _chain()
    artifacts = [
        json.loads((ROOT / entry["path"]).read_text(encoding="utf-8"))
        for entry in chain
    ]
    for prior, current in pairwise(artifacts):
        if current.get("replay", {}).get("status") != "carried_over":
            continue
        assert (
            current["sources"]["SMC Exit Signal"]["repositorySha256"]
            == prior["sources"]["SMC Exit Signal"]["repositorySha256"]
        ), "Exit Signal moved, so the carried replay no longer describes it"
        assert current["replay"]["evidence"] == prior["replay"]["evidence"]
        assert (
            current["replay"]["passedLogicalCases"]
            == prior["replay"]["passedLogicalCases"]
        )
