"""Defense-pin: ``tempfile.NamedTemporaryFile`` MUST pass ``delete=`` explicitly.

The ``delete=`` parameter of ``NamedTemporaryFile`` controls whether
the file is auto-removed on close. Default is ``True``, which is the
*wrong* default for the atomic-write pattern used throughout this
repo (open temp → write → fsync → ``os.replace`` to final path).
Without ``delete=False``, the temp file vanishes before
``os.replace`` runs and the rename fails — silently corrupting
output in some code paths and crashing in others.

The hard invariant: every call to ``tempfile.NamedTemporaryFile(...)``
in first-party code MUST pass ``delete=`` as an explicit keyword
argument. (Whether the value is True or False is up to the caller —
the point is that the choice is made consciously and visible at the
call site.)

Sister of #176 (random/tempfile usage ledger) — that pin freezes the
*inventory*; this pin freezes a *call shape*.
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


def _is_named_temporary_file_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    f = node.func
    return (
        isinstance(f, ast.Attribute)
        and isinstance(f.value, ast.Name)
        and f.value.id == "tempfile"
        and f.attr == "NamedTemporaryFile"
    )


def _scan(tree: ast.AST) -> list[tuple[int, bool]]:
    out: list[tuple[int, bool]] = []
    for node in ast.walk(tree):
        if not _is_named_temporary_file_call(node):
            continue
        assert isinstance(node, ast.Call)
        kw = {k.arg for k in node.keywords if k.arg}
        out.append((node.lineno, "delete" in kw))
    return out


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


def test_every_named_temporary_file_passes_delete_kwarg() -> None:
    """Hard invariant: ``tempfile.NamedTemporaryFile(...)`` requires explicit ``delete=``."""
    bad: list[str] = []
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        rel = path.relative_to(ROOT).as_posix()
        for lineno, has_delete in _scan(tree):
            if not has_delete:
                bad.append(f"  - {rel}:{lineno}")
    assert not bad, (
        "tempfile.NamedTemporaryFile(...) call(s) missing explicit "
        "``delete=`` keyword:\n"
        + "\n".join(bad)
        + "\n\nThe default ``delete=True`` is the wrong default for the "
        "atomic-write pattern (open temp -> write -> fsync -> "
        "os.replace). Without ``delete=False`` the temp file vanishes "
        "before ``os.replace`` can rename it. Make the choice explicit "
        "at every call site so reviewers can see it."
    )
