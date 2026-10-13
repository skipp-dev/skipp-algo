"""Audit guard: workflows must not paper over a `git push` to a protected
branch with the literal `git push ... || echo ...` success-faking pattern.

Scope is intentionally narrow: this guard targets the *specific* anti-
pattern where a rejected push (typically GH013 against the `main`-branch
ruleset) is downgraded to an `echo "::warning::..."` and the step exits 0,
leaving the workflow falsely green. Other masking patterns on `git push`
(e.g. `|| true`, `|| printf`, generic `|| <cmd>`) are out of scope here
and are covered by adjacent guards / code-review checklists.

Repository's `main-governance` ruleset blocks bare pushes to `main` (GH013).
Workflows that need to land file changes MUST either:

1. Push to a fresh `bot/*` branch and open an auto-merge PR (preferred for
   anything that should land on main), OR
2. Push to a stable, force-updated `bot/<channel>` branch as an explicit
   secondary delivery channel (preferred for high-frequency snapshots
   where a PR-per-tick would spam the queue).

Either way, a real `git push` failure must surface — not be downgraded to
a fake-success `echo "::warning::..."`.

Audit marker: F-V5-F1 / F-V3-11..15 (2026-05-01).
"""
from __future__ import annotations

import pathlib
import re

import pytest

_WORKFLOW_DIR = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
_WORKFLOWS = sorted(_WORKFLOW_DIR.glob("*.yml"))

# Regex catches the anti-pattern: `git push ... || echo ...` on a single
# logical line (with or without `2>&1`). Any such occurrence is forbidden.
_FAKE_SUCCESS_PUSH = re.compile(
    r"git\s+push\b[^\n|&]*(?:2>&1)?\s*\|\|\s*echo\b",
    re.IGNORECASE,
)

# `gh pr create ... || echo ...` and `gh pr create ... || true` have the
# same failure mode as the `git push || echo` pattern above: a real
# auth/ruleset/quota failure on PR creation is silently downgraded to a
# warning while the step exits 0. This regression was found in
# fvg-quality-quartile-gate.yml and fvg-context-pine-refresh.yml during
# the silent-publish-skip post-mortem (see PR #2415 / #2418 + audit
# 2026-05-28). The canonical fix captures stderr, exempts the benign
# "PR already exists" case, and surfaces everything else as ::error::
# with a non-zero exit.
#
# Scope: only `gh pr create` itself — `gh pr merge --auto || echo` is a
# legitimate "already-queued" race tolerance and is covered by adjacent
# guards. The regex permits bash line continuations (`\<newline>`) but
# stops at the first un-escaped newline so it does not span across the
# next command in the run-block.
_FAKE_SUCCESS_PR_CREATE = re.compile(
    r"gh\s+pr\s+create\b(?:\\\n|[^\n])*\|\|\s*(?:echo|true)\b",
    re.IGNORECASE,
)


@pytest.mark.parametrize("workflow_path", _WORKFLOWS, ids=lambda p: p.name)
def test_workflow_does_not_fake_push_success(workflow_path: pathlib.Path) -> None:
    body = workflow_path.read_text(encoding="utf-8")
    matches = _FAKE_SUCCESS_PUSH.findall(body)
    assert not matches, (
        f"{workflow_path.name}: contains `git push ... || echo ...` which "
        "fakes success on a rejected push to a protected branch. Migrate "
        "to a fresh `bot/*` branch + `gh pr create --auto` (regular cron) "
        "or to a force-updated rolling `bot/<channel>` branch (high-freq "
        "snapshot). See open-prep-outcome-backfill.yml for the canonical "
        "auto-PR pattern. (F-V5-F1 / F-V3-11..15)"
    )


@pytest.mark.parametrize("workflow_path", _WORKFLOWS, ids=lambda p: p.name)
def test_workflow_does_not_fake_pr_create_success(workflow_path: pathlib.Path) -> None:
    body = workflow_path.read_text(encoding="utf-8")
    matches = _FAKE_SUCCESS_PR_CREATE.findall(body)
    assert not matches, (
        f"{workflow_path.name}: contains `gh pr create ... || echo|true` "
        "which silently swallows real PR-creation failures (auth, ruleset, "
        "rate-limit) and lets the workflow finish green without ever "
        "opening the PR. Use the canonical pattern from smc-library-refresh.yml's "
        "`release_pending_pr` step or fvg-quality-quartile-gate.yml's "
        "post-2026-05-28 commit step: capture stderr, exempt only the "
        "literal 'a pull request for branch ... already exists' message, "
        "and exit non-zero on every other failure with an ::error:: "
        "annotation. (F-V5-F1 silent-skip post-mortem, audit 2026-05-28)"
    )
