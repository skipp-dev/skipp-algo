"""Audit pin: per-file budget for EVERY spelling of a pytest skip.

Every skip in the test suite is a test that *isn't* providing assertions.
Skips are often necessary (missing optional dependency, missing artifact in
a sparse checkout) but they should never *grow* silently. This pin freezes
the current per-file skip count.

2026-08-19 (Geburtsfehler-Sweep A/C): the budget was born counting two of
the five spellings — ``@pytest.mark.skip`` and ``pytest.skip(...)``. The
word boundary in ``@pytest\\.mark\\.skip\\b`` does not match ``skipif``, and
neither pattern matches a module-level ``pytestmark = pytest.mark.skip*``,
which silences an ENTIRE file. Measured that day: 13 files carried an
invisible skip, 12 of them with no ledger entry at all —
``tests/test_terminal_bitcoin.py`` alone parks 39 tests behind an API-key
condition that no workflow supplies, and the budget reported 0 for it. The
sibling discipline pin (``tests/test_test_suite_health_discipline.py``)
already scanned for the module-level form and said so in a comment, so the
wider population was known when this narrower one was written.

The regex now matches any ``pytest.mark.skip``/``skipif`` marker (decorator,
``pytestmark`` assignment or list element) plus the inline call.
``test_every_skip_spelling_is_counted`` pins all five forms.

Reductions are encouraged: when a skip site is removed, drop or
decrement the entry here.
"""

from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

import pytest

from tests._pin_registry import pytest_skip_file_counts

_REPO_ROOT = Path(__file__).resolve().parent.parent
_TESTS_DIR = _REPO_ROOT / "tests"

_SKIP_RE = re.compile(r"pytest\.mark\.skip(?:if)?\b|pytest\.skip\s*\(")

# Source of truth: pin_registry.toml (ADR-0009).
_FROZEN_FILE_COUNTS: dict[str, int] = pytest_skip_file_counts()

_TOTAL_BUDGET = sum(_FROZEN_FILE_COUNTS.values())


def _code_lines(text: str) -> list[str]:
    """Source lines with comments and string literals blanked out.

    Without this, a file that merely *documents* a skip spelling in its
    docstring counts as carrying one (and would then need a ledger entry
    for prose). Tokenising is exact where a line scan cannot be: a triple
    quoted block spans lines, and a marker inside it is not a marker.
    """
    lines = text.splitlines()
    grid = [list(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):  # pragma: no cover
        return lines
    for token in tokens:
        if token.type not in (tokenize.COMMENT, tokenize.STRING):
            continue
        (start_row, start_col), (end_row, end_col) = token.start, token.end
        for row in range(start_row, end_row + 1):
            if row - 1 >= len(grid):  # pragma: no cover - defensive
                break
            chars = grid[row - 1]
            first = start_col if row == start_row else 0
            last = end_col if row == end_row else len(chars)
            for col in range(first, min(last, len(chars))):
                chars[col] = " "
    return ["".join(chars) for chars in grid]


def _count_skips(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):  # pragma: no cover
        return 0
    return sum(1 for line in _code_lines(text) if _SKIP_RE.search(line))


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


_SKIP_SPELLINGS: tuple[tuple[str, str], ...] = (
    ("inline-call", 'def test_a():\n    pytest.skip("x")\n'),
    ("decorator-skip", '@pytest.mark.skip(reason="x")\ndef test_b():\n    pass\n'),
    ("decorator-skipif", '@pytest.mark.skipif(True, reason="x")\ndef test_c():\n    pass\n'),
    ("module-skipif", 'pytestmark = pytest.mark.skipif(True, reason="x")\n'),
    ("module-skip", 'pytestmark = pytest.mark.skip(reason="x")\n'),
    ("module-skip-list", 'pytestmark = [pytest.mark.skip(reason="x")]\n'),
)


@pytest.mark.parametrize(("spelling", "body"), _SKIP_SPELLINGS, ids=[s for s, _ in _SKIP_SPELLINGS])
def test_every_skip_spelling_is_counted(tmp_path: Path, spelling: str, body: str) -> None:
    """Forward probe over the full population of skip spellings.

    Synthesise each form a file can use to stop running and prove the
    counter sees it. Three of these six were invisible until 2026-08-19 —
    including both module-level forms, which silence a whole file. Mutating
    ``_SKIP_RE`` back to ``@pytest\\.mark\\.skip\\b|pytest\\.skip\\s*\\(``
    turns the last four parameters red.
    """
    probe = tmp_path / "test_probe.py"
    probe.write_text(f"import pytest\n{body}", encoding="utf-8")
    assert _count_skips(probe) >= 1, f"{spelling} is invisible to the skip budget"


def test_tests_inventory_sane() -> None:
    files = list(_TESTS_DIR.rglob("*.py"))
    assert len(files) >= 50, f"tests/ scan only found {len(files)} files"
