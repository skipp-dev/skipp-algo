"""Audit pins: dynamic-import budget + TODO/FIXME zero-tripwire.

Two cheap defense pins over the same first-party AST/text walk:

1. **`__import__("...")` budget.**

   Direct calls to ``__import__`` (instead of ``import`` at module top
   or ``importlib.import_module``) hide the dependency from static
   analysis, linters, dependency graphs, and test-discovery.  They are
   sometimes legitimate (e.g. lazy-importing inside hot paths in a
   Streamlit reload context to dodge import cycles), but every new
   instance deserves a deliberate review.  Inventory frozen at the 5
   known sites (all in ``open_prep/streamlit_monitor.py`` for lazy
   ``time.{time,monotonic}`` access inside Streamlit runtime fences).

2. **TODO/FIXME/XXX/HACK tripwire.**

   Production code currently contains zero of these markers (they live
   in ``docs/``, ``scripts/`` and tests).  Pure tripwire — any new
   marker in production code fails the test and forces a deliberate
   choice: file an issue, fix it now, or move the comment to the
   tracking doc.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module

_REPO_ROOT = Path(__file__).resolve().parent.parent

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


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


# ---------------------------------------------------------------------------
# Pin 1: __import__("...") frozen-inventory budget.
# ---------------------------------------------------------------------------


def _is_dunder_import_call(node: ast.Call) -> bool:
    func = node.func
    return isinstance(func, ast.Name) and func.id == "__import__"


def _all_dunder_import_sites() -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        tree = parse_module(path)
        if tree is None:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_dunder_import_call(node):
                out.append((rel, node.lineno))
    return out


_FROZEN_DUNDER_IMPORT_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        # Line numbers refreshed 2026-06-13 after Audit E-1 RS logging
        # instrumentation in streamlit_monitor.py shifted the lazy imports.
        # Same 5 lazy ``time`` imports inside the Streamlit re-render loop;
        # no semantic change.
        ("open_prep/streamlit_monitor.py", 1267),
        ("open_prep/streamlit_monitor.py", 1279),
        ("open_prep/streamlit_monitor.py", 1318),
        ("open_prep/streamlit_monitor.py", 1321),
        ("open_prep/streamlit_monitor.py", 1346),
    }
)


def test_no_new_dunder_import_sites() -> None:
    """Tripwire: every new ``__import__("...")`` call needs review + ledgering."""
    current = set(_all_dunder_import_sites())
    new_sites = sorted(current - _FROZEN_DUNDER_IMPORT_SITES)
    assert not new_sites, (
        "New ``__import__(...)`` call site detected — prefer a top-level "
        "``import`` or ``importlib.import_module(...)`` so static analysis "
        "and dependency graphs see the dependency. If the lazy-import is "
        "intentional (e.g. dodging a circular import inside a hot "
        "Streamlit re-render), extend _FROZEN_DUNDER_IMPORT_SITES with "
        "the new (file, line) tuple:\n  - "
        + "\n  - ".join(f"{rel}:{lineno}" for rel, lineno in new_sites)
    )


@pytest.mark.parametrize(("rel", "lineno"), sorted(_FROZEN_DUNDER_IMPORT_SITES))
def test_frozen_dunder_import_site_still_present(rel: str, lineno: int) -> None:
    """Stale guard: every ledger entry must still match a ``__import__`` call."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    tree = parse_module(path)
    assert tree is not None, f"{rel} no longer parses — refresh frozen ledger"
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.lineno == lineno
            and _is_dunder_import_call(node)
        ):
            return
    raise AssertionError(
        f"{rel}:{lineno}: ``__import__(...)`` no longer present — "
        f"refresh _FROZEN_DUNDER_IMPORT_SITES."
    )


def test_dunder_import_inventory_parity() -> None:
    """Bidirectional parity: ledger ∪ scan must be identical."""
    current = set(_all_dunder_import_sites())
    missing_from_ledger = current - _FROZEN_DUNDER_IMPORT_SITES
    stale_in_ledger = _FROZEN_DUNDER_IMPORT_SITES - current
    assert not missing_from_ledger and not stale_in_ledger, (
        f"__import__ ledger drift: "
        f"new={sorted(missing_from_ledger)} "
        f"stale={sorted(stale_in_ledger)}"
    )


# ---------------------------------------------------------------------------
# Pin 2: TODO/FIXME/XXX/HACK zero-tripwire in production comments.
# ---------------------------------------------------------------------------

# Whole-word match in a comment — leading ``#`` plus the marker as a
# standalone token. Avoids hitting strings / identifiers like ``TODO_LIST``.
_MARKER_RE = re.compile(r"#[^\n]*\b(TODO|FIXME|XXX|HACK)\b")


def _all_marker_sites() -> list[tuple[str, int, str]]:
    sites: list[tuple[str, int, str]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:  # pragma: no cover - defensive
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            match = _MARKER_RE.search(line)
            if match:
                sites.append((rel, lineno, match.group(1)))
    return sites


def test_no_todo_fixme_markers_in_production() -> None:
    """Zero-tripwire: TODO/FIXME/XXX/HACK belongs in trackers and docs/, not prod."""
    sites = _all_marker_sites()
    assert not sites, (
        "Production code contains TODO/FIXME/XXX/HACK comments — file an "
        "issue, fix the code, or move the note to docs/ / the tracker:\n  - "
        + "\n  - ".join(f"{rel}:{lineno} ({marker})" for rel, lineno, marker in sites)
    )


# ---------------------------------------------------------------------------
# Path-drift sanity (shared).
# ---------------------------------------------------------------------------


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
