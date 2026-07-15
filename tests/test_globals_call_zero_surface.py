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


# Dict operations that only read the namespace vs. those that mutate it.
# Anything not named here classifies as "unknown" and fails closed: the point
# of the ledger is that a new *kind* of globals() use is reviewed, and an
# unrecognised one is exactly that.
_GLOBALS_READ_ATTRS = frozenset({"get", "keys", "values", "items", "copy"})
_GLOBALS_WRITE_ATTRS = frozenset(
    {"update", "setdefault", "pop", "popitem", "clear", "__setitem__", "__delitem__"}
)


def _globals_usage(call: ast.Call, parents: dict[ast.AST, ast.AST]) -> str:
    """Classify a ``globals()`` call as ``read`` / ``write`` / ``unknown``.

    ``globals()["x"] = v`` reaches the namespace through a ``Subscript`` whose
    context is ``Store``/``Del``; ``globals().get(...)`` through an
    ``Attribute``. Everything else — most importantly handing the live dict to
    another callable, e.g. ``exec(src, globals())``, which can write anything —
    is ``unknown`` and cannot match a pinned entry.
    """

    parent = parents.get(call)
    if isinstance(parent, ast.Subscript):
        if isinstance(parent.ctx, (ast.Store, ast.Del)):
            return "write"
        if isinstance(parent.ctx, ast.Load):
            return "read"
        return "unknown"
    if isinstance(parent, ast.Attribute):
        if parent.attr in _GLOBALS_WRITE_ATTRS:
            return "write"
        if parent.attr in _GLOBALS_READ_ATTRS:
            return "read"
    return "unknown"


def _globals_call_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, usage)}`` for every ``globals()`` call.

    ``usage`` carries what this module's own allow-list comments assert per
    site — "read-only ``globals().get(...)``, no mutation" for the terminal
    bridge, "controlled write" for the lazy-import cache. A ``(path, lineno)``
    pin cannot tell those apart, so the read-only claim was decoration: turning
    that site into ``globals()["x"] = ...`` in place moves no line and kept the
    pin green. Pinning the usage is what makes the claim checkable.
    """

    sites: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        parents: dict[ast.AST, ast.AST] = {
            child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)
        }
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Name) or func.id != "globals":
                continue
            # POSIX form keeps the ledger stable across OSes (#2244).
            sites.add(
                (
                    path.relative_to(ROOT).as_posix(),
                    node.lineno,
                    _globals_usage(node, parents),
                )
            )
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
# The third element is the usage. It used to live in these comments, where
# nothing read it; 2026-07-15 promoted it into the tuple so the "no mutation"
# claim below fails instead of merging green when the site starts writing.
GLOBALS_CALL_ALLOWED: set[tuple[str, int, str]] = {
    # Sidebar-toggle bridge: _INTEL_ENABLED is set in the sidebar render
    # block and read by tab content rendered later in the same script
    # pass. Read-only globals().get(...) lookup, no mutation.
    # Line shifted 2225 → 2230 (F-V8-cutover branch, 2026-05-18).
    ("streamlit_terminal.py", 2234, "read"),
    ("terminal_tabs/__init__.py", 57, "write"),
    ("terminal_tabs/__init__.py", 60, "write"),
}


def test_globals_call_zero_surface_pin() -> None:
    sites = _globals_call_sites()

    unexpected = sites - GLOBALS_CALL_ALLOWED
    assert not unexpected, (
        "New globals() call site detected. ``globals()`` defeats static "
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
