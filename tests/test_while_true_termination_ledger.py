"""Defense ledger: ``while True:`` loops.

Pins every ``while True:`` loop in production by ``(path, line)``.
Each entry is a deliberate, reviewed long-lived loop (poller,
watcher, websocket runner, or signal-driven main loop). Adding a
new one becomes a deliberate change instead of a copy-paste.

Unbounded loops are a ``CWE-835`` surface (loop with unreachable
exit condition) and the most common refactoring foot-gun is to
remove the only ``break``/``return``/``raise`` from the body. The
ledger forces a re-review at the call site.

Note on termination: a strict body-must-contain-break invariant was
considered and rejected because some legitimate signal-driven main
loops here rely on ``KeyboardInterrupt`` propagating out of an
outer ``try``/``except KeyboardInterrupt`` (e.g.
``newsstack_fmp/pipeline.py:850``). Such loops have no in-body
exit but DO terminate cleanly. Pinning the (path, line) is the
right primitive.

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


def _while_true_sites() -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for path in _iter_py_files():
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.While):
                continue
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                out.add((str(path.relative_to(ROOT)), node.lineno))
    return out


# Locked surface — every entry is a reviewed long-lived loop.
WHILE_TRUE_LEDGER: set[tuple[str, int]] = {
    ("databento_volatility_screener.py", 1052),
    ("terminal_background_poller.py", 183),
    ("terminal_background_poller.py", 379),
    ("databento_universe.py", 247),
    ("open_prep/realtime_signals.py", 2662),
    ("open_prep/macro.py", 84),
    ("smc_core/resilient.py", 86),
    ("newsstack_fmp/ingest_benzinga.py", 515),
    ("newsstack_fmp/shared_fetch.py", 266),
    ("newsstack_fmp/pipeline.py", 886),
}


def test_while_true_site_ledger_pin() -> None:
    sites = _while_true_sites()

    unexpected = sites - WHILE_TRUE_LEDGER
    assert not unexpected, (
        "New ``while True:`` loop detected in production code. "
        "Unbounded loops are a CWE-835 surface (loop with unreachable "
        "exit condition) and must be a deliberate, reviewed addition. "
        "If this is a legitimate new poller / watcher / runner, "
        "append the (path, line) tuple to WHILE_TRUE_LEDGER and "
        "ensure the body contains a documented exit path "
        "(``break``, ``return``, or ``raise``).\n"
        f"unexpected = {sorted(unexpected)}"
    )

    missing = WHILE_TRUE_LEDGER - sites
    assert not missing, (
        "WHILE_TRUE_LEDGER entries no longer present at the recorded "
        "(path, line). Update the ledger to match the current call "
        "sites and verify the underlying loop semantics are unchanged.\n"
        f"missing = {sorted(missing)}"
    )
