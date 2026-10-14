"""Audit pin: ``pytest.skip`` per-file count budget.

Every ``pytest.skip(...)`` call or ``@pytest.mark.skip`` decorator in the
test suite is a test that *isn't* providing assertions. Skips are often
necessary (missing optional dependency, missing artifact in sparse
checkout) but they should never *grow* silently. This pin freezes the
current per-file skip count.

Reductions are encouraged: when a skip site is removed, drop or
decrement the entry here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests._pin_registry import pytest_skip_file_counts

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

_SKIP_RE = re.compile(r"@pytest\.mark\.skip\b|pytest\.skip\s*\(")

# Source of truth: pin_registry.toml (ADR-0009).
_FROZEN_FILE_COUNTS: dict[str, int] = pytest_skip_file_counts()

_TOTAL_BUDGET = sum(_FROZEN_FILE_COUNTS.values())


def _count_skips(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover
        return 0
    return sum(1 for line in text.splitlines() if _SKIP_RE.search(line))


def _measured_counts() -> dict[str, int]:
    measured: dict[str, int] = {}
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        # exclude self so docstring/regex literals don't count.
        if path.resolve() == Path(__file__).resolve():
            continue
        n = _count_skips(path)
        if n:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            measured[rel] = n
    return measured


def test_no_pytest_skip_count_increases() -> None:
    measured = _measured_counts()
    over_budget: list[str] = []
    for rel, count in measured.items():
        budget = _FROZEN_FILE_COUNTS.get(rel)
        if budget is None:
            over_budget.append(
                f"{rel}: {count} skip(s) but file not in ledger — add to "
                f"_FROZEN_FILE_COUNTS or remove the skip"
            )
        elif count > budget:
            over_budget.append(
                f"{rel}: {count} skip(s) > budget {budget} — reduce or "
                f"raise budget (and justify in CHANGELOG)"
            )
    assert not over_budget, "pytest.skip count regressed:\n  - " + "\n  - ".join(
        over_budget
    )


def test_no_stale_file_in_ledger() -> None:
    measured = _measured_counts()
    stale: list[str] = []
    for rel in _FROZEN_FILE_COUNTS:
        actual = measured.get(rel, 0)
        if actual == 0:
            stale.append(f"{rel}: ledger=N>0 but file has 0 skip(s) — remove entry")
    assert not stale, "Stale entries in pytest.skip ledger:\n  - " + "\n  - ".join(
        stale
    )


def test_total_budget_matches_inventory() -> None:
    measured_total = sum(_measured_counts().values())
    assert measured_total <= _TOTAL_BUDGET, (
        f"Total pytest.skip count {measured_total} exceeds frozen total "
        f"{_TOTAL_BUDGET}"
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_FILE_COUNTS.keys()))
def test_ledger_file_exists(rel: str) -> None:
    """Bidirectional sanity: every ledgered path must still exist."""
    assert (_REPO_ROOT / rel).is_file(), (
        f"Ledger references missing test file: {rel}"
    )


def test_tests_inventory_sane() -> None:
    files = list(_TESTS_DIR.rglob("*.py"))
    assert len(files) >= 50, f"tests/ scan only found {len(files)} files"
