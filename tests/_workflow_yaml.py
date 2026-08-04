"""Shared helpers for YAML-aware workflow guard tests.

Centralises a tiny walker that visits every ``step`` mapping inside every
job of a GitHub Actions workflow. Used by the ``continue-on-error``
inventory / semantics tests so both speak the same data model and no longer
depend on brittle 1-based line numbers or regex line-pinning.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"


COMPOSITE_ACTIONS_DIR = REPO_ROOT / ".github" / "actions"
WORKFLOW_TEMPLATES_DIR = REPO_ROOT / ".github" / "workflow-templates"


def iter_workflow_files() -> list[Path]:
    """Return the sorted list of all ``.github/workflows/*.yml`` files.

    Deliberately NOT widened to composite actions or templates: most callers
    walk ``jobs:``, which only a workflow has. Use
    :func:`iter_action_pin_surfaces` for guards that reason about ``uses:``
    pins rather than about job structure.
    """
    return sorted(WORKFLOWS_DIR.glob("*.yml")) + sorted(WORKFLOWS_DIR.glob("*.yaml"))


def iter_composite_action_files() -> list[Path]:
    """Every ``action.yml`` under ``.github/actions/``.

    These are real CI code — ``uses: ./.github/actions/<name>`` runs them — but
    they are not workflows, so the workflow corpus above never saw them.
    """
    if not COMPOSITE_ACTIONS_DIR.is_dir():
        return []
    return sorted(COMPOSITE_ACTIONS_DIR.rglob("action.yml")) + sorted(
        COMPOSITE_ACTIONS_DIR.rglob("action.yaml")
    )


def iter_workflow_template_files() -> list[Path]:
    """Every workflow template offered for creating new workflows.

    Not executed by CI, but copied verbatim into new workflows, so a rotten pin
    here is a rotten pin in whatever gets created from it tomorrow.
    """
    if not WORKFLOW_TEMPLATES_DIR.is_dir():
        return []
    # rglob, matching the composite walker: a template in a subdirectory is
    # still a template, and a corpus that silently omits one is the failure
    # mode every guard reading it inherits.
    return sorted(WORKFLOW_TEMPLATES_DIR.rglob("*.yml")) + sorted(
        WORKFLOW_TEMPLATES_DIR.rglob("*.yaml")
    )


def iter_action_pin_surfaces() -> list[Path]:
    """Every file in this repo that pins a GitHub Action by ``uses:``.

    Three surfaces, and until 2026-08-04 only the first was guarded — which is
    how ``.github/workflow-templates/`` came to pin
    ``astral-sh/setup-uv@caf0cab7a…`` (v3.2.4, 2024-11-23) while every workflow
    ran v8.2.0 (2026-06-03), unnoticed for twenty months.
    """
    return (
        iter_workflow_files() + iter_composite_action_files() + iter_workflow_template_files()
    )


# ONE regex, in one place, because the bug it replaces lived in two.
#
# The previous form excluded the quote characters from the capture class
# (``[^\s#'\"]+``). On ``uses: "actions/checkout@main"`` the very first
# character after ``uses:`` is a quote, so the ``+`` could not match and the
# WHOLE LINE was skipped — silently, by both supply-chain guards. Measured
# 2026-08-04: a quoted mutable tag in a workflow, a quoted mutable tag in the
# composite action, and an untrusted non-resolvable owner in the composite each
# left all 18 assertions green. Quoted scalars are identical YAML; Actions runs
# them.
#
# The quotes are stripped after capture instead, which is what the (previously
# dead) ``.strip("'\"")`` in both callers always believed was happening.
USES_RE = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)")


def iter_uses(paths: list[Path]) -> list[tuple[Path, int, str]]:
    """``(path, lineno, ref)`` for every ``uses:`` line in ``paths``.

    Line-based on purpose: the guards report a file and a line an operator can
    open, and a YAML round-trip would lose that. The ``lineno`` is 1-based.
    """
    out: list[tuple[Path, int, str]] = []
    for path in paths:
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            match = USES_RE.match(line)
            if match:
                out.append((path, lineno, match.group(1).strip().strip("'\"")))
    return out


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
