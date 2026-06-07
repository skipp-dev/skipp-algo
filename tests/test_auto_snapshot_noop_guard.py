"""Audit guard: auto-snapshot cron workflows must not open no-op PRs.

The ``fvg-context-pine-refresh`` and ``fvg-quality-quartile-gate`` workflows
regenerate a tracked artifact on every scheduled run. The emitter rewrites
volatile provenance (``generated_at`` / ``source_commit_sha`` /
``source_workflow_run``) each run, so a naive ``git diff --staged --quiet``
check is *never* empty even when the substantive content (FVG health status /
release-gate decision) is unchanged.

Without a content-aware guard the cron opens a fresh PR every run that only
bumps a timestamp — pure churn that burns a full CI cycle and a merge-queue
slot for zero information. Three such no-op PRs were closed by hand during the
2026-06-03 queue drain (#2486 superseded, #2514 / #2536 awaiting_first_run).

This test pins the guard: before committing, each workflow MUST strip the
volatile provenance lines from the staged diff and skip the commit/PR when
nothing substantive remains. A real change (status / decision / counts /
emitted constants) is not exempted and still lands a PR.

Audit marker: auto-snapshot no-op guard (2026-06-03).
"""
from __future__ import annotations

import pathlib

import pytest

_WORKFLOW_DIR = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"

# Each guarded workflow plus the volatile provenance tokens its guard must
# exempt from the substantive-diff computation.
_GUARDED_WORKFLOWS = {
    "fvg-context-pine-refresh.yml": (
        "generated_at",
        "source_commit_sha",
        "source_workflow_run",
    ),
    "fvg-quality-quartile-gate.yml": (
        "generated_at",
        "commit_sha",
        "workflow_run",
    ),
}


@pytest.mark.parametrize("workflow_name", sorted(_GUARDED_WORKFLOWS))
def test_auto_snapshot_workflow_has_noop_guard(workflow_name: str) -> None:
    path = _WORKFLOW_DIR / workflow_name
    assert path.is_file(), f"missing workflow {workflow_name}"
    body = path.read_text(encoding="utf-8")

    # The guard computes a substantive-diff and skips when it is empty.
    assert "substantive=$(git diff --staged" in body, (
        f"{workflow_name}: missing the substantive-diff computation that lets "
        "the no-op snapshot guard skip timestamp-only churn. Strip the volatile "
        "provenance lines from `git diff --staged` and skip the commit/PR when "
        "nothing substantive remains."
    )
    assert 'if [ -z "$substantive" ]; then' in body, (
        f"{workflow_name}: substantive-diff is computed but never used to skip "
        "the commit/PR. Guard the commit behind an empty-substantive check."
    )

    # The skip path must NOT commit/push — it restores the tree and exits 0
    # BEFORE the `git commit` line.
    guard_idx = body.index('if [ -z "$substantive" ]; then')
    commit_idx = body.index("git commit -m", guard_idx)
    skip_block = body[guard_idx:commit_idx]
    assert "git restore --staged --worktree" in skip_block, (
        f"{workflow_name}: the no-op skip path must restore the regenerated "
        "files (drop the volatile-only change) instead of committing them."
    )
    assert "exit 0" in skip_block, (
        f"{workflow_name}: the no-op skip path must exit 0 before the commit "
        "step so no PR is opened for a timestamp-only change."
    )


@pytest.mark.parametrize(
    ("workflow_name", "tokens"),
    [(name, tokens) for name, tokens in sorted(_GUARDED_WORKFLOWS.items())],
)
def test_guard_exempts_volatile_provenance(
    workflow_name: str, tokens: tuple[str, ...]
) -> None:
    body = (_WORKFLOW_DIR / workflow_name).read_text(encoding="utf-8")
    guard_idx = body.index("substantive=$(git diff --staged")
    commit_idx = body.index("git commit -m", guard_idx)
    guard_block = body[guard_idx:commit_idx]
    for token in tokens:
        assert token in guard_block, (
            f"{workflow_name}: the no-op guard must exempt the volatile "
            f"provenance field '{token}'; otherwise a timestamp-only change "
            "still counts as substantive and the no-op PR is opened anyway."
        )
