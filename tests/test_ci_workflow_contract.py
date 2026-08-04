"""Contract pin: ``ci.yml`` workflow (Bundle D-2 from issue #2422).

Pins the structural invariants of the main CI workflow so silent drift
of the trigger surface, the event gate, runner policy, or pytest lane
selection is caught at validate-time.

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


def test_single_validate_job_with_event_gate() -> None:
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
    assert gate_step is not None, "validate gate step missing"
    assert "Pull request CI is status-only" in gate_step["run"]
    assert "Non-main push CI is status-only" in gate_step["run"]
    assert "workflow_dispatch" in gate_step["run"]
    assert "REF_NAME" in gate_step["run"]
    assert "run_heavy=false" in gate_step["run"]
    # The gate's LAST word must be the expensive one. Anything the arms above do
    # not claim — an event this workflow does not declare today, or a trigger
    # added later — has to run the full suite rather than skip it in silence.
    assert gate_step["run"].rstrip().endswith(
        'echo "run_heavy=true" >> "$GITHUB_OUTPUT"'
    ), (
        "the gate no longer falls through to run_heavy=true. An unhandled event "
        "would then skip the repo's only full-suite run without saying so."
    )


# What used to stand here: three assertions pinning a ``bot/*`` path allow-list
# in this gate -- ``bot/*``, ``.filename``, ``run_heavy=$heavy``. That block was
# UNREACHABLE and was removed on 2026-08-04. ci.yml triggers on push,
# pull_request and workflow_dispatch only, and each exits in one of the four arms
# above; measured by executing the block for all three, plus a hypothetical
# merge_group, before and after removal -- identical verdicts in all seven cases.
#
# Those assertions were worse than dead weight: they read as "ci.yml path-checks
# bot PRs", and a maintainer could reasonably conclude bot PRs get a narrower
# lane here. They never did. In ci.yml ALL pull requests are status-only, bot or
# not, and the file-level protection is the outcome witnesses in
# tests/test_fast_gates_silent_skip_coverage.py, which execute this gate rather
# than reading it.


def test_runs_on_uses_github_hosted_var() -> None:
    job = _load()["jobs"]["validate"]
    assert "SMC_GH_HOSTED_RUNNER" in job["runs-on"], (
        "runner policy 2026-05-20: CI must default to GitHub-hosted via "
        "vars.SMC_GH_HOSTED_RUNNER (fallback ubuntu-latest)"
    )
    assert "ubuntu-latest" in job["runs-on"], "fallback ubuntu-latest required"


def test_two_pytest_invocation_lanes_present() -> None:
    """Coverage-on-main and no-coverage PR/non-main are distinct gates."""
    steps = _load()["jobs"]["validate"]["steps"]
    runs = [s.get("run", "") for s in steps if "pytest" in s.get("run", "")]
    assert len(runs) == 2, (
        f"expected exactly 2 pytest lanes (no-cov, with-cov); got {len(runs)}"
    )
    joined = "\n".join(runs)
    assert "--testmon" not in joined, "testmon must stay out of merge-critical validate lanes"
    assert "--cov" in joined and "--cov-report=term-missing:skip-covered" in joined, (
        "coverage lane removed or report format changed"
    )
    assert joined.count("-n auto --dist=loadscope --splits 4 --group") == 1, (
        "xdist parallelism should remain only on the main coverage lane"
    )
    assert joined.count("--splits 4 --group") == 2, "pytest-split sharding dropped from validate lanes"


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
