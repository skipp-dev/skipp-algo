"""ADR-0005 single source of truth (pure stdlib).

The measurement-runtime file set + banned import roots + the AST import scan,
shared by the pre-push CLI (``scripts/check_adr_0005_pure_stdlib.py``) and the
test (``tests/test_adr_0005_pure_stdlib_runtime.py``).

Deliberately import-light — only ``ast`` + ``pathlib``, **never pytest** — so the
CLI / pre-commit hook runs in a stdlib-only interpreter. Previously the CLI
``exec_module``'d the test module to reuse ``RUNTIME_FILES`` / ``BANNED_ROOTS``,
but that test imports ``pytest`` (for ``@parametrize``), so the hook crashed with
``ModuleNotFoundError: No module named 'pytest'`` under any interpreter without
pytest installed (e.g. the bare git-hook Python). This manifest is that shared
definition without the pytest dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: Files covered by ADR-0005's "measurement runtime" definition.
RUNTIME_FILES: tuple[Path, ...] = (
    REPO_ROOT / "scripts" / "run_ab_comparison.py",
    REPO_ROOT / "scripts" / "smc_sprt_stop_rule.py",
)

#: Heavy dependencies ADR-0005 forbids in the measurement runtime. The ban is on
#: the top-level name; sub-imports (``numpy.linalg``) match via the root.
BANNED_ROOTS: frozenset[str] = frozenset({
    "numpy",
    "scipy",
    "pandas",
    "statsmodels",
    "sklearn",
    "torch",
    "tensorflow",
})


def imported_roots(source: str) -> set[str]:
    """Return the set of top-level module names imported in *source* (AST, no exec)."""
    tree = ast.parse(source)
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".", 1)[0])
        # ImportFrom.module is None for "from . import x" — relative imports
        # cannot reach a banned root, so skip them.
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots
