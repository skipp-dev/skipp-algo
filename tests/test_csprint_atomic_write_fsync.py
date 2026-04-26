"""C-sprint deep-review regression: fsync on atomic-write helpers.

Pins that all four C-sprint atomic-write helpers call ``fh.flush()`` and
``os.fsync()`` *before* ``os.replace()``. Without that, a power failure
between the kernel-buffer write and the on-disk sync can leave a
truncated/empty JSON or JSONL artefact even though ``os.replace()`` has
returned (the rename is atomic, but the rename can land before the data
has been physically synced — POSIX guarantees ordering only after fsync).

The C-sprint deep-review found the ``run_drift_watchdog._atomic_write``
helper had this fsync but its sibling helpers in the same shipping batch
(compute_live_drift, build_track_record_gate, backfill_live_outcomes,
run_smc_live_incubation) did not. That asymmetry is a real durability
gap because the consumers of those artefacts (drift watchdog, dashboard,
calibration producers, live-incubation audit) all assume the file is
fully on disk once it appears.
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


def _collect_replace_blocks(tree: ast.Module) -> list[list[ast.stmt]]:
    """Find every ``try:`` body that contains ``os.replace(...)``."""

    blocks: list[list[ast.stmt]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        has_replace = False
        for sub in ast.walk(node):
            if (
                isinstance(sub, ast.Call)
                and isinstance(sub.func, ast.Attribute)
                and sub.func.attr == "replace"
                and isinstance(sub.func.value, ast.Name)
                and sub.func.value.id == "os"
            ):
                has_replace = True
                break
        if has_replace:
            blocks.append(node.body)
    return blocks


def _block_calls(body: list[ast.stmt]) -> set[str]:
    """Collect attribute call names (``a.b()`` → ``"b"``) inside a block."""

    seen: set[str] = set()
    for stmt in body:
        for sub in ast.walk(stmt):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                seen.add(sub.func.attr)
    return seen


@pytest.mark.parametrize("relpath", _TARGETS)
def test_atomic_write_helper_fsyncs_before_replace(relpath: str) -> None:
    """Every ``os.replace``-based atomic write site must flush + fsync first."""

    path = Path(__file__).resolve().parent.parent / relpath
    tree = ast.parse(path.read_text(encoding="utf-8"))
    blocks = _collect_replace_blocks(tree)
    assert blocks, f"{relpath}: no try/os.replace block found — check refactor"
    for body in blocks:
        calls = _block_calls(body)
        assert "flush" in calls, (
            f"{relpath}: try-block containing os.replace must call fh.flush() "
            f"before the replace; saw calls = {sorted(calls)}"
        )
        assert "fsync" in calls, (
            f"{relpath}: try-block containing os.replace must call os.fsync() "
            f"before the replace; saw calls = {sorted(calls)}"
        )
