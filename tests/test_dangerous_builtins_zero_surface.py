"""Defense pin: zero-surface invariants for a cluster of dangerous /
debug-only Python builtins and ``os`` process-control APIs in first-party
non-test code.

Banned APIs (all zero-surface today):

* ``os.popen(...)``   — CWE-78 shell-injection alternative path
                       (sister of #209's ``os.system`` ban).
* ``os.spawn*(...)``  — legacy process-spawn family (use ``subprocess``).
* ``os.exec*(...)``   — replaces current process; never used in our
                       pipelines and a foot-gun in long-running services.
* ``os.fork()``       — bypasses our threading + asyncio model.
* ``compile(...)``    — dynamic code compilation (CWE-95 vector).
* ``breakpoint()``    — left-in debugger; would freeze production.

Sister of #214 (pickle write + os.path.join literal absolute), #219
(pickle read + eval), #209 (os.system + input + assert).
"""
from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import parse_module

_ROOT = Path(__file__).resolve().parents[1]

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
}

_BANNED_BUILTINS = frozenset({"compile", "breakpoint"})


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _scan_offenders() -> dict[str, list[tuple[str, int]]]:
    by_kind: dict[str, list[tuple[str, int]]] = {
        "os.popen": [],
        "os.spawn*": [],
        "os.exec*": [],
        "os.fork": [],
        "compile": [],
        "breakpoint": [],
    }
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute):
                if (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "os"
                ):
                    if func.attr == "popen":
                        by_kind["os.popen"].append((rel, node.lineno))
                    elif func.attr.startswith("spawn"):
                        by_kind["os.spawn*"].append((rel, node.lineno))
                    elif func.attr.startswith("exec"):
                        by_kind["os.exec*"].append((rel, node.lineno))
                    elif func.attr == "fork":
                        by_kind["os.fork"].append((rel, node.lineno))
            elif isinstance(func, ast.Name) and func.id in _BANNED_BUILTINS:
                by_kind[func.id].append((rel, node.lineno))
    return by_kind


def test_no_os_popen_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["os.popen"] == [], (
        "os.popen(...) is banned in first-party non-test code (CWE-78 — "
        "shell-injection alternative path). "
        f"Offenders: {by_kind['os.popen']}"
    )


def test_no_os_spawn_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["os.spawn*"] == [], (
        "Legacy os.spawn* family is banned in first-party non-test code. "
        f"Use subprocess instead. Offenders: {by_kind['os.spawn*']}"
    )


def test_no_os_exec_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["os.exec*"] == [], (
        "os.exec* (process replacement) is banned in first-party non-test "
        f"code. Offenders: {by_kind['os.exec*']}"
    )


def test_no_os_fork_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["os.fork"] == [], (
        "os.fork() is banned in first-party non-test code (bypasses our "
        f"threading + asyncio model). Offenders: {by_kind['os.fork']}"
    )


def test_no_builtin_compile_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["compile"] == [], (
        "Built-in compile(...) is banned in first-party non-test code "
        f"(CWE-95 — dynamic code compilation). Offenders: {by_kind['compile']}"
    )


def test_no_builtin_breakpoint_in_production() -> None:
    by_kind = _scan_offenders()
    assert by_kind["breakpoint"] == [], (
        "Built-in breakpoint() is banned in first-party non-test code "
        f"(left-in debugger would freeze production). Offenders: {by_kind['breakpoint']}"
    )
