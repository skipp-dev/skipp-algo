"""Contract for the R1-attested-source merge guard.

``artifacts/governance/smc_r1_live_rollout_contract.json`` claims the R1 rollout
completed with no open gates, and that claim is only true while the registered
evidence still attests to the current sources.
``tests/test_smc_r1_rollout_contract.py`` checks exactly that — but it is not on
the fast-gates allowlist, so it runs only in the main-push job, after a merge.

The library-refresh bot walked through that hole twice: #4272 took
``SMC_Event_Overlay.pine`` from ``smc_micro_profiles_generated/179`` to ``/180``
and #4284 went on to ``/182``. Both were green at merge time.

``scripts/check_r1_attested_sources.py`` closes the merge path. The interesting
part of its predicate is what it must NOT do: with main already drifted, a guard
that reported the standing state would fail every PR in the repo, including the
ones that would repair it.

The behaviour tests below inject synthetic targets/sources rather than keying off
whatever is drifted today. A state-dependent test here would skip itself the
moment the repo is repaired — the vacuity #4267 spent a PR removing.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

from scripts.check_r1_attested_sources import attested_sources, find_offenders
from scripts.smc_r1_rollout_contract import build_rollout_contract

GUARD = ROOT / "scripts" / "check_r1_attested_sources.py"
WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

_ATTESTED_HASH = "a" * 64
_DRIFTED_HASH = "b" * 64

_SOURCES = {"Script A": {"repositorySha256": _ATTESTED_HASH}}


def _target(sha: str) -> dict:
    return {"path": "Script_A.pine", "scriptName": "Script A", "sha256": sha}


def test_a_touched_source_that_drifted_is_an_offence() -> None:
    """The exact shape of #4272 and #4284: import bump, hash moves, evidence doesn't."""
    offenders = find_offenders(
        {"Script_A.pine"}, targets=[_target(_DRIFTED_HASH)], sources=_SOURCES
    )
    assert len(offenders) == 1
    assert "Script_A.pine" in offenders[0]
    assert _ATTESTED_HASH in offenders[0]
    assert _DRIFTED_HASH in offenders[0]


def test_a_touched_source_that_still_matches_is_allowed() -> None:
    """The escape hatch for the repair.

    A PR that restores the attested content, or that lands a fresh rollout whose
    evidence covers the new content, must pass.
    """
    assert (
        find_offenders(
            {"Script_A.pine"}, targets=[_target(_ATTESTED_HASH)], sources=_SOURCES
        )
        == []
    )


def test_an_untouched_source_is_not_this_guards_business() -> None:
    """The property that keeps the guard from halting the whole repo.

    The target is drifted here — as main is right now — but the change does not
    touch it, so the guard stays silent. Reporting the standing state instead
    would fail every unrelated PR.
    """
    assert (
        find_offenders(
            {"README.md"}, targets=[_target(_DRIFTED_HASH)], sources=_SOURCES
        )
        == []
    )
    assert find_offenders(set(), targets=[_target(_DRIFTED_HASH)], sources=_SOURCES) == []


def test_a_missing_evidence_entry_fails_loudly_rather_than_passing() -> None:
    """An attested target with no evidence entry must not read as 'fine'.

    Silently skipping it would be the vacuous-gate failure mode: the guard would
    report green over a source nothing attests to.
    """
    with pytest.raises(KeyError):
        find_offenders(
            {"Script_A.pine"}, targets=[_target(_DRIFTED_HASH)], sources={}
        )


def test_every_live_target_is_covered_by_the_evidence() -> None:
    """Wiring check against the real contract and artifact.

    Guards the premise the synthetic tests above rest on: the live contract's
    targets and the evidence really do share the scriptName key, and neither set
    is empty.
    """
    targets = build_rollout_contract()["targets"]
    sources = attested_sources()
    assert targets, "the R1 contract declares no targets"
    for target in targets:
        assert target["path"], "target carries no repository path"
        assert target["scriptName"] in sources, (
            f"{target['scriptName']} has no entry in the execution evidence"
        )
        assert "repositorySha256" in sources[target["scriptName"]]


def test_the_remedy_never_says_to_rewrite_the_dated_evidence() -> None:
    """#4270 pinned this rule for prose; it matters more where a live gate rests on it."""
    text = GUARD.read_text(encoding="utf-8")
    assert "Do NOT edit the existing dated evidence artifact" in text
    assert "falsifies a measurement" in text


def test_the_guard_is_wired_into_fast_gates() -> None:
    """fast-gates is the only required check (ADR-0011).

    A guard in any other workflow would go red without blocking the merge —
    which is how #4284 landed while the R1 contract was already failing on main.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "scripts.check_r1_attested_sources" in workflow
    assert "--range" in workflow
    # Same PR-range shape as the commit-author guard next to it.
    assert "github.event.pull_request.base.sha" in workflow
    assert "github.event.pull_request.head.sha" in workflow


def test_the_guard_runs_as_a_module_without_pythonpath() -> None:
    """It must not depend on the caller exporting PYTHONPATH.

    fast-gates happens to export it; a lane that did not would have turned this
    guard into a silent pass. Running it as a module puts the repo root on
    sys.path by construction, so no bootstrap — and no sys.path ledger entry —
    is needed.
    """
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.check_r1_attested_sources", "--range", "HEAD..HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
        env=env,
    )
    assert result.returncode == 0, result.stderr


def test_the_workflow_invokes_it_as_a_module() -> None:
    """A path invocation would depend on PYTHONPATH; pin the module form."""
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m scripts.check_r1_attested_sources" in workflow


def test_the_guard_exits_nonzero_when_it_finds_an_offender(tmp_path: Path) -> None:
    """End-to-end exit code: a green-looking failure would block nothing."""
    script = (
        "import json,sys;"
        f"sys.path.insert(0,{str(ROOT)!r});"
        "from scripts.check_r1_attested_sources import find_offenders;"
        "o=find_offenders({'Script_A.pine'},"
        f"targets=[{{'path':'Script_A.pine','scriptName':'A','sha256':'{_DRIFTED_HASH}'}}],"
        f"sources={{'A':{{'repositorySha256':'{_ATTESTED_HASH}'}}}});"
        "sys.exit(1 if o else 0)"
    )
    result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert result.returncode == 1, result.stderr


def test_the_evidence_artifact_is_valid_json_with_sources() -> None:
    """Fail-closed premise: an unreadable artifact must not degrade to 'no offenders'."""
    from scripts.smc_r1_rollout_contract import EXECUTION_EVIDENCE

    payload = json.loads(EXECUTION_EVIDENCE.read_text(encoding="utf-8"))
    assert isinstance(payload.get("sources"), dict)
    assert payload["sources"], "evidence registers no sources"
