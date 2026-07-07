"""Lane 7 (provider-boundary audit) — LaunchAgent driver realism.

The local launchd cron drivers under ``automation/launchd/`` previously
ran ``git commit && git push origin <current-branch>`` after generating a
daily artefact, which silently pushed cron data onto whatever branch the
developer happened to have checked out when the agent fired. When local
``main`` lagged ``origin/main`` the push was rejected non-fast-forward and
the agents entered a compounding divergence loop, while the data never
reached the branch the GH-hosted cron actually overlays from
(``data/phase-a-audit``).

The drivers now publish through the shared ``lib_c13_data_push.sh`` helper,
which routes every artefact to ``data/phase-a-audit`` via an ISOLATED git
worktree keyed on ``origin/data/phase-a-audit`` — so the primary working
tree's checked-out branch is never touched. These tests assert:

    * Drivers no longer contain the old ``case "${CURRENT_BRANCH}"`` /
      ``git push origin HEAD`` pattern and instead call
      ``push_to_data_branch``.
    * The helper pushes to the data branch and leaves the primary tree's
      HEAD untouched, even when run from an unrelated feature branch.

The behavioural test exercises the real helper in a throwaway git sandbox
(bare remote + clone) so it is verified independently of FMP/Databento.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
DRIVERS = [
    REPO / "automation" / "launchd" / "run-c13-wsh.sh",
    REPO / "automation" / "launchd" / "run-c13-imbalance.sh",
    # audit pass-3 finding A1 (2026-06-10): audit-push previously duplicated
    # the worktree-push logic inline and silently drifted from the lib's
    # R1/R4/R5 hardening; it now consumes the shared helper like the rest.
    REPO / "automation" / "launchd" / "run-c13-audit-push.sh",
    # C13 revival (2026-07-06): the reconcile-fills stage publishes the
    # fill-stamped audit file through the same shared helper.
    REPO / "automation" / "launchd" / "run-c13-reconcile.sh",
]


def _run(cmd, cwd, env=None):
    return subprocess.run(
        cmd, cwd=str(cwd), env=env, check=False,
        capture_output=True, text=True,
    )


@pytest.fixture
def sandbox(tmp_path):
    work = tmp_path / "repo"
    work.mkdir()
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    _run(["git", "init", "-q", "-b", "main"], work, env)
    (work / "README.md").write_text("seed\n")
    _run(["git", "add", "."], work, env)
    _run(["git", "commit", "-q", "-m", "seed"], work, env)
    return work, env


def _data_branch_sandbox(tmp_path):
    """Bare remote + clone with a live ``data/phase-a-audit`` branch."""
    remote = tmp_path / "remote.git"
    _run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], tmp_path)

    work = tmp_path / "repo"
    work.mkdir()
    env = os.environ.copy()
    env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = "t"
    env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = "t@example.com"
    _run(["git", "init", "-q", "-b", "main"], work, env)
    _run(["git", "remote", "add", "origin", str(remote)], work, env)
    (work / "README.md").write_text("seed\n")
    _run(["git", "add", "."], work, env)
    _run(["git", "commit", "-q", "-m", "seed"], work, env)
    _run(["git", "push", "-q", "origin", "main"], work, env)
    # Seed the canonical data branch on origin.
    _run(["git", "checkout", "-q", "-b", "data/phase-a-audit"], work, env)
    _run(["git", "push", "-q", "origin", "data/phase-a-audit"], work, env)
    _run(["git", "checkout", "-q", "main"], work, env)
    # Isolate the persistent publishing clone per test — without this the
    # helper would write to the real ${HOME}/.cache location.
    env["C13_DATA_CLONE_DIR"] = str(tmp_path / "publish-clone")
    return work, env


LIB = REPO / "automation" / "launchd" / "lib_c13_data_push.sh"


def _utc_today() -> str:
    return datetime.datetime.now(datetime.UTC).date().strftime("%Y-%m-%d")


def test_helper_publishes_to_data_branch_without_touching_current_branch(tmp_path):
    """push_to_data_branch must land the artefact on data/phase-a-audit and
    leave the primary tree's checked-out (feature) branch untouched."""
    work, env = _data_branch_sandbox(tmp_path)
    # Stand on an unrelated feature branch — the exact scenario the old
    # ``git push origin HEAD`` pattern corrupted.
    _run(["git", "checkout", "-q", "-b", "feature/my-work"], work, env)
    head_before = _run(["git", "rev-parse", "HEAD"], work, env).stdout.strip()

    (work / "cache" / "wsh").mkdir(parents=True)
    (work / "cache" / "wsh" / "20260427.jsonl").write_text('{"x":1}\n')

    driver = work / "driver.sh"
    driver.write_text(textwrap.dedent(f"""
    set -euo pipefail
    cd "{work}"
    source "{LIB}"
    push_to_data_branch "snapshot 20260427" "cache/wsh/.push_status" \\
        "cache/wsh/20260427.jsonl"
    """))
    result = _run(["bash", str(driver)], work, env)
    assert result.returncode == 0, result.stderr

    # Marker records a successful push.
    marker = (work / "cache" / "wsh" / ".push_status").read_text()
    assert marker.startswith("ok:pushed"), marker

    # Primary tree is still on the feature branch at the same commit.
    assert _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], work, env).stdout.strip() == "feature/my-work"
    assert _run(["git", "rev-parse", "HEAD"], work, env).stdout.strip() == head_before

    # The artefact really landed on origin/data/phase-a-audit.
    _run(["git", "fetch", "-q", "origin", "data/phase-a-audit"], work, env)
    listed = _run(
        ["git", "ls-tree", "-r", "--name-only", "origin/data/phase-a-audit"],
        work, env,
    ).stdout
    assert "cache/wsh/20260427.jsonl" in listed, listed


