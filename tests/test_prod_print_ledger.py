"""Defense-pin: prod ``print()`` call-site ledger.

Most service code logs through ``logging`` for level filtering, structured
formatting, and routing. ``print()`` bypasses all of that and dumps to
stdout, which can corrupt machine-readable output channels (e.g. JSON-RPC
stdio, Pine surface reduction artifacts) and silently inflates log volume.

CLI scripts (``pine_input_surface.py``, ``pine_apply_surface_reduction.py``,
``test_usi_lint.py``) and ad-hoc reporting (``open_prep/feature_importance_report.py``,
``open_prep/candidate_weights.py``, ``open_prep/outcome_backfill.py``,
``smc_integration/provider_health.py``) legitimately use ``print``. Freeze the
exact distribution so we notice if a service module starts printing.

Defense-only, no production code changes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE = frozenset(
    {
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
        "scripts",
        "tests",
        "SMC++",
    }
)


def _iter_prod_py() -> Iterator[Path]:
    for p in ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in p.relative_to(ROOT).parts):
            continue
        yield p


# Frozen ledger: rel-path -> number of `print(...)` Call sites where the
# function is the bare Name `print` (not `pprint.print`, not `something.print`).
_FROZEN_PRINT_COUNTS: dict[str, int] = {
    "pine_apply_surface_reduction.py": 8,
    "pine_input_surface.py": 15,
    "test_usi_lint.py": 3,
    "smc_integration/provider_health.py": 1,
    "open_prep/outcome_backfill.py": 4,
    "open_prep/candidate_weights.py": 4,
    "open_prep/feature_importance_report.py": 4,
    # 2026-05-12 (#2171 audit-L-1 PR-D R12+R3): consistency check CLI tools
    # that print a human-readable findings report and exit 0/1. Both are
    # invoked as ``python tools/check_*.py`` from CI; print() is the
    # documented output channel.
    "tools/check_audit_doc_consistency.py": 4,
    "tools/check_defaults_table.py": 4,
}
_FROZEN_PRINT_TOTAL = sum(_FROZEN_PRINT_COUNTS.values())


def _scan_prints() -> dict[str, int]:
    out: dict[str, int] = {}
    for p in _iter_prod_py():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue
        n = 0
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "print"
            ):
                n += 1
        if n:
            # ``as_posix`` so Windows ``\`` doesn't desync from the POSIX-keyed ledger.
            out[p.relative_to(ROOT).as_posix()] = n
    return out


def test_prod_inventory_sane() -> None:
    files = list(_iter_prod_py())
    assert len(files) >= 30, f"prod py inventory shrank: {len(files)}"


def test_print_total_frozen() -> None:
    counts = _scan_prints()
    total = sum(counts.values())
    assert total == _FROZEN_PRINT_TOTAL, (
        f"prod print() total drifted: expected {_FROZEN_PRINT_TOTAL}, "
        f"got {total}; per-file = {counts}"
    )


def test_print_no_new_files() -> None:
    counts = _scan_prints()
    new = sorted(set(counts) - set(_FROZEN_PRINT_COUNTS))
    assert not new, (
        "New prod files use print() — switch to logging or append to "
        f"_FROZEN_PRINT_COUNTS if intentional CLI: {new}"
    )


def test_print_no_stale_entries() -> None:
    counts = _scan_prints()
    stale = sorted(set(_FROZEN_PRINT_COUNTS) - set(counts))
    assert not stale, (
        "Frozen print() ledger lists files with no remaining print() — "
        f"remove from _FROZEN_PRINT_COUNTS: {stale}"
    )


@pytest.mark.parametrize("rel,expected", sorted(_FROZEN_PRINT_COUNTS.items()))
def test_print_per_file_count(rel: str, expected: int) -> None:
    counts = _scan_prints()
    actual = counts.get(rel, 0)
    assert actual == expected, (
        f"{rel}: print() count drifted (expected {expected}, got {actual}). "
        "Review the diff and update the ledger if intentional."
    )


@pytest.mark.parametrize("rel", sorted(_FROZEN_PRINT_COUNTS))
def test_print_files_exist(rel: str) -> None:
    assert (ROOT / rel).is_file(), f"Ledger file missing: {rel}"
