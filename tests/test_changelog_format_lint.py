"""Format lint for ``CHANGELOG.md`` ``[Unreleased]`` section.

After PRs #117 / #118 / #119 / #120 (and the in-flight #121), the
``[Unreleased]`` section accumulates many sub-headings. This test
prevents Keep-a-Changelog format drift:

1. The first ``## [...]`` versioned heading is ``## [Unreleased]``.
2. Every ``###`` heading inside ``[Unreleased]`` uses a recognised
   category prefix from :data:`ALLOWED_CATEGORIES` (Keep-a-Changelog
   canonical set plus the repo-local extensions actively in use).

The test is intentionally **scoped to the Unreleased section only** and
intentionally narrow — historical sections are frozen, and stricter
date / uniqueness rules would clash with legitimate existing entries
(e.g. multiple ``### Verification`` blocks for the same date, or
date-range headers like ``### Added (2026-03-02 – 2026-03-02)``).
A category whitelist is the minimum-viable guard against silent
format drift (e.g. introducing ``### Misc`` or ``### Notes``).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

ALLOWED_CATEGORIES = frozenset({
    # Keep-a-Changelog canonical:
    "Added",
    "Changed",
    "Deprecated",
    "Removed",
    "Fixed",
    "Security",
    # Repo-local extensions in active use:
    "Documentation",
    "Tests / Quality",
    "Schema Versions",
    "Evidence",
    "Verification",
})

_CATEGORY_RE = re.compile(r"^###\s+([A-Za-z][A-Za-z /]*?)(?:\s*\(|\s*—|\s*-|\s*$)")


def _read_unreleased_block() -> list[str]:
    """Return the lines of the [Unreleased] block (between ## headers)."""
    text = CHANGELOG.read_text(encoding="utf-8")
    lines = text.splitlines()
    start = None
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## [unreleased]"):
            start = i
            break
    assert start is not None, (
        f"CHANGELOG.md is missing the '## [Unreleased]' header (searched "
        f"{len(lines)} lines). Add the header back at the top, immediately "
        "after the introductory blurb."
    )
    end = len(lines)
    for i, line in enumerate(lines[start + 1 :], start=start + 1):
        if line.startswith("## "):
            end = i
            break
    return lines[start:end]


def test_first_versioned_header_is_unreleased() -> None:
    """The first ``## [...]`` header must be ``[Unreleased]``."""
    text = CHANGELOG.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ["):
            assert stripped.lower().startswith("## [unreleased]"), (
                f"First versioned header in CHANGELOG.md is {stripped!r}, "
                "expected '## [Unreleased]'. The Unreleased section must "
                "always come first."
            )
            return
    pytest.fail("CHANGELOG.md has no '## [...]' versioned header at all.")


def test_unreleased_subheaders_use_known_categories() -> None:
    block = _read_unreleased_block()
    bad: list[tuple[int, str]] = []
    for offset, line in enumerate(block):
        if not line.startswith("### "):
            continue
        m = _CATEGORY_RE.match(line)
        if not m:
            bad.append((offset, line))
            continue
        category = m.group(1).strip()
        if category not in ALLOWED_CATEGORIES:
            bad.append((offset, line))
    assert not bad, (
        "Unrecognised CHANGELOG ### category headers in [Unreleased]:\n"
        + "\n".join(f"  line ~{o}: {h!r}" for o, h in bad)
        + f"\nAllowed: {sorted(ALLOWED_CATEGORIES)}"
    )


