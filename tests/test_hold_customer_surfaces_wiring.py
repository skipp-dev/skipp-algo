"""Pin: both automated .pine writers run the customer-surface hold — executed.

``scripts/hold_customer_surfaces.py`` is only a mechanism once a workflow runs
it after the last write to the tree and before anything commits or stages the
tree. Two workflows write customer surfaces:

* ``smc-library-publish.yml`` — the refresh chain's consumer bump (16x/day at
  export cadence). Its own repin proof (``check_pine_consumer_repin.py``) runs
  INSIDE the bump step; everything between that step and "Commit and push
  changes" was unguarded, which is the window the 2026-08-12 revert class
  (#4646) needs.
* ``pine-library-publish-handlibs.yml`` — ``repinAllConsumers`` rewrites every
  consumer weekly and the PR step stages ``'*.pine'`` wholesale.

The structural half below pins placement, gating and PR-body plumbing. The
executed half runs the step's real shell (tests/_workflow_step_shell.py)
against a fixture remote: a surface carrying a stale-tree revert must come
back byte-identical to current main while a pin-only surface keeps its bump.
A substring test cannot tell "restored the file" from "printed that it would".
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from tests._workflow_step_shell import Stub, run_step, step_by_name

REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLISH_WORKFLOW = "smc-library-publish.yml"
HANDLIBS_WORKFLOW = "pine-library-publish-handlibs.yml"
STEP_NAME = "Hold customer surfaces unless the change is pin-only"

_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _steps(workflow: str) -> list[dict]:
    doc = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    )
    return doc["jobs"]["publish"]["steps"]


def _index(steps: list[dict], name: str) -> int:
    names = [str(s.get("name", "")) for s in steps]
    assert name in names, f"no step named {name!r}"
    return names.index(name)


# ---------------------------------------------------------------------------
# Structure: placement, gating, PR-body plumbing.
# ---------------------------------------------------------------------------


def test_refresh_runs_the_hold_after_the_r1_hold_and_before_the_commit() -> None:
    steps = _steps(PUBLISH_WORKFLOW)
    r1_at = _index(steps, "Hold R1-attested sources at their attested content")
    hold_at = _index(steps, STEP_NAME)
    commit_at = _index(steps, "Commit and push changes")
    assert r1_at < hold_at < commit_at, (
        "the customer-surface hold must run after the last tree write and "
        f"before the commit — got r1={r1_at}, hold={hold_at}, commit={commit_at}"
    )
    step = steps[hold_at]
    assert step.get("id") == "surface_hold"
    assert "-m scripts.hold_customer_surfaces" in step["run"], (
        "the step must run the shared module — a reimplementation here would "
        "be a second roster and a second classifier to keep true"
    )
    # Same gate as the R1 hold: every run that commits must have held first,
    # and no run that cannot commit should fail on the hold.
    assert step.get("if") == steps[r1_at].get("if")


def test_refresh_hold_enumerates_exactly_what_the_bump_rewrites() -> None:
    """The candidate derivation is the bump step's own, against fresh main."""
    steps = _steps(PUBLISH_WORKFLOW)
    bump = steps[_index(steps, "Bump library version in all pine consumers")]
    hold = steps[_index(steps, STEP_NAME)]
    # The bump declares the library it owns in one shell assignment; the hold
    # must grep for that same pattern rather than a drifting restatement.
    pattern_lines = [
        line for line in str(bump["run"]).splitlines() if "PIN_PATTERN='" in line
    ]
    assert pattern_lines, "the bump step no longer declares PIN_PATTERN"
    pattern = pattern_lines[0].split("PIN_PATTERN='")[1].rstrip("'").strip("'")
    assert pattern in hold["run"], (
        f"the hold does not enumerate with the bump's pattern {pattern!r}; "
        "the two populations can now drift apart"
    )
    for exclude in (":(exclude)tests/**", ":(exclude)pine/**", ":(exclude)node_modules/**"):
        assert exclude in hold["run"], f"missing pathspec {exclude}"
    assert "FETCH_HEAD" in hold["run"], "the base must be freshly fetched main"
    assert "x-access-token" in hold["run"], (
        "persist-credentials: false — a bare `origin` fetch dies with exit 128 "
        "(measured 2026-08-14, run 31793906137)"
    )


