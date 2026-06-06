"""Audit pin: serialization & shell-injection zero-tripwires + ``__all__`` integrity.

Three defense layers in one bundle:

1. **Insecure serialization tripwires**: ``pickle``, ``cPickle``,
   ``marshal``, ``shelve`` — all four currently absent in production.
   These are deserialization-RCE vectors (CWE-502).
2. **Shell-injection tripwires**: ``os.system(...)`` and ``os.popen(...)``
   complement PR #154's ``subprocess(..., shell=True)`` ban.
3. **``__all__`` integrity**: every name exported via ``__all__`` must
   actually be defined or imported at module top level. Catches the
   classic "deleted helper but forgot to update ``__all__``" bug.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

_REPO_ROOT = Path(__file__).resolve().parent.parent

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

_BANNED_SERIALIZATION = frozenset({"pickle", "cPickle", "marshal", "shelve"})


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _scan_imports_and_calls() -> tuple[
    list[tuple[str, int, str]],  # serialization imports
    list[tuple[str, int, str]],  # os.system / os.popen calls
]:
    serialization: list[tuple[str, int, str]] = []
    shell: list[tuple[str, int, str]] = []
    for path in _iter_prod_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    head = alias.name.split(".")[0]
                    if head in _BANNED_SERIALIZATION:
                        serialization.append((rel, node.lineno, alias.name))
            elif isinstance(node, ast.ImportFrom):
                head = (node.module or "").split(".")[0]
                if head in _BANNED_SERIALIZATION:
                    serialization.append((rel, node.lineno, node.module or ""))
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                f = node.func
                if (
                    isinstance(f.value, ast.Name)
                    and f.value.id == "os"
                    and f.attr in {"system", "popen"}
                ):
                    shell.append((rel, node.lineno, f"os.{f.attr}"))
    return serialization, shell


def _collect_top_level_names(tree: ast.Module) -> set[str]:
    """Names that are definitions, assignments, or imports at module top level
    (including inside top-level if/try blocks for optional-dep patterns)."""
    names: set[str] = set()

    def walk_block(stmts: list[ast.stmt]) -> None:
        for n in stmts:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
            elif isinstance(n, ast.Assign):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        names.add(t.id)
            elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name):
                names.add(n.target.id)
            elif isinstance(n, ast.Import):
                for a in n.names:
                    names.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, ast.ImportFrom):
                for a in n.names:
                    names.add(a.asname or a.name)
            elif isinstance(n, ast.If):
                walk_block(n.body)
                walk_block(n.orelse)
            elif isinstance(n, ast.Try):
                walk_block(n.body)
                for h in n.handlers:
                    walk_block(h.body)
                walk_block(n.orelse)
                walk_block(n.finalbody)

    walk_block(tree.body)
    return names


def _scan_all_drift() -> list[tuple[str, int, list[str]]]:
    drift: list[tuple[str, int, list[str]]] = []
    for path in _iter_prod_files():
        tree = parse_module(path)
        if tree is None:
            continue
        all_names: list[str] | None = None
        all_lineno = 0
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if (
                        isinstance(t, ast.Name)
                        and t.id == "__all__"
                        and isinstance(node.value, (ast.List, ast.Tuple))
                    ):
                        try:
                            all_names = [
                                e.value
                                for e in node.value.elts
                                if isinstance(e, ast.Constant)
                                and isinstance(e.value, str)
                            ]
                            all_lineno = node.lineno
                        except (AttributeError, TypeError):
                            pass
        if all_names is None:
            continue
        defined = _collect_top_level_names(tree)
        missing = [n for n in all_names if n not in defined]
        if missing:
            rel = path.relative_to(_REPO_ROOT).as_posix()
            drift.append((rel, all_lineno, missing))
    return drift


def test_no_insecure_serialization_imports() -> None:
    serialization, _ = _scan_imports_and_calls()
    assert not serialization, (
        "Insecure-deserialization library import(s) introduced (CWE-502). "
        "Use json/orjson/msgpack instead:\n  - "
        + "\n  - ".join(f"{f}:{ln} import `{name}`" for f, ln, name in serialization)
    )


def test_no_os_system_or_os_popen_calls() -> None:
    _, shell = _scan_imports_and_calls()
    assert not shell, (
        "`os.system`/`os.popen` introduced — shell-injection vectors. "
        "Use subprocess.run(argv, shell=False):\n  - "
        + "\n  - ".join(f"{f}:{ln} `{name}(...)`" for f, ln, name in shell)
    )


def test_all_dunder_names_are_defined() -> None:
    drift = _scan_all_drift()
    assert not drift, (
        "`__all__` references undefined names (re-export drift):\n  - "
        + "\n  - ".join(f"{f}:{ln} missing={names}" for f, ln, names in drift)
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
