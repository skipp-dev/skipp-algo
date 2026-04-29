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

# Frozen inventory of every existing broad-except + silent-body site.
# ``(relative_posix_path, lineno_of_handler)``. Exact match required.
# When a refactor moves code, update the lineno here in the SAME PR.
_FROZEN_SITES: frozenset[tuple[str, int]] = frozenset(
    {
        ("streamlit_terminal_alerts.py", 92),
        ("smc_tv_bridge/smc_api.py", 85),
        ("open_prep/alerts.py", 240),
        ("open_prep/run_open_prep.py", 4502),
        ("open_prep/macro.py", 33),
        ("open_prep/streamlit_monitor.py", 75),
        ("open_prep/streamlit_monitor.py", 126),
        ("terminal_spike_scanner.py", 161),
        ("newsstack_fmp/ingest_benzinga.py", 565),
        ("newsstack_fmp/store_sqlite.py", 176),
        ("newsstack_fmp/store_sqlite.py", 283),
    }
)


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
    """Every broad-except + silent-body site must be in the frozen inventory.

    Failure here = a *new* ``except Exception: pass`` (or ``: continue``)
    appeared. Either narrow the exception type / add observability, or
    add the new site to ``_FROZEN_SITES`` with explicit justification in
    the PR description.
    """
    seen: set[tuple[str, int]] = set()
    for path in _iter_first_party_py_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for lineno in _collect_broad_silent_sites(path):
            seen.add((rel, lineno))
    new_sites = sorted(seen - _FROZEN_SITES)
    assert not new_sites, (
        "New broad-except + silent-body site(s) detected (not in "
        "_FROZEN_SITES):\n  - "
        + "\n  - ".join(f"{rel}:{ln}" for rel, ln in new_sites)
        + "\nPrefer narrowing to a specific exception type and adding a "
        "log line. If this site genuinely needs to swallow Exception, "
        "add it to _FROZEN_SITES with a one-line justification in the "
        "PR description."
    )


@pytest.mark.parametrize("entry", sorted(_FROZEN_SITES))
def test_frozen_sites_still_match(entry: tuple[str, int]) -> None:
    """Every frozen entry must still resolve to a broad-except + silent body.

    Forces the inventory to track real refactors instead of silently
    rotting into a free-pass list.
    """
    rel_path, lineno = entry
    path = _REPO_ROOT / rel_path
    assert path.is_file(), (
        f"Frozen-site path missing: {rel_path}. Update _FROZEN_SITES "
        "after the refactor that moved or deleted this file."
    )
    sites = _collect_broad_silent_sites(path)
    assert lineno in sites, (
        f"Frozen entry {rel_path}:{lineno} no longer matches a broad-"
        "except + silent-body handler. Update the lineno (or remove the "
        "entry) in _FROZEN_SITES."
    )
