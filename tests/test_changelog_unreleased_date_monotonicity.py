"""CHANGELOG ``[Unreleased]`` date-monotonicity pin.

Companion to ``test_changelog_unreleased_subsection_format.py``: that
test enforces the canonical format of dated subsections; this one
enforces that within the ``## [Unreleased]`` block, dated entries are
listed newest-first (non-increasing dates from top to bottom).

This catches merge-conflict artefacts where a stale local entry slips
back above a newer one, and also catches accidental backwards-dating
of new entries.

Scope: enforcement applies to entries dated on/after
``_ENFORCEMENT_FROM_DATE``. The ``[Unreleased]`` block also contains a
parallel "Plan 2.8" planning ledger whose dated entries follow a
separate roadmap discipline; those are excluded by title filter
(``Plan 2.8`` in header) so the two streams don't constrain each other.
"""

from __future__ import annotations

import re
from itertools import pairwise
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"

_ENFORCEMENT_FROM_DATE = "2026-04-22"
# Substrings in the subsection title that mark an entry as belonging to a
# parallel ledger and therefore exempt from monotonicity. Keep this list
# minimal; new exemptions should be justified.
_TITLE_EXEMPT_SUBSTRINGS: tuple[str, ...] = ("Plan 2.8",)

# Matches subsection headers like:
#   ### Tests / Quality (2026-04-24) — Title
# The em-dash (—) is required by the format pin; we capture date and title.
_HEADER_RE = re.compile(r"^###\s+.+?\((\d{4}-\d{2}-\d{2})\)\s+\u2014\s+(.+)$")


def _unreleased_dates_in_order() -> list[tuple[int, str]]:
    """Return list of (line_number, YYYY-MM-DD) within the [Unreleased] block."""
    lines = _CHANGELOG.read_text(encoding="utf-8").splitlines()
    in_unreleased = False
    out: list[tuple[int, str]] = []
    for idx, line in enumerate(lines, start=1):
        stripped = line.rstrip()
        if stripped.startswith("## "):
            in_unreleased = stripped.lower().startswith("## [unreleased]")
            continue
        if not in_unreleased:
            continue
        m = _HEADER_RE.match(stripped)
        if m is None:
            continue
        date, title = m.group(1), m.group(2)
        if date < _ENFORCEMENT_FROM_DATE:
            continue
        if any(token in title for token in _TITLE_EXEMPT_SUBSTRINGS):
            continue
        out.append((idx, date))
    return out


def test_changelog_exists() -> None:
    assert _CHANGELOG.is_file(), f"CHANGELOG.md missing at {_CHANGELOG}"


def test_unreleased_dates_are_non_increasing_top_to_bottom() -> None:
    dates = _unreleased_dates_in_order()
    if len(dates) < 2:
        # Nothing to compare; pin is structurally satisfied.
        return
    violations: list[str] = []
    for (line_a, date_a), (line_b, date_b) in pairwise(dates):
        # ``date_b`` appears BELOW ``date_a`` and must be <= date_a (older or same).
        if date_b > date_a:
            violations.append(
                f"line {line_b} ({date_b}) is newer than the entry above it on "
                f"line {line_a} ({date_a}); newest entries must be at the top of "
                f"the [Unreleased] block."
            )
    assert not violations, (
        "CHANGELOG [Unreleased] date order violations:\n  - "
        + "\n  - ".join(violations)
    )
