"""Tests for ``scripts.run_r1_reattestation``'s ``prepare`` subcommand (PR1).

Every test runs ``prepare`` against a real, isolated working tree built from
the ACTUAL checked-in files (``SMC_Event_Overlay.pine``, the manifest, the
current governance evidence artifact, and the rollout contract module) so a
regex drift in either file surfaces here rather than only against a fixture
that has silently diverged from reality. The live tree itself is never
touched.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from scripts.run_r1_reattestation import PENDING_GATES, prepare

REPO_ROOT = Path(__file__).resolve().parents[1]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _skeleton(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel in (
        "SMC_Event_Overlay.pine",
        "SMC_Exit_Signal.pine",
        "artifacts/tradingview/library_release_manifest.json",
        "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-04.json",
        "scripts/smc_r1_rollout_contract.py",
    ):
        src = REPO_ROOT / rel
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    manifest = root / "artifacts/tradingview/library_release_manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["library"]["publishedVersion"] = 187
    manifest.write_text(json.dumps(doc), encoding="utf-8")

    # `_git_head` shells out to `git rev-parse HEAD` in `root`, so the
    # skeleton needs a real repo with at least one commit.
    subprocess.run(["git", "init", "-q"], cwd=root, check=True, env=_GIT_ENV)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True, env=_GIT_ENV)
    subprocess.run(
        ["git", "commit", "-qm", "base"], cwd=root, check=True, env=_GIT_ENV
    )
    return root


def test_prepare_bumps_the_pin_to_published(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    rc = prepare(root=root, date="2026-08-05")
    assert rc == 0
    text = (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    assert "import preuss_steffen/smc_micro_profiles_generated/187 as mp" in text
    assert "/183 as mp" not in text


def test_prepare_writes_a_pending_artifact_with_new_shas(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    prepare(root=root, date="2026-08-05")
    artifact = json.loads(
        (root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-05.json")
        .read_text(encoding="utf-8")
    )
    assert artifact["executionState"] == "pending"
    assert artifact["supersedes"].endswith("2026-08-04.json")
    event = next(s for s in artifact["sources"] if s["path"] == "SMC_Event_Overlay.pine")
    expected = hashlib.sha256(
        (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8").encode()
    ).hexdigest()
    assert event["sha256"] == expected, "artifact must hash the BUMPED source"
    assert artifact["openGates"] == list(PENDING_GATES)


def test_prepare_updates_the_contract_constants(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    prepare(root=root, date="2026-08-05")
    text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert 'smc_r1_live_rollout_evidence_2026-08-05.json"' in text
    # the old EXECUTION value becomes the new PRIOR value:
    assert text.count("2026-08-04.json") >= 1
    compile(text, "contract", "exec")  # the edit must never break the file
    # OPEN_GATES must actually be rotated to PENDING_GATES, not left as the
    # empty tuple the real contract ships with today.
    assert "OPEN_GATES: Final = ()" not in text
    for gate in PENDING_GATES:
        assert repr(gate) in text


def test_prepare_is_idempotent(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    assert prepare(root=root, date="2026-08-05") == 0
    assert prepare(root=root, date="2026-08-05") != 0  # pin already at target -> abort


def test_prepare_aborts_when_pin_already_current(tmp_path: Path) -> None:
    root = _skeleton(tmp_path)
    manifest = root / "artifacts/tradingview/library_release_manifest.json"
    doc = json.loads(manifest.read_text(encoding="utf-8"))
    doc["library"]["publishedVersion"] = 183
    manifest.write_text(json.dumps(doc), encoding="utf-8")
    assert prepare(root=root, date="2026-08-05") != 0


def test_prepare_aborts_when_todays_artifact_already_exists(tmp_path: Path) -> None:
    """Idempotency abort via the ARTIFACT branch, not the pin branch.

    Distinct from test_prepare_aborts_when_pin_already_current: here the pin
    is still below published (187 in the skeleton, 183 in the tree), so a
    broken implementation that dropped the artifact-exists check would sail
    straight through to writing files. The abort must come from the
    artifact-exists check on its own, with nothing written -- not even the
    pin, which this branch is reached BEFORE any write happens.
    """
    root = _skeleton(tmp_path)
    artifact_path = root / "artifacts/governance/smc_r1_live_rollout_evidence_2026-08-05.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text('{"preexisting": true}\n', encoding="utf-8")

    pin_before = (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8")
    contract_before = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")

    rc = prepare(root=root, date="2026-08-05")

    assert rc != 0
    assert (root / "SMC_Event_Overlay.pine").read_text(encoding="utf-8") == pin_before
    assert (
        root / "scripts/smc_r1_rollout_contract.py"
    ).read_text(encoding="utf-8") == contract_before
    # And the pre-existing artifact itself was never touched.
    assert artifact_path.read_text(encoding="utf-8") == '{"preexisting": true}\n'