def test_helper_marks_degraded_when_no_files(tmp_path):
    """With zero artefact paths the helper must fail loud (return 1) and
    write a ``degraded:no-files`` marker rather than push an empty commit."""
    work, env = _data_branch_sandbox(tmp_path)
    driver = work / "driver.sh"
    driver.write_text(textwrap.dedent(f"""
    set -uo pipefail
    cd "{work}"
    source "{LIB}"
    push_to_data_branch "empty" "cache/.push_status"
    echo "rc=$?"
    """))
    (work / "cache").mkdir(exist_ok=True)
    result = _run(["bash", str(driver)], work, env)
    assert "rc=1" in result.stdout, result.stdout + result.stderr
    assert (work / "cache" / ".push_status").read_text().startswith("degraded:no-files")


def test_helper_selfheals_corrupted_publishing_clone(tmp_path):
    """A SIGKILL / power-loss can leave the persistent publishing clone in
    an unusable state (interrupted fetch, half-written objects). The lib
    must wipe and re-clone once instead of dying markerless."""
    work, env = _data_branch_sandbox(tmp_path)

    # Corrupt the publishing clone: valid directory, broken git internals.
    clone = tmp_path / "publish-clone"
    (clone / ".git").mkdir(parents=True)
    (clone / ".git" / "HEAD").write_text("garbage, not a ref\n")

    (work / "cache" / "wsh").mkdir(parents=True)
    (work / "cache" / "wsh" / "20260428.jsonl").write_text('{"x":2}\n')

    driver_sh = work / "driver_corrupt.sh"
    driver_sh.write_text(textwrap.dedent(f"""
    set -euo pipefail
    cd "{work}"
    source "{LIB}"
    push_to_data_branch "snapshot 20260428" "cache/wsh/.push_status_corrupt" \\
        "cache/wsh/20260428.jsonl"
    """))
    result = _run(["bash", str(driver_sh)], work, env)
    assert result.returncode == 0, result.stderr

    # A marker MUST have been written — no markerless death.
    marker_path = work / "cache" / "wsh" / ".push_status_corrupt"
    assert marker_path.exists(), "marker missing after corrupted-clone run"
    marker = marker_path.read_text()
    assert marker.startswith("ok:"), f"unexpected marker: {marker}"


