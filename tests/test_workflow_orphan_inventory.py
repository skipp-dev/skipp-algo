"""F-V4-G2 (2026-05-01): orphan workflow inventory.

A workflow is considered "orphan" if no file under tests/ references its
basename. Every other workflow has at least one test that pins some part
of its contract (cron schedule, on-block, jobs, env, permissions, etc.).

The orphans listed below are intentional:

- ``g23-ab-watchdog``: external A/B drift watcher with no fixed contract
  surface (it shells out to a runtime decision tree); coverage lives in
  the underlying script's unit tests.
- ``phase-b-promotion-readiness``: human-gated promotion checklist;
  outputs a markdown summary, not a programmatic artifact.
- ``regime-stratification-validation``: experimental regime sweep, kept
  out of the gate set deliberately while the methodology stabilises.

Adding a new orphan must be a deliberate ALLOW_LIST edit. Adding a test
for an existing orphan must drop it from ALLOW_LIST in the same PR.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
TESTS_DIR = REPO_ROOT / "tests"

# Frozen — see module docstring for rationale per entry.
ALLOWED_ORPHANS: frozenset[str] = frozenset({
    "regime-stratification-validation.yml",
})


def _has_test_reference(workflow_basename_no_ext: str) -> bool:
    """Return True iff any file under tests/ contains the workflow basename.

    Excludes this file itself, which lists every orphan basename literally
    in ``ALLOWED_ORPHANS`` and would otherwise trivially "reference" them.
    """
    for path in sorted(TESTS_DIR.rglob("*.py")):
        if path.name == Path(__file__).name:
            continue
        try:
            if workflow_basename_no_ext in path.read_text(encoding="utf-8"):
                return True
        except UnicodeDecodeError:
            continue
    return False


def test_orphan_workflow_set_matches_allowlist() -> None:
    workflows = sorted(WORKFLOW_DIR.glob("*.yml"))
    actual_orphans = {
        wf.name for wf in workflows if not _has_test_reference(wf.stem)
    }

    extra = actual_orphans - ALLOWED_ORPHANS
    missing = ALLOWED_ORPHANS - actual_orphans

    assert not extra, (
        "New orphan workflow(s) without test coverage: "
        f"{sorted(extra)}. Either add a test that references the workflow "
        "basename (filename minus .yml), or add the entry to ALLOWED_ORPHANS "
        "in this file with rationale."
    )
    assert not missing, (
        "ALLOWED_ORPHANS contains workflows that now HAVE test coverage: "
        f"{sorted(missing)}. Remove them from ALLOWED_ORPHANS — the orphan "
        "list must stay tight."
    )
