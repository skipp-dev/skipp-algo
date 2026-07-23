"""Zero-surface pin for ``globals()`` calls in production code.

``globals()`` returns the live module namespace dictionary. Reading from
it is harmless in isolation, but every call site is a vector for:

* late-bound state that defeats static analysis (Pyright/Pylance can no
  longer prove which symbols exist), making refactors more dangerous;
* hidden coupling between unrelated code paths via implicit module
  globals — exactly the pattern the rest of the codebase has been moving
  away from with explicit dataclass / TypedDict state layers;
* future ``globals()[name] = ...`` mutation if a contributor copies the
  pattern, which silently bypasses the import system and breaks the
  ``__all__`` export contract.

The whole repo currently allow-lists three production ``globals()``
call sites:

* a read-only ``globals().get("_INTEL_ENABLED", False)`` lookup inside
  the Streamlit terminal, where the symbol is bound by the sidebar
  toggle block above; and
* two ``globals()[name] = ...`` mutation sites inside
  ``terminal_tabs/__init__.py`` that implement a lazy-import
  ``__getattr__`` cache for optional tab modules (the import + cache
  is the *only* time those entries are written).

Lock that surface in so any new ``globals()`` use — read or write —
becomes a deliberate, reviewed change.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

ROOT = Path(__file__).resolve().parents[1]

_DIR_EXCLUDE = {
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
    "tests",
    "SMC++",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _globals_write_linenos(tree: ast.AST) -> set[int]:
    """Linenos of ``globals()`` calls whose result is used to WRITE the namespace.

    Shapes: ``globals()[k] = v`` / ``del globals()[k]`` (Subscript in a Store or
    Del context) and ``globals().update(...)`` and friends.
    """
    write_methods = {"update", "setdefault", "pop", "popitem", "clear"}
    out: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript) and _is_globals_call(node.value):
            if isinstance(node.ctx, (ast.Store, ast.Del)):
                out.add(node.value.lineno)
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in write_methods
            and _is_globals_call(node.func.value)
        ):
            out.add(node.func.value.lineno)
    return out


def _is_globals_call(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "globals"
    )


def _globals_call_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, kind)}`` for every ``globals()`` call.

    ``kind`` is ``"read"`` or ``"write"`` and is part of the pinned tuple since
    2026-07-15. The ledger pinned ``(path, lineno)`` only, so the read/write
    distinction — which is this module's entire thesis, and the property the
    streamlit entry's "Read-only ... no mutation" comment asserts — was never
    checked. Rewriting that allow-listed lookup in place to
    ``globals()["_INTEL_ENABLED"] = True`` kept the tuple identical and the pin
    green (verified). The two ``terminal_tabs`` writes are documented in the
    header and stay: pinning the kind is what tells them apart from a read that
    silently became a write.
    """

    sites: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        writes = _globals_write_linenos(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != "globals":
                continue
            kind = "write" if node.lineno in writes else "read"
            # POSIX form keeps the ledger stable across OSes (#2244).
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno, kind))
    return sites


# Allow-listed callers (mix of read and controlled write):
#   * ``streamlit_terminal.py`` — read-only ``globals().get("_INTEL_ENABLED",
#     False)``. The lookup target is set by the sidebar toggle block higher
#     up in the file before any tab content renders.
#   * ``terminal_tabs/__init__.py`` — lazy-loaded tab module pattern:
#     ``__getattr__`` resolves a tab name by importing the underlying module
#     on demand and caching the result (or ``None`` if the optional dep is
#     missing) into the package globals via ``globals()[name] = ...`` so
#     subsequent attribute lookups skip the import path.
# Adding a new caller is almost always wrong — prefer explicit module-level
# state or a dataclass/TypedDict context object (see
# ``terminal_attention_state`` / ``terminal_posture_state`` for the
# established pattern).
GLOBALS_CALL_ALLOWED: set[tuple[str, int, str]] = {
    # Sidebar-toggle bridge: _INTEL_ENABLED is set in the sidebar render
    # block and read by tab content rendered later in the same script
    # pass. Read-only globals().get(...) lookup, no mutation.
    # Line shifted 2225 → 2230 (F-V8-cutover branch, 2026-05-18).
    # 2026-07-15: "read" is now the THIRD tuple element and enforced — the
    # no-mutation claim above used to be prose the collector never read.
    ("streamlit_terminal.py", 2301, "read"),  # 2026-07-23 (News Ingest label + sidebar source lines above): 2287->2301
    # The two documented lazy-import writes (PEP 562 module __getattr__ caches
    # the resolved render fn, or None when the trader dep is absent). Pinned as
    # "write" so they stay distinguishable from a read that turned into one.
    ("terminal_tabs/__init__.py", 57, "write"),
    ("terminal_tabs/__init__.py", 60, "write"),
}


def test_globals_call_zero_surface_pin() -> None:
    sites = _globals_call_sites()

    unexpected = sites - GLOBALS_CALL_ALLOWED
    assert not unexpected, (
        "Unreviewed globals() site: either a NEW call, or an allow-listed one "
        "whose KIND changed (the third tuple element). A read that became a "
        "write is the dangerous one — it bypasses the import system while the "
        "line number stays put. ``globals()`` defeats static "
        "analysis and is a stepping stone toward ``globals()[name] = ...`` "
        "mutation. Prefer explicit module-level state or a dataclass / "
        "TypedDict context object (see terminal_attention_state / "
        "terminal_posture_state for the pattern). If a new caller is "
        "genuinely required, add the (path, line) pair to "
        "GLOBALS_CALL_ALLOWED with a justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = GLOBALS_CALL_ALLOWED - sites
    assert not missing, (
        "GLOBALS_CALL_ALLOWED entries no longer present in code. Update the "
        "allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )
