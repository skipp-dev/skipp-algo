"""Defense-pin: ``threading.Thread(...)`` must pass an explicit ``daemon=`` kwarg.

Every ``threading.Thread(...)`` constructor call in first-party
non-test code MUST set ``daemon=True`` or ``daemon=False`` explicitly.
Sister of the ``httpx`` ``timeout=`` invariant — a call-shape pin
that costs nothing to maintain (no ledger) and prevents a class of
real bugs.

Why:

* Without ``daemon=``, threading inherits the daemon flag from the
  *creating* thread. In the main thread that defaults to ``False`` —
  meaning the interpreter will refuse to exit while that thread is
  alive. Every long-running poller / watcher in this repo expects
  to be torn down with the process; the explicit ``daemon=True``
  contract makes that intent visible at the call site.
* Cases where you genuinely want ``daemon=False`` (e.g. background
  flush that must finish) become equally explicit — the pin forces
  you to write the choice down.

Surface today: 5 ``threading.Thread`` sites, 100% pass an explicit
``daemon=`` kwarg. The pin keeps it that way.

Defense-only — no production changes.
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


def _scan_thread_calls_missing_daemon(tree: ast.AST) -> list[int]:
    """Return linenos of ``threading.Thread(...)`` calls without ``daemon=``."""
    out: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == "threading"
            and f.attr == "Thread"
        ):
            continue
        if any(k.arg == "daemon" for k in node.keywords):
            continue
        out.append(node.lineno)
    return out


def test_threading_thread_must_pass_explicit_daemon_kwarg() -> None:
    """Invariant: every ``threading.Thread(...)`` call passes ``daemon=``.

    No ledger. Single shape. Adding a new ``threading.Thread(...)``
    without ``daemon=True`` (or ``daemon=False`` if genuinely needed)
    is rejected at CI time.
    """
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno in _scan_thread_calls_missing_daemon(tree):
            findings.append(f"  - {rel}:{lineno}  threading.Thread(...) missing daemon=")
    assert not findings, (
        "threading.Thread(...) call(s) without an explicit daemon= kwarg:\n"
        + "\n".join(findings)
        + "\n\nWithout an explicit ``daemon=True`` (or ``daemon=False``) "
        "the daemon flag is inherited from the creating thread, which "
        "in the main thread defaults to False — the interpreter will "
        "refuse to exit while the thread is alive. Make the choice "
        "explicit at the call site."
    )
