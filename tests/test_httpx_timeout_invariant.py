"""Defense-pin: every httpx network entry-point MUST pass ``timeout=``.

Sister of ``test_urllib_urlopen_ledger.py`` (CWE-1088 / availability
invariant) extended to httpx — the repo's primary HTTP client.

Two call shapes covered:

* **Client constructors**: ``httpx.Client(...)`` and
  ``httpx.AsyncClient(...)``. The default httpx timeout is 5s, but
  passing it explicitly at every site makes the choice visible to
  reviewers (and prevents accidentally inheriting future library
  changes).
* **Module-level verbs**: ``httpx.get / post / put / delete / patch /
  head / options / request / stream``. These bypass any client and
  therefore inherit only library defaults.

The repo has 21 ``httpx.Client(...)`` sites + 1 module-level
``httpx.post`` today — all currently pass ``timeout=``. This pin
keeps it that way.

Out of scope: instance-method calls like ``client.get(...)`` — those
inherit the client's timeout, which the constructor invariant already
enforces.
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

_HTTPX_CLIENTS = frozenset({"Client", "AsyncClient"})
_HTTPX_VERBS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "request", "stream"}
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


def _scan(tree: ast.AST) -> tuple[
    list[tuple[int, str, bool]], list[tuple[int, str, bool]]
]:
    """Return (clients, verbs) where each item is (lineno, attr, has_timeout)."""
    clients: list[tuple[int, str, bool]] = []
    verbs: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id == "httpx"):
            continue
        kw = {k.arg for k in node.keywords if k.arg}
        has_timeout = "timeout" in kw
        if f.attr in _HTTPX_CLIENTS:
            clients.append((node.lineno, f.attr, has_timeout))
        elif f.attr in _HTTPX_VERBS:
            verbs.append((node.lineno, f.attr, has_timeout))
    return clients, verbs


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def test_every_httpx_client_constructor_passes_timeout() -> None:
    """Hard invariant: ``httpx.Client(...) / AsyncClient(...)`` requires explicit ``timeout=``."""
    bad: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        clients, _ = _scan(tree)
        for lineno, attr, has_timeout in clients:
            if not has_timeout:
                bad.append(f"  - {rel}:{lineno}  httpx.{attr}(...)")
    assert not bad, (
        "httpx client constructor(s) without explicit ``timeout=``:\n"
        + "\n".join(bad)
        + "\n\nRelying on the library default makes the timeout "
        "invisible at the call site and brittle to future httpx "
        "version changes. Always pass an explicit ``timeout=`` "
        "(seconds, or ``httpx.Timeout(...)``)."
    )


def test_every_httpx_module_level_verb_passes_timeout() -> None:
    """Hard invariant: ``httpx.<verb>(...)`` (top-level) requires explicit ``timeout=``."""
    bad: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        _, verbs = _scan(tree)
        for lineno, attr, has_timeout in verbs:
            if not has_timeout:
                bad.append(f"  - {rel}:{lineno}  httpx.{attr}(...)")
    assert not bad, (
        "httpx module-level verb call(s) without explicit ``timeout=``:\n"
        + "\n".join(bad)
        + "\n\nModule-level ``httpx.get/post/...`` bypasses any client "
        "and inherits only library defaults. Always pass ``timeout=``."
    )
