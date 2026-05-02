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

    # F-V5-B1 round-2 (2026-05-02): strip YAML comments before substring search.
    # The original naive ``body.index(...)`` matched inside comments — e.g. the
    # F-V8-B1.1 explanatory comment in f2-promotion-gate-daily ("requirements.txt
    # MUST come before `pip install -e .`") falsely satisfied the editable-install
    # needle and reversed the apparent ordering. We now compare positions on the
    # comment-stripped view so the assertion reflects the actual run-step ordering.
    def _strip_comments(text: str) -> str:
        out_lines = []
        for line in text.splitlines(keepends=True):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                # Drop full-line comments entirely.
                continue
            # Drop inline comments while preserving the command before them.
            # YAML doesn't allow `#` mid-string in our run blocks (quoted args
            # use single quotes), so a simple split is safe here.
            if " #" in line:
                line = line.split(" #", 1)[0] + "\n"
            out_lines.append(line)
        return "".join(out_lines)

    haystack = _strip_comments(body)

    needle_requirements = "pip install -r requirements.txt"
    needle_editable = "pip install -e ."

    assert needle_requirements in haystack, (
        f"{workflow_name}: missing 'pip install -r requirements.txt' install step"
        " (regression of F-V5-B1 / F-CI-D1)"
    )
    assert needle_editable in haystack, (
        f"{workflow_name}: missing 'pip install -e .' install step"
    )

    idx_requirements = haystack.index(needle_requirements)
    idx_editable = haystack.index(needle_editable)
    assert idx_requirements < idx_editable, (
        f"{workflow_name}: requirements.txt must be installed BEFORE 'pip install -e .'"
        " or the editable install will not pick up missing transitive deps"
    )