def test_refresh_commit_step_carries_the_hold_notice_into_the_pr_body() -> None:
    steps = _steps(PUBLISH_WORKFLOW)
    commit = steps[_index(steps, "Commit and push changes")]
    env = commit.get("env", {})
    assert "surface_hold.outputs.notice" in str(env.get("SURFACE_HOLD_NOTICE", "")), (
        "the notice must reach the commit step through env, not expansion "
        "into code (template-injection seam)"
    )
    assert "SURFACE_HOLD_NOTICE" in commit["run"], (
        "a held surface must be explained in the PR body — a reviewer who "
        "finds it only by diffing reads the hold as a bug"
    )


def test_handlibs_runs_the_hold_between_publish_and_the_changed_measurement() -> None:
    steps = _steps(HANDLIBS_WORKFLOW)
    publish_at = _index(steps, "Ordered publish + repin")
    hold_at = _index(steps, STEP_NAME)
    r1_at = _index(steps, "Hold R1-attested sources at their attested content")
    assert publish_at < hold_at < r1_at, (
        "the hold must run after repinAllConsumers wrote the tree and before "
        "the R1-hold step measures the changed-set the PR will carry — got "
        f"publish={publish_at}, hold={hold_at}, r1={r1_at}"
    )
    step = steps[hold_at]
    assert step.get("id") == "surface_hold"
    assert "-m scripts.hold_customer_surfaces" in step["run"]
    assert "if" not in step, (
        "the hold must run unconditionally: every path that reaches the PR "
        "step must have passed through it"
    )
    # The changed-set is measured in the R1 hold step and ONLY there
    # (test_handlib_publish_r1_hold.py); this step must not add a second truth.
    assert 'echo "changed=' not in step["run"]


def test_handlibs_pr_body_names_the_held_surfaces() -> None:
    steps = _steps(HANDLIBS_WORKFLOW)
    pr = steps[_index(steps, "Open repin PR")]
    assert "surface_hold.outputs.held" in str(pr.get("env", {}).get("SURFACE_HELD", ""))
    assert "Customer-surface hold:" in pr["run"], (
        "a repin PR that silently omits a customer surface reads as a bug; "
        "the omission is the hold working"
    )


# ---------------------------------------------------------------------------
# Execution: the step's real shell against a fixture remote.
# ---------------------------------------------------------------------------

_PIN = "import preuss_steffen/smc_micro_profiles_generated/220 as mp\n"
_BUMPED = "import preuss_steffen/smc_micro_profiles_generated/221 as mp\n"
_CLEAN_VOCAB = 'var string g_bus_diag = "3. Chart Link - Context Signals"\n'
_OLD_VOCAB = 'var string g_bus_diag = "3. Operator Only - Diagnostic Support"\n'


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, env=_ENV, capture_output=True,
    )


def _commit_all(cwd: Path, message: str) -> None:
    _git(["add", "-A"], cwd)
    _git(["commit", "-qm", message], cwd)


def _fixture(tmp_path: Path, *, drop_from_main: str | None = None) -> Path:
    """A fresh `main` remote plus a stale working tree carrying refresh writes.

    History replayed: the run checked out main while Dashboard still spoke
    operator vocabulary; #4639's cleanup merged to main mid-run; the refresh
    bumped every pin. Dashboard's working copy is therefore a stale-tree
    revert (the #4646 signature); every other surface is a pure pin bump.
    """
    surfaces = {
        "SMC_Long_Dip_Suite.pine": _PIN + "plot(1)\n",
        "SMC_Long_Dip_Dashboard.pine": _PIN + _OLD_VOCAB,
        "SMC_Long_Dip_Mobile.pine": _PIN + "plot(2)\n",
        "SMC_Long_Dip_Alerts.pine": _PIN + "plot(3)\n",
        # An R1-attested companion is among the enumerated candidates and must
        # be left to its own, stricter hold rather than classified here.
        "SMC_Event_Overlay.pine": _PIN + "plot(4)\n",
    }
    remote = tmp_path / "remote"
    remote.mkdir()
    _git(["init", "-q"], remote)
    for name, body in surfaces.items():
        (remote / name).write_text(body, encoding="utf-8")
    _commit_all(remote, "stale state")

    # The working tree: cloned at the stale state (clone AFTER the stale
    # commit, BEFORE the mid-run merge).
    work = tmp_path / "work"
    _git(["clone", "-q", str(remote), str(work)], tmp_path)

    # The mid-run merge on main: Dashboard's vocabulary cleanup (#4639).
    (remote / "SMC_Long_Dip_Dashboard.pine").write_text(
        _PIN + _CLEAN_VOCAB, encoding="utf-8"
    )
    if drop_from_main is not None:
        (remote / drop_from_main).unlink()
    _commit_all(remote, "vocabulary cleanup merged mid-run")

    # The refresh's writes to the stale working tree: every pin bumped; the
    # Dashboard content is the STALE one — committing it would revert #4639.
    for name, body in surfaces.items():
        if name == "SMC_Event_Overlay.pine":
            continue  # the R1 hold already restored the companion
        (work / name).write_text(
            body.replace(_PIN, _BUMPED), encoding="utf-8"
        )
    return work


