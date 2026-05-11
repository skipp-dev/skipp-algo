"""Defense ledger for ``os.unlink(...)`` / ``os.remove(...)`` call sites.

File deletion is destructive and irreversible. The repository currently
has 23 production call sites across the open-prep pipeline, the
terminal export module, and a couple of newsstack helpers. Locking
those locations with a ledger means:

* drift detection — any line shift in these files surfaces here so the
  responsible PR explicitly acknowledges the change (the same drift
  protection used by ``test_hashlib_weak_hash_ledger.py`` and
  ``test_nonlocal_budget.py``);
* growth gate — adding a new ``os.remove`` / ``os.unlink`` caller in
  production becomes a deliberate, reviewed action with the
  justification recorded in the ledger entry;
* surface awareness — the ledger doubles as a quick map of every place
  the codebase deletes a file, useful for audits.

Note: ``shutil.rmtree(...)`` is already pinned by
``tests/test_dangerous_io_zero_surface_pin.py`` (allow-listed only
inside ``scripts/``). This ledger is the single-file complement.
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


def _os_delete_sites() -> set[tuple[str, int, str]]:
    """Return ``{(relpath, lineno, attr)}`` for every ``os.unlink(...)``
    or ``os.remove(...)`` call. ``attr`` is the literal method name so
    the ledger pins the chosen API, not just the line.
    """

    sites: set[tuple[str, int, str]] = set()
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
            if func.attr not in ("unlink", "remove"):
                continue
            value = func.value
            if not isinstance(value, ast.Name) or value.id != "os":
                continue
            sites.add((str(path.relative_to(ROOT)), node.lineno, func.attr))
    return sites


# Locked ledger of every production ``os.unlink`` / ``os.remove`` site.
# Adding a new caller? Append the (path, line, attr) tuple in the same
# PR with a justification in the commit message and prefer wrapping the
# call in a ``try / except FileNotFoundError`` (or ``Path.unlink(missing_ok=True)``)
# so a stale handle never crashes the caller.
OS_DELETE_LEDGER: set[tuple[str, int, str]] = {
    ("newsstack_fmp/open_prep_export.py", 35, "unlink"),
    ("newsstack_fmp/store_sqlite.py", 143, "remove"),
    ("open_prep/alerts.py", 79, "unlink"),
    ("open_prep/candidate_weights.py", 154, "unlink"),
    ("open_prep/diff.py", 68, "unlink"),
    ("open_prep/feature_importance_report.py", 256, "unlink"),
    ("open_prep/outcome_backfill.py", 97, "unlink"),
    ("open_prep/outcome_backfill.py", 539, "unlink"),
    ("open_prep/outcomes.py", 130, "unlink"),
    ("open_prep/outcomes.py", 408, "unlink"),
    ("open_prep/realtime_signals.py", 117, "remove"),
    ("open_prep/realtime_signals.py", 2512, "unlink"),
    ("open_prep/realtime_signals.py", 2551, "unlink"),
    ("open_prep/run_open_prep.py", 2217, "unlink"),
    ("open_prep/run_open_prep.py", 3013, "unlink"),
    ("open_prep/run_open_prep.py", 3349, "unlink"),
    ("open_prep/run_open_prep.py", 5684, "unlink"),
    ("open_prep/scorer.py", 145, "unlink"),
    ("open_prep/watchlist.py", 74, "unlink"),
    ("terminal_export.py", 186, "unlink"),
    ("terminal_export.py", 236, "unlink"),
    ("terminal_export.py", 618, "unlink"),
    ("terminal_export.py", 759, "unlink"),
}


def test_os_delete_ledger_exact() -> None:
    sites = _os_delete_sites()

    unexpected = sites - OS_DELETE_LEDGER
    assert not unexpected, (
        "New / drifted os.unlink(...) or os.remove(...) call site detected. "
        "File deletion is destructive — add the (path, line, attr) entry "
        "to OS_DELETE_LEDGER with a justification in the commit message "
        "and prefer wrapping the call to tolerate already-missing files "
        "(``Path.unlink(missing_ok=True)`` or "
        "``except FileNotFoundError``).\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = OS_DELETE_LEDGER - sites
    assert not missing, (
        "OS_DELETE_LEDGER entries no longer present in code. If a "
        "deletion call was deliberately removed, drop the matching "
        "tuple from the ledger.\n"
        f"missing = {sorted(missing)}"
    )
