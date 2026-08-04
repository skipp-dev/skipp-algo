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

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]

from scripts.check_r1_attested_sources import attested_sources, find_offenders
from scripts.smc_r1_rollout_contract import build_rollout_contract
from tests._fast_gates_gate import run_gate

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
    """#4270 pinned this rule for prose; it matters more where a live gate rests on it.

    Asserted against the CONSTANT the guard prints, not against the file's
    source text. Source text is satisfied by a docstring, a comment, or a dead
    string literal — the same gap ``_run_gate`` was written to close one layer
    up. ``_REMEDY`` is what reaches stderr on the required check, so it is what
    the operator reads.
    """
    from scripts.check_r1_attested_sources import _REMEDY

    assert "Do NOT edit the existing dated evidence artifact" in _REMEDY
    assert "falsifies a measurement" in _REMEDY


def test_the_remedy_names_both_places_the_registration_lives() -> None:
    """A remedy that repoints one of two pinned copies leaves the repo red.

    The registration is duplicated by construction: ``EXECUTION_EVIDENCE`` in
    ``scripts/smc_r1_rollout_contract.py`` and ``executionEvidence`` in the
    generated ``artifacts/governance/smc_r1_live_rollout_contract.json``, held
    equal by ``tests/test_smc_r1_rollout_contract.py``. An operator who follows
    a remedy naming only the artifact does the work and stays failing, which is
    how a correct instruction still costs a cycle.
    """
    from scripts.check_r1_attested_sources import _REMEDY

    for site in (
        "scripts/smc_r1_rollout_contract.py",
        "artifacts/governance/smc_r1_live_rollout_contract.json",
    ):
        assert site in _REMEDY, (
            f"the remedy does not name {site}, one of the two registration "
            "sites tests/test_smc_r1_rollout_contract.py pins equal to the "
            "other. Following it would leave the repository red."
        )


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


# --- the guard fired on PRs that touched nothing (2026-08-04) -----------------


def test_a_two_dot_range_is_read_from_the_merge_base() -> None:
    """`git diff A..B` is `git diff A B` — a comparison of two TREES, not a
    range. On a branch created before an attested source changed on main, that
    reports main's change as this PR's.

    Measured 2026-08-04 over `d3d387a80..233adebc0`: PR #4373 touches no .pine
    file at all and this guard failed it for SMC_Event_Overlay.pine, because
    #4371 changed that file on main after the branch point. Sixteen .pine files
    came back from the two-dot form and none from the three-dot form.
    """
    from scripts.check_r1_attested_sources import _merge_base_range

    assert _merge_base_range("abc..def") == "abc...def"
    # An explicit three-dot range is already the question we want; leave it.
    assert _merge_base_range("abc...def") == "abc...def"
    # A single revision has no range semantics to correct.
    assert _merge_base_range("HEAD") == "HEAD"


def test_the_diff_is_actually_invoked_with_three_dots(monkeypatch) -> None:
    """Pins the call, not just the helper: the normalisation is worthless if
    `_changed_paths` forgets to route through it."""
    from scripts import check_r1_attested_sources as guard

    seen: dict = {}

    class _Result:
        stdout = ""

    def _fake_run(argv, **kwargs):
        seen["argv"] = argv
        return _Result()

    monkeypatch.setattr(guard.subprocess, "run", _fake_run)
    guard._changed_paths("BASE..HEAD")

    assert seen["argv"] == ["git", "diff", "--name-only", "BASE...HEAD"]


def test_a_pine_only_bot_pr_still_runs_this_guard() -> None:
    """The hole this guard was built to close, re-opened by the lane it runs in.

    `*.pine` sits on fast-gates' data-only allowlist ("published to TradingView,
    never executed by CI"), which is true about execution risk and wrong about
    attestation. So a pine-only bot PR got run_heavy=false, the checkout was
    skipped, this step with it — measured on #4371, which merged green on
    2026-08-04 and left every later PR red on this guard.
    """
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "smc-fast-pr-gates.yml"
    )
    text = workflow.read_text(encoding="utf-8")

    # The gate must publish a pine signal ...
    assert "run_pine_guard=$pine" in text
    # ... the checkout must happen for it (no checkout, no guard) ...
    assert (
        "if: steps.gate.outputs.run_heavy == 'true' || "
        "steps.gate.outputs.run_pine_guard == 'true'" in text
    )
    # ... and the guard step itself must not hang on run_heavy alone.
    guard_step = text.split("- name: Guard R1-attested sources", 1)[1]
    condition = guard_step.split("run:", 1)[0]
    assert "run_pine_guard" in condition
    assert "steps.gate.outputs.run_heavy == 'true' &&" not in condition


def test_the_gate_raises_the_pine_flag_for_a_pine_only_bot_pr(tmp_path: Path) -> None:
    """#4371's own shape: one attested pine file, nothing else."""
    outputs = run_gate(["SMC_Event_Overlay.pine"], tmp_path)

    assert outputs["run_pine_guard"] == "true"
    # Pine still must not drag in the heavy suite — that exemption is the point.
    assert outputs["run_heavy"] == "false"


