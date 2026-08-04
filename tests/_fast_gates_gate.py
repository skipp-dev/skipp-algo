"""Run the fast-gates path-classification step instead of reading its text.

``smc-fast-pr-gates.yml``'s ``gate`` step decides two things for a ``bot/*``
PR: whether the heavy suite runs (``run_heavy``) and whether the R1-attested-
source guard runs (``run_pine_guard``). Both are decided in shell, and a test
that asserts on the shell's *source text* cannot tell "publishes the output"
from "publishes it as ``false`` forever".

That is not hypothetical. Measured 2026-08-04, twice on this one step:

* deleting ``*.pine|pine/generated/*) pine=true ;;`` left all fourteen tests in
  ``test_check_r1_attested_sources.py`` green while the R1 guard went blind
  again — the defect #4376 had just fixed, reintroduced under a passing suite
  (closed by #4377);
* deleting the ``*)`` arm that sets ``heavy=true`` left 2198 tests green under
  ``-k "fast_gates or workflow or r1_attested"``, and 202 green across the 14
  test files that name this workflow — while a ``bot/*`` PR touching
  ``services/*.py`` would merge without the heavy suite at all, verbatim the
  hole the step's own comment claims to have closed. (Two selections, two
  numbers, both measured; neither is "the whole suite".)

So execute the step. This module is the shared harness; the assertions live in
``test_fast_gates_silent_skip_coverage.py`` (the silent-skip contract) and in
``test_check_r1_attested_sources.py`` (the R1 half).

What it does NOT cover: GitHub's ``if:`` expression evaluation. That is no
longer for want of a local equivalent — ``_evaluate_condition`` in
``tests/test_fast_gates_attested_pine_coverage.py`` evaluates a step's ``if:``
against real gate outputs, and ``tests/test_ci_workflow_contract.py`` pins
ci.yml's two lane conditions by normalised equality. Both live outside this
module. If a third consumer appears, lift the evaluator in here rather than
copying it: a private helper imported across test modules is exactly what broke
``main`` on 2026-08-04, when #4383 moved ``_run_gate`` out from under #4385.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "smc-fast-pr-gates.yml"

# The shell GitHub really gives this block. smc-fast-pr-gates.yml declares
# `defaults: run: shell: bash`, which Actions expands to
# `bash --noprofile --norc -eo pipefail {0}` -- NOT the implicit default
# (`bash -e {0}`, no pipefail). test_the_harness_matches_the_declared_shell pins
# BOTH sides -- the workflow's declaration and this tuple -- because pinning only
# the declaration leaves the tuple free to drift, and a review measured exactly
# that: gutting it to ("bash", "-e") killed no test.
#
# `bash` resolves through PATH, so locally this is the developer's bash (3.2 on
# stock macOS) while CI runs 5.x. Every construct in the block is 3.2-safe; the
# skew can only cause a local false alarm, never a green local run that fails CI.
SHELL = ("bash", "--noprofile", "--norc", "-e", "-o", "pipefail")

# The path-inspection branch is unreachable for anything else, and this is the
# branch shape #4371 actually used.
BOT_BRANCH = "bot/library-refresh-30861895594-1"


# Everything the harness feeds the step besides PATH and GITHUB_OUTPUT. Kept as
# a module constant so a test can compare it against the step's own `env:` block
# -- the step runs under `-e` but NOT `-u`, so a variable the workflow adds and
# this dict does not expands to "" in silence, and a shape like
# `[[ -n "$NEW_FLAG" ]]` would then classify differently here than in CI without
# anything going red.
HARNESS_ENV: dict[str, str] = {
    "EVENT_NAME": "pull_request",
    "HEAD_REF": BOT_BRANCH,
    "PR_NUMBER": "4371",
    "REPO": "skipp-dev/skipp-algo",
    "GH_TOKEN": "stub-token",
}


def gate_step() -> dict:
    """The whole ``gate`` step, read structurally out of the workflow.

    Loaded through the YAML rather than sliced out of the text, so indentation,
    comment and ordering churn cannot break it -- and a missing step id is a
    named failure rather than a silently empty script.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["fast-gates"]["steps"]:
        if step.get("id") == "gate":
            return dict(step)
    raise AssertionError("fast-gates has no step with id 'gate'")


def gate_run_block() -> str:
    """The ``gate`` step's shell."""
    return str(gate_step()["run"])


