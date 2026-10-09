"""Defense-pin: zero-surface invariant for dynamic-exec + unsafe deserialization.

Two adjacent CWE families that share a property worth pinning *jointly*:

* **CWE-95 (dynamic exec)**: ``eval(...)``, ``exec(...)``, ``compile(...)``
  as bare builtin calls. This repo currently has zero — the test below
  keeps it that way.
* **CWE-502 (unsafe deserialization)**: ``pickle`` / ``cPickle`` / ``dill``
  / ``marshal`` imports and ``.load(...) / .loads(...) / .Unpickler(...)``
  call sites. This repo currently has zero of both — pinned likewise.

Both surfaces are "you almost never need this; if you do, do it on
purpose with a code review". A zero-surface invariant is the cleanest
possible defense-pin: any new occurrence is a forced design decision.

Defense-only — no production code changes. False-positive scope is
narrow because:

* We only catch *bare-name* ``eval`` / ``exec`` / ``compile`` calls
  (so e.g. ``re.compile`` / ``pandas.eval`` / ``sqlalchemy.compile`` are
  ignored — they are ``ast.Attribute`` calls, not ``ast.Name`` calls).
* Pickle-family detection only matches ``<module>.<attr>`` where
  ``<module>`` is one of the four well-known unsafe-deserialization
  modules. Custom classes named ``Unpickler`` elsewhere are not matched.
"""

from __future__ import annotations

import ast
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
        "tests",
        "SMC++",
    }
)

_DYNAMIC_EXEC_BUILTINS = frozenset({"eval", "exec", "compile"})

_UNSAFE_DESERIALIZE_MODULES = frozenset(
    {"pickle", "cPickle", "dill", "marshal"}
)
_UNSAFE_DESERIALIZE_ATTRS = frozenset(
    {"load", "loads", "Unpickler"}
)


def _iter_first_party_py_files() -> list[Path]:
    out: list[Path] = []
    for path in ROOT.rglob("*.py"):
        try:
            rel_parts = path.relative_to(ROOT).parts
        except ValueError:
            continue
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)


def _scan_dynamic_exec(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(builtin_name, lineno), ...] for bare ``eval/exec/compile`` calls."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in _DYNAMIC_EXEC_BUILTINS:
            out.append((f.id, node.lineno))
    return out


def _scan_unsafe_deserialize(tree: ast.AST) -> tuple[
    list[tuple[str, int]], list[tuple[str, str, int]]
]:
    """Return (imports, calls) where:

    * imports = [(module_name, lineno), ...]  for any pickle-family import
    * calls   = [(module_name, attr, lineno), ...] for ``mod.load|loads|Unpickler``
    """
    imports: list[tuple[str, int]] = []
    calls: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _UNSAFE_DESERIALIZE_MODULES:
                    imports.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.module in _UNSAFE_DESERIALIZE_MODULES:
                imports.append((node.module, node.lineno))
        elif isinstance(node, ast.Call):
            f = node.func
            if (
                isinstance(f, ast.Attribute)
                and f.attr in _UNSAFE_DESERIALIZE_ATTRS
                and isinstance(f.value, ast.Name)
                and f.value.id in _UNSAFE_DESERIALIZE_MODULES
            ):
                calls.append((f.value.id, f.attr, node.lineno))
    return imports, calls


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def test_no_bare_eval_exec_compile_calls() -> None:
    """CWE-95 invariant: no bare ``eval(...) / exec(...) / compile(...)`` in first-party code."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for name, lineno in _scan_dynamic_exec(tree):
            findings.append(f"  - {rel}:{lineno}  {name}(...)")
    assert not findings, (
        "CWE-95 surface re-opened — bare dynamic-exec builtin call(s) "
        "found:\n"
        + "\n".join(findings)
        + "\n\nIf truly required (very rarely), prefer a narrowly scoped "
        "AST-driven helper with explicit allow-list, and add the site to "
        "this test as an explicit exception with a justifying comment."
    )


def test_no_pickle_family_imports() -> None:
    """CWE-502 invariant (layer 1): no pickle/cPickle/dill/marshal imports."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        imports, _ = _scan_unsafe_deserialize(tree)
        for mod, lineno in imports:
            findings.append(f"  - {rel}:{lineno}  import {mod}")
    assert not findings, (
        "CWE-502 import surface re-opened — pickle-family module "
        "import(s) found:\n"
        + "\n".join(findings)
        + "\n\nUse JSON / msgpack / explicit schema (pydantic, "
        "dataclasses + json) for cross-process state. If a pickle "
        "import is genuinely required (e.g. fully trusted local "
        "cache), add the site to this test as an explicit exception "
        "with a justifying comment."
    )


def test_no_pickle_family_load_calls() -> None:
    """CWE-502 invariant (layer 2): no ``<mod>.load|loads|Unpickler(...)`` calls."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        _, calls = _scan_unsafe_deserialize(tree)
        for mod, attr, lineno in calls:
            findings.append(f"  - {rel}:{lineno}  {mod}.{attr}(...)")
    assert not findings, (
        "CWE-502 deserialization surface re-opened — pickle-family "
        "load call(s) found:\n"
        + "\n".join(findings)
        + "\n\nDeserializing untrusted bytes via pickle is arbitrary "
        "code execution. Use JSON / msgpack / explicit schema instead."
    )
