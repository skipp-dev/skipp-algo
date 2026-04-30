"""ADR-0005 enforcement: pure-stdlib measurement runtime.

ADR ``docs/adr/0005-pure-stdlib-measurement-runtime.md`` constrains the
measurement runtime to the Python 3.13 standard library. Without an
automated guard, a future contributor could quietly add
``import numpy``/``scipy``/``pandas``/``statsmodels`` and re-introduce
the heavy-dependency footprint the ADR forbids.

This module parses each runtime file with ``ast`` (no execution) and
asserts the AST contains no ``import``/``from`` of the banned modules.
The guard is intentionally a *static* AST check rather than a runtime
import-block: the runtime files must remain importable in a stdlib-only
environment, and an AST scan is the cheapest way to enforce that
without a sandboxed import.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

# Files covered by ADR-0005's "measurement runtime" definition.
RUNTIME_FILES = (
    REPO_ROOT / "scripts" / "run_ab_comparison.py",
    REPO_ROOT / "scripts" / "smc_sprt_stop_rule.py",
)

# Modules explicitly forbidden by ADR-0005. The ban applies to top-level
# names; sub-imports (``numpy.linalg``) are caught via the root match.
BANNED_ROOTS = frozenset({
    "numpy",
    "scipy",
    "pandas",
    "statsmodels",
    "sklearn",
    "torch",
    "tensorflow",
})


def _collect_imported_roots(source: str) -> set[str]:
    """Return the set of top-level module names imported in *source*."""
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        # ImportFrom.module is None for "from . import x" — skip
        # those; relative imports cannot reach a banned root.
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


@pytest.mark.parametrize(
    "runtime_file",
    RUNTIME_FILES,
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_measurement_runtime_uses_only_stdlib(runtime_file: Path) -> None:
    """ADR-0005: the listed file must not import any banned heavy dependency."""
    assert runtime_file.is_file(), (
        f"ADR-0005 runtime file missing: {runtime_file}. "
        "Update RUNTIME_FILES in this test or restore the file."
    )
    source = runtime_file.read_text(encoding="utf-8")
    imported = _collect_imported_roots(source)
    banned_used = imported & BANNED_ROOTS
    assert not banned_used, (
        f"ADR-0005 violation in {runtime_file.relative_to(REPO_ROOT)}: "
        f"banned imports {sorted(banned_used)}. The measurement runtime "
        "must remain pure-stdlib. If you intentionally lift this "
        "constraint, supersede ADR-0005 first and update RUNTIME_FILES "
        "or BANNED_ROOTS in tests/test_adr_0005_pure_stdlib_runtime.py."
    )