def test_the_gate_leaves_the_pine_flag_down_without_pine(tmp_path: Path) -> None:
    """The other half of the witness.

    A flag hardcoded to ``true`` would satisfy the test above while running the
    heavy checkout on every bot PR. Only both directions pin the behaviour.
    """
    outputs = run_gate(["artifacts/governance/some_measurement.json"], tmp_path)

    assert outputs["run_pine_guard"] == "false"
    assert outputs["run_heavy"] == "false"


# --- the pine lane runs this guard with nothing installed (2026-08-04) --------


def _module_level_imports(path: Path) -> set[str]:
    """Imports that execute when the module is imported.

    Excludes two kinds that cannot break a bare interpreter: everything inside
    ``if TYPE_CHECKING:`` (deferred to strings by ``from __future__ import
    annotations``) and everything inside a function or class body (only paid if
    that code runs). ``try:`` blocks ARE descended into — a module-level
    ``try: import x`` still executes.
    """
    imported: set[str] = set()

    def visit(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                # `level > 0` is a relative import: repo-local by construction.
                if node.module and node.level == 0:
                    imported.add(node.module)
            elif isinstance(node, ast.If):
                test = node.test
                name = getattr(test, "id", None) or getattr(test, "attr", None)
                if name != "TYPE_CHECKING":
                    visit(node.body)
                visit(node.orelse)
            elif isinstance(node, ast.Try):
                visit(node.body)
                visit(node.orelse)
                visit(node.finalbody)
                for handler in node.handlers:
                    visit(handler.body)

    visit(ast.parse(path.read_text(encoding="utf-8")).body)
    return imported


def _repo_module_path(dotted: str) -> Path | None:
    candidates = (
        ROOT / f"{dotted.replace('.', '/')}.py",
        ROOT / dotted.replace(".", "/") / "__init__.py",
    )
    return next((c for c in candidates if c.exists()), None)


def test_the_guard_import_chain_needs_nothing_installed() -> None:
    """The pine-only lane runs this guard with no dependencies installed.

    `run_heavy=false` skips "Set up pinned Python", "Resolve Python 3.12
    interpreter" AND "Install dependencies", yet the guard step still shells
    `python -m scripts.check_r1_attested_sources`. It therefore works only while
    every module it imports at import time is stdlib or repo-local — a
    load-bearing condition that, until this test, nothing enforced.

    The repo has already paid for this class once: `scripts/smc_atomic_write.py`
    carries a comment (Bug-Hunt F-05, 2026-05-01) explaining why its `pandas`
    import sits under TYPE_CHECKING — a cron that deliberately does not install
    pandas was crashing at import time. That module is in THIS chain.

    A single top-level `import pandas` anywhere below would not fail a review;
    it would fail every pine-only bot PR, which is the lane the library-refresh
    bot depends on.
    """
    pending = ["scripts.check_r1_attested_sources"]
    seen: set[str] = set()
    third_party: dict[str, str] = {}

    while pending:
        dotted = pending.pop()
        if dotted in seen:
            continue
        seen.add(dotted)
        path = _repo_module_path(dotted)
        if path is None:
            continue
        for imported in _module_level_imports(path):
            if _repo_module_path(imported) is not None:
                pending.append(imported)
            elif imported.split(".")[0] not in sys.stdlib_module_names:
                third_party[imported] = dotted

    assert not third_party, (
        "the R1 guard's runtime import chain left stdlib+repo: "
        + ", ".join(f"{mod} (imported by {by})" for mod, by in sorted(third_party.items()))
        + ". The pine-only fast-gates lane installs nothing, so this breaks "
        "every pine-touching bot PR. Move the import under TYPE_CHECKING, make "
        "it function-local, or give that lane a dependency install."
    )


def test_the_pine_lane_really_does_install_nothing() -> None:
    """Pins WHY the purity test above is load-bearing, not merely tidy.

    If the pine lane ever gains a dependency install, the constraint stops being
    real and the test above becomes a rule without a reason — the kind of pin
    this repo removes. If instead the guard stops running on the pine lane, the
    hole #4376 closed is back. Either way this should be read, not silently
    diverge.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = {
        step["name"]: str(step.get("if", ""))
        for step in workflow["jobs"]["fast-gates"]["steps"]
        if "name" in step
    }

    assert "run_pine_guard" in steps["Guard R1-attested sources"], (
        "the guard no longer runs on the pine-only lane — that is the hole "
        "#4376 closed (the library-refresh bot merged un-attested)"
    )
    for installer in (
        "Set up pinned Python (GitHub-hosted)",
        "Resolve Python 3.12 interpreter",
        "Install dependencies",
    ):
        assert "run_pine_guard" not in steps[installer], (
            f"{installer!r} now also runs on the pine-only lane. The import-"
            "purity constraint above is no longer load-bearing; either drop that "
            "test with this change, or drop this one."
        )
