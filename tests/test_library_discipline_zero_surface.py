"""Defense-pin: library-discipline zero-surface invariants.

Three "this codebase doesn't use that library / API" invariants over
first-party non-test code. Each one is a deliberate architectural choice;
the pins keep the choices visible and prevent silent drift.

``requests`` and ``shutil.copy*`` are empty. ``asyncio`` is empty in the
engine and carries one bounded, justified exception for a standalone
scaffold — see :data:`_ASYNCIO_ALLOWED_COUNTS`.

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

# Files allowed to call the banned asyncio shapes, and exactly how often.
# Empty for everything that is part of the engine — the rule below is what
# keeps it that way. An entry here is a conscious, bounded decision.
#
# 2026-07-15 (#3499 scaffold): agent.py is a standalone Claude Agent SDK +
# Composio example. The SDK is async-only, so its single ``asyncio.run(main())``
# is the documented entry point (invoked as ``python agent.py``), mirroring the
# ``"agent.py": 1`` entry that ``test_prod_print_ledger.py`` already carries for
# the same scaffold. Nothing imports it, so it cannot poison event-loop
# semantics for the sync+threaded engine this rule protects — which is the
# entire reason the rule exists.
_ASYNCIO_ALLOWED_COUNTS: dict[str, int] = {
    "agent.py": 1,
}

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
    """No ``asyncio.run`` / ``asyncio.create_task`` outside the allow-list.

    Zero in the engine; :data:`_ASYNCIO_ALLOWED_COUNTS` carries the bounded,
    justified exceptions. The count is exact in both directions, so the entry
    cannot quietly grow, and a stale one fails instead of masking the next
    real call site.
    """

    found: dict[str, list[str]] = {}
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, attr in _scan_module_attr_calls(tree, "asyncio", _ASYNCIO_BANNED):
            found.setdefault(rel, []).append(f"  - {rel}:{lineno}  asyncio.{attr}(...)")

    unlisted = sorted(
        hit
        for rel, hits in found.items()
        if rel not in _ASYNCIO_ALLOWED_COUNTS
        for hit in hits
    )
    assert not unlisted, (
        "asyncio.run / asyncio.create_task call(s) found — codebase is "
        "synchronous + threaded (see the threading.Thread daemon= pin "
        "#211). Adding async ad-hoc poisons event-loop semantics for "
        "every caller:\n"
        + "\n".join(unlisted)
        + "\n\nIf async is genuinely needed, land it via a deliberate "
        "architectural change, not a one-off call site."
    )

    drifted = sorted(
        (rel, expected, len(found.get(rel, [])))
        for rel, expected in _ASYNCIO_ALLOWED_COUNTS.items()
        if len(found.get(rel, [])) != expected
    )
    assert not drifted, (
        "_ASYNCIO_ALLOWED_COUNTS no longer matches the tree. A count that "
        "grew means async spread inside an allow-listed file; a count that "
        "shrank (or hit 0) means the entry is stale and would mask the next "
        "real call site. Reconcile it in the same PR.\n"
        f"(path, expected, actual) = {drifted}"
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
