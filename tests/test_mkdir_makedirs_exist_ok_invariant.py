"""Defense-pin: ``Path.mkdir`` / ``os.makedirs`` must pass explicit ``exist_ok=``.

Both shapes raise ``FileExistsError`` by default if the target
directory already exists. Every directory-creation site in this
codebase wants the idempotent semantics — ``parents=True,
exist_ok=True`` — and we want that to be visible at every call site.

Without ``exist_ok=`` the call is a race-condition + bug-on-restart
foot-gun: any code path that calls into the same setup twice
(retry, second worker, second process, second test invocation) blows
up on the second pass. The fix is always the same; the pin makes it
mandatory at the call site.

Surface today:

* ``*.mkdir(...)`` — 555 sites across the repo, **100% pass
  ``exist_ok=``**.
* ``os.makedirs(...)`` — 9 sites, **100% pass ``exist_ok=``**.

Sister of the ``threading.Thread`` ``daemon=`` invariant (#211),
``httpx`` ``timeout=`` invariant (#208), and
``tempfile.NamedTemporaryFile`` ``delete=`` invariant (#207). No
ledger to maintain.

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


def _is_os_makedirs(call: ast.Call) -> bool:
    f = call.func
    return (
        isinstance(f, ast.Attribute)
        and f.attr == "makedirs"
        and isinstance(f.value, ast.Name)
        and f.value.id == "os"
    )


def _is_any_mkdir(call: ast.Call) -> bool:
    """Match any ``<expr>.mkdir(...)`` call.

    Path.mkdir is an instance method so the attribute receiver is
    almost always a Path object. Matching on attribute name alone
    catches every binding style (``Path("x").mkdir()``, ``p.mkdir()``,
    ``self.dir.mkdir()`` etc.) without needing per-import tracking.
    """
    f = call.func
    return isinstance(f, ast.Attribute) and f.attr == "mkdir"


def test_pathlib_mkdir_must_pass_explicit_exist_ok_kwarg() -> None:
    """Invariant: every ``*.mkdir(...)`` passes ``exist_ok=``.

    Default is ``exist_ok=False`` which raises ``FileExistsError`` —
    a race-condition + bug-on-restart foot-gun that the codebase has
    consistently avoided. 555 sites, 100% compliant today.
    """
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_any_mkdir(node):
                continue
            if any(k.arg == "exist_ok" for k in node.keywords):
                continue
            findings.append(f"  - {rel}:{node.lineno}  *.mkdir(...) missing exist_ok=")
    assert not findings, (
        "*.mkdir(...) call(s) without an explicit ``exist_ok=`` kwarg:\n"
        + "\n".join(findings)
        + "\n\nDefault is ``exist_ok=False`` which raises "
        "``FileExistsError`` on the second invocation — a race-"
        "condition + bug-on-restart foot-gun. Pass ``exist_ok=True`` "
        "(and usually ``parents=True``) explicitly."
    )


def test_os_makedirs_must_pass_explicit_exist_ok_kwarg() -> None:
    """Invariant: every ``os.makedirs(...)`` passes ``exist_ok=``.

    Same shape as ``Path.mkdir`` (default ``exist_ok=False``). 9 sites,
    100% compliant today.
    """
    findings: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not _is_os_makedirs(node):
                continue
            if any(k.arg == "exist_ok" for k in node.keywords):
                continue
            findings.append(
                f"  - {rel}:{node.lineno}  os.makedirs(...) missing exist_ok="
            )
    assert not findings, (
        "os.makedirs(...) call(s) without an explicit ``exist_ok=`` kwarg:\n"
        + "\n".join(findings)
        + "\n\nDefault is ``exist_ok=False``. Pass ``exist_ok=True`` "
        "explicitly."
    )