def _run_in(workflow: str, tmp_path: Path, work: Path):
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(exist_ok=True)
    env = {
        **_ENV,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(REPO_ROOT),
        "RUNNER_TEMP": str(runner_temp),
        "BUMP_REMOTE": str(tmp_path / "remote"),
        "SMC_PYTHON_BIN": sys.executable,
    }
    step = step_by_name(workflow, STEP_NAME)
    # The step body runs with the checkout as its working directory; the
    # harness runs at tmp_path, so enter the fixture tree the same way the
    # runner's `working-directory` would.
    assert "cd " not in str(step["run"]), "the step must rely on the job cwd"
    return run_step(
        workflow,
        STEP_NAME,
        work,
        env=env,
        stubs={"python3": Stub(passthrough=sys.executable)}
        if workflow == HANDLIBS_WORKFLOW
        else None,
    )


def test_refresh_hold_step_restores_the_revert_and_keeps_the_pin_bumps(
    tmp_path: Path,
) -> None:
    work = _fixture(tmp_path)
    result = _run_in(PUBLISH_WORKFLOW, tmp_path, work)

    assert result.returncode == 0, result.stderr
    # The revert-in-waiting is byte-identical to current main again: clean
    # vocabulary, pin NOT advanced (it advances with the next refresh).
    assert (work / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == (
        _PIN + _CLEAN_VOCAB
    )
    # Pure pin bumps pass through untouched.
    for name in ("SMC_Long_Dip_Suite.pine", "SMC_Long_Dip_Mobile.pine", "SMC_Long_Dip_Alerts.pine"):
        assert _BUMPED in (work / name).read_text(encoding="utf-8"), name
    # The attested companion was left to its own hold.
    assert (work / "SMC_Event_Overlay.pine").read_text(encoding="utf-8") == (
        _PIN + "plot(4)\n"
    )
    assert json.loads(result.outputs["held"]) == ["SMC_Long_Dip_Dashboard.pine"]
    assert "Customer surfaces held" in result.outputs["notice"]


def test_refresh_hold_step_fails_closed_when_main_lost_a_surface(
    tmp_path: Path,
) -> None:
    """A candidate set that lost a customer surface is UNKNOWN, not clean."""
    work = _fixture(tmp_path, drop_from_main="SMC_Long_Dip_Alerts.pine")
    result = _run_in(PUBLISH_WORKFLOW, tmp_path, work)

    assert result.returncode != 0
    assert "SMC_Long_Dip_Alerts.pine" in result.stdout + result.stderr


def test_handlibs_hold_step_restores_the_revert_and_keeps_the_pin_bumps(
    tmp_path: Path,
) -> None:
    work = _fixture(tmp_path)
    result = _run_in(HANDLIBS_WORKFLOW, tmp_path, work)

    assert result.returncode == 0, result.stderr
    assert (work / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == (
        _PIN + _CLEAN_VOCAB
    )
    assert _BUMPED in (work / "SMC_Long_Dip_Mobile.pine").read_text(encoding="utf-8")
    assert json.loads(result.outputs["held"]) == ["SMC_Long_Dip_Dashboard.pine"]
    # And the module really ran through the stubbed interpreter.
    assert result.called_with("scripts.hold_customer_surfaces")
