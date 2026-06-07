"""Pin: discipline rules for ``requirements.txt``.

Three layers of defense against supply-chain regressions:

1. **Version specifier required.** Every non-comment, non-empty line must
   carry at least one of ``>= == ~= < > !=`` so a fresh ``pip install``
   cannot silently pull in a brand-new (potentially compromised) major
   version. Today: all 23 deps use ``>=``.

2. **No third-party index URLs.** Lines starting with ``--index-url`` or
   ``--extra-index-url`` would let pip resolve packages from outside
   PyPI — a known dependency-confusion vector. Today: 0 such lines.

3. **Line-count budget.** Total dep-line count is frozen at 23. New
   dependencies must update the budget consciously, surfacing
   supply-chain surface growth in code review.

Future work (not blocking): migrate to ``pip-compile --generate-hashes``
to add SHA-256 pinning. That requires committing to exact versions
(``==`` instead of ``>=``), which is a separate decision.

OWASP A06 (Vulnerable & Outdated Components) +
OWASP A08 (Software & Data Integrity Failures).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_REQUIREMENTS = _REPO_ROOT / "requirements.txt"

# Frozen budget — bump consciously when adding deps. Unit: dep-lines.
# 2026-05-12 (F-V8-Q5b, PR #2148): bumped 23 -> 24 to add psutil>=5.9.0
# for the per-sheet RSS/USS memory-snapshot diagnostic in
# scripts/databento_production_workbook.py::_memory_snapshot.
# 2026-06-07: bumped 25 -> 26 to add pytest-split>=0.11.0 for the
# duration-balanced 4-shard sharding of the `validate` CI job.
_DEP_LINE_BUDGET = 26

_SPECIFIER_RE = re.compile(r"[<>=~!]")


def _dep_lines() -> list[tuple[int, str]]:
    """Return ``(1-based-line-number, content)`` for every dep line.

    A dep line is a non-empty, non-comment line that does not start
    with a pip option flag (``--index-url`` etc).
    """
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(_REQUIREMENTS.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("--"):
            continue
        out.append((i, line))
    return out


def _option_lines() -> list[tuple[int, str]]:
    """Return ``(1-based-line-number, content)`` for every pip-option line."""
    out: list[tuple[int, str]] = []
    for i, raw in enumerate(_REQUIREMENTS.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if line.startswith("--"):
            out.append((i, line))
    return out


def test_requirements_file_exists() -> None:
    assert _REQUIREMENTS.is_file(), f"missing {_REQUIREMENTS}"


@pytest.mark.parametrize(("lineno", "line"), _dep_lines())
def test_every_dep_has_version_specifier(lineno: int, line: str) -> None:
    """Every dep line must carry a version specifier (``>=``, ``==``, …).

    A bare ``requests`` line would let a fresh install pull in any
    version, including a freshly-published compromised one. Even a
    soft lower bound (``>=X.Y``) gives a floor and signals the
    intended major.
    """
    assert _SPECIFIER_RE.search(line), (
        f"requirements.txt line {lineno} is unpinned: {line!r}. "
        f"Add at least a lower bound (e.g. '>=1.0') to avoid pulling "
        f"in arbitrary future major versions."
    )


def test_no_third_party_index_urls() -> None:
    """No ``--index-url`` / ``--extra-index-url`` lines allowed.

    Third-party indexes are a dependency-confusion vector. PyPI is
    the only allowed source.
    """
    forbidden = ("--index-url", "--extra-index-url")
    offenders = [
        (n, line) for n, line in _option_lines()
        if any(line.startswith(f) for f in forbidden)
    ]
    assert offenders == [], (
        "requirements.txt must not declare third-party package indexes. "
        f"Offenders: {offenders}"
    )


def test_dep_line_count_budget() -> None:
    """Frozen total dep-line count.

    Bumping this number requires conscious approval — surfaces
    supply-chain surface growth in code review.
    """
    actual = len(_dep_lines())
    assert actual == _DEP_LINE_BUDGET, (
        f"requirements.txt dep-line count drifted: expected "
        f"{_DEP_LINE_BUDGET}, got {actual}. If this is intentional, "
        f"update _DEP_LINE_BUDGET in this test."
    )
