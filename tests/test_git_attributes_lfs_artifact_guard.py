"""Regression guard for stale artifact Git LFS attributes.

The repo currently stores historical artifact fixtures as normal Git blobs
(not LFS pointers). Marking ``artifacts/**/*.parquet`` or ``artifacts/**/*.xlsx``
with ``filter=lfs`` makes checkout emit thousands of
``should have been pointers`` warnings and can overflow tools that buffer
checkout stderr (notably GitHub Copilot Code Review).
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_artifact_fixtures_are_not_marked_as_lfs() -> None:
    text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
    active_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    forbidden = [
        line
        for line in active_lines
        if line.startswith("artifacts/") and "filter=lfs" in line
    ]
    assert not forbidden, (
        "Artifact fixture paths must not be marked filter=lfs unless the same "
        f"change migrates the files to real LFS pointers: {forbidden!r}"
    )