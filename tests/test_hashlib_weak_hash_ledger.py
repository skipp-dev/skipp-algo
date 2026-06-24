"""Defense-pin: ledger of ``hashlib.md5`` / ``hashlib.sha1`` weak-hash sites.

Both MD5 and SHA1 are cryptographically broken. They remain
acceptable for *non-security-sensitive* use (e.g. cache keys,
deduplication fingerprints) — which is exactly how this repo uses
them today: short content fingerprints for atomic-write cache, item
IDs, and dedup keys. None gate authentication or signature
verification.

This pin **freezes the inventory** so any new use is a forced design
decision (and the test message points reviewers at SHA-256 /
BLAKE2 for any fingerprint that may grow into a security boundary).

Detection:
* ``hashlib.md5(...)`` and ``hashlib.sha1(...)`` direct attribute
  calls.
* ``hashlib.new("md5"|"sha1", ...)`` constant-string variants.

Out of scope: HMAC, PBKDF2, scrypt — all of which use MD5/SHA1
internally for legacy-compat reasons. The pin only catches direct
top-level digest construction.
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

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

_WEAK_DIGESTS = frozenset({"md5", "sha1"})

# Frozen ledger: {rel_posix_path: {algo: frozenset[lineno]}}.
_FROZEN_SITES: dict[str, dict[str, frozenset[int]]] = {
    # #2334: the cache-version comment block was added above
    # CACHE_VERSION_BY_CATEGORY (not inside build_cache_path), which shifted
    # the sha1 call by 3 lines (85 -> 88); semantics unchanged (non-security
    # cache key fingerprint).
    "databento_utils.py": {"sha1": frozenset({88})},
    # Phase-A cache-probe instrumentation moved the three cache-key sha1 uses
    # downward in the file; semantics stay non-security cache fingerprinting.
    # PR #2339 added _build_universe_metadata (sha1 universe fingerprint, line
    # 475) and shifted the two cache-probe sites by ~100 lines (cache-pollution
    # filter + drift detector block). Still non-security fingerprinting.
    # 2026-06-10 (#2670 W9): timestamp_substitutions disclosure shifted +5.
    "databento_volatility_screener.py": {"sha1": frozenset({400, 482, 698, 716})},
    "newsstack_fmp/normalize.py": {
        "md5": frozenset({132, 255}),
        "sha1": frozenset({336, 422, 460, 504}),
    },
    "newsstack_fmp/scoring.py": {"sha1": frozenset({123})},
    "newsstack_fmp/shared_fetch.py": {
        "md5": frozenset({77}),
        "sha1": frozenset({186}),
    },
    "open_prep/dirty_flag_manager.py": {"md5": frozenset({74})},
    "open_prep/realtime_signals.py": {"md5": frozenset({1249})},
    # #2334: offline simulation script mirrors build_cache_path's digest
    # computation to re-key probe paths. Non-security cache-fingerprint use.
    "scripts/simulate_cache_redesign_2334.py": {"sha1": frozenset({49})},
    "terminal_poller.py": {"md5": frozenset({195, 234})},
}

_FROZEN_TOTAL = sum(
    len(linenos) for site in _FROZEN_SITES.values() for linenos in site.values()
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


def _scan_weak_hashes(tree: ast.AST) -> list[tuple[str, int]]:
    """Return [(algo, lineno), ...] for hashlib.md5/sha1 + hashlib.new('md5'/'sha1')."""
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not isinstance(f, ast.Attribute):
            continue
        if not (isinstance(f.value, ast.Name) and f.value.id == "hashlib"):
            continue
        if f.attr in _WEAK_DIGESTS:
            out.append((f.attr, node.lineno))
        elif f.attr == "new" and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Constant) and isinstance(a0.value, str):
                algo = a0.value.lower()
                if algo in _WEAK_DIGESTS:
                    out.append((algo, node.lineno))
    return out


def _parse(path: Path) -> ast.AST | None:
    return parse_module(path)


@functools.cache
def _live_inventory() -> dict[str, dict[str, frozenset[int]]]:
    out: dict[str, dict[str, frozenset[int]]] = {}
    for path in _iter_first_party_py_files():
        tree = _parse(path)
        if tree is None:
            continue
        sites = _scan_weak_hashes(tree)
        if not sites:
            continue
        rel = path.relative_to(ROOT).as_posix()
        per_algo: dict[str, set[int]] = {}
        for algo, lineno in sites:
            per_algo.setdefault(algo, set()).add(lineno)
        out[rel] = {algo: frozenset(linenos) for algo, linenos in per_algo.items()}
    return out


def test_no_new_weak_hash_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    new = sorted(live - frozen)
    assert not new, (
        "New file(s) introduced hashlib.md5/sha1 without ledger update:\n"
        + "\n".join(f"  - {f}" for f in new)
        + "\n\nMD5 and SHA1 are cryptographically broken. They are OK "
        "for non-security fingerprints (cache keys, dedup IDs) but if "
        "the new use crosses into auth / signature / integrity, prefer "
        "SHA-256 / BLAKE2. Add the file to ``_FROZEN_SITES`` with a "
        "justifying comment."
    )


def test_no_removed_weak_hash_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_SITES.keys())
    removed = sorted(frozen - live)
    assert not removed, (
        "Frozen weak-hash file(s) disappeared (good if migrated to "
        "SHA-256, but shrink ``_FROZEN_SITES`` accordingly):\n"
        + "\n".join(f"  - {f}" for f in removed)
    )


@pytest.mark.parametrize(
    ("rel_path", "algo", "expected_linenos"),
    sorted(
        (rel, algo, linenos)
        for rel, per_algo in _FROZEN_SITES.items()
        for algo, linenos in per_algo.items()
    ),
)
def test_frozen_weak_hash_linenos_still_match(
    rel_path: str, algo: str, expected_linenos: frozenset[int]
) -> None:
    inv = _live_inventory()
    assert rel_path in inv, (
        f"Frozen file {rel_path!r} no longer contains any weak-hash call. "
        "Either re-introduce it or shrink ``_FROZEN_SITES``."
    )
    assert algo in inv[rel_path], (
        f"Frozen algo {algo!r} no longer present in {rel_path}. "
        "Update ``_FROZEN_SITES`` after auditing the migration."
    )
    live_linenos = inv[rel_path][algo]
    assert live_linenos == expected_linenos, (
        f"hashlib.{algo} line drift in {rel_path}: "
        f"frozen={sorted(expected_linenos)} live={sorted(live_linenos)}. "
        "Update ``_FROZEN_SITES`` if the move is intentional."
    )


def test_total_count_pinned() -> None:
    inv = _live_inventory()
    total = sum(len(linenos) for site in inv.values() for linenos in site.values())
    assert total == _FROZEN_TOTAL, (
        f"Total weak-hash call count drifted: frozen={_FROZEN_TOTAL} "
        f"live={total}. Update ``_FROZEN_TOTAL`` after audit."
    )
