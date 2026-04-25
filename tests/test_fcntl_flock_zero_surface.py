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

Today exactly two production modules acquire/release advisory locks:

* ``open_prep/realtime_signals.py:254`` (``LOCK_EX|LOCK_NB``) +
  ``:280`` (``LOCK_UN``) — daemon PID-file singleton lock.
* ``open_prep/watchlist.py:41`` (``LOCK_EX``) + ``:44`` (``LOCK_UN``) —
  watchlist read/write critical section.

A new ``flock`` caller forces a deliberate allow-list update and a
matching unlock-pair review.

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


def _fcntl_flock_sites() -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for every ``fcntl.flock(...)`` call."""

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
            if func.attr != "flock":
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id == "fcntl"):
                continue
            sites.add((str(path.relative_to(ROOT)), node.lineno))
    return sites


# Locked surface — every entry is a reviewed advisory-lock leg.
FCNTL_FLOCK_ALLOWED: set[tuple[str, int]] = {
    # Realtime-signals daemon PID-file singleton lock.
    ("open_prep/realtime_signals.py", 254),  # LOCK_EX | LOCK_NB
    ("open_prep/realtime_signals.py", 280),  # LOCK_UN
    # Watchlist read/write critical section.
    ("open_prep/watchlist.py", 41),  # LOCK_EX
    ("open_prep/watchlist.py", 44),  # LOCK_UN
}


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
