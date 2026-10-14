"""Lock the import-order contract for scripts that mutate ``sys.path``.

Bug-Hunt 2026-05-01 Finding **F-01** (AMBER) traced a workflow failure
to ``scripts/analyze_smc_contextual_calibration_history.py`` which
imported ``from scripts.smc_atomic_write import atomic_write_text``
*before* the ``sys.path.insert(0, str(REPO_ROOT))`` block that makes
the top-level packages discoverable. The script worked under
``python -m scripts.X`` (where the parent dir is auto-added) but
crashed with ``ModuleNotFoundError`` under the more common direct-path
form ``python scripts/X.py`` used by several workflows.

This regression test guards the rule:

    For every script under ``scripts/`` that *does* perform a
    ``sys.path.insert`` for the repository root, any
    ``from scripts.<X> import …`` or any first-party-package import
    that depends on the inserted path MUST appear in the file *after*
    that ``sys.path.insert`` statement.

Static AST check — fast, deterministic, no subprocess spawn.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Top-level first-party packages whose imports require REPO_ROOT to be
# on sys.path. Kept conservative on purpose — we only flag packages we
# *know* live at the repo root and would not be importable on a vanilla
# Python install.
_FIRST_PARTY_PACKAGES = frozenset(
    {
        "scripts",
        "smc_integration",
        "automation",
        "ml",
        "rl",
        "open_prep",
        "newsstack_fmp",
    }
)


def _module_root(name: str | None) -> str | None:
    if not name:
        return None
    return name.split(".", 1)[0]


def _first_sys_path_mutation_lineno(tree: ast.AST) -> int | None:
    """Return the line number of the first ``sys.path.insert``/``append``
    call in *tree*, or ``None`` if the file does not mutate sys.path.
    """
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr not in {"insert", "append"}:
            continue
        value = func.value
        if not isinstance(value, ast.Attribute):
            continue
        if value.attr != "path":
            continue
        inner = value.value
        if isinstance(inner, ast.Name) and inner.id == "sys":
            return node.lineno
    return None


def _first_party_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Yield ``(lineno, root_module)`` for every Import / ImportFrom of a
    first-party package."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # relative import, unaffected by sys.path
            root = _module_root(node.module)
            if root in _FIRST_PARTY_PACKAGES:
                out.append((node.lineno, root))  # type: ignore[arg-type]
        elif isinstance(node, ast.Import):
            for alias in node.names:
                root = _module_root(alias.name)
                if root in _FIRST_PARTY_PACKAGES:
                    out.append((node.lineno, root))  # type: ignore[arg-type]
    return out


def test_first_party_imports_follow_sys_path_insert() -> None:
    """If a script mutates ``sys.path`` for REPO_ROOT, every first-party
    import in that script must appear *after* the mutation."""
    violations: list[str] = []
    for path in sorted(SCRIPTS_DIR.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            violations.append(f"{path.relative_to(REPO_ROOT)}: SyntaxError: {exc}")
            continue
        insert_line = _first_sys_path_mutation_lineno(tree)
        if insert_line is None:
            # Script does not mutate sys.path → nothing to enforce here.
            continue
        for lineno, root in _first_party_imports(tree):
            if lineno < insert_line:
                violations.append(
                    f"{path.relative_to(REPO_ROOT)}:{lineno}: "
                    f"`{root}` imported before `sys.path.insert` at line "
                    f"{insert_line}. Move the import below the sys.path "
                    f"mutation (use `# noqa: E402`) so the script also "
                    f"works when invoked as `python scripts/{path.name}`."
                )
    assert not violations, (
        "First-party import-order violations detected (Bug-Hunt F-01):\n  - "
        + "\n  - ".join(violations)
    )
