"""Defense pin: zero-surface invariants for ``pickle.load(s)`` (and friends)
read-side calls and built-in ``eval(...)`` in first-party non-test code.

Rationale
---------
* **CWE-502 (Deserialization of Untrusted Data)** — `pickle.load`,
  `pickle.loads`, `cPickle.load(s)`, `dill.load(s)`, and `marshal.load(s)`
  execute arbitrary code on input. The write-side counterpart was pinned in
  #214; this pin closes the read side.
* **CWE-95 (Code Injection)** — built-in `eval(...)` evaluates arbitrary
  Python expressions. There is no legitimate reason for our pipelines to
  call `eval`; banning it outright prevents drift toward unsafe
  configuration parsing.

Today's surface for both invariants is **zero**, and we keep it that way.

Sister of #214 (pickle.dump(s) write-side + os.path.join literal absolute),
#212 (TLS context tampering + JWT skip-verify), and #209 (os.system / input /
assert triple zero-surface).
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

_PICKLE_MODULES = frozenset({"pickle", "cPickle", "dill", "marshal"})
_PICKLE_READ_ATTRS = frozenset({"load", "loads"})


def _iter_python_files() -> list[Path]:
    out: list[Path] = []
    for path in _ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_ROOT).parts):
            continue
        out.append(path)
    return out


def _scan_pickle_read_calls() -> list[tuple[str, int, str, str]]:
    offenders: list[tuple[str, int, str, str]] = []
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not isinstance(func, ast.Attribute):
                continue
            if func.attr not in _PICKLE_READ_ATTRS:
                continue
            if not (isinstance(func.value, ast.Name) and func.value.id in _PICKLE_MODULES):
                continue
            offenders.append((rel, node.lineno, func.value.id, func.attr))
    return offenders


def _scan_eval_calls() -> list[tuple[str, int]]:
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "eval":
                offenders.append((rel, node.lineno))
    return offenders


def test_no_pickle_read_calls_in_production() -> None:
    offenders = _scan_pickle_read_calls()
    assert offenders == [], (
        "pickle/cPickle/dill/marshal .load/.loads (read-side) is banned in "
        "first-party non-test code — CWE-502 (Deserialization of Untrusted "
        f"Data). Offenders: {offenders}"
    )


def test_no_eval_calls_in_production() -> None:
    offenders = _scan_eval_calls()
    assert offenders == [], (
        "Built-in eval(...) is banned in first-party non-test code — "
        f"CWE-95 (Code Injection). Offenders: {offenders}"
    )
