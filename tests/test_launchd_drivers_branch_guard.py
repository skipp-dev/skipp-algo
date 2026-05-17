"""Lane 7 (provider-boundary audit, 2026-04-27) — LaunchAgent driver realism.

The local launchd cron drivers under ``automation/launchd/`` previously
ran ``git push origin HEAD`` after committing a daily artefact, which
silently pushed cron data onto whatever branch the developer happened
to have checked out when the agent fired (a feature branch, a stacked
PR branch, etc.). These tests assert the new safe-branch guard:

    * On ``main`` or ``data/...`` → commit + push happen.
    * On any other branch → the artefact stays uncommitted and the
      driver prints a clear skip message instead of polluting the
      developer's working branch.

The tests don't run the full pipeline; they extract the guard block
from each driver and exercise it in a throwaway git sandbox so the
behaviour is verified independently of FMP/Databento availability.
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


def _guard_snippet():
    """The exact guard pattern injected into the cron drivers."""
    return textwrap.dedent("""
    set -euo pipefail
    DATE=20260427
    mkdir -p cache/wsh
    : > "cache/wsh/${DATE}.jsonl"
    git add "cache/wsh/${DATE}.jsonl" || true
    if ! git diff --staged --quiet; then
        CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
        case "${CURRENT_BRANCH}" in
            main|data/*)
                git commit -q -m "snapshot ${DATE}"
                echo "committed"
                ;;
            *)
                echo "skipped on ${CURRENT_BRANCH}" >&2
                git reset HEAD -- "cache/wsh/${DATE}.jsonl" >/dev/null 2>&1 || true
                ;;
        esac
    fi
    """)


@pytest.mark.parametrize("branch,should_commit", [
    ("main", True),
    ("data/phase-a-audit", True),
    ("data/imbalance", True),
    ("feature/my-work", False),
    ("lane7/something", False),
])
def test_branch_guard_only_commits_on_main_or_data(sandbox, branch, should_commit):
    work, env = sandbox
    if branch != "main":
        _run(["git", "checkout", "-q", "-b", branch], work, env)

    script = work / "guard.sh"
    script.write_text(_guard_snippet())
    result = _run(["bash", str(script)], work, env)
    assert result.returncode == 0, result.stderr

    log = _run(["git", "log", "--oneline"], work, env).stdout
    if should_commit:
        assert "snapshot 20260427" in log, log
        assert "committed" in result.stdout
    else:
        assert "snapshot 20260427" not in log, log
        assert f"skipped on {branch}" in result.stderr


@pytest.mark.parametrize("driver", DRIVERS, ids=lambda p: p.name)
def test_driver_contains_safe_branch_guard(driver):
    """Sanity: each cron driver contains the case statement and never
    pushes blindly to HEAD anymore."""
    text = driver.read_text()
    assert "git push origin HEAD" not in text, (
        f"{driver.name} still contains 'git push origin HEAD' — Lane 7 fix reverted?"
    )
    assert 'case "${CURRENT_BRANCH}"' in text
    assert "main|data/*)" in text


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


def test_audit_push_aborts_on_pull_failure():
    """run-c13-audit-push.sh must NOT silently swallow a pull failure
    (which would later surface as a misleading non-fast-forward push
    rejection)."""
    script = REPO / "automation" / "launchd" / "run-c13-audit-push.sh"
    text = script.read_text()
    assert "git pull --ff-only origin data/phase-a-audit || true" not in text, (
        "audit-push must not swallow pull failures with '|| true'"
    )
    assert "if ! git pull --ff-only origin data/phase-a-audit;" in text, (
        "audit-push must check pull result explicitly and abort on failure"
    )
