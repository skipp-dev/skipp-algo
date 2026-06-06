"""Defense-pin: library-discipline zero-surface invariants.

Three "this codebase doesn't use that library / API" invariants that
are all currently empty in first-party non-test code. Each one is a
deliberate architectural choice that has held to date; the pins keep
the choices visible and prevent silent drift.

The three banned shapes:

* **No ``requests`` HTTP calls.** The codebase is exclusively on
  ``httpx`` (which the httpx ``timeout=`` pin in #208 already covers).
  Mixing ``requests`` and ``httpx`` doubles the connection pools,
  TLS configs, and timeout-policy surfaces. Pin the ``requests``
  side to zero to keep the choice unambiguous.

* **No ``asyncio.run`` / ``asyncio.create_task``.** The codebase is
  synchronous + threaded (see the ``threading.Thread`` ``daemon=``
  pin in #211). Adding async at random call sites poisons the
  event loop semantics for every caller. If async is genuinely
  needed it should land via a deliberate architectural change, not
  a one-off ``asyncio.run`` somewhere.

* **No ``shutil.copy`` / ``shutil.copyfile``.** Both shapes are
  non-atomic (no fsync, no temp+rename) and ``copy`` carries
  permission bits in a platform-dependent way. The atomic-write
  helpers in ``scripts/smc_atomic_write.py`` (sister of the
  ``tempfile.NamedTemporaryFile`` ``delete=`` pin in #207) are the
  approved path. Pin ``shutil.copy*`` to zero to prevent regressions.

Defense-only — no production changes. Three surfaces, three tests.
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

_REQUESTS_VERBS = frozenset(
    {"get", "post", "put", "delete", "patch", "head", "options", "request"}
)

_ASYNCIO_BANNED = frozenset({"run", "create_task"})

_SHUTIL_BANNED = frozenset({"copy", "copyfile"})


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


def _scan_module_attr_calls(
    tree: ast.AST, module: str, attrs: frozenset[str]
) -> list[tuple[int, str]]:
    """Return ``[(lineno, attr), ...]`` for ``<module>.<attr>(...)`` calls."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (
            isinstance(f, ast.Attribute)
            and isinstance(f.value, ast.Name)
            and f.value.id == module
            and f.attr in attrs
        ):
            continue
        out.append((node.lineno, f.attr))
    return out


def test_no_requests_http_calls() -> None:
    """No ``requests.<verb>(...)`` — codebase is exclusively on httpx."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, attr in _scan_module_attr_calls(tree, "requests", _REQUESTS_VERBS):
            findings.append(f"  - {rel}:{lineno}  requests.{attr}(...)")
    assert not findings, (
        "requests.<verb>(...) call(s) found — codebase is exclusively "
        "on httpx (see the httpx timeout= pin #208). Mixing libraries "
        "doubles the connection pools, TLS configs, and timeout "
        "policies:\n"
        + "\n".join(findings)
        + "\n\nUse ``httpx`` instead."
    )


def test_no_asyncio_run_or_create_task() -> None:
    """No ``asyncio.run`` / ``asyncio.create_task`` — codebase is synchronous + threaded."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, attr in _scan_module_attr_calls(tree, "asyncio", _ASYNCIO_BANNED):
            findings.append(f"  - {rel}:{lineno}  asyncio.{attr}(...)")
    assert not findings, (
        "asyncio.run / asyncio.create_task call(s) found — codebase is "
        "synchronous + threaded (see the threading.Thread daemon= pin "
        "#211). Adding async ad-hoc poisons event-loop semantics for "
        "every caller:\n"
        + "\n".join(findings)
        + "\n\nIf async is genuinely needed, land it via a deliberate "
        "architectural change, not a one-off call site."
    )


def test_no_shutil_copy_or_copyfile() -> None:
    """No ``shutil.copy`` / ``shutil.copyfile`` — use the atomic-write helpers."""
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, attr in _scan_module_attr_calls(tree, "shutil", _SHUTIL_BANNED):
            findings.append(f"  - {rel}:{lineno}  shutil.{attr}(...)")
    assert not findings, (
        "shutil.copy / shutil.copyfile call(s) found — both are "
        "non-atomic (no fsync, no temp+rename) and ``copy`` carries "
        "permission bits in a platform-dependent way:\n"
        + "\n".join(findings)
        + "\n\nUse the atomic-write helpers in "
        "``scripts/smc_atomic_write.py`` (sister of the "
        "tempfile.NamedTemporaryFile delete= pin #207)."
    )
