"""Shared helpers for YAML-aware workflow guard tests.

Centralises a tiny walker that visits every ``step`` mapping inside every
job of a GitHub Actions workflow. Used by the ``continue-on-error``
inventory / semantics tests so both speak the same data model and no longer
depend on brittle 1-based line numbers or regex line-pinning.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


def iter_workflow_files() -> list[Path]:
    """Return the sorted list of all ``.github/workflows/*.yml`` files."""
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def load_workflow(path: Path) -> dict[str, Any]:
    """Parse a workflow YAML file into a dict; tolerant of empty files."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def iter_steps(workflow: dict[str, Any]) -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield ``(job_id, step_mapping)`` for every step in every job.

    Composite ``uses:`` action calls and reusable workflows have no
    ``steps:`` block; those jobs are skipped silently.
    """
    jobs = workflow.get("jobs") or {}
    if not isinstance(jobs, dict):
        return
    for job_id, job in jobs.items():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if isinstance(step, dict):
                yield job_id, step


def step_anchor(step: dict[str, Any]) -> str:
    """Stable human-readable identifier for a step.

    Prefers ``id`` (intentionally stable handle), falls back to ``name``,
    then to a ``uses:<action>`` shorthand. Used as the inventory key.
    """
    sid = step.get("id")
    if isinstance(sid, str) and sid:
        return f"id:{sid}"
    name = step.get("name")
    if isinstance(name, str) and name:
        return f"name:{name}"
    uses = step.get("uses")
    if isinstance(uses, str) and uses:
        return f"uses:{uses}"
    return "<unnamed-step>"


def has_continue_on_error_true(step: dict[str, Any]) -> bool:
    """True iff ``continue-on-error: true`` is set on this step (booleans only)."""
    return step.get("continue-on-error") is True
