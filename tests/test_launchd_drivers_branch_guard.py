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

import os
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# launchd is macOS-only; the driver shell scripts under automation/launchd/
# are LaunchAgents and only run on Darwin. Skip on Linux/Windows so the suite
# is green on every developer machine and on Linux CI runners (#2244).
pytestmark = pytest.mark.skipif(
    sys.platform != "darwin",
    reason="launchd drivers are macOS-only (see #2244)",
)

REPO = Path(__file__).resolve().parents[1]
DRIVERS = [
    REPO / "automation" / "launchd" / "run-c13-wsh.sh",
    REPO / "automation" / "launchd" / "run-c13-imbalance.sh",
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
    return work, env


LIB = REPO / "automation" / "launchd" / "lib_c13_data_push.sh"


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


def test_helper_recovers_from_stale_worktree_registration(tmp_path):
    """R1 regression: a SIGKILL / power-loss can leave a stale worktree
    registration (.git/worktrees/<name>) whose directory no longer exists.
    ``git worktree add`` used to fail on such registrations, killing the
    agent *before* any marker was written.  The lib must prune stale entries
    first so the push still succeeds and the marker is always written."""
    work, env = _data_branch_sandbox(tmp_path)

    # Simulate a stale registration: add a worktree, then rm -rf the dir
    # WITHOUT calling ``git worktree remove`` (the SIGKILL scenario).
    stale_dir = tmp_path / "stale-wt"
    _run(
        ["git", "worktree", "add", "--detach", str(stale_dir),
         "origin/data/phase-a-audit"],
        work, env,
    )
    shutil.rmtree(stale_dir)  # path gone, .git/worktrees entry remains

    # Verify the stale entry is actually present (pre-condition).
    wt_list = _run(["git", "worktree", "list"], work, env).stdout
    assert "stale" in wt_list.lower() or str(stale_dir) in wt_list, (
        "test setup failed: no stale worktree entry found"
    )

    (work / "cache" / "wsh").mkdir(parents=True)
    (work / "cache" / "wsh" / "20260428.jsonl").write_text('{"x":2}\n')

    driver_sh = work / "driver_stale.sh"
    driver_sh.write_text(textwrap.dedent(f"""
    set -euo pipefail
    cd "{work}"
    source "{LIB}"
    push_to_data_branch "snapshot 20260428" "cache/wsh/.push_status_stale" \\
        "cache/wsh/20260428.jsonl"
    """))
    result = _run(["bash", str(driver_sh)], work, env)
    assert result.returncode == 0, result.stderr

    # A marker MUST have been written — no markerless death.
    marker_path = work / "cache" / "wsh" / ".push_status_stale"
    assert marker_path.exists(), "marker missing after stale-worktree run"
    marker = marker_path.read_text()
    assert marker.startswith("ok:"), f"unexpected marker: {marker}"


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
    """run-c13-audit-push.sh must use the isolated worktree approach (merged
    via PR #2660 / origin/main) rather than the old branch-switch pattern
    that could leave the primary tree on the wrong branch.

    Previously this test checked for a ``git pull --ff-only … || true``
    guard, which was relevant to the legacy branch-switch version.  After
    PR #2660 the script no longer calls ``git pull`` at all — it builds a
    throwaway worktree keyed on ``origin/data/phase-a-audit``.  Asserting
    the worktree pattern is present is the semantically equivalent guard."""
    script = REPO / "automation" / "launchd" / "run-c13-audit-push.sh"
    text = script.read_text()
    assert "git pull --ff-only origin data/phase-a-audit || true" not in text, (
        "audit-push must not swallow pull failures with '|| true'"
    )
    assert "git worktree add" in text, (
        "audit-push must use the isolated-worktree pattern (PR #2660), not git pull"
    )
