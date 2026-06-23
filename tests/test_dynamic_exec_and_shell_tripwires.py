"""Audit pin: dynamic-execution & shell-injection zero-tripwires.

Defense bundle of five zero-inventory tripwires that catch high-impact
security/correctness regressions early:

* ``exec(...)`` — arbitrary-code execution.
* ``eval(...)`` — arbitrary-expression evaluation.
* ``compile(...)`` — bytecode compilation (precursor to exec/eval).
* ``input(...)`` — interactive blocking read in non-interactive services.
* ``subprocess.{run,Popen,call,check_call,check_output}(..., shell=True)``
  — shell-injection vector.

All five currently have zero call-sites in production ``*.py``. This
pin tripps as soon as anyone reintroduces them.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests._guard_corpus import iter_tracked_files, parse_module

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

_BANNED_BUILTINS = frozenset({"exec", "eval", "compile", "input"})


def _iter_prod_files() -> list[Path]:
    return iter_tracked_files("*.py", _DIR_EXCLUDE, root=_REPO_ROOT)


def _shell_true(node: ast.Call) -> bool:
    for kw in node.keywords:
        if (
            kw.arg == "shell"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value is True
        ):
            return True
    return False


def _scan() -> tuple[
    list[tuple[str, int, str]],  # banned builtin calls
    list[tuple[str, int, str]],  # subprocess shell=True calls
]:
    builtins_hits: list[tuple[str, int, str]] = []
    shell_hits: list[tuple[str, int, str]] = []
    for path in _iter_prod_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            # banned builtin: bare-name call only (skip method `.eval(` on
            # a pandas/numpy DataFrame which is unrelated to builtin eval).
            if (
                isinstance(node.func, ast.Name)
                and node.func.id in _BANNED_BUILTINS
            ):
                builtins_hits.append((rel, node.lineno, node.func.id))
            # subprocess shell=True: detect any callable named run/Popen/
            # call/check_call/check_output with shell=True kwarg.
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Attribute):
                name = func.attr
            elif isinstance(func, ast.Name):
                name = func.id
            if name in {"run", "Popen", "call", "check_call", "check_output"} and _shell_true(node):
                shell_hits.append((rel, node.lineno, name))
    return builtins_hits, shell_hits


def test_no_banned_dynamic_execution_calls() -> None:
    builtins_hits, _ = _scan()
    assert not builtins_hits, (
        "Banned dynamic-execution builtin call(s) introduced — these are "
        "arbitrary-code-execution vectors and break static analysis:\n  - "
        + "\n  - ".join(f"{f}:{ln} `{name}(...)`" for f, ln, name in builtins_hits)
    )


def test_no_subprocess_shell_true_calls() -> None:
    _, shell_hits = _scan()
    assert not shell_hits, (
        "subprocess `shell=True` introduced — shell-injection vector. "
        "Pass an argv list and shell=False (default):\n  - "
        + "\n  - ".join(f"{f}:{ln} `{name}(..., shell=True)`" for f, ln, name in shell_hits)
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
