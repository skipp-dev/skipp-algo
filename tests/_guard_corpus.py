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
import os
import shutil
import subprocess
from collections.abc import Iterable
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]

MIN_EXPECTED_PROD_FILES = 50
"""Minimum number of production ``*.py`` files expected in the repo scan.

Used across ledger/pin/budget tests to guard against overly broad
``_DIR_EXCLUDE`` sets or sparse-checkout environments returning too few files.
"""


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


@functools.cache
def _git_ls_files(base_str: str, pattern: str) -> tuple[str, ...] | None:
    """Return git-tracked files for ``pattern`` relative to ``base_str``.

    Returns ``None`` when git is unavailable or the command fails, so callers
    can gracefully fall back to filesystem walks.

    The ``GIT_*`` environment is stripped so ``base_str`` is authoritative.
    Without that, ``-C`` is only half the story: ``pre-commit`` exports
    ``GIT_DIR`` / ``GIT_INDEX_FILE`` when it runs a hook, and those WIN over
    ``-C`` — so under the pre-push hook this resolved to the repo the hook runs
    in and quietly ignored the caller's ``root``. Benign for the production
    guards, which pass the repo root anyway, but it made the ``root`` parameter
    a lie for anyone else (a test pointing at a throwaway repo got this repo's
    inventory back).
    """
    git = shutil.which("git")
    if git is None:
        return None
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        proc = subprocess.run(
            [git, "-C", base_str, "ls-files", "-z", "--", pattern],
            check=True,
            capture_output=True,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if not proc.stdout:
        return tuple()
    entries = [item for item in proc.stdout.decode("utf-8").split("\x00") if item]
    return tuple(entries)


def iter_tracked_files(
    pattern: str,
    exclude_dirs: Iterable[str],
    *,
    root: Path | None = None,
) -> list[Path]:
    """Return sorted git-tracked files matching ``pattern`` under ``root``.

    If git is unavailable, falls back to a filesystem walk with the same
    exclude semantics used by :func:`iter_py_files`.
    """
    base = root or _ROOT
    excluded = frozenset(exclude_dirs)

    rels = _git_ls_files(str(base.resolve()), pattern)
    out: list[Path] = []

    if rels is None:
        for path in base.rglob(pattern):
            try:
                rel_parts = path.relative_to(base).parts
            except ValueError:
                continue
            if any(part in excluded for part in rel_parts):
                continue
            out.append(path)
        return sorted(out)

    for rel in rels:
        path = base / rel
        rel_parts = Path(rel).parts
        if any(part in excluded for part in rel_parts):
            continue
        if path.exists():
            out.append(path)
    return sorted(out)


def iter_production_py_files(
    exclude_dirs: Iterable[str],
    *,
    root: Path | None = None,
    minimum: int = MIN_EXPECTED_PROD_FILES,
) -> list[Path]:
    """Like :func:`iter_tracked_files` for ``*.py``, but refuses a collapsed corpus.

    Use this — not the raw :func:`iter_tracked_files` — whenever a guard's claim
    is "I checked the whole production tree". It is the difference between a
    guard that PASSED and a guard that merely found nothing to look at.

    :data:`MIN_EXPECTED_PROD_FILES` documented this exact hazard ("overly broad
    ``_DIR_EXCLUDE`` sets or sparse-checkout environments returning too few
    files") but nothing enforced it, and the collapse is reachable: when git
    runs fine and simply matches nothing, ``_git_ls_files`` returns an empty
    tuple rather than ``None``, so :func:`iter_tracked_files` returns ``[]`` and
    the filesystem fallback is deliberately NOT taken. A guard scanning that
    empty list asserts over nothing and reports green.

    The floor lives here rather than in :func:`iter_tracked_files` on purpose:
    that helper takes an arbitrary pattern and root, so a legitimate zero-match
    query must stay able to return ``[]`` honestly. Only callers that promise
    the full corpus opt into the floor, and they say so by calling this.

    Raises:
        AssertionError: if fewer than ``minimum`` files are found.
    """
    files = iter_tracked_files("*.py", exclude_dirs, root=root)
    if len(files) < minimum:
        base = root or _ROOT
        raise AssertionError(
            f"production corpus collapsed: found {len(files)} *.py file(s) under "
            f"{base}, expected >= {minimum}. The guard calling this would "
            f"otherwise have scanned almost nothing and reported green. Likely "
            f"causes: an over-broad exclude_dirs, a sparse checkout, or a root "
            f"that is not the repo."
        )
    return files


MIN_EXPECTED_BRIDGES = 3


def live_overlay_bridge_names(*, root: Path | None = None) -> tuple[str, ...]:
    """Every bridge name the daemon actually exports, read out of ``metrics.py``.

    The alert-rule contract and the dashboard's bridge panel both have to cover
    *all* bridges. Both used to carry a hand-written tuple of three names, so a
    fourth bridge would have shipped uncovered by either — and the tests would
    still have passed, because they only ever asserted about the three names
    they themselves listed. Deriving the list from the exporter turns that into
    a failing test the day a bridge is added.

    Raises:
        AssertionError: if fewer than :data:`MIN_EXPECTED_BRIDGES` are found —
            an empty or collapsed result would make every caller vacuous.
    """
    base = root or _ROOT
    tree = parse_module(base / "services" / "live_overlay_daemon" / "metrics.py")
    names: set[str] = set()
    if tree is not None:
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            called = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if called != "_append_bridge_metrics":
                continue
            for keyword in node.keywords:
                if keyword.arg == "bridge" and isinstance(keyword.value, ast.Constant):
                    value = keyword.value.value
                    if isinstance(value, str) and value:
                        names.add(value)
    if len(names) < MIN_EXPECTED_BRIDGES:
        raise AssertionError(
            f"bridge inventory collapsed: found {sorted(names)} in metrics.py, "
            f"expected >= {MIN_EXPECTED_BRIDGES}. Callers would otherwise assert "
            f"coverage over almost nothing and report green."
        )
    return tuple(sorted(names))
