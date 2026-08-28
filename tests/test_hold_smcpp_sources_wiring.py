"""Pin: the handlibs publish holds SMC++ library sources — executed.

The PR step of ``pine-library-publish-handlibs.yml`` stages ``'*.pine'`` +
``'SMC++'/*.pine`` wholesale out of the run-start checkout, and the ordered
publisher (``scripts/tv_publish_hand_authored_libraries.ts``) rewrites
import-pin lines IN the stale working-tree copies — its per-library own-dep
repins and ``repinAllConsumers``. An SMC++ source whose pin moved this run is
therefore committed with the run-start BASE content underneath: a merge into
that source mid-run comes back reverted on the bot lane, the 2026-08-12
#4646 class for library sources (the #5148 gap). The customer-surface hold
excludes ``SMC++/**`` by design (library sources are not customer surfaces)
and the R1 hold owns only the attested sources (both at the repo root), so a
non-attested SMC++ source was held by NOTHING.

The structural half pins placement and PR-body plumbing. The executed half
runs the step's real shell (tests/_workflow_step_shell.py) against a fixture
remote: a mid-run merge into a non-attested SMC++ source must come back
byte-identical to current main, while the run's own pin bumps — the files
this run legitimately wrote — pass the door. A substring test cannot tell
"restored the file" from "printed that it would".

The module's own behaviour (roster derivation, attested exclusion, floor) is
executed by ``tests/test_hold_smcpp_sources.py``; this file pins the
composition, which is exactly what the module's tests cannot see. The
customer-surface hold keeps its own wiring file
(``tests/test_hold_customer_surfaces_wiring.py``) — extended there, not
duplicated here: this file covers only the SMC++ population that hold
excludes.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from tests._workflow_step_shell import Stub, run_step, step_by_name

REPO_ROOT = Path(__file__).resolve().parents[1]
HANDLIBS_WORKFLOW = "pine-library-publish-handlibs.yml"
STEP_NAME = "Hold SMC++ library sources unless the change is pin-only"
SURFACE_STEP = "Hold customer surfaces unless the change is pin-only"
R1_STEP = "Hold R1-attested sources at their attested content"

_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "PATH": "/usr/bin:/bin:/usr/local/bin",
}


def _steps() -> list[dict]:
    doc = yaml.safe_load(
        (REPO_ROOT / ".github" / "workflows" / HANDLIBS_WORKFLOW).read_text(
            encoding="utf-8"
        )
    )
    return doc["jobs"]["publish"]["steps"]


def _index(steps: list[dict], name: str) -> int:
    names = [str(s.get("name", "")) for s in steps]
    assert name in names, f"no step named {name!r}"
    return names.index(name)


def _hand_lib_sources() -> list[str]:
    """The SMC++ sources the publisher can write, from the writer itself."""
    publisher = (
        REPO_ROOT / "scripts" / "tv_publish_hand_authored_libraries.ts"
    ).read_text(encoding="utf-8")
    sources = re.findall(r'source:\s*"(SMC\+\+/[A-Za-z0-9_]+\.pine)"', publisher)
    assert len(sources) >= 10, (
        f"HAND_LIBS parse found only {sources} — the derivation lost the "
        "population it exists to cover (10 sources measured 2026-08-28)"
    )
    return sources


# ---------------------------------------------------------------------------
# Structure: placement, gating, PR-body plumbing.
# ---------------------------------------------------------------------------


def test_handlibs_runs_the_smcpp_hold_before_the_changed_measurement() -> None:
    steps = _steps()
    publish_at = _index(steps, "Ordered publish + repin")
    surface_at = _index(steps, SURFACE_STEP)
    smcpp_at = _index(steps, STEP_NAME)
    r1_at = _index(steps, R1_STEP)
    assert publish_at < surface_at < smcpp_at < r1_at, (
        "the SMC++ hold must run after repinAllConsumers wrote the tree and "
        "before the R1-hold step measures the changed-set the PR will carry — "
        f"got publish={publish_at}, surface={surface_at}, smcpp={smcpp_at}, "
        f"r1={r1_at}"
    )
    step = steps[smcpp_at]
    assert step.get("id") == "smcpp_hold"
    assert "-m scripts.hold_smcpp_sources" in step["run"], (
        "the step must run the shared module — a reimplementation here would "
        "be a second roster and a second classifier to keep true"
    )
    assert "if" not in step, (
        "the hold must run unconditionally: every path that reaches the PR "
        "step must have passed through it"
    )
    # The changed-set is measured in the R1 hold step and ONLY there
    # (test_handlib_publish_r1_hold.py); this step must not add a second truth.
    assert 'echo "changed=' not in step["run"]
    assert "FETCH_HEAD" in step["run"], (
        "the base must be freshly fetched main — a hold against the run-start "
        "HEAD would revert the mid-run merge itself (#5141)"
    )
    assert "x-access-token" in step["run"], (
        "persist-credentials: false — a bare `origin` fetch dies with exit "
        "128 (measured 2026-08-14, run 31793906137)"
    )


def test_smcpp_hold_enumerates_the_whole_smcpp_population() -> None:
    """The candidates are ALL of SMC++/*.pine, not an import-pin grep.

    The surface hold enumerates by owner-import grep because "carries a pin"
    is exactly "some publish path can write this surface". For SMC++ the
    publisher scans every ``SMC++/*.pine`` (``consumerPineFiles``), and four
    sources carry no import at all (smc_core_types imports nothing) — a
    pin-grep enumeration would silently drop them from the population.
    """
    step = step_by_name(HANDLIBS_WORKFLOW, STEP_NAME)
    assert "git ls-tree -r --name-only FETCH_HEAD" in str(step["run"])
    assert "SMC++/" in str(step["run"])
    assert "git grep" not in str(step["run"])


def test_pr_body_names_the_held_smcpp_sources() -> None:
    steps = _steps()
    pr = steps[_index(steps, "Open repin PR")]
    assert "smcpp_hold.outputs.held" in str(pr.get("env", {}).get("SMCPP_HELD", "")), (
        "the held roster must reach the PR step through env, not expansion "
        "into code (template-injection seam)"
    )
    assert "SMC++ source hold:" in pr["run"], (
        "a repin PR that silently omits an SMC++ repin reads as a bug; the "
        "omission is the hold working"
    )


# ---------------------------------------------------------------------------
# Execution: the step's real shell against a fixture remote.
# ---------------------------------------------------------------------------

_CORE_PIN = "import preuss_steffen/smc_core_types/5 as ct\n"
_CORE_BUMPED = "import preuss_steffen/smc_core_types/6 as ct\n"
_UTILS_PIN = "import preuss_steffen/smc_utils/4 as u\n"
_UTILS_BUMPED = "import preuss_steffen/smc_utils/5 as u\n"
_STALE_BODY = "export f() => 1\n"
# The mid-run merge: a content fix in a NON-attested SMC++ source. Committing
# the run's stale copy would revert it — the incident class under test.
_MID_RUN_FIX = "export fixed_helper() => 42\n"


def _git(args: list[str], cwd: Path) -> None:
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, check=True, env=_ENV, capture_output=True,
    )


def _commit_all(cwd: Path, message: str) -> None:
    _git(["add", "-A"], cwd)
    _git(["commit", "-qm", message], cwd)


def _fixture(tmp_path: Path, *, drop_from_main: str | None = None) -> Path:
    """A fresh `main` remote plus a stale working tree carrying publish writes.

    History replayed: the run checked out main; a content fix to smc_utils
    merged to main mid-run; the publisher repinned smc_utils' own dep-import
    (core_types moved) and smc_profile_engine's utils pin — both IN the stale
    working tree, which is exactly what repinAllConsumers does. smc_utils'
    working copy is therefore a stale-tree revert; smc_profile_engine is a
    pure pin bump that must pass.
    """
    sources = _hand_lib_sources()
    bodies: dict[str, str] = {}
    for src in sources:
        stem = Path(src).stem
        if stem == "smc_utils":
            bodies[src] = _CORE_PIN + _STALE_BODY
        elif stem == "smc_profile_engine":
            bodies[src] = _UTILS_PIN + "export g() => 2\n"
        else:
            bodies[src] = f"export {stem}_marker() => 3\n"

    remote = tmp_path / "remote"
    remote.mkdir()
    _git(["init", "-q"], remote)
    for src, body in bodies.items():
        target = remote / src
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _commit_all(remote, "stale state")

    # The working tree: cloned at the stale state (clone AFTER the stale
    # commit, BEFORE the mid-run merge).
    work = tmp_path / "work"
    _git(["clone", "-q", str(remote), str(work)], tmp_path)

    # The mid-run merge on main: a content fix in smc_utils.
    (remote / "SMC++" / "smc_utils.pine").write_text(
        _CORE_PIN + _STALE_BODY + _MID_RUN_FIX, encoding="utf-8"
    )
    if drop_from_main is not None:
        (remote / drop_from_main).unlink()
    _commit_all(remote, "content fix merged mid-run")

    # The run's writes to the STALE working tree: pin lines only, on the
    # run-start base content — smc_utils' own dep-import and
    # smc_profile_engine's utils pin.
    (work / "SMC++" / "smc_utils.pine").write_text(
        _CORE_BUMPED + _STALE_BODY, encoding="utf-8"
    )
    (work / "SMC++" / "smc_profile_engine.pine").write_text(
        _UTILS_BUMPED + "export g() => 2\n", encoding="utf-8"
    )
    return work


def _run_in(tmp_path: Path, work: Path):
    runner_temp = tmp_path / "runner_temp"
    runner_temp.mkdir(exist_ok=True)
    env = {
        **_ENV,
        "HOME": str(tmp_path),
        "PYTHONPATH": str(REPO_ROOT),
        "RUNNER_TEMP": str(runner_temp),
        "BUMP_REMOTE": str(tmp_path / "remote"),
    }
    step = step_by_name(HANDLIBS_WORKFLOW, STEP_NAME)
    assert "cd " not in str(step["run"]), "the step must rely on the job cwd"
    return run_step(
        HANDLIBS_WORKFLOW,
        STEP_NAME,
        work,
        env=env,
        stubs={"python3": Stub(passthrough=sys.executable)},
    )


def test_smcpp_hold_restores_the_mid_run_merge_and_keeps_the_pin_bumps(
    tmp_path: Path,
) -> None:
    work = _fixture(tmp_path)
    # The seam is real before the step runs: the working copy carries the
    # stale base + the run's pin bump, and the PR step would stage exactly
    # this via `git add '*.pine' 'SMC++'/*.pine` — committing it reverts the
    # mid-run fix.
    stale = (work / "SMC++" / "smc_utils.pine").read_text(encoding="utf-8")
    assert _MID_RUN_FIX not in stale
    assert _CORE_BUMPED in stale

    result = _run_in(tmp_path, work)

    assert result.returncode == 0, result.stderr
    # The revert-in-waiting is byte-identical to current main again: content
    # fix present, pin NOT advanced (it advances with the next publish).
    assert (work / "SMC++" / "smc_utils.pine").read_text(encoding="utf-8") == (
        _CORE_PIN + _STALE_BODY + _MID_RUN_FIX
    )
    # The run's own writes pass the door: a pure pin bump on a source main
    # did not touch keeps its bump.
    assert (work / "SMC++" / "smc_profile_engine.pine").read_text(
        encoding="utf-8"
    ) == (_UTILS_BUMPED + "export g() => 2\n")
    # Sources neither the run nor main touched stay untouched.
    assert (work / "SMC++" / "smc_core_types.pine").read_text(
        encoding="utf-8"
    ) == "export smc_core_types_marker() => 3\n"
    assert json.loads(result.outputs["held"]) == ["SMC++/smc_utils.pine"]
    assert "SMC++ library sources held" in result.outputs["notice"]
    # And the module really ran through the stubbed interpreter.
    assert result.called_with("scripts.hold_smcpp_sources")


def test_smcpp_hold_fails_closed_when_main_lost_a_hand_lib_source(
    tmp_path: Path,
) -> None:
    """A candidate set that lost a publisher source is UNKNOWN, not clean."""
    work = _fixture(tmp_path, drop_from_main="SMC++/smc_draw.pine")
    result = _run_in(tmp_path, work)

    assert result.returncode != 0
    assert "smc_draw" in result.stdout + result.stderr
