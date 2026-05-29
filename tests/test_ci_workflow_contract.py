"""Contract pin: ``ci.yml`` workflow (Bundle D-2 from issue #2422).

Pins the structural invariants of the main CI workflow so silent drift
of the trigger surface, bot-PR short-circuit, runner policy, or pytest
lane selection is caught at validate-time.

Note: ``ci.yml`` is NOT a required status check on main (only
``fast-gates`` is — see ``smc-fast-pr-gates.yml``). It is the heavy
audit-trail lane. The invariants pinned here therefore protect the
audit-trail integrity rather than gate enforcement.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
_WF_PATH = _REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _load() -> dict:
    return yaml.safe_load(_WF_PATH.read_text(encoding="utf-8"))


def _on(data: dict) -> dict:
    # PyYAML parses bare ``on`` as boolean True.
    return data.get("on") or data.get(True)


def test_workflow_file_exists() -> None:
    assert _WF_PATH.is_file(), f"missing workflow: {_WF_PATH}"


def test_live_window_marker_any_trigger() -> None:
    head = _WF_PATH.read_text(encoding="utf-8").splitlines()[0]
    assert "live-window: any-trigger" in head, (
        "first-line live-window marker required by F-V6-F2.1"
    )


def test_triggers_pinned() -> None:
    on_block = _on(_load())
    assert set(on_block.keys()) == {"push", "pull_request", "workflow_dispatch"}, (
        "ci.yml trigger surface drifted; expected push + pull_request + workflow_dispatch"
    )
    assert on_block["push"]["branches"] == ["**"], "push must cover all branches"
    assert on_block["pull_request"]["branches"] == ["**"], "PR must cover all branches"
    paths_ignore = on_block["pull_request"].get("paths-ignore", [])
    assert "**/*.md" in paths_ignore and "docs/**" in paths_ignore, (
        "doc-only PR short-circuit must keep ignoring **/*.md and docs/** "
        "(F-V8-C5-A, 2026-05-07)"
    )


def test_concurrency_cancel_only_for_pr() -> None:
    data = _load()
    concurrency = data["concurrency"]
    assert concurrency["group"].startswith("ci-")
    assert "github.event_name == 'pull_request'" in concurrency["cancel-in-progress"], (
        "cancel-in-progress must remain PR-only; push runs are audit trail"
    )


def test_pythonunbuffered_env_pinned() -> None:
    data = _load()
    assert data["env"].get("PYTHONUNBUFFERED") == "1", (
        "F-V5-A2 (2026-05-01) requires PYTHONUNBUFFERED=1"
    )
    assert "PYTHONPATH" in data["env"]


def test_single_validate_job_with_bot_pr_gate() -> None:
    data = _load()
    assert list(data["jobs"].keys()) == ["validate"], (
        "ci.yml must expose exactly one job named ``validate`` "
        "(this name is also a status-check context candidate; see PR #2427)"
    )
    job = data["jobs"]["validate"]
    assert job["timeout-minutes"] == 45
    gate_step = next(
        (s for s in job["steps"] if s.get("id") == "gate"), None
    )
    assert gate_step is not None, "bot-PR short-circuit step ``gate`` missing"
    assert "bot/*" in gate_step["run"], (
        "bot-PR short-circuit must keep matching ``bot/*`` head refs"
    )
    assert "run_heavy=false" in gate_step["run"]
    assert "run_heavy=true" in gate_step["run"]


def test_runs_on_uses_github_hosted_var() -> None:
    job = _load()["jobs"]["validate"]
    assert "SMC_GH_HOSTED_RUNNER" in job["runs-on"], (
        "runner policy 2026-05-20: CI must default to GitHub-hosted via "
        "vars.SMC_GH_HOSTED_RUNNER (fallback ubuntu-latest)"
    )
    assert "ubuntu-latest" in job["runs-on"], "fallback ubuntu-latest required"


def test_three_pytest_invocation_lanes_present() -> None:
    """Coverage-on-main, testmon-fast-lane, no-coverage are 3 distinct gates."""
    steps = _load()["jobs"]["validate"]["steps"]
    runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert len(runs) == 3, (
        f"expected exactly 3 pytest lanes (testmon, no-cov, with-cov); got {len(runs)}"
    )
    joined = "\n".join(runs)
    assert "--testmon" in joined, "testmon fast lane removed"
    assert "--cov" in joined and "--cov-report=term-missing:skip-covered" in joined, (
        "coverage lane removed or report format changed"
    )
    assert joined.count("-n auto --dist=worksteal") == 2, (
        "xdist parallelism dropped from non-testmon lanes"
    )


def test_coverage_lane_gated_on_main_push_only() -> None:
    steps = _load()["jobs"]["validate"]["steps"]
    cov_step = next(
        s for s in steps if "--cov" in s.get("run", "")
    )
    cond = cov_step["if"]
    assert "github.event_name == 'push'" in cond
    assert "github.ref == 'refs/heads/main'" in cond, (
        "coverage must only run on main push; otherwise PR feedback loop slows"
    )
