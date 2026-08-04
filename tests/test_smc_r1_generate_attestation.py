"""Fail-closed contracts for the mechanical R1 re-attestation generator.

``hold_r1_attested_sources`` keeps the automated refresh away from the R1
companions and defers their pin bump to "a deliberate re-attestation PR".
``scripts/smc_r1_generate_attestation.py`` is the machine half of that PR: it
turns the rollout driver's write+verify reports into a new dated evidence
artifact and appends it to the supersession chain.

The whole design stands on the generator refusing everything it cannot prove:

* **Pin-only supersession is proven by hash reconstruction, not by diffing.**
  Take the current Event Overlay text, swap its import pin back to the prior
  attested version, and the result must hash to the prior attested SHA-256.
  Any change beyond the pin line -- a comment, whitespace, a reordered input --
  makes the reconstruction miss, and the generator demands a human
  attestation instead of quietly widening what "automated" may claim.
* **Exit Signal may not move at all.** It carries the replay evidence forward,
  which is only honest while it is byte-identical to the measured source.
* **The reports must prove a clean rollout**: every save succeeded, the
  independent verify pass read back zero drift and zero binding mismatches,
  out-of-band drift clean, both passes on the same commit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.smc_r1_generate_attestation import (
    append_chain,
    build_attestation,
    classify_event_overlay_change,
    evidence_filename,
    write_attestation,
)

PIN_LINE = "import preuss_steffen/smc_micro_profiles_generated/{v} as mp"

PRIOR_EVENT_TEXT = (
    "//@version=6\n"
    'indicator("SMC Event Overlay")\n'
    + PIN_LINE.format(v=183)
    + "\nplot(mp.value)\n"
)
CURRENT_EVENT_TEXT = PRIOR_EVENT_TEXT.replace(
    PIN_LINE.format(v=183), PIN_LINE.format(v=186)
)
EXIT_TEXT = "//@version=6\nindicator(\"SMC Exit Signal\")\nplot(close)\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _prior_evidence() -> dict:
    return {
        "schemaVersion": 2,
        "capturedAt": "2026-08-04T02:54:45.085Z",
        "sources": {
            "SMC Event Overlay": {
                "path": "SMC_Event_Overlay.pine",
                "repositorySha256": _sha(PRIOR_EVENT_TEXT),
                "savedSourceReadbackSha256": _sha(PRIOR_EVENT_TEXT),
            },
            "SMC Exit Signal": {
                "path": "SMC_Exit_Signal.pine",
                "repositorySha256": _sha(EXIT_TEXT),
                "savedSourceReadbackSha256": _sha(EXIT_TEXT),
            },
        },
        "rollback": {
            "status": "carried_over",
            "evidence": "artifacts/governance/smc_r1_rollback_drill_2026-08-01.json",
        },
        "replay": {
            "status": "carried_over",
            "passedLogicalCases": 11,
            "evidence": "artifacts/governance/smc_exit_signal_tradingview_replay_2026-07-29.json",
        },
        "openGates": [
            "alert-condition inventory for both companions",
            "Hold Manager exclusivity and Simple Management layout inventory",
            "chart-instance compile status after a final reload",
            "rollback drill removing and restoring both companions",
        ],
        "libraryReleaseVersion": 183,
    }


def _write_report() -> dict:
    return {
        "schemaVersion": 2,
        "executionMode": "write",
        "generatedAt": "2026-08-05T06:10:00.000Z",
        "repoCommitSha": "f" * 40,
        "repositoryExpected": {
            "sources": [
                {
                    "repoRelativePath": "SMC_Event_Overlay.pine",
                    "scriptName": "SMC Event Overlay",
                    "sha256": _sha(CURRENT_EVENT_TEXT),
                },
                {
                    "repoRelativePath": "SMC_Exit_Signal.pine",
                    "scriptName": "SMC Exit Signal",
                    "sha256": _sha(EXIT_TEXT),
                },
            ],
            "bindings": [
                {
                    "repoRelativePath": "SMC_Event_Overlay.pine",
                    "scriptName": "SMC Event Overlay",
                    "expectedProducerName": "SMC Long-Dip Suite",
                    "labels": ["BUS LeanPackA"],
                },
                {
                    "repoRelativePath": "SMC_Exit_Signal.pine",
                    "scriptName": "SMC Exit Signal",
                    "expectedProducerName": "SMC Long-Dip Suite",
                    "labels": [
                        "BUS SchemaVersion",
                        "BUS Armed",
                        "BUS Confirmed",
                        "BUS Ready",
                        "BUS Trigger",
                        "BUS Invalidation",
                        "BUS StopLevel",
                        "BUS Target1",
                        "BUS Target2",
                    ],
                },
            ],
        },
        "mutations": {"sourceSavesCompleted": 11, "layoutSaved": True},
        "save": {"expected": 11, "succeeded": [f"c{i}" for i in range(11)], "failed": []},
    }


def _verify_report() -> dict:
    return {
        "schemaVersion": 2,
        "executionMode": "verify-only",
        "generatedAt": "2026-08-05T06:25:00.000Z",
        "repoCommitSha": "f" * 40,
        "sources": {"expected": 11, "checked": 11, "drifted": 0, "failed": []},
        "bindings": {
            "expectedConsumers": 9,
            "checkedConsumers": 9,
            "checkedBindings": 118,
            "mismatches": 0,
            "failed": [],
        },
        "outOfBandDrift": {"status": "clean", "changed": []},
    }


def _build(**overrides):
    kwargs = {
        "write_report": _write_report(),
        "verify_report": _verify_report(),
        "prior_evidence": _prior_evidence(),
        "prior_evidence_relpath": "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-04.json",
        "event_overlay_text": CURRENT_EVENT_TEXT,
        "exit_signal_text": EXIT_TEXT,
        "run_id": 31000000001,
        "workflow": "tv-save-consumer-source",
        "write_conclusion": "failure - at the un-attested-save guard, after the saves completed",
        "authorized_note": "automated re-attestation chain, operator-authorized 2026-08-04",
    }
    kwargs.update(overrides)
    return build_attestation(**kwargs)


# ---------------------------------------------------------------- classifier


def test_a_pure_pin_bump_classifies_pin_only() -> None:
    verdict = classify_event_overlay_change(
        CURRENT_EVENT_TEXT, prior_version=183, prior_sha256=_sha(PRIOR_EVENT_TEXT)
    )
    assert verdict == "pin-only"


def test_an_unchanged_source_classifies_identical() -> None:
    verdict = classify_event_overlay_change(
        PRIOR_EVENT_TEXT, prior_version=183, prior_sha256=_sha(PRIOR_EVENT_TEXT)
    )
    assert verdict == "identical"


def test_any_change_beyond_the_pin_line_classifies_other() -> None:
    """The boundary of what the machine may attest, enforced by reconstruction.

    A pin bump plus ONE extra comment line: swapping the pin back no longer
    reproduces the prior attested bytes, so the classifier must refuse --
    this is the case where a human attestation is required.
    """
    tampered = CURRENT_EVENT_TEXT + "// innocuous comment\n"
    verdict = classify_event_overlay_change(
        tampered, prior_version=183, prior_sha256=_sha(PRIOR_EVENT_TEXT)
    )
    assert verdict == "other"


def test_a_missing_pin_line_is_refused_loudly() -> None:
    with pytest.raises(ValueError, match="import pin"):
        classify_event_overlay_change(
            "//@version=6\nplot(close)\n",
            prior_version=183,
            prior_sha256=_sha(PRIOR_EVENT_TEXT),
        )


# ------------------------------------------------------------ happy path


def test_build_attestation_attests_the_current_sources() -> None:
    evidence = _build()
    overlay = evidence["sources"]["SMC Event Overlay"]
    exit_signal = evidence["sources"]["SMC Exit Signal"]

    assert overlay["repositorySha256"] == _sha(CURRENT_EVENT_TEXT)
    assert overlay["savedSourceReadbackSha256"] == _sha(CURRENT_EVENT_TEXT)
    assert exit_signal["repositorySha256"] == _sha(EXIT_TEXT)
    assert evidence["libraryReleaseVersion"] == 186
    assert evidence["capturedAt"] == "2026-08-05T06:25:00.000Z"
    assert evidence["repoCommitSha"] == "f" * 40
    assert evidence["supersedes"].endswith("smc_r1_live_rollout_evidence_2026-08-04.json")


def test_build_attestation_quotes_the_superseded_reading() -> None:
    evidence = _build()
    trigger = evidence["reattestationTrigger"]
    assert trigger["attestedEventOverlaySha256"] == _sha(PRIOR_EVENT_TEXT)
    assert trigger["supersededByRepositorySha256"] == _sha(CURRENT_EVENT_TEXT)
    assert "183 -> 186" in trigger["sourceDiffCharacter"]


def test_build_attestation_carries_bindings_gates_rollback_and_replay() -> None:
    evidence = _build()

    assert sorted(evidence["tradingView"]["bindings"]["SMC Event Overlay"]) == [
        "BUS LeanPackA"
    ]
    assert len(evidence["tradingView"]["bindings"]["SMC Exit Signal"]) == 9
    for consumer in evidence["tradingView"]["bindings"].values():
        for label, parent in consumer.items():
            assert parent == f"SMC Long-Dip Suite: {label}"
    assert evidence["tradingView"]["bindingsChecked"] == 10
    assert evidence["tradingView"]["bindingMismatches"] == 0
    assert evidence["tradingView"]["outOfBandDrift"] == "clean"
    assert evidence["tradingView"]["suitePresence"] == "inferred"
    for field in (
        "compileStatusAfterFinalReload",
        "alertConditionInventory",
        "holdManagerPresent",
        "forbiddenConcurrentScriptsPresent",
        "finalInventory",
    ):
        assert evidence["tradingView"][field] == "not_run"

    prior = _prior_evidence()
    assert evidence["openGates"] == prior["openGates"]
    assert evidence["rollback"]["status"] == "carried_over"
    assert evidence["rollback"]["evidence"] == prior["rollback"]["evidence"]
    assert "NOT re-run" in evidence["rollback"]["justification"]
    assert evidence["replay"]["status"] == "carried_over"
    assert evidence["replay"]["passedLogicalCases"] == 11
    assert evidence["replay"]["evidence"] == prior["replay"]["evidence"]

    modes = [run["executionMode"] for run in evidence["evidenceRuns"]]
    assert modes == ["write", "verify-only"]
    assert all(run["runId"] == 31000000001 for run in evidence["evidenceRuns"])
    assert "un-attested-save guard" in evidence["evidenceRuns"][0]["conclusion"]


def test_the_authorization_scope_never_widens() -> None:
    evidence = _build()
    auth = evidence["authorization"]
    assert auth["publicationAuthorized"] is False
    assert auth["alertMutationAuthorized"] is False
    assert auth["railwayMutationAuthorized"] is False


# ------------------------------------------------------------- fail-closed


def test_a_failed_save_is_refused() -> None:
    report = _write_report()
    report["save"]["failed"] = ["SMC Setup Check"]
    with pytest.raises(ValueError, match="save"):
        _build(write_report=report)


def test_verify_drift_is_refused() -> None:
    report = _verify_report()
    report["sources"]["drifted"] = 1
    with pytest.raises(ValueError, match="drift"):
        _build(verify_report=report)


def test_binding_mismatches_are_refused() -> None:
    report = _verify_report()
    report["bindings"]["mismatches"] = 2
    with pytest.raises(ValueError, match="mismatch"):
        _build(verify_report=report)


def test_out_of_band_drift_is_refused() -> None:
    report = _verify_report()
    report["outOfBandDrift"]["status"] = "unknown"
    with pytest.raises(ValueError, match="out-of-band"):
        _build(verify_report=report)


def test_mismatched_commits_between_passes_are_refused() -> None:
    report = _verify_report()
    report["repoCommitSha"] = "e" * 40
    with pytest.raises(ValueError, match="commit"):
        _build(verify_report=report)


def _report_with(overlay_text: str | None = None, exit_text: str | None = None) -> dict:
    """A write report consistent with the given tree -- report and tree move
    together in reality (same checkout), so a policy refusal must be provoked
    with BOTH changed, or the integrity check fires first and the test would
    pass for the wrong reason."""
    report = _write_report()
    if overlay_text is not None:
        report["repositoryExpected"]["sources"][0]["sha256"] = _sha(overlay_text)
    if exit_text is not None:
        report["repositoryExpected"]["sources"][1]["sha256"] = _sha(exit_text)
    return report


def test_a_moved_exit_signal_is_refused() -> None:
    """Replay carry-over would be a claim about a source nobody replayed."""
    moved = EXIT_TEXT + "// drift\n"
    with pytest.raises(ValueError, match="Exit Signal"):
        _build(exit_signal_text=moved, write_report=_report_with(exit_text=moved))


def test_a_beyond_pin_change_in_event_overlay_is_refused() -> None:
    tampered = CURRENT_EVENT_TEXT + "// extra\n"
    with pytest.raises(ValueError, match="pin-only"):
        _build(
            event_overlay_text=tampered,
            write_report=_report_with(overlay_text=tampered),
        )


def test_an_unmoved_pin_is_refused_as_nothing_to_attest() -> None:
    with pytest.raises(ValueError, match="identical"):
        _build(
            event_overlay_text=PRIOR_EVENT_TEXT,
            write_report=_report_with(overlay_text=PRIOR_EVENT_TEXT),
        )


def test_a_report_hash_disagreeing_with_the_tree_is_refused() -> None:
    """The report must describe the same bytes the generator is attesting."""
    report = _write_report()
    report["repositoryExpected"]["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="report"):
        _build(write_report=report)


# -------------------------------------------------------- chain integration


def test_write_and_append_extend_the_chain_mechanically(tmp_path: Path) -> None:
    evidence = _build()
    governance = tmp_path / "artifacts" / "governance"
    governance.mkdir(parents=True)

    index = governance / "smc_r1_evidence_chain.json"
    index.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "chain": [
                    {
                        "path": "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-04.json",
                        "capturedAt": "2026-08-04T02:54:45.085Z",
                        "sha256": "9" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    out = write_attestation(evidence, tmp_path)
    assert out.name == evidence_filename(evidence["capturedAt"])
    assert out.parent == governance
    assert json.loads(out.read_text(encoding="utf-8")) == evidence

    append_chain(index, out, evidence, repo_root=tmp_path)
    chain = json.loads(index.read_text(encoding="utf-8"))["chain"]
    assert chain[-1]["path"] == out.relative_to(tmp_path).as_posix()
    assert chain[-1]["capturedAt"] == evidence["capturedAt"]
    assert chain[-1]["sha256"] == hashlib.sha256(out.read_bytes()).hexdigest()


def test_append_refuses_when_supersedes_does_not_name_the_head(tmp_path: Path) -> None:
    """Appending out of order would silently orphan a reading."""
    evidence = _build()
    governance = tmp_path / "artifacts" / "governance"
    governance.mkdir(parents=True)
    index = governance / "smc_r1_evidence_chain.json"
    index.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "chain": [
                    {
                        "path": "artifacts/governance/somewhere_else.json",
                        "capturedAt": "2026-08-01T00:00:00Z",
                        "sha256": "9" * 64,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    out = write_attestation(evidence, tmp_path)
    with pytest.raises(ValueError, match="head"):
        append_chain(index, out, evidence, repo_root=tmp_path)


def test_evidence_filename_is_collision_free_within_a_day() -> None:
    """Two attestations on one day must not fight over a date-named file."""
    a = evidence_filename("2026-08-05T06:25:00.000Z")
    b = evidence_filename("2026-08-05T19:25:00.000Z")
    assert a != b
    assert a.startswith("smc_r1_live_rollout_evidence_2026-08-05T")
    assert a.endswith("Z.json")
    assert ":" not in a
