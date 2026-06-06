"""Defense pin: dangerous-call zero-tripwire 6-fold bundle.

Six AST scans across first-party prod ``*.py`` files, each banning a
historically catastrophic primitive. All current inventories are 0; this
file exists to keep them at 0 forever.

Banned:

1. ``import pickle`` / ``from pickle import ...`` / ``import cPickle``
   — pickle deserialisation = arbitrary code execution. Use json/msgpack.
2. ``pickle.load(...)`` / ``pickle.loads(...)`` — same risk via attribute call.
3. ``os.system(...)`` — shell injection; spawns a real shell. Use
   ``subprocess.run([...], shell=False)``.
4. ``subprocess.<anything>(..., shell=True)`` — same root cause as os.system.
5. ``eval(...)`` — arbitrary code from arbitrary string.
6. ``exec(...)`` — same.

Defense-only. No prod source touched.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from pathlib import Path

from tests._guard_corpus import parse_module

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


def _iter_prod_py() -> Iterable[Path]:
    for p in sorted(ROOT.rglob("*.py")):
        if any(part in _DIR_EXCLUDE for part in p.parts):
            continue
        yield p


def _parse(p: Path) -> ast.AST | None:
    return parse_module(p)


def test_prod_inventory_sane() -> None:
    files = list(_iter_prod_py())
    assert len(files) >= 30, f"prod inventory shrank: {len(files)}"


def test_no_pickle_imports() -> None:
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "pickle" or a.name.startswith("pickle.") or a.name == "cPickle":
                        bad.append(f"{rel}:{node.lineno}: import {a.name}")
            elif isinstance(node, ast.ImportFrom) and node.module and (
                node.module == "pickle" or node.module.startswith("pickle.")
            ):
                bad.append(f"{rel}:{node.lineno}: from {node.module} import …")
    assert not bad, (
        "pickle imports are banned (deserialisation = arbitrary code execution; "
        "use json or msgpack):\n  - " + "\n  - ".join(bad)
    )


def test_no_pickle_load_calls() -> None:
    """Defence-in-depth in case `pickle` arrives via a re-exporting module."""
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in ("load", "loads")
                and isinstance(f.value, ast.Name)
                and f.value.id in ("pickle", "cPickle")
            ):
                bad.append(f"{rel}:{node.lineno}: {f.value.id}.{f.attr}(…)")
    assert not bad, "pickle.load/loads calls banned:\n  - " + "\n  - ".join(bad)


def test_no_os_system_calls() -> None:
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr == "system"
                and isinstance(f.value, ast.Name)
                and f.value.id == "os"
            ):
                bad.append(f"{rel}:{node.lineno}: os.system(…)")
    assert not bad, (
        "os.system spawns a shell — shell-injection vector. Use "
        "subprocess.run([...], shell=False):\n  - " + "\n  - ".join(bad)
    )


def test_no_subprocess_shell_true() -> None:
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            # subprocess.<run|call|Popen|check_output|check_call>(..., shell=True)
            if not (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id == "subprocess"
            ):
                continue
            for kw in node.keywords:
                if (
                    kw.arg == "shell"
                    and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True
                ):
                    bad.append(f"{rel}:{node.lineno}: subprocess.{f.attr}(..., shell=True)")
    assert not bad, (
        "subprocess shell=True banned (shell-injection):\n  - " + "\n  - ".join(bad)
    )


def test_no_eval_calls() -> None:
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "eval"
            ):
                bad.append(f"{rel}:{node.lineno}: eval(…)")
    assert not bad, (
        "eval() banned — use ast.literal_eval for safe constants:\n  - "
        + "\n  - ".join(bad)
    )


def test_no_exec_calls() -> None:
    bad: list[str] = []
    for p in _iter_prod_py():
        tree = _parse(p)
        if tree is None:
            continue
        rel = p.as_posix()
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "exec"
            ):
                bad.append(f"{rel}:{node.lineno}: exec(…)")
    assert not bad, "exec() banned:\n  - " + "\n  - ".join(bad)
