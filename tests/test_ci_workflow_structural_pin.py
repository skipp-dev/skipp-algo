"""Structural pin for ``.github/workflows/ci.yml`` — Bundle D-2.

Background
==========

This file used to open by asserting that ``ci.yml``'s ``validate`` job is
bound to a ``validate`` required-status check on main, and derived its whole
purpose from that binding. **That was never true here.** Measured 2026-08-04
against the live configuration rather than against the 2026-05-29 audit
document it cited::

    gh api repos/skipp-dev/skipp-algo/rulesets/15245308 \
      --jq '.rules[]|select(.type=="required_status_checks")
            |.parameters.required_status_checks[].context'
    fast-gates

One context, and it is not ``validate``. Protection lives in a **ruleset**,
not in classic branch protection — the classic endpoint this docstring told
readers to consult answers 404 (see ``docs/adr/0011-*``: ``fast-gates`` is the
sole required check by design).

What this pin is actually worth, then, is narrower but real: ``ci.yml`` is
where the repo's **only full-suite execution** lives, and it runs on main
pushes and manual dispatch. A rename or accidental drop of the load-bearing
structure (job key, runner selector, heavy-step gate, pytest invocations,
concurrency policy) would stop that suite from running without turning any
PR red — nothing gates on it. The shape-check is the thing that notices.

PR #2427 covered the same *job rename* failure mode for
``regime-stratification-validation.yml``.

Failure semantics: an assertion failure here means the workflow was
restructured in a way that may break the runner-policy contract or silence
the full suite. Either roll back the structural change, or update this pin
in the same PR — and if the change is meant to alter what gates merges, the
ruleset above has to change with it.
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
# Event gate (which events run the heavy suite)
# ─────────────────────────────────────────────────────────────────────


def test_event_gate_present_and_fails_closed(validate_job: dict) -> None:
    steps = validate_job.get("steps")
    assert isinstance(steps, list) and steps, "validate MUST declare steps"
    gate = next(
        (s for s in steps if isinstance(s, dict) and s.get("id") == "gate"),
        None,
    )
    assert gate is not None, (
        "validate MUST contain a step with id=`gate` that decides run_heavy."
    )
    run = gate.get("run") or ""
    # 2026-08-20: pull requests run the slow complement (Operator-Entscheidung,
    # ADR-0012 Option B + Operator-Punkt 1). Die vorherige Zusicherung hier
    # begruendete den Kurzschluss mit "GitHub merge-ref validate(4) zombies" --
    # gemessen steht dieser Satz GENAU EINMAL im Baum (22 "zombie"-Treffer
    # gesamt, 9 davon C13 als Positivkontrolle), ohne ADR, Issue oder Commit
    # dahinter; die Zeile stammt aus dem Wurzel-Commit der Historie. Die Sorge
    # wird nicht verworfen, sondern auf ihre zwei Gegenmittel gepinnt: die
    # PR-Concurrency bricht Vorlaeufer ab, und der Job hat ein Zeitlimit. Ein
    # haengender Lauf kann sich damit nicht ueber PR-Updates hinweg stapeln.
    assert "Pull request runs the slow complement" in run, (
        "pull_request validate must state which lane it runs; a required check "
        "that silently short-circuits is protection in appearance only."
    )
    assert "Non-main push CI is status-only" in run, (
        "non-main push validate runs MUST stay status-only; otherwise PR "
        "branches can inherit stuck validate(4) push checks."
    )
    assert "workflow_dispatch" in run and "Manual CI dispatch runs heavy validation" in run, (
        "manual workflow_dispatch MUST remain available for explicit heavy branch validation."
    )
    assert "REF_NAME" in run and "main" in run, (
        "gate step MUST distinguish main pushes from PR branch pushes via ref_name."
    )
    assert "run_heavy=false" in run, "pull_request gate MUST emit run_heavy=false"
    # The gate MUST fail closed: its last word is run_heavy=true, so an event no
    # arm above claims runs the full suite instead of skipping it silently.
    #
    # Until 2026-08-04 this spot also pinned `bot/*`, `.filename` and
    # `run_heavy=$heavy` -- a path allow-list that was UNREACHABLE under ci.yml's
    # own triggers (push / pull_request / workflow_dispatch all exit in the four
    # arms above; measured before and after removal, identical verdicts). Pinning
    # it made this file claim ci.yml path-checks bot PRs. It does not: here every
    # pull request is status-only. What the gate actually decides is witnessed by
    # execution in tests/test_fast_gates_silent_skip_coverage.py.
    assert run.rstrip().endswith('echo "run_heavy=true" >> "$GITHUB_OUTPUT"'), (
        "gate step MUST fail closed to run_heavy=true as its final fallback"
    )
    assert 'EVENT_NAME' in run and "pull_request" in run, (
        "gate step MUST branch on pull_request events explicitly"
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
    # (pytest-split). The PR/non-main lane intentionally stays serial inside
    # each shard because xdist has produced validate(4) runner hangs there.
    split_lanes = [
        run
        for _, run in pytest_runs
        if "--splits 4" in run and "--group" in run
    ]
    assert len(split_lanes) >= 2, (
        "Both the PR-no-coverage and main-with-coverage pytest lanes MUST use "
        "`--splits 4 --group ${{ matrix.group }}` so the full suite is sharded "
        "across the matrix; without it the validate job exceeds its 45-min budget."
    )
    xdist_lanes = [
        run
        for _, run in pytest_runs
        if "-n auto" in run
        and "--dist=loadscope" in run
        and "--splits 4" in run
        and "--group" in run
    ]
    assert len(xdist_lanes) == 1, (
        "Only the main coverage lane should use xdist; PR/non-main stays serial "
        "inside each pytest-split shard for validate(4) stability."
    )
    for run in split_lanes:
        assert "--maxfail=1" in run, (
            "Pytest validate lanes MUST stop on first failure (`--maxfail=1`); "
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


def test_main_coverage_lane_disables_per_shard_fail_under(validate_job: dict) -> None:
    """Regression pin: the main-push coverage lane MUST NOT enforce the global
    ``fail_under`` threshold per shard.

    The lane runs ``--cov`` on each of four ``pytest-split`` shards, but a
    single 1/4 shard only exercises a fraction of the codebase (~48 %). With
    ``pyproject``'s ``fail_under=85`` left active, ``pytest-cov`` enforces that
    threshold *per shard*, which can never pass and failed every main-push CI
    run for days. ``--cov-fail-under=0`` neutralises the per-shard gate while
    keeping coverage as a non-blocking audit artefact (merge gating is the
    required ``fast-gates`` check, not this lane). This test ensures the fix
    cannot silently regress.
    """
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
    run = coverage_step.get("run") or ""
    assert "--cov-fail-under=0" in run, (
        "The main-push coverage lane MUST pass `--cov-fail-under=0` to override "
        "pyproject's `fail_under=85`. Each pytest-split shard measures only its "
        "own slice (~48 % of the codebase), so a per-shard 85 % gate is "
        "mathematically impossible and breaks every main-push CI run. Coverage "
        "here is a non-blocking audit artefact; gating is handled by fast-gates."
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
