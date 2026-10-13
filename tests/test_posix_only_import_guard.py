"""Guard: no bare module-level POSIX-only imports in cross-platform production code.

POSIX-only modules (``fcntl``, ``termios``, ``grp``, ``pwd``, ``resource``)
raise ``ModuleNotFoundError`` on Windows at import time, silently breaking the
entire module — and every module that transitively imports it — on the Windows
CI runner.

Root cause that prompted this guard: ``open_prep/realtime_signals.py`` had a
bare ``import fcntl`` at module level.  ``streamlit_terminal`` imports
``realtime_signals``, so the ``smc-fast-pr-gates`` terminal-coverage step
(which runs on a Windows self-hosted runner) failed with
``ModuleNotFoundError: No module named 'fcntl'`` on every test that imported
``streamlit_terminal``.

**Allowed pattern** (mirrors ``open_prep/realtime_signals.py``)::

    try:
        import fcntl          # plain ``import``, no alias
        _FLOCK_SUPPORTED = True
    except ImportError:       # Windows
        _FLOCK_SUPPORTED = False

**Forbidden patterns**:

* Bare module-level ``import fcntl`` outside a ``try`` block
* ``import fcntl as <alias>`` (bypasses the flock surface-pin test)
* ``from fcntl import <name>`` (same bypass risk)

Files listed in ``_POSIX_ONLY_FILES`` are permitted to use a bare top-level
``import fcntl`` (they are unconditionally POSIX and never run on Windows).
Add new entries only for files that genuinely require unconditional POSIX and
will never be imported from cross-platform code.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_POSIX_MODULES = frozenset({"fcntl", "termios", "grp", "pwd", "resource"})

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
        "tests",
        "SMC++",
    }
)

# Files where a bare module-level POSIX import is acceptable because they are
# unconditionally POSIX-only and never imported from cross-platform code.
_POSIX_ONLY_FILES: frozenset[str] = frozenset(
    {
        "ib_client_id.py",  # IB TWS client — Linux/macOS daemon only
    }
)


def _iter_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if any(part in _DIR_EXCLUDE or part.startswith(".") for part in rel.parts):
            continue
        out.append(path)
    return out


def _bare_posix_import_sites(py_file: Path) -> list[tuple[str, int, str]]:
    """Return (relpath, lineno, import_stmt) for every bare POSIX-only import
    that is NOT guarded by a surrounding ``try`` block.

    An import is "bare" if the ``import`` statement node is a direct child of
    the module body (i.e. ``ast.Module.body``) rather than nested inside a
    ``Try`` node.
    """
    try:
        source = py_file.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, UnicodeDecodeError):
        return []

    rel = py_file.relative_to(ROOT).as_posix()

    # Collect the set of AST nodes that are direct children of a Try block
    # so we can exclude them from the "bare" check.
    guarded_nodes: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in ast.walk(node):
                guarded_nodes.add(id(child))

    violations: list[tuple[str, int, str]] = []
    for stmt in ast.walk(tree):
        if id(stmt) in guarded_nodes:
            continue
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                if alias.name in _POSIX_MODULES:
                    form = (
                        f"import {alias.name} as {alias.asname}"
                        if alias.asname
                        else f"import {alias.name}"
                    )
                    violations.append((rel, stmt.lineno, form))
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.module in _POSIX_MODULES and stmt.level == 0:
                names = ", ".join(a.name for a in stmt.names)
                violations.append((rel, stmt.lineno, f"from {stmt.module} import {names}"))
    return violations


def test_no_bare_posix_imports_in_cross_platform_modules() -> None:
    """All POSIX-only imports in cross-platform modules must be inside a
    ``try/except ImportError`` guard so the module remains importable on
    Windows.
    """
    all_violations: list[tuple[str, int, str]] = []
    for path in _iter_py_files():
        rel_name = path.name
        if rel_name in _POSIX_ONLY_FILES:
            continue
        all_violations.extend(_bare_posix_import_sites(path))

    assert not all_violations, (
        "Bare module-level POSIX-only import detected in a cross-platform "
        "file.  Wrap the import in a ``try/except ImportError`` guard (see "
        "``open_prep/realtime_signals.py`` for the canonical pattern).  "
        "If the file genuinely only runs on POSIX, add it to "
        "``_POSIX_ONLY_FILES`` in this test with a justification.\n\n"
        "Violations:\n"
        + "\n".join(f"  {rel}:{line}  {stmt}" for rel, line, stmt in sorted(all_violations))
    )
