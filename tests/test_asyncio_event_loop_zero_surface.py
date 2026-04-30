"""Zero-surface pin for manual ``asyncio`` event-loop management.

Manually creating and installing an event loop with
``asyncio.new_event_loop()`` + ``asyncio.set_event_loop(loop)`` is a
known foot-gun:

* It is unnecessary in mainline code paths — ``asyncio.run(coro)``
  creates, installs, runs, and cleanly tears down a loop.
* It is *only* legitimate when the loop must live on a non-main
  thread (e.g. a daemon worker that owns a websocket session).
* When mis-applied it leaks loops, double-installs handlers,
  competes with ``asyncio.run`` on the same thread, and produces
  the dreaded ``RuntimeError: There is no current event loop in thread 'X'``
  / ``This event loop is already running`` failures in tests.

Today the production tree has exactly one legitimate usage pair —
the ``BenzingaWsAdapter._run_loop`` daemon-thread entry point in
``newsstack_fmp/ingest_benzinga.py``. Pinning the (path, line) of
each call means any new manual loop installation is a deliberate,
reviewed change instead of a copy-paste.

Sister of the ``threading.Thread`` ``daemon=`` invariant
(``test_thread_daemon_invariant.py``).

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

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
    "scripts",
}


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _asyncio_attr_call_sites(attr: str) -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for literal ``asyncio.<attr>(...)`` calls.

    Detects only the ``asyncio.<attr>`` shape currently used in the
    tree: an attribute call whose receiver is exactly ``Name('asyncio')``.
    This helper does *not* resolve imported aliases or direct-name imports,
    so forms like ``import asyncio as aio; aio.<attr>(...)`` and
    ``from asyncio import <attr>; <attr>(...)`` are intentionally out of
    scope for this pin — adding such a form would bypass the allow-list.
    The companion ``test_asyncio_alias_import_zero_surface_pin`` below
    fails closed if either alias form appears in production code.
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != attr:
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "asyncio"):
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


# Single legitimate caller pair: the daemon-thread entry point in the
# Benzinga websocket adapter, which owns its own loop because it lives
# off the main thread for the lifetime of the websocket session.
NEW_EVENT_LOOP_ALLOWED: set[tuple[str, int]] = {
    ("newsstack_fmp/ingest_benzinga.py", 537),
}

SET_EVENT_LOOP_ALLOWED: set[tuple[str, int]] = {
    ("newsstack_fmp/ingest_benzinga.py", 538),
}


def _asyncio_alias_or_direct_import_sites() -> set[tuple[str, int, str]]:
    """Return ``(path, lineno, form)`` for any aliased / direct ``asyncio`` import.

    Catches ``import asyncio as <alias>`` and
    ``from asyncio import <name>``, both of which would let a future
    caller bypass the literal ``asyncio.<attr>(...)`` pins.
    """

    found: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "asyncio" and alias.asname:
                        found.add((rel, node.lineno, f"import asyncio as {alias.asname}"))
            elif isinstance(node, ast.ImportFrom) and node.module == "asyncio" and node.level == 0:
                for alias in node.names:
                    found.add((rel, node.lineno, f"from asyncio import {alias.name}"))
    return found


def test_asyncio_inventory_sane() -> None:
    # Guard against silent coverage loss (sparse checkout, layout change,
    # CI misconfiguration). The repo has well over 100 first-party .py
    # files; a sudden drop to a handful means the AST scan saw nothing
    # and would silently false-pass.
    files = _iter_py_files()
    assert len(files) >= 50, (
        f"first-party python file count collapsed to {len(files)} — "
        "the AST scan is likely seeing an empty tree, which would let "
        "new asyncio.new_event_loop / set_event_loop callers slip in "
        "unnoticed."
    )


def test_asyncio_alias_import_zero_surface_pin() -> None:
    # The literal-attribute pins below only catch ``asyncio.<attr>(...)``.
    # Aliased imports (``import asyncio as aio``) and direct imports
    # (``from asyncio import new_event_loop``) would silently bypass them.
    # Forbid both forms so the pin's narrow scope can't be circumvented.
    found = _asyncio_alias_or_direct_import_sites()
    assert not found, (
        "Aliased or direct ``asyncio`` import detected. These forms "
        "bypass the literal ``asyncio.<attr>(...)`` pins below. Use "
        "plain ``import asyncio`` and qualified ``asyncio.<attr>(...)`` "
        "calls only.\n"
        f"found = {sorted(found)}"
    )


def test_asyncio_new_event_loop_zero_surface_pin() -> None:
    sites = _asyncio_attr_call_sites("new_event_loop")

    unexpected = sites - NEW_EVENT_LOOP_ALLOWED
    assert not unexpected, (
        "New ``asyncio.new_event_loop()`` call site detected. Manual "
        "loop creation is almost always wrong on the main thread — "
        "use ``asyncio.run(coro)`` instead. The only legitimate use "
        "is owning a loop on a non-main thread (e.g. a daemon worker "
        "with a websocket session). If a new caller is genuinely "
        "required, append the (path, line) tuple to "
        "NEW_EVENT_LOOP_ALLOWED with a justification in the commit "
        "message and pair it with the matching "
        "``asyncio.set_event_loop(loop)`` allow-list entry.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = NEW_EVENT_LOOP_ALLOWED - sites
    assert not missing, (
        "NEW_EVENT_LOOP_ALLOWED entries no longer present in code. "
        "Update the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )


def test_asyncio_set_event_loop_zero_surface_pin() -> None:
    sites = _asyncio_attr_call_sites("set_event_loop")

    unexpected = sites - SET_EVENT_LOOP_ALLOWED
    assert not unexpected, (
        "New ``asyncio.set_event_loop(loop)`` call site detected. "
        "Installing a loop manually is only legitimate paired with "
        "``asyncio.new_event_loop()`` in a non-main thread that owns "
        "the loop for its entire lifetime. Anything else competes "
        "with ``asyncio.run`` and produces flaky 'no current event "
        "loop in thread X' / 'This event loop is already running' "
        "failures. If a new caller is genuinely required, append the "
        "(path, line) tuple to SET_EVENT_LOOP_ALLOWED with a "
        "justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = SET_EVENT_LOOP_ALLOWED - sites
    assert not missing, (
        "SET_EVENT_LOOP_ALLOWED entries no longer present in code. "
        "Update the allow-list to match the current call sites.\n"
        f"missing = {sorted(missing)}"
    )
