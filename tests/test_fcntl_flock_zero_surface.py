"""Zero-surface pin for ``fcntl.flock(...)`` advisory file locks.

Pins every production ``fcntl.flock`` call by ``(path, line)``.

Why pin file locks:

* ``fcntl.flock`` is POSIX-only — every new caller silently breaks
  Windows portability and the existing import-guard pattern in
  ``open_prep/watchlist.py`` (which has a documented test for the
  ``ImportError`` fallback path: ``test_open_prep.py:3603``).
* Mis-matched ``LOCK_EX`` / ``LOCK_UN`` pairs cause silent deadlocks
  on subsequent runs (file descriptor outlives the process if the
  caller forgets the unlock leg).
* ``flock`` is the only file-locking primitive used in this tree —
  every entry below is a deliberate, reviewed pair.

Today exactly three production/script modules acquire/release advisory locks:

* ``open_prep/realtime_signals.py:265`` (``LOCK_EX|LOCK_NB``) +
* ``:291`` (``LOCK_UN``) — daemon PID-file singleton lock.
* ``open_prep/watchlist.py:41`` (``LOCK_EX``) + ``:44`` (``LOCK_UN``) —
  watchlist read/write critical section.
* ``scripts/ib_client_id.py`` uses guarded POSIX ``flock`` for the IBKR
    client-id registry and falls back to random allocation when ``fcntl`` is not
    available (Windows/self-hosted portability path).

A new ``flock`` caller forces a deliberate allow-list update and a
matching unlock-pair review.

Defense-only — no production changes.
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


def _fcntl_flock_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every literal ``fcntl.flock(...)`` call.

    Detects only the ``fcntl.flock`` shape: an attribute call whose
    receiver is exactly ``Name('fcntl')``. Aliased imports
    (``import fcntl as f``) and direct imports
    (``from fcntl import flock``) are out of scope here — the companion
    ``test_fcntl_alias_import_zero_surface_pin`` fails closed if either
    form appears in production code, so they cannot be used to silently
    bypass this pin.
    """

    sites: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr != "flock":
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "fcntl"):
                continue
            sites.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return sites


def _fcntl_alias_or_direct_import_sites() -> set[tuple[str, int, str]]:
    """Return ``(path, lineno, form)`` for any aliased / direct ``fcntl`` import.

    Catches ``import fcntl as <alias>`` and ``from fcntl import <name>``,
    both of which would let a future caller bypass the literal
    ``fcntl.flock(...)`` pin. Plain ``import fcntl`` is allowed (and is
    the form used by the two existing call-site files).
    """

    found: set[tuple[str, int, str]] = set()
    for path in _iter_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "fcntl" and alias.asname:
                        found.add((rel, node.lineno, f"import fcntl as {alias.asname}"))
            elif (
                isinstance(node, ast.ImportFrom)
                and node.module == "fcntl"
                and node.level == 0
            ):
                for alias in node.names:
                    found.add((rel, node.lineno, f"from fcntl import {alias.name}"))
    return found


# Locked surface — every entry is a reviewed advisory-lock leg.
FCNTL_FLOCK_ALLOWED: set[tuple[str, int]] = {
    # Realtime-signals daemon PID-file singleton lock.
    ("open_prep/realtime_signals.py", 292),  # LOCK_EX | LOCK_NB
    ("open_prep/realtime_signals.py", 319),  # LOCK_UN
    # Watchlist read/write critical section.
    ("open_prep/watchlist.py", 41),  # LOCK_EX
    ("open_prep/watchlist.py", 44),  # LOCK_UN
    # IBKR client-id registry lease lock (guarded; random fallback on no fcntl).
    ("scripts/ib_client_id.py", 151),  # LOCK_EX | LOCK_NB
    ("scripts/ib_client_id.py", 195),  # LOCK_UN
    ("scripts/ib_client_id.py", 215),  # LOCK_EX | LOCK_NB
    ("scripts/ib_client_id.py", 227),  # LOCK_UN
    # Corpus deduplication writer: POSIX-guarded try/except ImportError;
    # LOCK_EX acquired before checking existing keys, LOCK_UN in finally.
    # Line numbers updated 2026-06-17: written=0 initialised before the
    # with-block (bug-fix: function was returning None instead of int).
    ("scripts/collect_drift_calibration_corpus.py", 171),  # LOCK_EX
    ("scripts/collect_drift_calibration_corpus.py", 189),  # LOCK_UN
    # Databento reference-cache interprocess lock (advisory, POSIX-guarded exception/import).
    ("databento_reference.py", 127),  # LOCK_EX
    ("databento_reference.py", 131),  # LOCK_UN
}


def test_fcntl_inventory_sane() -> None:
    # Guard against silent coverage loss (sparse checkout, layout change,
    # CI misconfiguration). The repo has well over 100 first-party .py
    # files; a sudden drop to a handful means the AST scan saw nothing
    # and would silently false-pass.
    files = _iter_py_files()
    assert len(files) >= 50, (
        f"first-party python file count collapsed to {len(files)} — "
        "the AST scan is likely seeing an empty tree, which would let "
        "new fcntl.flock callers slip in unnoticed."
    )


def test_fcntl_alias_import_zero_surface_pin() -> None:
    # The literal-attribute pin below only catches ``fcntl.flock(...)``.
    # Aliased imports (``import fcntl as f``) and direct imports
    # (``from fcntl import flock``) would silently bypass it.
    # Forbid both forms so the pin's narrow scope can't be circumvented.
    found = _fcntl_alias_or_direct_import_sites()
    assert not found, (
        "Aliased or direct ``fcntl`` import detected. These forms "
        "bypass the literal ``fcntl.flock(...)`` pin below. Use plain "
        "``import fcntl`` and qualified ``fcntl.flock(...)`` calls only.\n"
        f"found = {sorted(found)}"
    )


def test_fcntl_flock_zero_surface_pin() -> None:
    sites = _fcntl_flock_sites()

    unexpected = sites - FCNTL_FLOCK_ALLOWED
    assert not unexpected, (
        "New ``fcntl.flock(...)`` call site detected. ``flock`` is "
        "POSIX-only and breaks Windows portability silently; "
        "mis-matched ``LOCK_EX`` / ``LOCK_UN`` pairs cause silent "
        "deadlocks. If a new locking caller is genuinely required, "
        "wrap the import behind an availability guard (mirror the "
        "``open_prep/watchlist.py`` ImportError-fallback pattern), "
        "ensure every acquire is paired with a release in a ``try``/"
        "``finally``, and append BOTH legs (lock + unlock) to "
        "FCNTL_FLOCK_ALLOWED with a justification in the commit "
        "message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = FCNTL_FLOCK_ALLOWED - sites
    assert not missing, (
        "FCNTL_FLOCK_ALLOWED entries no longer present at the "
        "recorded (path, line). Update the allow-list to match the "
        "current call sites and re-verify lock/unlock pairing is "
        "intact.\n"
        f"missing = {sorted(missing)}"
    )
