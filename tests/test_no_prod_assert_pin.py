"""Pin: zero ``assert`` statements in first-party production Python.

Rationale
---------
``assert`` statements are silently stripped under ``python -O`` (optimisation
mode), turning would-be ``AssertionError`` into latent bugs (e.g. ``None``
type-narrowing collapses into ``AttributeError`` somewhere downstream, or
worse: silent acceptance of an invalid state).

For runtime invariants in production code we therefore require explicit
``raise`` statements (typically ``raise RuntimeError(...)`` or
``raise ValueError(...)``).

Test code under ``tests/`` is exempt: pytest contracts depend on ``assert``,
and tests are never run under ``-O``.

This pin replaces the per-file ledger in
``tests/test_assert_and_open_encoding_pin.py`` with a stricter zero-budget
guarantee for production. The legacy ledger remains the upper bound; this
pin enforces the *current* lower bound (zero).
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]

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


def _iter_first_party_py() -> list[Path]:
    out: list[Path] = []
    for p in sorted(_REPO_ROOT.rglob("*.py")):
        rel_parts = p.relative_to(_REPO_ROOT).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(p)
    return out


def _collect_assert_sites() -> list[tuple[str, int]]:
    sites: list[tuple[str, int]] = []
    for p in _iter_first_party_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = p.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assert):
                sites.append((rel, node.lineno))
    return sites


def test_no_assert_statements_in_production() -> None:
    """Zero ``assert`` statements allowed in first-party production code.

    Replace any new ``assert`` with an explicit ``if … : raise …`` block so
    the invariant survives ``python -O``.
    """
    sites = _collect_assert_sites()
    assert sites == [], (
        "Production assert statement(s) found — these are stripped under "
        "python -O. Replace with explicit `if … : raise RuntimeError(...)`. "
        f"Offenders ({len(sites)}): {sites}"
    )


_SITES_FOR_PARAM = _collect_assert_sites() or [("__none__", 0)]


@pytest.mark.parametrize("site", _SITES_FOR_PARAM, ids=lambda s: f"{s[0]}:{s[1]}")
def test_each_assert_site_documented(site: tuple[str, int]) -> None:
    """Per-site enumeration: makes any new prod assert show up by file:line.

    Stays green only when ``_collect_assert_sites()`` returns ``[]`` (the
    sentinel placeholder ``("__none__", 0)`` is recognised as the empty
    state).
    """
    rel, lineno = site
    assert rel == "__none__" and lineno == 0, (
        f"Production assert at {rel}:{lineno} — convert to explicit raise."
    )
