"""Defense pin: ``assert`` statements in first-party production code.

``assert`` is removed by CPython under ``-O`` / ``PYTHONOPTIMIZE=1``.
Any production code relying on it (runtime contracts or type-narrowing
crutches for mypy/pyright) silently changes behaviour in optimised
builds. Latent bug class. Freeze the inventory and block new sites.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
        ".git", ".github", ".mypy_cache", ".pytest_cache", ".ruff_cache",
        ".venv", "venv", "node_modules", "artifacts", "docs", "scripts",
        "tests", "SMC++",
    }
)

_FROZEN_SITES: frozenset[tuple[str, int]] = frozenset()


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(REPO_ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _collect_assert_sites(path: Path) -> list[tuple[str, int]]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    rel = path.relative_to(REPO_ROOT).as_posix()
    return [
        (rel, node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Assert)
    ]


def test_first_party_files_present() -> None:
    files = _iter_first_party_py_files()
    assert len(files) >= 50, (
        f"path drift: expected >=50 first-party prod *.py files, "
        f"found {len(files)}. Did the layout change?"
    )


def test_no_unexpected_assert_sites() -> None:
    found: set[tuple[str, int]] = set()
    for path in _iter_first_party_py_files():
        found.update(_collect_assert_sites(path))
    unexpected = sorted(found - _FROZEN_SITES)
    assert not unexpected, (
        "Found new `assert` statement(s) in first-party production code:\n"
        + "\n".join(f"  {rel}:{lineno}" for rel, lineno in unexpected)
        + "\n\n`assert` is stripped by `python -O` / PYTHONOPTIMIZE=1.\n"
        "Replace with explicit `if not ...: raise ...` for runtime\n"
        "contracts, or -- only if the assert is a narrow type-narrowing\n"
        "crutch immediately adjacent to the use -- add to _FROZEN_SITES\n"
        "in tests/test_assert_in_production_budget.py with justification."
    )


@pytest.mark.parametrize("entry", sorted(_FROZEN_SITES))
def test_frozen_sites_still_match(entry: tuple[str, int]) -> None:
    rel, expected_lineno = entry
    path = REPO_ROOT / rel
    assert path.is_file(), f"frozen site missing on disk: {rel}"
    sites = {site for site in _collect_assert_sites(path) if site == entry}
    assert sites, (
        f"Frozen `assert` site no longer matches: expected "
        f"{rel}:{expected_lineno}. If the code was refactored or the\n"
        "line moved, update _FROZEN_SITES in the same PR. If the site\n"
        "was removed (great!), drop the entry from _FROZEN_SITES."
    )
