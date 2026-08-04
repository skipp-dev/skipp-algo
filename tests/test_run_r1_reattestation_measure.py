"""Tests for ``scripts.run_r1_reattestation``'s ``measure`` subcommand (PR2).

Builds on the same real-tree skeleton ``test_run_r1_reattestation_prepare``
uses, advanced one step further: PR1 (``prepare``) has already run, so
``measure`` starts from the state PR1 actually leaves behind rather than a
hand-built fixture that could silently diverge from it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import run_r1_reattestation
from scripts.run_r1_reattestation import PENDING_GATES, _open_gates_literal, measure
from tests.test_run_r1_reattestation_prepare import _skeleton

_PREPARE_DATE = "2026-08-05"
_MEASURE_DATE = "2026-08-06"


def _skeleton_after_pr1(tmp_path: Path) -> Path:
    from scripts.run_r1_reattestation import prepare

    root = _skeleton(tmp_path)
    rc = prepare(root=root, date=_PREPARE_DATE)
    assert rc == 0, "PR1 (prepare) must succeed before PR2 (measure) tests can run"
    return root


def test_green_runs_produce_an_executed_artifact(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)
    rc = measure(
        root=root,
        date=_MEASURE_DATE,
        save_run_id="111",
        verify_run_id="222",
        fetch_run=lambda run_id: {
            "status": "completed",
            "conclusion": "success",
            "created_at": "2026-08-05T21:00:00Z",
            "name": "tv-save-consumer-source",
        },
    )
    assert rc == 0
    artifact = json.loads(
        (root / f"artifacts/governance/smc_r1_live_rollout_evidence_{_MEASURE_DATE}.json")
        .read_text(encoding="utf-8")
    )
    assert artifact["executionState"] == "executed"
    assert {r["runId"] for r in artifact["evidenceRuns"]} == {"111", "222"}
    assert artifact["supersedes"].endswith(f"{_PREPARE_DATE}.json")
    assert artifact["openGates"] == []
    contract_text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert "OPEN_GATES: Final = ()" in contract_text
    assert f'{_MEASURE_DATE}.json"' in contract_text
    assert f'{_PREPARE_DATE}.json"' in contract_text  # rotated into PRIOR_EXECUTION_EVIDENCE
    compile(contract_text, "contract", "exec")


def test_red_save_still_writes_an_artifact_but_stays_pending(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)
    rc = measure(
        root=root,
        date=_MEASURE_DATE,
        save_run_id="111",
        verify_run_id="222",
        fetch_run=lambda run_id: {
            "status": "completed",
            "conclusion": "failure" if run_id == "111" else "success",
            "created_at": "2026-08-05T21:00:00Z",
            "name": "tv-save-consumer-source",
        },
    )
    assert rc != 0
    artifact = json.loads(
        (root / f"artifacts/governance/smc_r1_live_rollout_evidence_{_MEASURE_DATE}.json")
        .read_text(encoding="utf-8")
    )
    assert artifact["executionState"] == "pending"
    assert "failure" in json.dumps(artifact["evidenceRuns"])
    contract_text = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    assert "OPEN_GATES: Final = ()" not in contract_text, "rote Messung darf keine Gates schließen"
    # the contract's constants still rotate -- the failure itself is registered
    assert f'{_MEASURE_DATE}.json"' in contract_text


def test_incomplete_runs_write_nothing(tmp_path: Path) -> None:
    root = _skeleton_after_pr1(tmp_path)
    contract_before = (root / "scripts/smc_r1_rollout_contract.py").read_text(encoding="utf-8")
    rc = measure(
        root=root,
        date=_MEASURE_DATE,
        save_run_id="111",
        verify_run_id="222",
        fetch_run=lambda run_id: {
            "status": "in_progress",
            "conclusion": None,
            "created_at": "2026-08-05T21:00:00Z",
            "name": "x",
        },
    )
    assert rc != 0
    assert not (
        root / f"artifacts/governance/smc_r1_live_rollout_evidence_{_MEASURE_DATE}.json"
    ).exists(), "keine vakuöse Messung: unfertige Läufe schreiben nichts"
    assert (
        root / "scripts/smc_r1_rollout_contract.py"
    ).read_text(encoding="utf-8") == contract_before, "no partial contract rotation either"


def test_stray_unbalanced_paren_in_open_gates_raises_before_write(tmp_path: Path) -> None:
    """Review repro: a gate string with an unbalanced ')' must not silently
    corrupt the contract.

    The paren-depth scan alone finds a plausible-looking (but wrong) close
    paren at the stray ')' and would report count=1 as if it had succeeded.
    ``ast.literal_eval`` on the matched span is what actually catches this,
    and it must raise HERE -- before ``measure`` writes anything -- not by
    accident later via the caller's ``ast.parse`` syntax guard on an
    already-written file.
    """
    root = _skeleton_after_pr1(tmp_path)
    contract_path = root / "scripts/smc_r1_rollout_contract.py"
    contract_text = contract_path.read_text(encoding="utf-8")
    original_open_gates_block = _open_gates_literal(PENDING_GATES)
    assert original_open_gates_block in contract_text  # fixture assumption still holds
    poisoned_block = "OPEN_GATES: Final = (\n    'some gate with a stray ) inside it',\n)"
    contract_text = contract_text.replace(original_open_gates_block, poisoned_block, 1)
    contract_path.write_text(contract_text, encoding="utf-8")
    contract_before = contract_text
    artifact_path = root / f"artifacts/governance/smc_r1_live_rollout_evidence_{_MEASURE_DATE}.json"

    with pytest.raises(RuntimeError, match="OPEN_GATES"):
        measure(
            root=root,
            date=_MEASURE_DATE,
            save_run_id="111",
            verify_run_id="222",
            fetch_run=lambda run_id: {
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-08-05T21:00:00Z",
                "name": "tv-save-consumer-source",
            },
        )

    assert not artifact_path.exists(), "guard must fire before any write, not sneak one through"
    assert contract_path.read_text(encoding="utf-8") == contract_before, "contract must stay untouched"


@pytest.mark.parametrize(
    "remote_url,expected_slug",
    [
        ("git@github.com:skipp-dev/skipp-algo.git", "skipp-dev/skipp-algo"),
        ("https://github.com/skipp-dev/skipp-algo.git", "skipp-dev/skipp-algo"),
        ("https://github.com/skipp-dev/skipp-algo", "skipp-dev/skipp-algo"),
        # Non-GitHub host: _repo_slug is deliberately host-agnostic -- it only
        # parses the trailing "<owner>/<repo>[.git]" segment, which is exactly
        # what `gh api repos/<owner>/<repo>/...` needs regardless of what host
        # `origin` points at. Whether `gh api` then succeeds against a
        # non-GitHub remote is on the operator, not this function.
        ("https://gitlab.com/some-group/some-repo.git", "some-group/some-repo"),
    ],
)
def test_repo_slug_parses_owner_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, remote_url: str, expected_slug: str
) -> None:
    monkeypatch.setattr(run_r1_reattestation, "_git", lambda root, *args: remote_url)
    assert run_r1_reattestation._repo_slug(tmp_path) == expected_slug


def test_repo_slug_raises_on_an_unparseable_remote_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(run_r1_reattestation, "_git", lambda root, *args: "not a url at all")
    with pytest.raises(RuntimeError, match="could not parse owner/repo"):
        run_r1_reattestation._repo_slug(tmp_path)
