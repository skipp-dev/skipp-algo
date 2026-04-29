"""Bounded-cache sweep across the in-repo source tree.

Phase-9 finding from `smc-system-review-2026-04-24.md`: ``@lru_cache``
without an explicit ``maxsize=N`` is unbounded by default and silently
accumulates one cache entry per distinct argument tuple for the lifetime
of the Python process. In long-running Streamlit sessions and the
background poller, this is a memory leak.

The current state is **clean** (3 in-repo uses, all bounded). This test
locks the property in so a future contributor cannot land an unbounded
``@lru_cache`` without an explicit waiver.

Out-of-scope: ``.venv/`` and ``site-packages/`` (third-party).
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Folders to skip entirely. Vendored deps + virtualenv + caches.
_SKIP_DIRS = frozenset({
    ".venv",
    "venv",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    "site-packages",
    "__pycache__",
    ".git",
    "build",
    "dist",
})

# Path-fragment waivers (relative to REPO_ROOT, posix). Add an entry
# here ONLY with a written justification in CHANGELOG.md.
_WAIVERS: frozenset[str] = frozenset()


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for path in REPO_ROOT.rglob("*.py"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in _SKIP_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def _decorator_calls_lru_cache(deco: ast.expr) -> tuple[bool, bool]:
    """Return (is_lru_cache, has_explicit_maxsize) for a decorator node.

    Recognises:
      @lru_cache
      @lru_cache()
      @lru_cache(maxsize=N)
      @functools.lru_cache  / @functools.lru_cache(...)
    """
    name: str | None = None
    has_call = False
    keywords: list[ast.keyword] = []

    if isinstance(deco, ast.Name):
        name = deco.id
    elif isinstance(deco, ast.Attribute):
        name = deco.attr
    elif isinstance(deco, ast.Call):
        has_call = True
        keywords = list(deco.keywords)
        func = deco.func
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr

    if name != "lru_cache":
        return (False, False)

    # Bare ``@lru_cache`` or ``@lru_cache()`` → unbounded default 128.
    # We treat absence of ``maxsize`` (or any positional first arg) as
    # "no explicit cap configured" — fail.
    if not has_call:
        return (True, False)

    # ``@lru_cache(N)`` (positional) — counted as explicit cap.
    if isinstance(deco, ast.Call) and deco.args:
        return (True, True)

    for kw in keywords:
        if kw.arg == "maxsize":
            # ``maxsize=None`` is **explicitly** unbounded — disallow.
            if isinstance(kw.value, ast.Constant) and kw.value.value is None:
                return (True, False)
            return (True, True)
    return (True, False)


def _collect_unbounded(path: Path) -> list[int]:
    """Return line numbers of unbounded ``@lru_cache`` decorators."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            is_lru, bounded = _decorator_calls_lru_cache(deco)
            if is_lru and not bounded:
                hits.append(deco.lineno)
    return hits


def test_no_unbounded_lru_cache_in_repo() -> None:
    """Pin: every in-repo ``@lru_cache`` carries an explicit ``maxsize=N``."""
    offenders: list[tuple[str, int]] = []
    for path in _iter_python_files():
        rel_posix = path.relative_to(REPO_ROOT).as_posix()
        if rel_posix in _WAIVERS:
            continue
        for line in _collect_unbounded(path):
            offenders.append((rel_posix, line))
    assert not offenders, (
        "Unbounded @lru_cache detected (Phase-9 / PR #98 A-2 regression):\n"
        + "\n".join(f"  {f}:{ln}" for f, ln in offenders)
        + "\n\nFix: add an explicit ``maxsize=N`` based on the cache "
        "domain cardinality. ``maxsize=None`` is also rejected — it is "
        "explicitly unbounded. If a true global cache is intentional, "
        "add the path to ``_WAIVERS`` in this test with a justification "
        "in CHANGELOG.md."
    )


def test_sweep_visits_at_least_one_known_consumer() -> None:
    """Sanity: the sweep actually scans known cached files.

    Without this guard, a refactor that renames or skips the cached
    modules would silently turn the sweep into a no-op.
    """
    files = {p.relative_to(REPO_ROOT).as_posix() for p in _iter_python_files()}
    expected_at_least_one = {
        "scripts/smc_newsapi_ai.py",
        "newsstack_fmp/_market_cal.py",
    }
    overlap = files & expected_at_least_one
    assert overlap, (
        f"Bounded-cache sweep failed to enumerate known-cached files. "
        f"Expected at least one of {expected_at_least_one}, scanned "
        f"{len(files)} files. _SKIP_DIRS may be too aggressive."
    )
