"""Audit guard: every workflow must set ``PYTHONUNBUFFERED`` so Python output
streams reach the GHA log in real time.

Combined with ``logging.basicConfig`` in workflow-invoked entry-point scripts
(see ``scripts/databento_production_export.py`` after F-V5-A1), this prevents
the silent-failure mode where a long-running pipeline runs for an hour with
no visible progress before runner eviction.

Audit marker: F-V5-A2 / F-CI-O1 (2026-05-01).
"""
from __future__ import annotations

import pathlib

import pytest

_WORKFLOW_DIR = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
_WORKFLOWS = sorted(_WORKFLOW_DIR.glob("*.yml"))


@pytest.mark.parametrize("workflow_path", _WORKFLOWS, ids=lambda p: p.name)
def test_workflow_sets_pythonunbuffered(workflow_path: pathlib.Path) -> None:
    body = workflow_path.read_text(encoding="utf-8")
    assert "PYTHONUNBUFFERED" in body, (
        f"{workflow_path.name}: missing PYTHONUNBUFFERED env var. "
        "Without it, Python stdout/stderr is buffered and CI logs stay empty "
        "until the process exits — defeating live progress tracking. "
        "Add `PYTHONUNBUFFERED: \"1\"` under the top-level `env:` block "
        "(F-V5-A2 / F-CI-O1)."
    )
