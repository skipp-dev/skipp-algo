"""Defense pin: frozen ledger of built-in ``open(...)`` text-mode calls in
first-party non-test code that omit an explicit ``encoding=`` keyword.

Rationale
---------
Mirror of #218 (Path.read_text/write_text encoding= ledger) but for
built-in ``open(...)``. Without ``encoding=``, text-mode ``open`` falls
back to ``locale.getpreferredencoding(False)`` which differs by platform
and runner, producing silent artifact corruption / decode errors only
under specific deployment conditions.

This pin freezes today's surface (4 sites across 3 files, all under
``scripts/``) so the ledger can only **shrink**.
"""
from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from tests._guard_corpus import iter_tracked_files, parse_module

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

# Frozen ledger — fully fixed (2026-06-17, G1 encoding discipline sweep).
# Was 2 sites across 2 files (2026-04-25); all now have encoding="utf-8".
_FROZEN_SITES: dict[str, frozenset[int]] = {}
_FROZEN_TOTAL = sum(len(v) for v in _FROZEN_SITES.values())


def _iter_python_files() -> list[Path]:
    return iter_tracked_files("*.py", _DIR_EXCLUDE, root=_ROOT)


def _open_call_mode(node: ast.Call) -> str | None:
    """Return mode literal if statically resolvable, else None."""
    if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
        return node.args[1].value if isinstance(node.args[1].value, str) else None
    for kw in node.keywords:
        if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
            return kw.value.value if isinstance(kw.value.value, str) else None
    return None


@functools.cache
def _collect_offenders() -> dict[str, set[int]]:
    offenders: dict[str, set[int]] = {}
    for path in _iter_python_files():
        tree = parse_module(path)
        if tree is None:
            continue
        rel = path.relative_to(_ROOT).as_posix()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Name) and func.id == "open"):
                continue
            mode = _open_call_mode(node)
            # Skip explicitly binary modes; default is text.
            if mode is not None and "b" in mode:
                continue
            kw_names = {kw.arg for kw in node.keywords if kw.arg}
            if "encoding" not in kw_names:
                offenders.setdefault(rel, set()).add(node.lineno)
    return offenders


def test_builtin_open_total_does_not_grow() -> None:
    offenders = _collect_offenders()
    total = sum(len(v) for v in offenders.values())
    assert total == _FROZEN_TOTAL, (
        f"Built-in open() text-mode without encoding= total drifted: "
        f"frozen={_FROZEN_TOTAL}, observed={total}. "
        "Either add encoding= or, if intentional, update _FROZEN_SITES + _FROZEN_TOTAL."
    )


def test_no_new_files_join_the_open_ledger() -> None:
    offenders = _collect_offenders()
    new_files = sorted(set(offenders) - set(_FROZEN_SITES))
    assert not new_files, (
        "New files joined the built-in open() encoding= ledger. Add encoding= "
        f"or update _FROZEN_SITES if intentional. New: {new_files}"
    )


@pytest.mark.parametrize(
    "rel,frozen_lines",
    sorted(_FROZEN_SITES.items()),
    ids=lambda v: v if isinstance(v, str) else "lines",
)
def test_per_file_open_lines_match(rel: str, frozen_lines: frozenset[int]) -> None:
    offenders = _collect_offenders()
    observed = offenders.get(rel, set())
    extra = observed - frozen_lines
    assert not extra, (
        f"{rel}: new built-in open() text-mode call without encoding= at "
        f"lines {sorted(extra)}. Frozen lines were {sorted(frozen_lines)}."
    )
