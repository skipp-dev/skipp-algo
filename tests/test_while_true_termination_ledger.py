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
        tree = parse_module(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.While):
                continue
            if isinstance(node.test, ast.Constant) and node.test.value is True:
                # POSIX form keeps the ledger stable across OSes (#2244).
                out.add((path.relative_to(ROOT).as_posix(), node.lineno))
    return out


# Locked surface — every entry is a reviewed long-lived loop, pinned by
# **per-file count** (not exact line numbers).
#
# Why count, not (path, lineno):
#   The previous version of this ledger pinned each loop's exact lineno,
#   which made the test break on every unrelated edit that shifted lines
#   (the ingest_benzinga.py entry broke twice in a single day on
#   2026-04-30). The policy this guard enforces is *no growth in the
#   unbounded-loop surface*, which is fundamentally a count, not a
#   location. Refactors that move a ``while True:`` within a file are
#   now no-ops; net additions / removals still fail closed.
WHILE_TRUE_LEDGER: dict[str, int] = {
    "databento_volatility_screener.py": 1,
    # PR #2125 extracts the enqueue retry loop into bounded helper
    # ``_enqueue_batch`` (``for`` loop), leaving only the deliberate
    # ``drain()`` consumer loop as ``while True`` in this module.
    "terminal_background_poller.py": 1,
    "databento_universe.py": 1,
    "open_prep/realtime_signals.py": 1,
    # resilient retry decorator: exits via return on success, raise after
    # max retries, or return on_failure(exc) callback. CWE-835 mitigated
    # by three explicit exit paths (system review 2026-04-30).
    "smc_core/resilient.py": 1,
    "newsstack_fmp/ingest_benzinga.py": 1,
    "newsstack_fmp/shared_fetch.py": 1,
    "newsstack_fmp/pipeline.py": 1,
    # 2026-06-21: live overlay feed thread uses one deliberate long-lived
    # loop with explicit break paths (stop event + fail-fast breaker).
    "services/live_overlay_daemon/feed.py": 1,
}


def _per_file_counts(sites: set[tuple[str, int]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for rel, _ in sites:
        counts[rel] = counts.get(rel, 0) + 1
    return counts


def test_while_true_site_ledger_pin() -> None:
    counts = _per_file_counts(_while_true_sites())

    unexpected_files = sorted(set(counts) - set(WHILE_TRUE_LEDGER))
    assert not unexpected_files, (
        "New ``while True:`` loop detected in file(s) not in "
        "WHILE_TRUE_LEDGER. Unbounded loops are a CWE-835 surface (loop "
        "with unreachable exit condition) and must be a deliberate, "
        "reviewed addition. If this is a legitimate new poller / "
        "watcher / runner, append the file to WHILE_TRUE_LEDGER and "
        "ensure the body contains a documented exit path "
        "(``break``, ``return``, or ``raise``).\n  - "
        + "\n  - ".join(f"{rel} ({counts[rel]} loop(s))" for rel in unexpected_files)
    )

    missing_files = sorted(set(WHILE_TRUE_LEDGER) - set(counts))
    assert not missing_files, (
        "WHILE_TRUE_LEDGER entries no longer present in code. "
        "Update the ledger to match the current call sites and verify "
        "the underlying loop semantics are unchanged.\n  - "
        + "\n  - ".join(missing_files)
    )

    drifted = sorted(
        (rel, WHILE_TRUE_LEDGER[rel], counts[rel])
        for rel in WHILE_TRUE_LEDGER.keys() & counts.keys()
        if WHILE_TRUE_LEDGER[rel] != counts[rel]
    )
    assert not drifted, (
        "Per-file ``while True:`` count drift:\n  - "
        + "\n  - ".join(f"{rel}: ledger={ledger}, actual={actual}" for rel, ledger, actual in drifted)
        + "\nUpdate WHILE_TRUE_LEDGER with justification."
    )
