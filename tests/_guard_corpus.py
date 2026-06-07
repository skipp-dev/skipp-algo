"""Shared, process-wide cache of repo source text and parsed AST modules.

Why
---
The discipline-guard suite is built from ~100 "ledger / pin / budget /
invariant" tests. The dominant cost in each of them is identical: glob the
repository for ``*.py`` files, ``read_text`` every one, and ``ast.parse`` it,
then ``ast.walk`` the tree looking for a forbidden pattern. Every guard did
this independently, and *parametrized* guards repeated the full parse on every
case — so the same ~1.2k source files were re-read and re-parsed dozens of
times per ``pytest`` run (measured: ~1.8 s per parametrized case, ~100 s for a
13-file batch).

Parsing a given file yields the same tree regardless of which guard asks for
it, so the parse is trivially cacheable for the lifetime of the process. This
module provides that cache. The cache key includes the file's ``mtime``/size,
so an edit during a session is still picked up correctly.

Contract
--------
* :func:`parse_module` and :func:`read_source` return ``None`` on a missing
  file, a decode error, or a syntax error — callers keep their existing
  ``continue`` / skip behavior, so **no guard changes which files it inspects**.
* The returned :class:`ast.Module` is a **shared, read-only** object. Guards in
  this repo only ``ast.walk`` it; do **not** mutate the returned tree (no
  ``ast.increment_lineno``/``NodeTransformer``/attribute assignment), or other
  guards in the same process would observe the mutation.

Each guard keeps its own file-discovery (``_iter_py_files`` /
``_DIR_EXCLUDE``); only the per-file *parse* is centralized here. That keeps the
exact inspected file-set per guard unchanged while sharing the expensive work.
"""

from __future__ import annotations

import ast
import functools
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    """Return the repository root (the parent of ``tests/``)."""
    return _ROOT


def _stat_key(path: Path) -> tuple[str, int, int]:
    """Resolve ``path`` and return a cache key that invalidates on edits."""
    resolved = path.resolve()
    st = resolved.stat()
    return (str(resolved), st.st_mtime_ns, st.st_size)


@functools.cache
def _read_cached(path_str: str, _mtime_ns: int, _size: int) -> str | None:
    try:
        return Path(path_str).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


@functools.cache
def _parse_cached(path_str: str, mtime_ns: int, size: int) -> ast.Module | None:
    source = _read_cached(path_str, mtime_ns, size)
    if source is None:
        return None
    try:
        return ast.parse(source, filename=path_str)
    except SyntaxError:
        return None


def read_source(path: Path) -> str | None:
    """Return the UTF-8 text of ``path``, or ``None`` if missing/undecodable.

    Cached for the process lifetime, keyed on path + mtime + size.
    """
    try:
        key = _stat_key(path)
    except OSError:
        return None
    return _read_cached(*key)


def parse_module(path: Path) -> ast.Module | None:
    """Return the parsed AST for ``path``, or ``None`` on decode/syntax error.

    Cached for the process lifetime, keyed on path + mtime + size. The result
    is shared and must be treated as read-only (see module docstring).
    """
    try:
        key = _stat_key(path)
    except OSError:
        return None
    return _parse_cached(*key)


def iter_py_files(
    exclude_dirs: Iterable[str],
    *,
    root: Path | None = None,
) -> list[Path]:
    """Return sorted ``*.py`` files under ``root`` (default: repo root).

    A file is skipped when any path component (relative to ``root``) is in
    ``exclude_dirs``. This reproduces the canonical ``rglob`` + ``_DIR_EXCLUDE``
    idiom used across the guard suite so newly consolidated guards can share it
    instead of re-implementing the walk.
    """
    base = root or _ROOT
    excluded = frozenset(exclude_dirs)
    out: list[Path] = []
    for path in base.rglob("*.py"):
        try:
            rel_parts = path.relative_to(base).parts
        except ValueError:
            continue
        if any(part in excluded for part in rel_parts):
            continue
        out.append(path)
    return sorted(out)
