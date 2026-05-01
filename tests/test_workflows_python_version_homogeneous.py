"""F-V4-B3 (2026-05-01): all workflows must pin a single python-version.

Before standardization: 18 of 28 workflows used "3.12", 10 used "3.13".
ADR-0005 mandates the Python 3.13 runtime; the Dockerfile is pinned to
``python:3.13-slim``; pyproject.toml declares ``requires-python = ">=3.12"``
so the project still imports on 3.12 but CI must run on 3.13.

This test prevents regressing back to 3.12 (or skipping ahead to 3.14
without a deliberate ADR update).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml"))
EXPECTED = "3.13"

# Capture the version from setup-python `python-version: <X.Y>` lines.
# Tolerate both `"X.Y"` and `'X.Y'` quoting (and the unquoted form).
_RX = re.compile(r"python-version:\s*['\"]?(\d+\.\d+)['\"]?")


@pytest.mark.parametrize("wf", WORKFLOWS, ids=lambda p: p.name)
def test_workflow_python_version_is_3_13(wf: Path) -> None:
    text = wf.read_text(encoding="utf-8")
    for m in _RX.finditer(text):
        version = m.group(1)
        assert version == EXPECTED, (
            f"{wf.name}: python-version={version!r}, expected {EXPECTED!r}. "
            f"Standardization requirement set by F-V4-B3 (2026-05-01); "
            f"if you need to bump, do so across ALL workflows + ADR-0005 + "
            f"Dockerfile + this test in the same PR."
        )


def test_at_least_most_workflows_pin_python_version() -> None:
    """Sanity guard: regex must actually be matching things."""
    found = sum(1 for wf in WORKFLOWS if _RX.search(wf.read_text(encoding="utf-8")))
    assert found > 20, (
        f"Only {found} workflows pin python-version; suspiciously low. "
        f"Either the regex broke, or workflows are no longer using setup-python."
    )
