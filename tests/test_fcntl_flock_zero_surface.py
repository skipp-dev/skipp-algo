"""Zero-surface pin for ``fcntl.flock(...)`` advisory file locks.

Pins every production ``fcntl.flock`` call by ``(path, line, lock_op)``.

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

Today exactly five production/script modules acquire/release advisory locks.
:data:`FCNTL_FLOCK_ALLOWED` is the authority for the line numbers; the list
below names the modules and their purpose only, so it cannot drift out of date
the way a duplicated line reference does:

* ``open_prep/realtime_signals.py`` (``LOCK_EX|LOCK_NB`` + ``LOCK_UN``) —
  daemon PID-file singleton lock.
* ``open_prep/watchlist.py`` (``LOCK_EX`` + ``LOCK_UN``) —
  watchlist read/write critical section.
* ``scripts/ib_client_id.py`` uses guarded POSIX ``flock`` for the IBKR
    client-id registry (two ``LOCK_EX|LOCK_NB`` + ``LOCK_UN`` pairs) and falls
    back to random allocation when ``fcntl`` is not available
    (Windows/self-hosted portability path).
* ``scripts/collect_drift_calibration_corpus.py`` (``LOCK_EX`` + ``LOCK_UN``)
  — corpus deduplication writer.
* ``databento_reference.py`` (``LOCK_EX`` + ``LOCK_UN``) — reference-cache
  interprocess lock.

A new ``flock`` caller forces a deliberate allow-list update and a
matching unlock-pair review.

Defense-only — no production changes.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_production_py_files, parse_module

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
    return iter_production_py_files(_DIR_EXCLUDE)


def _flock_operation(node: ast.Call) -> str:
    """Normalise the lock-operation argument of an ``fcntl.flock(fd, OP)`` call.

    Returns a canonical string such as ``"LOCK_EX|LOCK_NB"`` or ``"LOCK_UN"``,
    with the flags sorted so ``LOCK_NB | LOCK_EX`` and ``LOCK_EX | LOCK_NB``
    normalise to the same value (the pin should bind the semantics, not the
    author's flag order). Anything not built purely out of ``fcntl.LOCK_*``
    constants is returned verbatim so the ledger comparison rejects it: a
    dynamic operation cannot be reviewed statically.
    """
    if len(node.args) < 2:
        return f"malformed: {ast.unparse(node)}"

    def flags(expr: ast.expr) -> list[str] | None:
        # fcntl.LOCK_EX  /  LOCK_EX (from-import form; the alias pin bans it,
        # but classify rather than crash if it ever appears)
        if isinstance(expr, ast.Attribute) and expr.attr.startswith("LOCK_"):
            return [expr.attr]
        if isinstance(expr, ast.Name) and expr.id.startswith("LOCK_"):
            return [expr.id]
        # LOCK_EX | LOCK_NB
        if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.BitOr):
            left, right = flags(expr.left), flags(expr.right)
            if left is None or right is None:
                return None
            return left + right
        return None

    parsed = flags(node.args[1])
    if parsed is None:
        return f"dynamic: {ast.unparse(node.args[1])}"
    return "|".join(sorted(parsed))


def _fcntl_flock_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, operation)}`` for every ``fcntl.flock(...)`` call.

    The operation is part of the tuple (2026-07-15) because pinning only
    ``(path, lineno)`` bound WHERE a lock leg sits but never WHICH operation it
    performs — so mutating an allow-listed leg in place, ``LOCK_UN`` ->
    ``LOCK_EX``, turned a release into a second exclusive acquire while the pin
    stayed green. That is precisely the "mis-matched LOCK_EX / LOCK_UN pairs
    cause silent deadlocks" failure this module's docstring names as its reason
    to exist. Verified: that mutation passed before the operation was pinned.

    Detects only the ``fcntl.flock`` shape: an attribute call whose receiver is
    exactly ``Name('fcntl')``. Aliased imports (``import fcntl as f``) and
    direct imports (``from fcntl import flock``) are out of scope here — the
    companion ``test_fcntl_alias_import_zero_surface_pin`` fails closed if
    either form appears in production code, so they cannot be used to silently
    bypass this pin.
    """

    sites: set[tuple[str, int, str]] = set()
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
            sites.add(
                (path.relative_to(ROOT).as_posix(), node.lineno, _flock_operation(node))
            )
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
#
# 2026-07-15: the operation is now the third tuple element and is ENFORCED.
# It used to be a trailing `# LOCK_UN` comment, i.e. documentation the test
# never read — so an allow-listed release could be mutated into a second
# exclusive acquire (LOCK_UN -> LOCK_EX) at the same line and the pin stayed
# green, which is the exact deadlock this module exists to prevent. Flags are
# sorted, so "LOCK_EX|LOCK_NB" also covers `LOCK_NB | LOCK_EX`.
FCNTL_FLOCK_ALLOWED: set[tuple[str, int, str]] = {
    # Realtime-signals daemon PID-file singleton lock.
    # 2026-07-15 (reconcile): 294/321 -> 310/337. Pure drift -- the file still holds
    # exactly 2 flock legs and the EX/UN pairing is intact; #3584/#3587 edited above.
    ("open_prep/realtime_signals.py", 312, "LOCK_EX|LOCK_NB"),  # 2026-07-25 (databento-signal-migration): 311->312
    ("open_prep/realtime_signals.py", 339, "LOCK_UN"),  # 2026-07-25 (databento-signal-migration): 338->339
    # Watchlist read/write critical section.
    ("open_prep/watchlist.py", 47, "LOCK_EX"),  # 2026-07-27 (docstring adoption/persistence note above): 41->47
    ("open_prep/watchlist.py", 50, "LOCK_UN"),  # 2026-07-27 (docstring adoption/persistence note above): 44->50
    # IBKR client-id registry lease lock (guarded; random fallback on no fcntl).
    # 2026-07-15 (reconcile): 151/195/215/227 -> 175/219/239/251. Pure drift -- still
    # exactly 4 legs, still two EX/UN pairs in the same order.
    # 2026-08-18 (B7 reaper keeps live pids): 175/219/239/251 -> 188/232/252/264.
    # Pure drift from the longer _reap_stale body above; legs unchanged.
    ("scripts/ib_client_id.py", 188, "LOCK_EX|LOCK_NB"),
    ("scripts/ib_client_id.py", 232, "LOCK_UN"),
    ("scripts/ib_client_id.py", 252, "LOCK_EX|LOCK_NB"),
    ("scripts/ib_client_id.py", 264, "LOCK_UN"),
    # Corpus deduplication writer: POSIX-guarded try/except ImportError;
    # LOCK_EX acquired before checking existing keys, LOCK_UN in finally.
    # Line numbers updated 2026-06-17: written=0 initialised before the
    # with-block (bug-fix: function was returning None instead of int).
    ("scripts/collect_drift_calibration_corpus.py", 171, "LOCK_EX"),
    ("scripts/collect_drift_calibration_corpus.py", 189, "LOCK_UN"),
    # Databento reference-cache interprocess lock (advisory, POSIX-guarded exception/import).
    ("databento_reference.py", 163, "LOCK_EX"),  # 2026-08-18 (D7 retry helper above): 127->163
    ("databento_reference.py", 167, "LOCK_UN"),  # 2026-08-18 (D7 retry helper above): 131->167
    # Monthly Databento usage snapshot: POSIX-guarded advisory lock around
    # read/merge/atomic-replace, with release in the context manager finally.
    ("databento_usage.py", 189, "LOCK_EX"),
    ("databento_usage.py", 197, "LOCK_UN"),
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
        "Unreviewed ``fcntl.flock(...)`` leg detected — either a NEW call site, "
        "or an allow-listed one whose OPERATION changed (the third tuple "
        "element). A changed operation is the more dangerous case: turning a "
        "``LOCK_UN`` into a ``LOCK_EX`` in place converts a release into a "
        "second exclusive acquire, which is exactly the silent deadlock this "
        "pin exists to prevent, and it leaves the line number untouched. "
        "``flock`` is also POSIX-only and breaks Windows portability silently. "
        "If a new locking caller is genuinely required, wrap the import behind "
        "an availability guard (mirror the ``open_prep/watchlist.py`` "
        "ImportError-fallback pattern), ensure every acquire is paired with a "
        "release in a ``try``/``finally``, and append BOTH legs (lock + unlock) "
        "to FCNTL_FLOCK_ALLOWED with a justification in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = FCNTL_FLOCK_ALLOWED - sites
    assert not missing, (
        "FCNTL_FLOCK_ALLOWED entries no longer present at the "
        "recorded (path, line, lock_op). Update the allow-list to match the "
        "current call sites and re-verify lock/unlock pairing is "
        "intact.\n"
        f"missing = {sorted(missing)}"
    )


def test_fcntl_flock_acquire_release_legs_balanced() -> None:
    """Each locking module must release every lock it acquires.

    #3678 made each leg's operation checkable, which proves every leg is
    *reviewed* — not that the legs still balance. This module's docstring names
    mis-matched ``LOCK_EX`` / ``LOCK_UN`` pairs as a reason the surface is
    pinned at all, so count them: an acquire whose release leg was dropped from
    both the code and the allow-list (the coordinated edit that keeps a
    per-site pin green) fails here.

    A static count, not a control-flow proof: it cannot show the release
    actually runs on every path — that is what the ``try``/``finally``
    convention in each caller is for. It does fail closed on the common shape.
    """

    acquired: dict[str, int] = {}
    released: dict[str, int] = {}
    for rel, _lineno, op in FCNTL_FLOCK_ALLOWED:
        legs = op.split("|")
        if "LOCK_UN" in legs:
            released[rel] = released.get(rel, 0) + 1
        elif "LOCK_EX" in legs or "LOCK_SH" in legs:
            acquired[rel] = acquired.get(rel, 0) + 1

    unbalanced = sorted(
        (rel, acquired.get(rel, 0), released.get(rel, 0))
        for rel in set(acquired) | set(released)
        if acquired.get(rel, 0) != released.get(rel, 0)
    )
    assert not unbalanced, (
        "Advisory-lock legs do not balance per module: every LOCK_EX / LOCK_SH "
        "acquire needs a matching LOCK_UN release, or the file descriptor "
        "outlives the process and the next run deadlocks. Pair the legs in a "
        "try/finally and record both in FCNTL_FLOCK_ALLOWED.\n"
        f"(path, acquires, releases) = {unbalanced}"
    )
