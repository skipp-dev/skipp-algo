"""Defense ledger: ``subprocess.run`` / ``subprocess.Popen`` call-sites.

Pins every production process-spawn call by ``(path, line)``. Every
entry is a deliberate, reviewed external command invocation. New
spawns must be a reviewed change instead of a copy-paste.

Why pin sites (in addition to the existing kwarg-shape invariants):

* ``test_subprocess_run_check_invariant.py`` already enforces
  ``check=`` is passed.
* ``test_dangerous_call_tripwires.py`` /
  ``test_shell_true_tripwire.py`` already ban ``shell=True``.
* But neither covers *where* commands are spawned. The site ledger
  is the missing piece — it surfaces drift, doubles as a one-grep
  audit of every place we shell out, and forces a reviewer to ask
  "is this new shell-out actually necessary?".

Today the entire production tree spawns external commands from
exactly three locations:

* ``smc_integration/release_policy.py:1066`` — read git HEAD SHA
  (``git rev-parse HEAD``) for release manifest provenance.
* ``open_prep/realtime_signals.py:181`` — locate the realtime
  signals daemon by scanning the process list (``pgrep``).
* ``open_prep/realtime_signals.py:325`` — re-launch the realtime
  signals daemon as a detached child (``Popen`` of
  ``python -m open_prep.realtime_signals``).

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


def _subprocess_attr_sites(attr: str) -> set[tuple[str, int]]:
    """Return ``{(relpath, lineno)}`` for ``subprocess.<attr>(...)`` calls."""

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
            if not (isinstance(func.value, ast.Name) and func.value.id == "subprocess"):
                continue
            sites.add((str(path.relative_to(ROOT)), node.lineno))
    return sites


# Locked surface — every entry is a reviewed external command.
SUBPROCESS_RUN_LEDGER: set[tuple[str, int]] = {
    # `git rev-parse HEAD` for release-manifest provenance.
    ("smc_integration/release_policy.py", 1066),
    # `pgrep` to discover the realtime-signals daemon PID.
    ("open_prep/realtime_signals.py", 181),
}

SUBPROCESS_POPEN_LEDGER: set[tuple[str, int]] = {
    # Detached re-launch of the realtime-signals daemon.
    ("open_prep/realtime_signals.py", 325),
}


def test_subprocess_run_site_ledger_pin() -> None:
    sites = _subprocess_attr_sites("run")

    unexpected = sites - SUBPROCESS_RUN_LEDGER
    assert not unexpected, (
        "New ``subprocess.run(...)`` call site detected. Every shell-"
        "out is a reviewable surface — argument injection, "
        "exit-code mishandling, PATH-dependence, and platform "
        "portability are all real risks. If this is a legitimate new "
        "external command, append the (path, line) tuple to "
        "SUBPROCESS_RUN_LEDGER and document the command + safety "
        "posture (argv list, ``check=``, ``timeout=``, ``shell=False``) "
        "in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = SUBPROCESS_RUN_LEDGER - sites
    assert not missing, (
        "SUBPROCESS_RUN_LEDGER entries no longer present at the "
        "recorded (path, line). Update the ledger to match the "
        "current call sites and verify the underlying command is "
        "unchanged.\n"
        f"missing = {sorted(missing)}"
    )


def test_subprocess_popen_site_ledger_pin() -> None:
    sites = _subprocess_attr_sites("Popen")

    unexpected = sites - SUBPROCESS_POPEN_LEDGER
    assert not unexpected, (
        "New ``subprocess.Popen(...)`` call site detected. "
        "``Popen`` is even riskier than ``run`` — it spawns a "
        "long-lived child whose lifetime, stdio buffering, and "
        "termination semantics are owned by the caller. Prefer "
        "``subprocess.run`` for synchronous one-shot commands. If a "
        "detached child process is genuinely required, append the "
        "(path, line) tuple to SUBPROCESS_POPEN_LEDGER and document "
        "the lifecycle ownership in the commit message.\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = SUBPROCESS_POPEN_LEDGER - sites
    assert not missing, (
        "SUBPROCESS_POPEN_LEDGER entries no longer present at the "
        "recorded (path, line). Update the ledger to match the "
        "current call sites.\n"
        f"missing = {sorted(missing)}"
    )