def test_helper_publishes_despite_failing_primary_prepush_hook(tmp_path):
    """C13 revival regression pin (2026-07-06): the worktree-based publish
    shared the primary clone's client-side hooks, so the code repo's
    pre-push guard suite ran against every data publish and aborted it —
    the audit branch froze from 2026-06-12 onward. The dedicated publishing
    clone has no hooks installed, so a hook that would fail (or rewrite
    files) in the PRIMARY clone must not affect the data publish."""
    work, env = _data_branch_sandbox(tmp_path)

    hook = work / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho 'primary pre-push guard: refusing' >&2\nexit 1\n")
    hook.chmod(0o755)

    (work / "cache" / "wsh").mkdir(parents=True)
    (work / "cache" / "wsh" / "20260429.jsonl").write_text('{"x":3}\n')

    driver_sh = work / "driver_hook.sh"
    driver_sh.write_text(textwrap.dedent(f"""
    set -euo pipefail
    cd "{work}"
    source "{LIB}"
    push_to_data_branch "snapshot 20260429" "cache/wsh/.push_status_hook" \\
        "cache/wsh/20260429.jsonl"
    """))
    result = _run(["bash", str(driver_sh)], work, env)
    assert result.returncode == 0, result.stderr

    marker = (work / "cache" / "wsh" / ".push_status_hook").read_text()
    assert marker.startswith("ok:pushed"), marker

    # The artefact really landed despite the failing primary hook.
    _run(["git", "fetch", "-q", "origin", "data/phase-a-audit"], work, env)
    listed = _run(
        ["git", "ls-tree", "-r", "--name-only", "origin/data/phase-a-audit"],
        work, env,
    ).stdout
    assert "cache/wsh/20260429.jsonl" in listed, listed


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda p: p.name)
def test_driver_publishes_via_isolated_data_branch(driver):
    """Each data-producing cron driver must publish through the shared
    isolated-worktree helper and must NOT commit/push onto the primary
    tree's currently checked-out branch (the old Lane 7 failure mode)."""
    text = driver.read_text()
    assert "git push origin HEAD" not in text, (
        f"{driver.name} still contains 'git push origin HEAD' — Lane 7 fix reverted?"
    )
    assert 'git push origin "${CURRENT_BRANCH}"' not in text, (
        f"{driver.name} still pushes to the current branch — use push_to_data_branch"
    )
    assert 'case "${CURRENT_BRANCH}"' not in text, (
        f"{driver.name} still branches on CURRENT_BRANCH — use push_to_data_branch"
    )
    assert "lib_c13_data_push.sh" in text, (
        f"{driver.name} must source the shared data-branch push helper"
    )
    assert "push_to_data_branch" in text, (
        f"{driver.name} must publish via push_to_data_branch"
    )


def test_git_available():
    assert shutil.which("git"), "git CLI required for Lane 7 driver tests"


# ---------------------------------------------------------------------------
# Lane 7 (continued, 2026-04-28) — venv-realism guard.
# Sourcing a missing venv activate script under ``set -u`` produces a
# cryptic error. Each cron driver MUST surface a clear actionable
# message and exit non-zero so launchd marks the job red.
# ---------------------------------------------------------------------------

VENV_GUARD_DRIVERS = [
    REPO / "automation" / "launchd" / "run-c13-wsh.sh",
    REPO / "automation" / "launchd" / "run-c13-imbalance.sh",
    REPO / "automation" / "launchd" / "run-c13-phase-a.sh",
    REPO / "automation" / "launchd" / "run-c13-phase-a-export.sh",
    REPO / "automation" / "launchd" / "run-c13-reconcile.sh",
]


@pytest.mark.parametrize("driver", VENV_GUARD_DRIVERS, ids=lambda p: p.name)
def test_driver_has_venv_existence_guard(driver):
    text = driver.read_text()
    assert '[[ ! -f "${VENV}/bin/activate" ]]' in text, (
        f"{driver.name} must check venv activate exists before sourcing"
    )
    assert "set C13_VENV in plist" in text, (
        f"{driver.name} venv error message must mention C13_VENV"
    )


def test_venv_guard_snippet_aborts_with_clear_message(tmp_path):
    """Behavioural check: the guard idiom exits 1 with a useful stderr
    when the venv path doesn't exist."""
    script = tmp_path / "guard.sh"
    script.write_text(textwrap.dedent("""
    #!/usr/bin/env bash
    set -euo pipefail
    VENV="/nonexistent/venv"
    if [[ ! -f "${VENV}/bin/activate" ]]; then
        echo "cron: virtualenv activate script not found at ${VENV}/bin/activate (set C13_VENV in plist)" >&2
        exit 1
    fi
    source "${VENV}/bin/activate"
    """))
    result = _run(["bash", str(script)], tmp_path)
    assert result.returncode == 1
    assert "virtualenv activate script not found" in result.stderr
    assert "C13_VENV" in result.stderr


