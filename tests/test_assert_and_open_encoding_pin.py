"""Defense-pin: prod ``assert`` & encoding-less ``open()`` ledgers.

Two independent layers freezing call-sites that drift silently.

A. ``assert`` in prod ledger
   ------------------------
   Python with ``-O`` strips ``assert`` statements. Any prod ``assert`` that
   guards a runtime invariant becomes a no-op under ``python -O`` / a
   ``PYTHONOPTIMIZE`` build. New prod ``assert`` sites must be reviewed and
   added to the ledger so we can decide between keeping them (development
   sanity) and replacing them with explicit ``raise``.

B. ``open()`` without ``encoding=`` ledger
   ---------------------------------------
   Without an explicit encoding ``open()`` falls back to
   ``locale.getencoding()``, which silently changes by platform / runtime
   environment. New encoding-less call sites must be ledgered so we can
   confirm they are intentionally binary mode (``"rb"`` / ``"wb"``) — those
   never need ``encoding`` and are not flagged here because the AST scan
   only counts text-mode ``open()`` calls (mode literal lacks ``b``).

Defense-only, no production code changes.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests._guard_corpus import iter_tracked_files, parse_module

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
        ".git",
        ".github",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "artifacts",
        "docs",
        "scripts",
        "tests",
        "SMC++",
    }
)


def _iter_prod_py() -> Iterator[Path]:
    yield from iter_tracked_files("*.py", _DIR_EXCLUDE, root=ROOT)


def _parse(p: Path) -> ast.AST | None:
    return parse_module(p)


# ---------------------------------------------------------------------------
# Layer A — assert sites
# ---------------------------------------------------------------------------

# Frozen ledger: rel-path -> number of `assert` statements.
# All four prior sites were migrated to explicit raise blocks in PR #171
# (chore: migrate prod asserts to explicit raise + zero-budget pin).
# This ledger is now zero — `test_assert_no_new_files` keeps the door shut.
_FROZEN_ASSERT_COUNTS: dict[str, int] = {}
_FROZEN_ASSERT_TOTAL = sum(_FROZEN_ASSERT_COUNTS.values())


@functools.cache
def _scan_asserts() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        n = sum(1 for node in ast.walk(tree) if isinstance(node, ast.Assert))
        if n:
            out[str(p.relative_to(ROOT))] = n
    return out


def test_prod_inventory_sane() -> None:
    files = list(_iter_prod_py())
    assert len(files) >= 30, f"prod py inventory shrank: {len(files)}"


def test_assert_total_frozen() -> None:
    counts = _scan_asserts()
    total = sum(counts.values())
    assert total == _FROZEN_ASSERT_TOTAL, (
        f"prod `assert` total drifted: expected {_FROZEN_ASSERT_TOTAL}, "
        f"got {total}; per-file = {counts}"
    )


def test_assert_no_new_files() -> None:
    counts = _scan_asserts()
    new = sorted(set(counts) - set(_FROZEN_ASSERT_COUNTS))
    assert not new, (
        "New prod files contain `assert` — review (-O strips them) and "
        f"either replace with explicit raise or append to ledger: {new}"
    )


def test_assert_no_stale_entries() -> None:
    counts = _scan_asserts()
    stale = sorted(set(_FROZEN_ASSERT_COUNTS) - set(counts))
    assert not stale, (
        "Frozen `assert` ledger lists files with no remaining asserts — "
        f"remove from _FROZEN_ASSERT_COUNTS: {stale}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_ASSERT_COUNTS.items()))
def test_assert_per_file_count(rel: str, expected: int) -> None:
    counts = _scan_asserts()
    actual = counts.get(rel, 0)
    assert actual == expected, (
        f"{rel}: prod `assert` count drifted (expected {expected}, got {actual})."
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_ASSERT_COUNTS))
def test_assert_files_exist(rel: str) -> None:
    assert (ROOT / rel).is_file(), f"Ledger file missing: {rel}"


# ---------------------------------------------------------------------------
# Layer B — text-mode `open()` without `encoding=`
# ---------------------------------------------------------------------------

_FROZEN_OPEN_COUNTS: dict[str, int] = {}
_FROZEN_OPEN_TOTAL = sum(_FROZEN_OPEN_COUNTS.values())


def _is_text_mode(node: ast.Call) -> bool:
    """True if the call is ``open(...)`` in text mode (no ``b`` in mode)."""
    # mode arg can be positional (index 1) or keyword 'mode'; default text
    mode_value: str | None = None
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        v = node.args[1].value
        if isinstance(v, str):
            mode_value = v
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            v = kw.value.value
            if isinstance(v, str):
                mode_value = v
    if mode_value is None:
        return True  # default text mode
    return "b" not in mode_value


@functools.cache
def _scan_open_no_encoding() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        n = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (isinstance(f, ast.Name) and f.id == "open"):
                continue
            if not _is_text_mode(node):
                continue
            kw_names = {k.arg for k in node.keywords}
            if "encoding" not in kw_names:
                n += 1
        if n:
            out[str(p.relative_to(ROOT))] = n
    return out


def test_open_no_encoding_total_frozen() -> None:
    counts = _scan_open_no_encoding()
    total = sum(counts.values())
    assert total == _FROZEN_OPEN_TOTAL, (
        f"text-mode open() w/o encoding total drifted: expected "
        f"{_FROZEN_OPEN_TOTAL}, got {total}; per-file = {counts}"
    )


def test_open_no_encoding_no_new_files() -> None:
    counts = _scan_open_no_encoding()
    new = sorted(set(counts) - set(_FROZEN_OPEN_COUNTS))
    assert not new, (
        "New prod files use text-mode open() without encoding= — pass "
        f"encoding='utf-8' or update the ledger: {new}"
    )


def test_open_no_encoding_no_stale_entries() -> None:
    counts = _scan_open_no_encoding()
    stale = sorted(set(_FROZEN_OPEN_COUNTS) - set(counts))
    assert not stale, (
        "Frozen open()-no-encoding ledger lists files with no remaining "
        f"hits — remove from _FROZEN_OPEN_COUNTS: {stale}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_OPEN_COUNTS.items()))
def test_open_no_encoding_per_file_count(rel: str, expected: int) -> None:
    counts = _scan_open_no_encoding()
    actual = counts.get(rel, 0)
    assert actual == expected, (
        f"{rel}: text-mode open() w/o encoding count drifted "
        f"(expected {expected}, got {actual})."
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_OPEN_COUNTS))
def test_open_files_exist(rel: str) -> None:
    assert (ROOT / rel).is_file(), f"Ledger file missing: {rel}"
