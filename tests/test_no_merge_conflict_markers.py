"""Tripwire: no committed Git merge-conflict markers anywhere tracked.

Regression guard for the 2026-06-12 incident on PR #2707: a
``gh pr update-branch`` merge of ``CHANGELOG.md`` was committed with
unresolved conflict markers (``<<<<<<<`` / ``=======`` / ``>>>>>>>``)
plus a duplicated heading line. Nothing in CI scanned for markers, so
the broken file only surfaced via human review.

Scans every git-tracked text file (cheap: ``git ls-files`` + line
scan). ``=======`` alone is ambiguous (legitimate Markdown setext
heading / RST underline), so it only counts when a ``<<<<<<<`` opener
was seen earlier in the same file — the start/end markers themselves
are unambiguous at line start in conflict-marker form.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Conflict markers are exactly 7 chars + (for <<</>>>) a space and label.
_START = "<<<<<<< "
_MID = "======="
_END = ">>>>>>> "

# Files that legitimately discuss conflict markers (this test, docs
# describing the incident). Extend deliberately, never wildcard.
_ALLOWED = frozenset(
    {
        "tests/test_no_merge_conflict_markers.py",
    }
)


def _tracked_files() -> list[Path]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=_REPO_ROOT,
            capture_output=True,
            check=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.SubprocessError) as exc:
        # Mirror the other repo tripwires: environments without git (or a
        # non-git checkout) skip instead of failing/hanging.
        pytest.skip(f"git ls-files unavailable: {exc}")
    files = []
    for rel in out.stdout.decode("utf-8", errors="replace").split("\0"):
        if not rel or rel in _ALLOWED:
            continue
        path = _REPO_ROOT / rel
        if path.is_file():
            files.append(path)
    return files


def _is_binary(path: Path) -> bool:
    """NUL-byte sniff on the first 8 KiB — conflict markers only matter in text."""
    try:
        with path.open("rb") as fh:
            return b"\0" in fh.read(8192)
    except OSError:
        return True


def test_no_merge_conflict_markers_in_tracked_files() -> None:
    offenders: list[str] = []
    for path in _tracked_files():
        if _is_binary(path):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        saw_start = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.startswith(_START):
                saw_start = True
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} {_START.strip()}")
            elif line.startswith(_END) and saw_start:
                # Block closed — stop treating bare ======= as a marker so a
                # single conflict does not flag later setext headings too.
                saw_start = False
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} {_END.strip()}")
            elif line == _MID and saw_start:
                offenders.append(f"{path.relative_to(_REPO_ROOT)}:{lineno} {_MID}")
    assert not offenders, (
        "Git merge-conflict markers committed to tracked files. "
        "Resolve the conflict (keep both hunks deliberately) and remove "
        "the markers before pushing — see PR #2707 incident "
        "(CHANGELOG.md shipped with unresolved markers).\n"
        + "\n".join(offenders)
    )
