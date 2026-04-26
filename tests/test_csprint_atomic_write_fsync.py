"""C-sprint deep-review regression: fsync on atomic-write helpers.

Pins that all six targeted atomic-write sites call ``fh.flush()`` and
``os.fsync()`` *before* ``os.replace()``. Without that, a power failure
between the kernel-buffer write and the on-disk sync can leave a
truncated/empty JSON or JSONL artefact even though ``os.replace()`` has
returned (the rename is atomic, but the rename can land before the data
has been physically synced — POSIX guarantees ordering only after fsync).

The C-sprint deep-review found the ``run_drift_watchdog._atomic_write``
helper had this fsync but four sibling helpers in the same shipping batch
(compute_live_drift, build_track_record_gate, backfill_live_outcomes,
run_smc_live_incubation) did not. That asymmetry is a real durability
gap because the consumers of those artefacts (drift watchdog, dashboard,
calibration producers, live-incubation audit) all assume the file is
fully on disk once it appears.

The two pre-existing reference implementations (``run_drift_watchdog``
and ``open_prep/outcomes``) are pinned alongside the four newly-fixed
sites so the contract stays uniform across the batch.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TARGETS = [
    "scripts/compute_live_drift.py",
    "scripts/build_track_record_gate.py",
    "scripts/backfill_live_outcomes.py",
    "scripts/run_smc_live_incubation.py",
    "scripts/run_drift_watchdog.py",
    "open_prep/outcomes.py",
]


def _stmt_contains_os_replace(stmt: ast.stmt) -> bool:
    """Return True iff ``stmt`` contains a call to ``os.replace(...)``."""

    for sub in ast.walk(stmt):
        if (
            isinstance(sub, ast.Call)
            and isinstance(sub.func, ast.Attribute)
            and sub.func.attr == "replace"
            and isinstance(sub.func.value, ast.Name)
            and sub.func.value.id == "os"
        ):
            return True
    return False


def _collect_replace_blocks(tree: ast.Module) -> list[tuple[list[ast.stmt], int]]:
    """Find every ``try:`` whose ``body`` (success path) contains ``os.replace(...)``.

    Returns a list of ``(body, replace_stmt_idx)`` pairs. Only ``node.body``
    is scanned — ``except``/``finally`` clauses are intentionally ignored
    because the durability invariant only applies to the success path.
    """

    blocks: list[tuple[list[ast.stmt], int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for idx, stmt in enumerate(node.body):
            if _stmt_contains_os_replace(stmt):
                blocks.append((node.body, idx))
                break
    return blocks


def _stmts_call_attr(stmts: list[ast.stmt], attr: str) -> bool:
    """True iff any statement in ``stmts`` invokes a call ``something.<attr>(...)``."""

    for stmt in stmts:
        for sub in ast.walk(stmt):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == attr
            ):
                return True
    return False


@pytest.mark.parametrize("relpath", _TARGETS)
def test_atomic_write_helper_fsyncs_before_replace(relpath: str) -> None:
    """Every ``os.replace``-based atomic write site must flush + fsync *before* it."""

    path = Path(__file__).resolve().parent.parent / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"))
    blocks = _collect_replace_blocks(tree)
    assert blocks, f"{relpath}: no try/os.replace block found — check refactor"
    for body, replace_idx in blocks:
        preceding = body[:replace_idx]
        assert _stmts_call_attr(preceding, "flush"), (
            f"{relpath}: fh.flush() must be called in a statement *preceding* "
            f"os.replace() inside the same try-block (replace at body idx {replace_idx})"
        )
        assert _stmts_call_attr(preceding, "fsync"), (
            f"{relpath}: os.fsync() must be called in a statement *preceding* "
            f"os.replace() inside the same try-block (replace at body idx {replace_idx})"
        )
