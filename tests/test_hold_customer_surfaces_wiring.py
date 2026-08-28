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
import re
import subprocess
import sys
from pathlib import Path

import yaml

from tests._guard_corpus import iter_tracked_files
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


def _hold_enumeration_pattern(workflow: str) -> str:
    """The ERE the hold step's candidate enumeration greps for."""
    step = step_by_name(workflow, STEP_NAME)
    match = re.search(r"git grep -lE '([^']+)' FETCH_HEAD", str(step["run"]))
    assert match, f"{workflow}: hold step no longer enumerates via git grep -lE"
    return match.group(1)


def _ere_matches(pattern: str, line: str) -> bool:
    """POSIX-ERE match exactly as `git grep -lE` would judge the line."""
    return (
        subprocess.run(
            ["grep", "-qE", pattern], input=line.encode(), env=_ENV
        ).returncode
        == 0
    )


def test_hold_enumeration_covers_what_every_publish_path_rewrites() -> None:
    """Derived per publish path, not restated (the #5145 gap, closed).

    Until 2026-08-28 the hold enumerated with the refresh bump's own
    generated-library pattern — but ``repinAllConsumers``
    (scripts/tv_publish_hand_authored_libraries.ts) rewrites EVERY
    ``import preuss_steffen/<lib>/<n>`` pin, so a handlibs run wrote
    hand-lib-only surfaces (SMC_Breakout_Overlay.pine) that were never
    candidates. The invariant now: each workflow's enumeration pattern must
    match a pin of every library its publish path can rewrite — the refresh
    bump's declared PIN_PATTERN population and the whole HAND_LIBS table,
    both read from the writers themselves so a new library cannot land
    outside the hold's population.
    """
    refresh_pattern = _hold_enumeration_pattern(PUBLISH_WORKFLOW)
    handlibs_pattern = _hold_enumeration_pattern(HANDLIBS_WORKFLOW)
    assert refresh_pattern == handlibs_pattern, (
        "the two holds enumerate with different patterns; their populations "
        f"can drift apart ({refresh_pattern!r} vs {handlibs_pattern!r})"
    )

    # Refresh path: a line the bump step's own PIN_PATTERN rewrites.
    steps = _steps(PUBLISH_WORKFLOW)
    bump = steps[_index(steps, "Bump library version in all pine consumers")]
    pattern_lines = [
        line for line in str(bump["run"]).splitlines() if "PIN_PATTERN='" in line
    ]
    assert pattern_lines, "the bump step no longer declares PIN_PATTERN"
    bump_pattern = pattern_lines[0].split("PIN_PATTERN='")[1].rstrip("'").strip("'")
    generated_pin = "import preuss_steffen/smc_micro_profiles_generated/221 as mp"
    assert _ere_matches(bump_pattern, generated_pin), (
        "the sample line no longer matches the bump's PIN_PATTERN; "
        "update the sample, it is this test's positive control"
    )
    assert _ere_matches(refresh_pattern, generated_pin), (
        "the hold enumeration does not cover the bump step's own writes"
    )

    # Handlibs path: every library in the publisher's HAND_LIBS table,
    # derived from the writer itself rather than restated here.
    publisher = (REPO_ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts").read_text(
        encoding="utf-8"
    )
    hand_libs = re.findall(r'\{ name: "([A-Za-z0-9_]+)",', publisher)
    assert len(hand_libs) >= 10, (
        f"HAND_LIBS parse found only {hand_libs} — the derivation lost the "
        "population it exists to cover (10 libraries measured 2026-08-28)"
    )
    for lib in hand_libs:
        for pin in (
            f"import preuss_steffen/{lib}/54 as x",
            f"import preuss_steffen/{lib}/54",  # alias-less form
        ):
            assert _ere_matches(refresh_pattern, pin), (
                f"the hold enumeration does not cover {pin!r} — "
                "repinAllConsumers writes it, so a surface pinning only "
                f"{lib} would be rewritten without ever being a candidate"
            )

    for workflow in (PUBLISH_WORKFLOW, HANDLIBS_WORKFLOW):
        hold = step_by_name(workflow, STEP_NAME)
        for exclude in (
            ":(exclude)tests/**",
            ":(exclude)pine/**",
            ":(exclude)node_modules/**",
            # Library SOURCES are not customer surfaces: the hand-authored
            # SMC++ sources pin each other, so the broadened pattern would
            # otherwise pull them into a hold whose roster floor is defined
            # over surfaces. Their mid-run seam has its own hold since
            # 2026-08-28 (scripts/hold_smcpp_sources.py, executed by
            # tests/test_hold_smcpp_sources_wiring.py) — before that it was
            # covered by nothing (the #5148 gap).
            ":(exclude)SMC++/**",
        ):
            assert exclude in hold["run"], f"{workflow}: missing pathspec {exclude}"
        assert "FETCH_HEAD" in hold["run"], "the base must be freshly fetched main"
        assert "x-access-token" in hold["run"], (
            "persist-credentials: false — a bare `origin` fetch dies with exit "
            "128 (measured 2026-08-14, run 31793906137)"
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
# A hand-authored library pin: what repinAllConsumers rewrites and the old
# generated-pin enumeration never saw (the #5145 gap).
_ENGINE_PIN = "import preuss_steffen/smc_engine_private/54 as eng\n"
_ENGINE_BUMPED = "import preuss_steffen/smc_engine_private/55 as eng\n"
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
        # The #5145 gap pair: a customer surface pinning ONLY a hand-authored
        # library carries the same stale-tree revert as the Dashboard, and a
        # non-surface hand-lib consumer proves a pure hand-lib pin bump still
        # passes the door (the weekly repin must not be held).
        "SMC_Breakout_Overlay.pine": _ENGINE_PIN + _OLD_VOCAB,
        "SMC_Context_Bus.pine": _ENGINE_PIN + "plot(5)\n",
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

    # The mid-run merge on main: the vocabulary cleanup (#4639) — on the
    # Dashboard AND on the hand-lib-only Breakout Overlay.
    (remote / "SMC_Long_Dip_Dashboard.pine").write_text(
        _PIN + _CLEAN_VOCAB, encoding="utf-8"
    )
    (remote / "SMC_Breakout_Overlay.pine").write_text(
        _ENGINE_PIN + _CLEAN_VOCAB, encoding="utf-8"
    )
    if drop_from_main is not None:
        (remote / drop_from_main).unlink()
    _commit_all(remote, "vocabulary cleanup merged mid-run")

    # The run's writes to the stale working tree: every pin bumped (the
    # generated pin by the refresh bump, the hand-lib pin by
    # repinAllConsumers); Dashboard and Breakout content is the STALE one —
    # committing either would revert #4639.
    for name, body in surfaces.items():
        if name == "SMC_Event_Overlay.pine":
            continue  # the R1 hold already restored the companion
        (work / name).write_text(
            body.replace(_PIN, _BUMPED).replace(_ENGINE_PIN, _ENGINE_BUMPED),
            encoding="utf-8",
        )
    return work


def _run_in(workflow: str, tmp_path: Path, work: Path, *, pythonpath: str | None = None):
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(exist_ok=True)
    env = {
        **_ENV,
        "HOME": str(tmp_path),
        "PYTHONPATH": pythonpath if pythonpath is not None else str(REPO_ROOT),
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
    # The reverts-in-waiting are byte-identical to current main again: clean
    # vocabulary, pin NOT advanced (it advances with the next refresh) — on
    # the generated-pin Dashboard AND the hand-lib-only Breakout Overlay
    # (the #5145 gap: the old enumeration never made it a candidate).
    assert (work / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == (
        _PIN + _CLEAN_VOCAB
    )
    assert (work / "SMC_Breakout_Overlay.pine").read_text(encoding="utf-8") == (
        _ENGINE_PIN + _CLEAN_VOCAB
    )
    # Pure pin bumps pass through untouched — the hand-lib pin bump on a
    # non-surface consumer included (the weekly repin must not be held).
    for name in ("SMC_Long_Dip_Suite.pine", "SMC_Long_Dip_Mobile.pine", "SMC_Long_Dip_Alerts.pine"):
        assert _BUMPED in (work / name).read_text(encoding="utf-8"), name
    assert _ENGINE_BUMPED in (work / "SMC_Context_Bus.pine").read_text(encoding="utf-8")
    # The attested companion was left to its own hold.
    assert (work / "SMC_Event_Overlay.pine").read_text(encoding="utf-8") == (
        _PIN + "plot(4)\n"
    )
    assert json.loads(result.outputs["held"]) == [
        "SMC_Breakout_Overlay.pine",
        "SMC_Long_Dip_Dashboard.pine",
    ]
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
    # The #5145 gap, executed: the surface repinAllConsumers rewrites without
    # any generated-library pin comes back byte-identical to current main —
    # under the old enumeration this file was never a candidate and the stale
    # revert would have been staged wholesale by the PR step.
    assert (work / "SMC_Breakout_Overlay.pine").read_text(encoding="utf-8") == (
        _ENGINE_PIN + _CLEAN_VOCAB
    )
    assert _BUMPED in (work / "SMC_Long_Dip_Mobile.pine").read_text(encoding="utf-8")
    assert _ENGINE_BUMPED in (work / "SMC_Context_Bus.pine").read_text(encoding="utf-8")
    assert json.loads(result.outputs["held"]) == [
        "SMC_Breakout_Overlay.pine",
        "SMC_Long_Dip_Dashboard.pine",
    ]
    # And the module really ran through the stubbed interpreter.
    assert result.called_with("scripts.hold_customer_surfaces")


def test_refresh_hold_survives_a_checkout_that_predates_the_script(
    tmp_path: Path,
) -> None:
    """Run 33150273077 (2026-08-28): the refresh publish job checks out
    ``steps.source_tree.outputs.ref`` — a commit that lags main by hours —
    while its YAML is pinned at run creation from main. The step body must
    not assume the checkout carries this module: the run died with ``No
    module named scripts.hold_customer_surfaces`` AFTER the TV publish and
    BEFORE the manifest commit, stranding the release manifest one version
    behind TradingView and fail-closing every tv-save run on library
    drift. When the checkout predates the module, it must run from freshly
    fetched main instead. (handlibs is structurally immune: its checkout
    and YAML come from the same sha.)
    """
    work = _fixture(tmp_path)
    # The hold script lands on main mid-run (the #5141 merge): the fixture
    # remote's main carries the whole scripts/ tree, not a hand-kept
    # dependency list (the module lazy-imports its roster and attestation
    # helpers, and a curated list here would rot with them).
    remote = tmp_path / "remote"
    young = Path("scripts") / "hold_customer_surfaces.py"
    # Git-derived, not an rglob walk (test_guard_corpus_tracked_files budget);
    # positive control below: the enumeration must contain the module under
    # test, or the whole scenario silently degrades to the plain fixture.
    tracked = iter_tracked_files("scripts/*.py", ("__pycache__",), root=REPO_ROOT)
    assert REPO_ROOT / young in tracked
    for src in tracked:
        rel = src.relative_to(REPO_ROOT)
        dst = remote / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        # The stale checkout carries every module EXCEPT the young one —
        # that is what "predates the script" means; its older modules must
        # keep resolving from the checkout with their __file__-anchored
        # data files (symlinks: ``resolve()`` lands in the real repo, where
        # the governance artifacts the attestation roster reads live — the
        # same anchoring every other executed test here leans on).
        if rel != young:
            work_dst = work / rel
            work_dst.parent.mkdir(parents=True, exist_ok=True)
            work_dst.symlink_to(src)
    _commit_all(remote, "hold script lands on main mid-run")

    # Actions points PYTHONPATH at the workspace — the stale checkout — so
    # the young module cannot resolve from anywhere but fetched main.
    result = _run_in(PUBLISH_WORKFLOW, tmp_path, work, pythonpath=str(work))

    assert result.returncode == 0, result.stderr
    # The hole-filling extracted exactly the module the checkout lacks —
    # present modules keep their checkout version and anchoring.
    hold_src = tmp_path / "runner_temp" / "surface-hold-src"
    assert (hold_src / young).is_file()
    assert not (hold_src / "scripts" / "hold_r1_attested_sources.py").exists()
    assert (work / "SMC_Long_Dip_Dashboard.pine").read_text(encoding="utf-8") == (
        _PIN + _CLEAN_VOCAB
    )
    assert (work / "SMC_Breakout_Overlay.pine").read_text(encoding="utf-8") == (
        _ENGINE_PIN + _CLEAN_VOCAB
    )
    assert json.loads(result.outputs["held"]) == [
        "SMC_Breakout_Overlay.pine",
        "SMC_Long_Dip_Dashboard.pine",
    ]