def test_audit_push_uses_worktree_not_branch_switch():
    """run-c13-audit-push.sh must publish through the shared isolated-worktree
    helper rather than the old branch-switch pattern that could leave the
    primary tree on the wrong branch.

    History: the legacy version used ``git pull --ff-only … || true`` +
    branch switch; PR #2660 replaced that with an INLINE worktree, which
    then silently drifted from the lib's R1/R4/R5 hardening (audit pass-3
    finding A1, 2026-06-10) — e.g. no stale-worktree prune, so a SIGKILL
    could kill the agent markerless.  The script now delegates to
    ``push_to_data_branch`` and must NOT re-grow its own inline
    ``git worktree add`` / ``git push`` pipeline."""
    script = REPO / "automation" / "launchd" / "run-c13-audit-push.sh"
    text = script.read_text()
    assert "git pull --ff-only origin data/phase-a-audit || true" not in text, (
        "audit-push must not swallow pull failures with '|| true'"
    )
    assert "push_to_data_branch" in text, (
        "audit-push must publish via the shared lib_c13_data_push.sh helper"
    )
    assert "git worktree add" not in text, (
        "audit-push must not duplicate the worktree pipeline inline — that "
        "copy drifts from the lib's hardening (audit pass-3 finding A1)"
    )


# ---------------------------------------------------------------------------
# F-001 (audit 2026-06-14) — preflight failures must emit a DEGRADED marker
# before exiting so machine-detectable monitoring can catch silent failures.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "driver,marker_subdir,marker_prefix",
    [
        (
            REPO / "automation" / "launchd" / "run-c13-imbalance.sh",
            "cache/imbalance",
            ".push_status_",
        ),
        (
            REPO / "automation" / "launchd" / "run-c13-wsh.sh",
            "cache/wsh",
            ".feed_status_",
        ),
    ],
    ids=["imbalance", "wsh"],
)
def test_driver_writes_degraded_marker_on_missing_venv(
    tmp_path, driver, marker_subdir, marker_prefix
):
    """When the venv activate script is absent the driver must write a
    ``degraded:preflight-error:*`` marker and exit 1 — no silent death."""
    today = _utc_today()
    # The script derives REPO from $0, so markers land in REPO/cache/...
    real_marker_dir = REPO / marker_subdir
    real_marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = real_marker_dir / f"{marker_prefix}{today}"
    marker_path.unlink(missing_ok=True)  # remove stale marker from a prior run

    try:
        result = subprocess.run(
            ["bash", str(driver)],
            env={
                **os.environ,
                # Bypass the ET scheduling gate: this test exercises the
                # driver's venv/collector pipeline, not the gate.
                "C13_SKIP_ET_GATE": "1",
                "C13_VENV": str(tmp_path / "no-such-venv"),
                "C13_WATCHLIST": "/dev/null",
            },
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        assert result.returncode != 0, "driver should fail on missing venv"
        assert marker_path.exists(), (
            f"{driver.name}: no marker written to {marker_path} on missing-venv failure.\n"
            f"stdout: {result.stdout[:400]}\nstderr: {result.stderr[:400]}"
        )
        content = marker_path.read_text()
        assert content.startswith("degraded:preflight-error:"), (
            f"{driver.name}: marker content unexpected: {content!r}"
        )
    finally:
        marker_path.unlink(missing_ok=True)


@pytest.mark.parametrize(
    "driver,marker_subdir,marker_prefix",
    [
        (
            REPO / "automation" / "launchd" / "run-c13-imbalance.sh",
            "cache/imbalance",
            ".push_status_",
        ),
        (
            REPO / "automation" / "launchd" / "run-c13-wsh.sh",
            "cache/wsh",
            ".feed_status_",
        ),
    ],
    ids=["imbalance", "wsh"],
)
def test_driver_writes_degraded_marker_on_missing_python(
    tmp_path, driver, marker_subdir, marker_prefix
):
    """When the venv python binary is missing the driver must write a
    ``degraded:preflight-error:*`` marker and exit 1."""
    today = _utc_today()

    # Create a venv with an activate script but NO python binary.
    fake_venv = tmp_path / "fake-venv"
    bin_dir = fake_venv / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("# fake activate\n")
    # Deliberately do NOT create bin/python.

    real_marker_dir = REPO / marker_subdir
    real_marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = real_marker_dir / f"{marker_prefix}{today}"
    marker_path.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            ["bash", str(driver)],
            env={
                **os.environ,
                # Bypass the ET scheduling gate: this test exercises the
                # driver's venv/collector pipeline, not the gate.
                "C13_SKIP_ET_GATE": "1",
                "C13_VENV": str(fake_venv),
                "C13_WATCHLIST": "/dev/null",
            },
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        assert result.returncode != 0, "driver should fail on missing python"
        assert marker_path.exists(), (
            f"{driver.name}: no marker written to {marker_path} on missing-python failure.\n"
            f"stdout: {result.stdout[:400]}\nstderr: {result.stderr[:400]}"
        )
        content = marker_path.read_text()
        assert content.startswith("degraded:preflight-error:"), (
            f"{driver.name}: marker content unexpected: {content!r}"
        )
    finally:
        marker_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# SA-02/SA-03 (audit 2026-06-14) — application-level failures (post-preflight)
# must also emit a DEGRADED/degraded marker before exiting.
# ---------------------------------------------------------------------------


def test_imbalance_sh_writes_degraded_marker_on_collector_failure(tmp_path):
    """When collect_opening_imbalances exits non-zero run-c13-imbalance.sh
    must write a ``degraded:collector-error:*`` marker and exit 1.

    SA-03 regression guard (audit 2026-06-14).
    """
    today = _utc_today()

    # Create a fake venv: activate script present, python binary present but
    # always exits 1 (simulates collector failure after successful preflight).
    fake_venv = tmp_path / "venv"
    bin_dir = fake_venv / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("# fake activate\n")
    fake_python = bin_dir / "python"
    fake_python.write_text("#!/bin/bash\nexit 1\n")
    fake_python.chmod(0o755)

    real_marker_dir = REPO / "cache" / "imbalance"
    real_marker_dir.mkdir(parents=True, exist_ok=True)
    marker_path = real_marker_dir / f".push_status_{today}"
    marker_path.unlink(missing_ok=True)

    try:
        result = subprocess.run(
            ["bash", str(REPO / "automation" / "launchd" / "run-c13-imbalance.sh")],
            env={
                **os.environ,
                # Bypass the ET scheduling gate: this test exercises the
                # driver's venv/collector pipeline, not the gate.
                "C13_SKIP_ET_GATE": "1",
                "C13_VENV": str(fake_venv),
                "C13_WATCHLIST": "/dev/null",
            },
            capture_output=True,
            text=True,
            cwd=str(REPO),
        )
        assert result.returncode != 0, (
            "run-c13-imbalance.sh should fail when collector exits non-zero"
        )
        assert marker_path.exists(), (
            "run-c13-imbalance.sh: no degraded marker written on collector failure.\n"
            f"stdout: {result.stdout[:400]}\nstderr: {result.stderr[:400]}"
        )
        content = marker_path.read_text()
        assert content.startswith("degraded:collector-error:"), (
            f"run-c13-imbalance.sh: unexpected marker content: {content!r}"
        )
    finally:
        marker_path.unlink(missing_ok=True)


def test_phase_a_sh_incubation_failure_path_writes_degraded_marker() -> None:
    """Static guard: run-c13-phase-a.sh must wrap run_smc_live_incubation
    in a catchable ``if``/``else`` shell branch and call
    ``_write_marker "DEGRADED"`` on failure.

    SA-02 regression guard (audit 2026-06-14).
    The subprocess equivalent is impractical (requires a multi-step fake
    venv that passes build_phase_a_inputs but fails the runner), so we
    enforce the invariant via source inspection instead.
    """
    text = (REPO / "automation" / "launchd" / "run-c13-phase-a.sh").read_text()
    assert (
        'if ! "${PY}" -m scripts.run_smc_live_incubation' in text
        or 'if "${PY}" -m scripts.run_smc_live_incubation' in text
        # cbcb6195: refactored to capture exit-code so the logged value is
        # accurate; pattern is: run cmd, then _run_exit=$?, then if-check.
        or ('_run_exit=$?' in text and 'if [ "${_run_exit}" -ne 0 ]' in text)
    ), (
        "run-c13-phase-a.sh: run_smc_live_incubation must be wrapped in "
        "a catchable shell branch so a non-zero exit can be caught — "
        "SA-02 fix missing."
    )
    assert '_write_marker "DEGRADED" "incubation-failed:' in text, (
        "run-c13-phase-a.sh: DEGRADED marker write missing for incubation "
        "failure path — SA-02 fix missing."
    )
    # Sanity: the SUCCESS marker must still be present on the happy path.
    assert '_write_marker "SUCCESS" "incubation-complete:' in text, (
        "run-c13-phase-a.sh: SUCCESS marker write on happy path not found."
    )
