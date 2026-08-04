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

What it does NOT cover: GitHub's ``if:`` expression evaluation. Whether the
Checkout and guard steps actually consume these outputs is still pinned by
source-text assertions, because that evaluation has no local equivalent.
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


def gate_run_block() -> str:
    """The ``gate`` step's shell, read structurally out of the workflow.

    Loaded through the YAML rather than sliced out of the text, so indentation,
    comment and ordering churn cannot break it -- and a missing step id is a
    named failure rather than a silently empty script.
    """
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    for step in workflow["jobs"]["fast-gates"]["steps"]:
        if step.get("id") == "gate":
            return str(step["run"])
    raise AssertionError("fast-gates has no step with id 'gate'")


def run_gate(
    changed_files: list[str],
    tmp_path: Path,
    *,
    head_ref: str = BOT_BRANCH,
    event_name: str = "pull_request",
    gh_exit_code: int = 0,
) -> dict[str, str]:
    """Execute the gate against a stubbed ``gh``; return what it wrote.

    ``gh_exit_code`` drives the fail-closed path: the step must fall back to the
    heavy suite when it cannot list the PR's files, rather than skip on a branch
    name alone.
    """
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
        [*SHELL, "-c", gate_run_block()],
        # Deliberately not `{**os.environ, ...}`: `bash -c` sources BASH_ENV
        # even under --noprofile --norc, so a developer's shell could change
        # what this measures. PATH is kept (with the stub in front) because the
        # step legitimately needs to find `gh` and bash itself.
        env={
            "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "GITHUB_OUTPUT": str(github_output),
            "EVENT_NAME": event_name,
            "HEAD_REF": head_ref,
            "PR_NUMBER": "4371",
            "REPO": "skipp-dev/skipp-algo",
            "GH_TOKEN": "stub-token",
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