# --- ci.yml's own gate ------------------------------------------------------
#
# The same shape, one workflow over: `validate` has an `id: gate` step whose
# run_heavy output every later step hangs on -- including the full pytest run.
# Its contract is pinned in test_ci_workflow_contract.py by source text, and a
# mutation sweep on 2026-08-04 showed what that cannot see: flipping the
# main-push arm from `run_heavy=true` to `false` killed NO test, because the
# string `run_heavy=true` still appears in another arm. Deletions are caught,
# inversions are not.
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"

# Mirrors the `env:` block of that step, and nothing more. It once also carried
# HEAD_REF/PR_NUMBER/REPO/GH_TOKEN, for the bot-path arm #4396 removed as
# unreachable; keeping scaffolding named after deleted logic is how a harness
# starts describing a workflow that no longer exists.
CI_HARNESS_ENV: dict[str, str] = {
    "EVENT_NAME": "push",
    "REF_NAME": "main",
}


def ci_gate_step() -> dict:
    """The ``gate`` step of ci.yml's ``validate`` job."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["validate"]["steps"]:
        if step.get("id") == "gate":
            return dict(step)
    raise AssertionError("ci.yml's validate job has no step with id 'gate'")


def run_ci_gate(
    tmp_path: Path,
    *,
    event_name: str,
    ref_name: str,
    head_ref: str = "",
    changed_files: list[str] | None = None,
    gh_exit_code: int = 0,
) -> dict[str, str]:
    """Execute ci.yml's gate and return what it wrote to GITHUB_OUTPUT."""
    return _run_step_shell(
        str(ci_gate_step()["run"]),
        tmp_path,
        env={
            **CI_HARNESS_ENV,
            "EVENT_NAME": event_name,
            "REF_NAME": ref_name,
            "HEAD_REF": head_ref,
        },
        changed_files=changed_files or [],
        gh_exit_code=gh_exit_code,
    )


def run_gate(
    changed_files: list[str],
    tmp_path: Path,
    *,
    head_ref: str = BOT_BRANCH,
    event_name: str = "pull_request",
    gh_exit_code: int = 0,
) -> dict[str, str]:
    """Execute the fast-gates gate against a stubbed ``gh``; return its outputs.

    ``gh_exit_code`` drives the fail-closed path: the step must fall back to the
    heavy suite when it cannot list the PR's files, rather than skip on a branch
    name alone.
    """
    return _run_step_shell(
        gate_run_block(),
        tmp_path,
        env={**HARNESS_ENV, "EVENT_NAME": event_name, "HEAD_REF": head_ref},
        changed_files=changed_files,
        gh_exit_code=gh_exit_code,
    )


def _run_step_shell(
    run_block: str,
    tmp_path: Path,
    *,
    env: dict[str, str],
    changed_files: list[str],
    gh_exit_code: int,
) -> dict[str, str]:
    """Run one workflow step's shell with a stubbed ``gh``; return its outputs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "gh"
    # printf over the list rather than a heredoc: a heredoc delimiter can be
    # collided with by a changed path that happens to equal it, and this
    # harness's whole job is to not have blind spots of that shape.
    quoted = " ".join(shlex.quote(path) for path in changed_files)
    stub.write_text(
        f"#!/bin/sh\nprintf '%s\\n' {quoted}\nexit {gh_exit_code}\n" if changed_files
        else f"#!/bin/sh\nexit {gh_exit_code}\n",
        encoding="utf-8",
    )
    stub.chmod(0o755)

    github_output = tmp_path / "github_output"
    github_output.write_text("", encoding="utf-8")

    result = subprocess.run(
        [*SHELL, "-c", run_block],
        # Deliberately not `{**os.environ, ...}`: `bash -c` sources BASH_ENV
        # even under --noprofile --norc, so a developer's shell could change
        # what this measures. PATH is kept (with the stub in front) because the
        # step legitimately needs to find `gh` and bash itself.
        env={
            **env,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_OUTPUT": str(github_output),
        },
        capture_output=True,
        text=True,
        # The step is pure path classification; anything slower is a hang, and
        # a hang here would burn the job's whole timeout instead of failing.
        timeout=60,
    )
    assert result.returncode == 0, result.stderr

    return dict(
        line.split("=", 1)
        for line in github_output.read_text(encoding="utf-8").splitlines()
        if "=" in line
    )
