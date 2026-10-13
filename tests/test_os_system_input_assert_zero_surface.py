"""Defense-pin: triple zero-surface invariant for ``os.system`` + ``input`` + ``assert``.

Three cheap-to-pin invariants that share a common shape: all three
surfaces are currently empty in first-party non-test code, and any
reintroduction is a forced design decision.

* **CWE-78 / shell injection (`os.system`)**: ``os.system(cmd)`` runs
  ``cmd`` through ``/bin/sh -c``, which is the worst possible
  shell-injection surface. The ``subprocess`` shell-injection pin
  (#201) already enforces ``shell=True == 0``; this pin closes the
  remaining backdoor.
* **CWE-400 / blocking on stdin (`input`)**: every interactive
  ``input(...)`` call blocks the process forever waiting on stdin.
  Acceptable in a deliberate REPL/CLI, but in this repo it has
  always been done via argparse / config, never blocking I/O. Pin it
  to keep automated runs deterministic.
* **CWE-617 / reachable assertion (`assert`)**: ``assert`` is *not*
  a runtime check — Python with ``-O`` strips every assertion. Using
  ``assert`` for input validation, invariant guards, or "fail closed"
  paths in production code is the canonical mistake. The repo uses
  ``assert`` only inside ``tests/`` (which this scan excludes); pin
  that fact.

Defense-only — no production changes. Tests pin the empty surfaces
with hard, single-shot invariants (no ledger to maintain).
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


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def _scan_os_system(tree: ast.AST) -> list[int]:
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "os"
            and f.attr == "system"
        ):
            out.append(node.lineno)
    return out


def _scan_input_calls(tree: ast.AST) -> list[int]:
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id == "input":
            out.append(node.lineno)
    return out


def _scan_assert_stmts(tree: ast.AST) -> list[int]:
    out: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Assert):
            out.append(node.lineno)
    return out


def test_no_os_system_calls() -> None:
    """CWE-78 / shell-injection invariant: no ``os.system(...)`` in first-party code."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno in _scan_os_system(tree):
            findings.append(f"  - {rel}:{lineno}  os.system(...)")
    assert not findings, (
        "os.system(...) call(s) found — equivalent to shell=True via "
        "subprocess and a CWE-78 shell-injection vector:\n"
        + "\n".join(findings)
        + "\n\nUse ``subprocess.run([...])`` with a list of args (no "
        "``shell=True``). The subprocess shell-injection pin (#201) "
        "already enforces this on subprocess.run / Popen / call etc."
    )


def test_no_blocking_input_calls() -> None:
    """CWE-400 / blocking-on-stdin invariant: no ``input(...)`` in first-party code."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno in _scan_input_calls(tree):
            findings.append(f"  - {rel}:{lineno}  input(...)")
    assert not findings, (
        "input(...) call(s) found — process will block forever waiting "
        "on stdin during automated runs:\n"
        + "\n".join(findings)
        + "\n\nUse argparse / environment variables / a config file "
        "instead. If a deliberate REPL is genuinely required, add the "
        "site as an explicit exception with a justifying comment."
    )


def test_no_assert_statements_in_production_code() -> None:
    """CWE-617 / reachable-assertion invariant.

    The ``tests/`` tree is excluded — this only scans production code.
    Python with ``-O`` strips every ``assert``; using assertions for
    input validation or "fail closed" paths is the canonical mistake.
    Use ``raise ValueError(...)`` or ``raise RuntimeError(...)``.
    """
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno in _scan_assert_stmts(tree):
            findings.append(f"  - {rel}:{lineno}")
    assert not findings, (
        "``assert`` statement(s) in production (non-test) code:\n"
        + "\n".join(findings)
        + "\n\n``assert`` is not a runtime check — Python with ``-O`` "
        "strips them all. Use ``raise ValueError(...)`` / "
        "``RuntimeError(...)`` for input validation and invariant "
        "guards. ``assert`` belongs only in tests."
    )
