"""Defense-pin: per-file budget of field-preference ``or``-chains.

Audit #2670 G1 (follow-up to #2668): chains like::

    row.get("size") or row.get("volume")

silently substitute a *semantically different* field when the preferred
one is missing — AND treat falsy-but-valid values (``0``, ``0.0``, ``""``,
``[]``) as missing. Round-1/round-2 audits found real bugs from this
pattern (premium computed from session volume instead of print size,
quote timestamps passing trade-staleness gates, proxy regimes served as
measured indicators).

This ledger freezes two things per file: the COUNT of such chains, and the
KEYS each chain reads. Line numbers are deliberately NOT pinned — these files
churn too much; the sister ``subprocess_shell_injection_pin`` uses the same
count-based shape.

The keys matter because the count alone cannot see the harm above. Swapping a
key at an already-budgeted chain — ``quote.get("last") or quote.get("close")``
-> ``... or quote.get("open")`` — substitutes a semantically different field
and leaves the count untouched. The scanner had always computed the keys and
then discarded them (2026-07-15).

A new site trips this test. The author must then either:

1. Replace the chain with an explicit ``is None`` check **plus** a
   ``*_source`` disclosure field (see
   ``docs/review-checklist-field-preference-chains.md``), or
2. Consciously bump the budget in ``pin_registry.toml`` with a comment
   explaining why the chain is benign (true synonyms from one upstream
   contract, e.g. ``title``/``headline``).

Detection is conservative: only ``ast.BoolOp(Or)`` whose operands contain
>=2 ``<expr>.get("string-literal", ...)`` calls with >=2 distinct keys.
``getattr(...) or getattr(...)``, subscripts, and non-literal keys are out
of scope (rare in this repo; extend deliberately if they appear).
"""

from __future__ import annotations

import ast
import functools
from pathlib import Path

import pytest

from tests._guard_corpus import parse_module
from tests._pin_registry import (
    field_preference_chain_file_counts,
    field_preference_chain_file_keys,
)

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

# Source of truth: pin_registry.toml (ADR-0009).
_FROZEN_FILE_COUNTS: dict[str, int] = field_preference_chain_file_counts()
_FROZEN_FILE_KEYS: dict[str, list[tuple[str, ...]]] = (
    field_preference_chain_file_keys()
)

_FROZEN_TOTAL = sum(_FROZEN_FILE_COUNTS.values())


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


def _get_literal_key(node: ast.AST) -> str | None:
    """Return the key when *node* is ``<expr>.get("literal", ...)``."""
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ):
        return node.args[0].value
    return None


def _scan_preference_chains(tree: ast.AST) -> list[int]:
    """Return linenos of ``or``-chains over >=2 distinct ``.get`` keys."""
    return [lineno for lineno, _keys in _scan_preference_chain_keys(tree)]


def _scan_preference_chain_keys(tree: ast.AST) -> list[tuple[int, tuple[str, ...]]]:
    """Return ``(lineno, keys)`` for each ``or``-chain over >=2 distinct keys.

    The keys were already being computed here — :func:`_get_literal_key` reads
    them off every leg — and then thrown away, because
    :func:`_scan_preference_chains` returned line numbers only. That is what let
    ``row.get("size") or row.get("volume")`` become
    ``row.get("size") or row.get("timestamp")`` while the per-file count above
    held: a *semantically different* field substituted at an already-budgeted
    chain, which is the harm this ledger names and one of the real bugs #2670
    found (premium computed from session volume instead of print size).
    """

    out: list[tuple[int, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)):
            continue
        keys = [
            key
            for key in (_get_literal_key(value) for value in node.values)
            if key is not None
        ]
        if len(keys) >= 2 and len(set(keys)) >= 2:
            out.append((node.lineno, tuple(keys)))
    return out


@functools.cache
def _live_inventory() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for path in _iter_first_party_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        sites = _scan_preference_chains(tree)
        if sites:
            out[path.relative_to(ROOT).as_posix()] = sites
    return out


def test_no_new_files_with_preference_chains() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_FILE_COUNTS.keys())
    new_files = sorted(live - frozen)
    assert not new_files, (
        "New file(s) introduced field-preference or-chains "
        "(`x.get('a') or y.get('b')` over different keys) without a "
        "ledger entry:\n"
        + "\n".join(
            f"  - {f}: lines {_live_inventory()[f]}" for f in new_files
        )
        + "\n\nPreferred fix: explicit `is None` check + `*_source` "
        "disclosure field (docs/review-checklist-field-preference-chains.md). "
        "If the chain is a benign synonym chain, add the file to "
        "[field_preference_chain_ledger.file_counts] in pin_registry.toml "
        "with a justifying comment."
    )


