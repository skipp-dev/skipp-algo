"""Defense-pin: pickle write-side zero-surface + os.path.join absolute-path tripwire.

Two more empty surfaces pinned with single-shot AST invariants. Both
sister to existing pins; both currently zero in first-party non-test
code; both costing nothing to maintain.

The two banned shapes:

* **Pickle write side** — ``pickle.dumps`` / ``pickle.dump`` (also
  ``cPickle`` / ``dill`` / ``marshal``). The eval/pickle pin (#202)
  already bans the *read* side (``loads`` / ``load`` / ``Unpickler``)
  because that's where untrusted bytes become arbitrary code
  execution. The write side is the symmetric guard: if no code
  *produces* pickled bytes, no code can ever be tempted to *consume*
  them. Use ``json``, ``msgpack``, or an explicit schema instead.

* **``os.path.join(..., "/abs")`` foot-gun** — CWE-22 / CWE-73.
  ``os.path.join`` silently *discards* every component before an
  absolute path: ``os.path.join("/safe/dir", "/etc/passwd")`` →
  ``"/etc/passwd"``. This is the canonical path-traversal sink in
  Python codebases. Surface today: 0 literal absolute second
  arguments. Pin keeps it that way; non-literal joins (where the
  second arg is a variable) are *not* flagged because that's where
  the actual sanitization needs to happen at the call site.

Defense-only — no production changes. Two surfaces, two tests.
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

_PICKLE_MODULES = frozenset({"pickle", "cPickle", "dill", "marshal"})
_PICKLE_WRITE_ATTRS = frozenset({"dump", "dumps"})


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


def test_no_pickle_write_calls() -> None:
    """No ``pickle.dump`` / ``pickle.dumps`` (also ``cPickle`` / ``dill`` / ``marshal``)."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if not (
                isinstance(f, ast.Attribute)
                and isinstance(f.value, ast.Name)
                and f.value.id in _PICKLE_MODULES
                and f.attr in _PICKLE_WRITE_ATTRS
            ):
                continue
            findings.append(f"  - {rel}:{node.lineno}  {f.value.id}.{f.attr}(...)")
    assert not findings, (
        "Pickle write-side call(s) found — symmetric guard for the "
        "pickle.load / Unpickler read-side ban (#202). If no code "
        "produces pickled bytes, no code can ever be tempted to "
        "consume them:\n"
        + "\n".join(findings)
        + "\n\nUse ``json``, ``msgpack``, or an explicit schema."
    )


def _is_os_path_join(call: ast.Call) -> bool:
    """``ast.Call`` that resolves to ``os.path.join``."""
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "join"
        and isinstance(f.value, ast.Attribute)
        and f.value.attr == "path"
        and isinstance(f.value.value, ast.Name)
        and f.value.value.id == "os"
    )


def test_no_os_path_join_with_literal_absolute_component() -> None:
    """CWE-22: ``os.path.join(.., "/abs")`` silently discards earlier components."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_os_path_join(node):
                continue
            # Skip the very first arg (it's the base path; absolute is fine).
            for arg in node.args[1:]:
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and arg.value.startswith("/")
                ):
                    findings.append(
                        f"  - {rel}:{node.lineno}  os.path.join(..., {arg.value!r})"
                    )
                    break
    assert not findings, (
        "os.path.join() called with a literal absolute path component "
        "after the first arg — every preceding component is silently "
        "discarded (CWE-22 path-traversal foot-gun):\n"
        + "\n".join(findings)
        + "\n\nUse ``pathlib.Path(base) / sub`` (still has the same "
        "behaviour — also bad — so strip leading ``/`` first), or just "
        "use the absolute path directly."
    )
