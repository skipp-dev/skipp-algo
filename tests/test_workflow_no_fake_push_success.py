"""Audit guard: workflows must not paper over a `git push` to a protected
branch with `|| echo "::warning::..."` or similar success-faking patterns.

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
