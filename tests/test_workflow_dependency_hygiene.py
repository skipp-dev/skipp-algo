"""Audit guard: workflows must install requirements.txt before ``pip install -e .``.

History: ``f2-promotion-gate-daily`` failed on 2026-04-30 with
``ModuleNotFoundError: pandas`` because the workflow installed only the project
in editable mode without first hydrating the runtime requirements. This module
keeps that regression from sneaking back in for any workflow that needs the
full stack.

Audit marker: F-V5-B1 / F-CI-D1 (2026-05-01).
"""
from __future__ import annotations

import pathlib

import pytest

_WORKFLOWS_REQUIRING_REQUIREMENTS_TXT = (
    "f2-promotion-gate-daily.yml",
    "f2-weekly-digest.yml",
    "feature-importance-daily.yml",
)


@pytest.mark.parametrize("workflow_name", _WORKFLOWS_REQUIRING_REQUIREMENTS_TXT)
def test_workflow_installs_requirements_before_editable(workflow_name: str) -> None:
    workflow_path = (
        pathlib.Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / workflow_name
    )
    body = workflow_path.read_text(encoding="utf-8")

    needle_requirements = "pip install -r requirements.txt"
    needle_editable = "pip install -e ."

    assert needle_requirements in body, (
        f"{workflow_name}: missing 'pip install -r requirements.txt' install step"
        " (regression of F-V5-B1 / F-CI-D1)"
    )
    assert needle_editable in body, (
        f"{workflow_name}: missing 'pip install -e .' install step"
    )

    idx_requirements = body.index(needle_requirements)
    idx_editable = body.index(needle_editable)
    assert idx_requirements < idx_editable, (
        f"{workflow_name}: requirements.txt must be installed BEFORE 'pip install -e .'"
        " or the editable install will not pick up missing transitive deps"
    )
