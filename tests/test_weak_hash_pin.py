"""Pin weak-hash usage ledger (md5/sha1) across first-party prod modules.

Defense-only: ensures md5/sha1 are used **only** at the listed sites and
solely for non-cryptographic content-addressing/dedupe (cache keys, dirty-
flag fingerprints, ID stability) — never for security/auth/integrity. New
weak-hash uses must be reviewed and the ledger updated.

If a security-bearing context is ever introduced, switch to sha256 and
remove from this ledger; do not extend it silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

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

# Frozen ledger: {relative_path: count_of_md5_or_sha1_call_sites}
_FROZEN_LEDGER: dict[str, int] = {
    "databento_utils.py": 1,
    # PR #2339: +1 (3→4) — _build_universe_metadata adds a sha1 fingerprint
    # of the sorted universe symbol list for parquet schema metadata
    # (non-security; cache-version stamp).
    "databento_volatility_screener.py": 4,
    "newsstack_fmp/normalize.py": 6,
    "newsstack_fmp/scoring.py": 1,
    "newsstack_fmp/shared_fetch.py": 2,
    "open_prep/dirty_flag_manager.py": 1,
    "open_prep/realtime_signals.py": 1,
    "terminal_poller.py": 2,
}

_TOTAL_BUDGET = sum(_FROZEN_LEDGER.values())  # = 18


def _is_weak_hash_call(node: ast.AST) -> bool:
    """True for ``hashlib.md5(...)``, ``hashlib.sha1(...)``,
    or ``hashlib.new("md5"/"sha1", ...)``.

    Other algorithms (sha256, sha3_*, blake2*) and non-``hashlib`` calls
    are ignored.
    """
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
        return False
    if func.value.id != "hashlib":
        return False
    if func.attr in ("md5", "sha1"):
        return True
    if func.attr == "new" and node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.lower() in ("md5", "sha1")
    return False


def _iter_first_party_py():
    for p in REPO.rglob("*.py"):
        rel_parts = p.relative_to(REPO).parts
        if any(part in _DIR_EXCLUDE for part in rel_parts):
            continue
        yield p


def _count_weak_hash_calls(p: Path) -> int:
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return 0
    return sum(1 for node in ast.walk(tree) if _is_weak_hash_call(node))


def _scan_all() -> dict[str, int]:
    counts: dict[str, int] = {}
    for p in _iter_first_party_py():
        n = _count_weak_hash_calls(p)
        if n:
            # POSIX form keeps the key stable across OSes (#2244).
            rel = p.relative_to(REPO).as_posix()
            counts[rel] = n
    return counts


# --------------------------------------------------------------------------- #
# Total budget                                                                #
# --------------------------------------------------------------------------- #


def test_weak_hash_total_call_budget_is_frozen() -> None:
    counts = _scan_all()
    actual = sum(counts.values())
    assert actual == _TOTAL_BUDGET, (
        f"Weak-hash (md5/sha1) total drifted: actual={actual} "
        f"frozen={_TOTAL_BUDGET}. Per-file: {sorted(counts.items())}. "
        "If a new weak-hash use was added, justify (non-crypto only) and "
        "update the ledger; if a use was removed/migrated to sha256, "
        "shrink the ledger."
    )


# --------------------------------------------------------------------------- #
# No new files                                                                #
# --------------------------------------------------------------------------- #


def test_weak_hash_no_new_files() -> None:
    counts = _scan_all()
    new_files = sorted(set(counts) - set(_FROZEN_LEDGER))
    assert not new_files, (
        f"New first-party files introduced weak-hash usage: {new_files}. "
        "Either migrate to sha256 (preferred) or extend the ledger with "
        "explicit non-crypto justification in the PR."
    )


# --------------------------------------------------------------------------- #
# No stale ledger entries                                                     #
# --------------------------------------------------------------------------- #


def test_weak_hash_no_stale_ledger_entries() -> None:
    counts = _scan_all()
    stale = sorted(set(_FROZEN_LEDGER) - set(counts))
    assert not stale, (
        f"Ledger entries no longer have weak-hash usage: {stale}. "
        "Remove them from `_FROZEN_LEDGER`."
    )


# --------------------------------------------------------------------------- #
# Per-file count parametrised                                                 #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rel_path,expected", sorted(_FROZEN_LEDGER.items()))
def test_weak_hash_per_file_count_pinned(rel_path: str, expected: int) -> None:
    p = REPO / rel_path
    assert p.exists(), f"Ledger file {rel_path!r} no longer exists."
    actual = _count_weak_hash_calls(p)
    assert actual == expected, (
        f"{rel_path}: weak-hash call count drifted "
        f"actual={actual} expected={expected}. Update the ledger."
    )


# --------------------------------------------------------------------------- #
# Files in ledger must exist                                                  #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rel_path", sorted(_FROZEN_LEDGER))
def test_weak_hash_ledger_file_exists(rel_path: str) -> None:
    assert (REPO / rel_path).exists(), (
        f"Ledger file {rel_path!r} no longer exists."
    )
