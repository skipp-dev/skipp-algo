"""Structural pin for ``.github/workflows/ci.yml`` — Bundle D-2.

Background
==========

``ci.yml``'s ``validate`` job is bound to the ``validate`` required-status
check on the main branch (see ``branch-protection-required-checks-audit-2026-05-29.md``).
Renames or accidental drops of the load-bearing structure (job key, runner
selector, heavy-step gate, pytest invocations, concurrency policy, etc.)
would silently bypass the required check by mutating the contract that
GitHub matches by name.

PR #2427 already covered the *job rename* failure mode for
``regime-stratification-validation.yml`` (renamed to ``regime-validate``);
this file extends the same defensive shape-check to ``ci.yml`` so the
required-check binding never silently rots.

Failure semantics: any assertion failure here means the workflow has been
restructured in a way that may break branch-protection enforcement OR the
runner-policy contract. The fix is either to roll back the structural
change OR to update both this pin AND the branch-protection configuration
(``gh api repos/:owner/:repo/branches/main/protection``) in the same PR.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


@pytest.fixture(scope="module")
def ci_doc() -> dict:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert isinstance(data, dict), "ci.yml must parse as a mapping"
    return data


@pytest.fixture(scope="module")
def ci_text() -> str:
    return CI_WORKFLOW.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def validate_job(ci_doc: dict) -> dict:
    jobs = ci_doc.get("jobs")
    assert isinstance(jobs, dict) and "validate" in jobs, (
        "ci.yml MUST keep job key `validate` — branch-protection requires it by name."
    )
    job = jobs["validate"]
    assert isinstance(job, dict)
    return job


# ─────────────────────────────────────────────────────────────────────
# Triggers
# ─────────────────────────────────────────────────────────────────────


def test_validate_job_key_present(validate_job: dict) -> None:
    """The `validate` key is the load-bearing required-check anchor."""
    assert validate_job, "validate job body must not be empty"


def test_triggers_include_push_pull_workflow_dispatch(ci_doc: dict) -> None:
    # PyYAML parses bare `on:` as the boolean True. Tolerate both shapes.
    on_block = ci_doc.get("on") if "on" in ci_doc else ci_doc.get(True)
    assert isinstance(on_block, dict), "ci.yml MUST declare `on:` as a mapping"
    for trig in ("push", "pull_request", "workflow_dispatch"):
        assert trig in on_block, (
            f"ci.yml MUST trigger on `{trig}` — required for the validate "
            f"required-check to ever run on the relevant event."
        )


# ─────────────────────────────────────────────────────────────────────
# Concurrency / runner policy
# ─────────────────────────────────────────────────────────────────────


def test_concurrency_group_is_workflow_and_ref(ci_doc: dict) -> None:
    concurrency = ci_doc.get("concurrency")
    assert isinstance(concurrency, dict), "ci.yml MUST declare a `concurrency:` block"
    group = concurrency.get("group")
    assert isinstance(group, str)
    assert "${{ github.workflow }}" in group and "${{ github.ref }}" in group, (
        "concurrency.group MUST anchor on github.workflow + github.ref so "
        "main-branch runs never cancel each other and PR refs are isolated."
    )


def test_concurrency_cancels_only_pull_requests(ci_doc: dict) -> None:
    concurrency = ci_doc.get("concurrency")
    assert isinstance(concurrency, dict)
    cancel = concurrency.get("cancel-in-progress")
    assert isinstance(cancel, str), (
        "cancel-in-progress MUST be a conditional expression (string), not a bare bool — "
        "main-branch and cron runs must NEVER cancel each other (loses audit trail)."
    )
    assert "pull_request" in cancel, (
        "cancel-in-progress condition MUST gate on event_name == 'pull_request' so "
        "only PR refs cancel siblings; main pushes and dispatches run to completion."
    )


def test_runs_on_uses_hosted_runner_variable(validate_job: dict) -> None:
    runs_on = validate_job.get("runs-on")
    assert isinstance(runs_on, str)
    assert "vars.SMC_GH_HOSTED_RUNNER" in runs_on, (
        "validate.runs-on MUST reference vars.SMC_GH_HOSTED_RUNNER per the "
        "2026-05-20 runner policy (CI is GitHub-hosted by default; self-hosted "
        "is reserved for workflows with explicit local-resource needs)."
    )
    assert "self-hosted" not in runs_on, (
        "validate.runs-on MUST NOT route to self-hosted runners — CI policy "
        "requires the hosted lane for audit reproducibility."
    )


def test_timeout_minutes_45(validate_job: dict) -> None:
    timeout = validate_job.get("timeout-minutes")
    assert timeout == 45, (
        "validate.timeout-minutes MUST stay at 45 — the full pytest suite "
        "runs ~30-40 min on hosted runners and we want a hard cap on hangs "
        "rather than a runaway 6 h GHA default."
    )


# ─────────────────────────────────────────────────────────────────────
# Bot-PR short-circuit gate
# ─────────────────────────────────────────────────────────────────────


def test_bot_pr_short_circuit_gate_present(validate_job: dict) -> None:
    steps = validate_job.get("steps")
    assert isinstance(steps, list) and steps, "validate MUST declare steps"
    gate = next(
        (s for s in steps if isinstance(s, dict) and s.get("id") == "gate"),
        None,
    )
    assert gate is not None, (
        "validate MUST contain a step with id=`gate` that sets run_heavy=false "
        "for bot data-only PRs (`head_ref == bot/*`); without it every bot "
        "artifact PR re-runs the full ~40 min suite for zero signal."
    )
    run = gate.get("run") or ""
    assert "bot/*" in run, "gate step MUST match the `bot/*` head_ref pattern"
    assert "run_heavy=false" in run, "gate step MUST emit run_heavy=false on match"
    assert "run_heavy=true" in run, "gate step MUST emit run_heavy=true otherwise"
    assert 'github.event_name' in run and "pull_request" in run, (
        "gate step MUST scope the bot-PR short-circuit to pull_request events only"
    )


# ─────────────────────────────────────────────────────────────────────
# Pytest invocation lanes
# ─────────────────────────────────────────────────────────────────────


def test_pytest_lanes_pinned(validate_job: dict) -> None:
    steps = validate_job.get("steps") or []
    pytest_runs = [
        (s.get("name", ""), s.get("run", ""))
        for s in steps
        if isinstance(s, dict) and "python -m pytest" in (s.get("run") or "")
    ]
    assert len(pytest_runs) >= 2, (
        "validate MUST keep at least two pytest invocation lanes "
        "(PR-no-coverage + main-with-coverage); a testmon fast lane is optional."
    )
    # The full-suite lanes are duration-balanced and sharded across the matrix
    # (pytest-split). `--dist=loadscope` keeps a module's tests on a single
    # xdist worker so module-level caches stay warm within a shard.
    fast_lanes = [
        run
        for _, run in pytest_runs
        if "-n auto" in run
        and "--dist=loadscope" in run
        and "--splits 4" in run
        and "--group" in run
    ]
    assert len(fast_lanes) >= 2, (
        "Both the PR-no-coverage and main-with-coverage pytest lanes MUST use "
        "`-n auto --dist=loadscope --splits 4 --group ${{ matrix.group }}` so the "
        "full suite is sharded across the matrix; without it the validate job "
        "exceeds its 45-min budget on full suites."
    )
    for run in fast_lanes:
        assert "--maxfail=1" in run, (
            "Parallel pytest lanes MUST stop on first failure (`--maxfail=1`); "
            "otherwise a single broken test consumes the full runner budget."
        )
    coverage_lanes = [run for _, run in pytest_runs if "--cov" in run]
    assert len(coverage_lanes) >= 1, (
        "validate MUST keep at least one `--cov` lane (the main-push lane) "
        "so coverage reporting on `main` does not silently disappear."
    )


def test_main_coverage_lane_is_gated_on_main_push(validate_job: dict) -> None:
    steps = validate_job.get("steps") or []
    coverage_step = next(
        (
            s for s in steps
            if isinstance(s, dict)
            and "--cov" in (s.get("run") or "")
            and "python -m pytest" in (s.get("run") or "")
        ),
        None,
    )
    assert coverage_step is not None, "Could not locate the main-push coverage pytest step"
    cond = coverage_step.get("if") or ""
    assert "github.ref" in cond and "refs/heads/main" in cond, (
        "Coverage pytest lane MUST be gated to `github.ref == 'refs/heads/main'` "
        "so non-main pushes do not pay the coverage-instrumentation tax."
    )
    assert "github.event_name" in cond and "push" in cond, (
        "Coverage pytest lane MUST be gated to push events on main "
        "(not pull_request, not workflow_dispatch)."
    )


# ─────────────────────────────────────────────────────────────────────
# Permissions
# ─────────────────────────────────────────────────────────────────────


def test_permissions_contents_read_only(ci_doc: dict) -> None:
    perms = ci_doc.get("permissions")
    assert isinstance(perms, dict), (
        "ci.yml MUST declare top-level `permissions:` (least-privilege; not the "
        "default GITHUB_TOKEN write scope)."
    )
    assert perms.get("contents") == "read", (
        "ci.yml top-level permissions.contents MUST be `read` — validate is "
        "read-only and elevating to write expands the blast radius of any "
        "compromised action without justification."
    )
