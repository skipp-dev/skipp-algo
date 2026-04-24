"""Audit pin: weak-hash budget for ``hashlib.md5`` and ``hashlib.sha1``.

MD5 and SHA-1 are cryptographically broken; using them in a security
context (auth tokens, signatures, password hashing) is a bug.  The
codebase uses them only for **non-security cache keys / dedup digests**
where collision-resistance is sufficient and the algorithm cost is the
point of the choice.

This pin freezes that intent in two layers:

1. **Frozen-site budget.** The 14 currently known call sites are
   enumerated below; any new ``hashlib.md5(`` or ``hashlib.sha1(`` call
   in production fails the no-new-sites tripwire and forces an
   intentional review (move to SHA-256, document non-security intent,
   and extend the ledger).
2. **Stale-entry guard.** Each frozen site is parametrised — if the
   call moves or disappears, the ledger must be refreshed.

Companion to the per-call ``usedforsecurity=False`` cleanup (separate
follow-up) which makes the FIPS-friendly intent explicit at every
remaining site.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent

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
        "scripts",
        "tests",
        "SMC++",
    }
)

_WEAK = frozenset({"md5", "sha1"})


def _iter_prod_files() -> list[Path]:
    out: list[Path] = []
    for path in _REPO_ROOT.rglob("*.py"):
        if any(part in _DIR_EXCLUDE for part in path.relative_to(_REPO_ROOT).parts):
            continue
        out.append(path)
    return sorted(out)


def _is_weak_hash_call(node: ast.Call) -> str | None:
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr in _WEAK
        and isinstance(func.value, ast.Name)
        and func.value.id == "hashlib"
    ):
        return func.attr
    return None


def _all_sites() -> list[tuple[str, int, str]]:
    sites: list[tuple[str, int, str]] = []
    for path in _iter_prod_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - defensive
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                algo = _is_weak_hash_call(node)
                if algo is not None:
                    sites.append((rel, node.lineno, algo))
    return sites


# Frozen inventory of weak-hash sites at the time this pin landed.
# Each entry is intentional, non-security cache-key / dedup digest use.
# Extend deliberately when (a) a new compliant site is added with
# documented non-security rationale, or (b) an existing site moves.
_FROZEN_SITES: frozenset[tuple[str, int, str]] = frozenset(
    {
        ("databento_utils.py", 85, "sha1"),
        ("databento_volatility_screener.py", 253, "sha1"),
        ("databento_volatility_screener.py", 373, "sha1"),
        ("databento_volatility_screener.py", 388, "sha1"),
        ("newsstack_fmp/normalize.py", 130, "md5"),
        ("newsstack_fmp/normalize.py", 253, "md5"),
        ("newsstack_fmp/scoring.py", 108, "sha1"),
        ("newsstack_fmp/shared_fetch.py", 74, "md5"),
        ("newsstack_fmp/shared_fetch.py", 182, "sha1"),
        ("open_prep/dirty_flag_manager.py", 74, "md5"),
        ("open_prep/realtime_signals.py", 1009, "md5"),
        ("terminal_poller.py", 189, "md5"),
        ("terminal_poller.py", 228, "md5"),
    }
)


def test_no_new_weak_hash_sites() -> None:
    """Tripwire: every new md5/sha1 site must be reviewed and ledgered."""
    current = set(_all_sites())
    new_sites = sorted(current - _FROZEN_SITES)
    assert not new_sites, (
        "New hashlib.md5/sha1 site detected — prefer hashlib.sha256(...) "
        "unless this is a documented non-security cache/dedup use; if so, "
        "pass ``usedforsecurity=False`` and extend _FROZEN_SITES with the "
        "(file, line, algo) tuple:\n  - "
        + "\n  - ".join(f"{rel}:{lineno} ({algo})" for rel, lineno, algo in new_sites)
    )


@pytest.mark.parametrize(("rel", "lineno", "algo"), sorted(_FROZEN_SITES))
def test_frozen_weak_hash_site_still_present(rel: str, lineno: int, algo: str) -> None:
    """Stale guard: every ledger entry must still match a hashlib.<algo>(...) call."""
    path = _REPO_ROOT / rel
    assert path.is_file(), f"{rel} no longer exists — refresh frozen ledger"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and node.lineno == lineno
            and _is_weak_hash_call(node) == algo
        ):
            return
    raise AssertionError(
        f"{rel}:{lineno}: hashlib.{algo}(...) no longer present — "
        f"refresh _FROZEN_SITES (call may have moved by ±N lines)."
    )


def test_frozen_inventory_size_matches_scan() -> None:
    """Inventory parity: ledger size must equal scanned site count."""
    current = set(_all_sites())
    missing_from_ledger = current - _FROZEN_SITES
    stale_in_ledger = _FROZEN_SITES - current
    assert not missing_from_ledger and not stale_in_ledger, (
        f"Weak-hash ledger drift: "
        f"new={sorted(missing_from_ledger)} "
        f"stale={sorted(stale_in_ledger)}"
    )


def test_prod_file_inventory_sane() -> None:
    files = _iter_prod_files()
    assert len(files) >= 50, (
        f"Production *.py scan only found {len(files)} files — "
        f"_DIR_EXCLUDE may be over-broad or sparse-checkout incomplete."
    )