def test_no_stale_ledger_files() -> None:
    live = set(_live_inventory().keys())
    frozen = set(_FROZEN_FILE_COUNTS.keys())
    removed_files = sorted(frozen - live)
    assert not removed_files, (
        "Ledgered file(s) no longer contain any field-preference chain "
        "(good!), but the ledger must be shrunk to match:\n"
        + "\n".join(f"  - {f}" for f in removed_files)
    )


@pytest.mark.parametrize(
    ("rel_path", "expected_count"),
    sorted(_FROZEN_FILE_COUNTS.items()),
)
def test_per_file_chain_count_pinned(rel_path: str, expected_count: int) -> None:
    live_sites = _live_inventory().get(rel_path, [])
    assert len(live_sites) == expected_count, (
        f"Field-preference chain count drifted in {rel_path}: "
        f"frozen={expected_count} live={len(live_sites)} "
        f"(live lines: {live_sites}).\n"
        "Grew: fix the new chain (is-None + *_source disclosure, see "
        "docs/review-checklist-field-preference-chains.md) or bump the "
        "budget with a justifying comment in pin_registry.toml. "
        "Shrank: lower the budget — never leave headroom."
    )


def test_total_count_pinned() -> None:
    total = sum(len(sites) for sites in _live_inventory().values())
    assert total == _FROZEN_TOTAL, (
        f"Total field-preference chain count drifted: "
        f"frozen={_FROZEN_TOTAL} live={total}. Update "
        "pin_registry.toml after auditing the delta."
    )


def test_scanner_detects_canonical_pattern() -> None:
    """Self-test: the scanner recognises the canonical bug shape."""
    tree = ast.parse(
        "size = row.get('size') or row.get('volume') or 0.0\n"
        "same = row.get('x') or row.get('x')\n"  # same key — not a chain
        "single = row.get('y') or 0.0\n"  # one get — not a chain
    )
    assert _scan_preference_chains(tree) == [1]
    assert _scan_preference_chain_keys(tree) == [(1, ("size", "volume"))]


# ─── which keys, not just how many chains ────────────────────────────


@functools.cache
def _live_chain_keys() -> dict[str, list[tuple[str, ...]]]:
    out: dict[str, list[tuple[str, ...]]] = {}
    for path in _iter_first_party_py_files():
        tree = parse_module(path)
        if tree is None:
            continue
        chains = [keys for _lineno, keys in _scan_preference_chain_keys(tree)]
        if chains:
            out[path.relative_to(ROOT).as_posix()] = sorted(chains)
    return out


def test_chain_keys_match_frozen_keys() -> None:
    """Which fields a budgeted chain substitutes must not change unreviewed.

    The counts above answer "how many chains does this file have". Swapping a
    key at an existing chain keeps the count and changes the meaning — the
    substitution this ledger exists to force a review of.
    """
    live = _live_chain_keys()
    frozen = {rel: sorted(chains) for rel, chains in _FROZEN_FILE_KEYS.items()}

    drifted = sorted(
        (rel, frozen.get(rel, []), live.get(rel, []))
        for rel in set(frozen) | set(live)
        if frozen.get(rel, []) != live.get(rel, [])
    )
    assert not drifted, (
        "field-preference chain keys drifted. A chain now reads different "
        "field(s) than the ledger records — the count is unchanged, so nothing "
        "else catches it. This is the #2670 G1 harm: a semantically different "
        "field silently substituted (premium from session volume instead of "
        "print size; quote timestamps passing trade-staleness gates). If the "
        "change is intentional, update [field_preference_chain_ledger.file_keys] "
        "in pin_registry.toml with a justification.\n"
        + "\n".join(
            f"  - {rel}\n      frozen: {f}\n      live:   {live_}"
            for rel, f, live_ in drifted
        )
    )


def test_chain_counts_match_frozen_keys() -> None:
    """The two ledger layers must describe the same inventory.

    ``file_counts`` and ``file_keys`` are maintained side by side, so they can
    disagree. One entry per chain means the count is just ``len(keys)``; this
    keeps a partial edit of either from passing.
    """
    mismatched = sorted(
        (rel, _FROZEN_FILE_COUNTS.get(rel), len(_FROZEN_FILE_KEYS.get(rel, [])))
        for rel in set(_FROZEN_FILE_COUNTS) | set(_FROZEN_FILE_KEYS)
        if _FROZEN_FILE_COUNTS.get(rel) != len(_FROZEN_FILE_KEYS.get(rel, []))
    )
    assert not mismatched, (
        "pin_registry.toml: file_counts and file_keys disagree. Every chain "
        "needs exactly one key entry.\n"
        + "\n".join(
            f"  - {rel}: file_counts={c}, len(file_keys)={k}"
            for rel, c, k in mismatched
        )
    )
