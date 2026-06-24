"""Defense tripwire: ``except Exception: pass`` (and ``: continue``) sites
in first-party production code are frozen at the current count and
exact locations.

Background
----------
Broad-except + silent body is a known footgun: it swallows every
exception (including ``KeyboardInterrupt`` is excluded since 3.x because
``Exception`` no longer inherits from ``BaseException``, but it still
swallows ``MemoryError``, ``OSError``, programming bugs, and silently
hides regressions). We **do** have a small number of legitimate uses:

- DNS-resolution best-effort guards (private-IP detection)
- ``conn.close()`` cleanup
- Optional ``yfinance``/``ws`` calls where failure is tolerable
- Module-import fallbacks (``# pragma: no cover``)
- Wall-clock fallback on missing market-session helper

Rather than rewrite each site (each one would need its own narrower
exception type and observability decision), we **freeze** the current
inventory: the pin records every existing site by ``(rel_path, lineno)``
and fails when

1. a new ``except Exception: pass`` (or ``: continue``) appears, or
2. an existing pinned site no longer matches (forces the allowlist to
   stay accurate when refactors move code).

This is the same defense-pin pattern used by the FDR / SPRT vocab pins.
Production behaviour is unchanged.

Scope
-----
First-party production ``*.py`` only. ``tests/``, ``scripts/``, ``docs/``,
virtualenvs, caches, and the ``SMC++/`` Pine workspace are excluded.

Notes
-----
"Broad" means ``except Exception``, ``except BaseException``, bare
``except:``, or any exception tuple that contains one of those names.
Specific exception types (``OSError``, ``ValueError``, …) are NOT
covered by this pin and are considered legitimate by construction.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

_DIR_EXCLUDE: frozenset[str] = frozenset(
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
        "scripts",
        "tests",
        "SMC++",
    }
)

# Frozen inventory of every existing broad-except + silent-body site,
# pinned by **per-file count** (not exact line numbers).
#
# Why count, not (path, lineno):
#   The previous version of this pin recorded each handler's lineno.
#   That made the test break on every unrelated edit that shifted lines
#   (the ingest_benzinga.py entry broke twice in a single day on
#   2026-04-30). The policy here is *no growth in the broad-silent
#   surface*, which is fundamentally a count, not a location. Refactors
#   that move a swallow within a file are now no-ops for this guard;
#   net additions / removals still fail closed.
_FROZEN_SITE_COUNTS: dict[str, int] = {
    "smc_tv_bridge/smc_api.py": 1,
    "open_prep/alerts.py": 1,
    # 2026-05-17 C12.1 ConstraintHitLog wiring: an audit-log write
    # failure must never block a guard decision. See HardConstraintLayer._log.
    "rl/safety/__init__.py": 1,
    # 2026-06-24 feat/benzinga-rss: best-effort guards in measurement_evidence.
    "smc_integration/measurement_evidence.py": 2,
}


def _iter_first_party_py_files() -> list[Path]:
    files: list[Path] = []
    for entry in _REPO_ROOT.iterdir():
        if entry.name.startswith("."):
            continue
        if entry.name in _DIR_EXCLUDE:
            continue
        if entry.is_file() and entry.suffix == ".py":
            files.append(entry)
        elif entry.is_dir():
            for path in entry.rglob("*.py"):
                if any(part.startswith(".") for part in path.parts):
                    continue
                if any(part in _DIR_EXCLUDE for part in path.parts):
                    continue
                files.append(path)
    return sorted(files)


def _is_broad_except(handler: ast.ExceptHandler) -> bool:
    """True if the handler matches every Exception (incl. bare except)."""
    htype = handler.type
    if htype is None:
        return True
    if isinstance(htype, ast.Name) and htype.id in ("Exception", "BaseException"):
        return True
    if isinstance(htype, ast.Tuple):
        for el in htype.elts:
            if isinstance(el, ast.Name) and el.id in ("Exception", "BaseException"):
                return True
    return False


def _has_silent_body(handler: ast.ExceptHandler) -> bool:
    """True if the body is a single ``pass`` or ``continue`` statement."""
    if len(handler.body) != 1:
        return False
    only = handler.body[0]
    return isinstance(only, (ast.Pass, ast.Continue))


def _collect_broad_silent_sites(path: Path) -> set[int]:
    """Return line numbers of every broad-except + silent-body handler."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()
    out: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for handler in node.handlers:
            if _is_broad_except(handler) and _has_silent_body(handler):
                out.add(handler.lineno)
    return out


def test_first_party_files_present() -> None:
    """Sanity: scan finds production files (catch layout drift)."""
    files = _iter_first_party_py_files()
    assert len(files) >= 50, (
        f"Expected at least 50 first-party .py files; found {len(files)}. "
        "If the repo layout changed, update _DIR_EXCLUDE."
    )


def test_no_unexpected_broad_except_silent_sites() -> None:
    """Per-file count of broad-except + silent-body must match the frozen
    inventory.

    Failure here = a *new* ``except Exception: pass`` (or ``: continue``)
    appeared, OR a frozen file dropped a previously-pinned site, OR a
    file outside the inventory grew a broad-silent handler. Either
    narrow the new exception type / add observability, or update
    ``_FROZEN_SITE_COUNTS`` with explicit justification in the PR
    description.
    """
    actual_counts: dict[str, int] = {}
    for path in _iter_first_party_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        sites = _collect_broad_silent_sites(path)
        if sites:
            actual_counts[rel] = len(sites)

    new_files = sorted(set(actual_counts) - set(_FROZEN_SITE_COUNTS))
    assert not new_files, (
        "New file(s) with broad-except + silent-body handler(s) (not in "
        "_FROZEN_SITE_COUNTS):\n  - "
        + "\n  - ".join(f"{rel} ({actual_counts[rel]} site(s))" for rel in new_files)
        + "\nPrefer narrowing to a specific exception type and adding a "
        "log line. If this site genuinely needs to swallow Exception, "
        "add it to _FROZEN_SITE_COUNTS with a one-line justification in "
        "the PR description."
    )

    gone_files = sorted(set(_FROZEN_SITE_COUNTS) - set(actual_counts))
    assert not gone_files, (
        "Frozen file(s) no longer contain any broad-except + silent "
        "handler:\n  - "
        + "\n  - ".join(gone_files)
        + "\nRemove the entry from _FROZEN_SITE_COUNTS (the cleanup is "
        "a good outcome \u2014 the pin just needs to follow it)."
    )

    drifted = sorted(
        (rel, _FROZEN_SITE_COUNTS[rel], actual_counts[rel])
        for rel in _FROZEN_SITE_COUNTS.keys() & actual_counts.keys()
        if _FROZEN_SITE_COUNTS[rel] != actual_counts[rel]
    )
    assert not drifted, (
        "Per-file broad-silent count drift detected:\n  - "
        + "\n  - ".join(f"{rel}: frozen={frozen}, actual={actual}" for rel, frozen, actual in drifted)
        + "\nUpdate _FROZEN_SITE_COUNTS with justification, or restore "
        "the previous handler."
    )


@pytest.mark.parametrize("rel_path", sorted(_FROZEN_SITE_COUNTS))
def test_frozen_files_still_exist(rel_path: str) -> None:
    """Every frozen file path must still exist on disk.

    Forces the inventory to track real refactors instead of silently
    rotting into a stale list pointing at deleted files.
    """
    path = _REPO_ROOT / rel_path
    assert path.is_file(), (
        f"Frozen-site path missing: {rel_path}. Update "
        "_FROZEN_SITE_COUNTS after the refactor that moved or deleted "
        "this file."
    )
