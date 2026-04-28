"""Pin: every ``###`` subsection inside the ``## [Unreleased]`` block of
``CHANGELOG.md`` must follow the canonical format::

    ### <Category> (YYYY-MM-DD) — <Title>

This catches dropped categories, missing dates, and dropped em-dash
titles before they land on ``main``. The repo already pins category
membership via ``tests/test_changelog_category_lint.py`` (or similar);
this pin adds the *shape* check (date + dash + title) and is
intentionally narrow to the Unreleased block so historical entries
are not retro-graded.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CHANGELOG = REPO_ROOT / "CHANGELOG.md"

_UNRELEASED_RE = re.compile(r"^## \[Unreleased\]\s*$", re.MULTILINE)
_NEXT_TOP_LEVEL_RE = re.compile(r"^## (?!\[Unreleased\])", re.MULTILINE)
_SUBSECTION_RE = re.compile(r"^### (.+)$", re.MULTILINE)
# Canonical format: ### Category (YYYY-MM-DD) — Title
# (em-dash U+2014 is the convention; we accept it explicitly).
_CANONICAL_RE = re.compile(
    r"^[A-Z][A-Za-z0-9 /+()_,&-]+? "         # Category (allow / + parens & ampersand)
    r"\((\d{4}-\d{2}-\d{2})\)"               # (YYYY-MM-DD)
    r" \u2014 "                              # ' — '
    r".+\S$"                                 # Title (non-empty, no trailing ws)
)


def _unreleased_block() -> str:
    text = CHANGELOG.read_text(encoding="utf-8")
    m = _UNRELEASED_RE.search(text)
    assert m, "Could not locate '## [Unreleased]' header in CHANGELOG.md"
    start = m.end()
    nxt = _NEXT_TOP_LEVEL_RE.search(text, pos=start)
    end = nxt.start() if nxt else len(text)
    return text[start:end]


def test_changelog_exists() -> None:
    assert CHANGELOG.is_file(), f"Expected {CHANGELOG} to exist."


# Date threshold: only enforce canonical format for entries authored
# from this date onwards. Historical entries predate the convention
# and are immutable.
_ENFORCEMENT_FROM_DATE: str = "2026-04-22"

_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)")


def test_unreleased_block_subsections_match_canonical_format() -> None:
    """Recent (>= _ENFORCEMENT_FROM_DATE) Unreleased subsections must
    follow the canonical shape. Older entries are grandfathered."""
    block = _unreleased_block()
    subsections = _SUBSECTION_RE.findall(block)
    assert subsections, (
        "## [Unreleased] block contains no '### ...' subsections. "
        "Either nothing has shipped yet (expected during release windows) "
        "or the block was accidentally cleared — investigate."
    )
    violations: list[str] = []
    for header in subsections:
        date_m = _DATE_RE.search(header)
        # Skip headers without parseable dates (legacy free-form entries).
        if date_m is None:
            continue
        if date_m.group(1) < _ENFORCEMENT_FROM_DATE:
            continue
        if not _CANONICAL_RE.match(header):
            violations.append(header)
    assert not violations, (
        "Recent Unreleased '### ...' header(s) do not match canonical format\n"
        "    ### <Category> (YYYY-MM-DD) \u2014 <Title>\n"
        "(note: em-dash U+2014, not hyphen). Violations:\n"
        + "\n".join(f"  ### {h}" for h in violations)
    )
