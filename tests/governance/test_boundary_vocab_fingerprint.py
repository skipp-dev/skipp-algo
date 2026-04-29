"""Governance gate: Boundary Vocab Fingerprint.

Closes HIGH-Finding H-4 from SMC_SYSTEM_REVIEW_2026-04-24 — "Kein
Boundary-Vocab-Fingerprint-Gate". The intent is to make any rename or
addition of a ``HERO_*`` field / value or an ``SMC_BUS`` channel an
**intentional, reviewable** change instead of a silent drift between
Python producers and Pine / Streamlit consumers.

How it works
------------
The governance test:

1. Reads the source-of-truth constants from their canonical Python
   modules (``scripts.smc_hero_state`` and ``scripts.smc_bus_manifest``).
2. Computes a deterministic SHA-256 fingerprint per vocabulary.
3. Compares the live fingerprints + raw values against the pinned
   snapshot in :file:`tests/governance/vocab_fingerprint.json`.
4. On a mismatch, emits a machine-actionable diff and the exact command
   needed to regenerate the snapshot **after** a cross-surface review.

Why two layers (values + fingerprint)
-------------------------------------
Pinning only the raw list tells you *what* changed. Pinning only the
fingerprint tells you *that* something changed. Both together let a
reviewer instantly see the semantic delta in the pytest failure output
while keeping an O(1) hash they can grep for in the Pine source.

Ordering rules
--------------
- Vocabularies stored as ``frozenset`` (HERO_TRUST_VOCAB, ...) are
  sorted ASCII-lexicographic before hashing.
- Channel tuples whose **order** is semantically load-bearing
  (ENGINE_BUS_CHANNELS drives Pine plot order) are hashed as-is.

To regenerate the snapshot after an approved change
---------------------------------------------------
::

    python tests/governance/test_boundary_vocab_fingerprint.py \\
        --regenerate-snapshot

and commit the resulting ``vocab_fingerprint.json`` in the same PR as
the vocabulary change. The commit message must reference the consumer
surfaces that were updated in lock-step (Pine dashboards, Streamlit
widgets, Showcase export, docs/BOUNDARY_CONTRACT.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from scripts.smc_bus_manifest import (
    C9_DETAIL_BUS_CHANNELS,
    C9_LEGACY_COMPAT_BUS_CHANNELS,
    C9_REBUILD_BUS_CHANNELS,
    C9_REDUCE_BUS_CHANNELS,
    C9_STABLE_PRO_BUS_CHANNELS,
    DASHBOARD_GROUP_TITLES,
    DASHBOARD_GROUP_TITLES_BY_KEY,
    ENGINE_BUS_CHANNELS,
    EXECUTABLE_BUS_CHANNELS,
    LITE_BUS_CHANNELS,
    LITE_SURFACE_BUS_CHANNELS,
    PRO_ONLY_BUS_CHANNELS,
    STRATEGY_GROUP_TITLES,
    STRATEGY_GROUP_TITLES_BY_KEY,
)
from scripts.smc_hero_state import (
    DEFAULTS as HERO_DEFAULTS,
)
from scripts.smc_hero_state import (
    HERO_ACTION_VOCAB,
    HERO_QUALITY_A_TO_B,
    HERO_SETUP_QUALITY_VOCAB,
    HERO_TRUST_VOCAB,
)

SNAPSHOT_PATH = Path(__file__).with_name("vocab_fingerprint.json")

# ---------------------------------------------------------------------------
# Hashing primitives
# ---------------------------------------------------------------------------


def _canonical_bytes(payload: Any) -> bytes:
    """Canonical JSON encoding — sorted keys, no whitespace, UTF-8."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _fp(payload: Any) -> str:
    """SHA-256 fingerprint of canonical JSON, prefixed with ``sha256:``."""
    return "sha256:" + hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def _sorted_fp(values: Sequence[str] | frozenset[str] | set[str]) -> str:
    """Fingerprint of a set-like vocabulary (order-insensitive)."""
    return _fp(sorted(values))


def _ordered_fp(values: Sequence[str]) -> str:
    """Fingerprint of an ordered tuple (order IS semantic)."""
    return _fp(list(values))


def _mapping_fp(values: Mapping[str, Any]) -> str:
    """Fingerprint of a mapping (keys + values, sorted by key)."""
    return _fp({str(k): values[k] for k in sorted(values)})


# ---------------------------------------------------------------------------
# Vocabulary registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VocabEntry:
    """One pinned boundary-vocabulary row.

    Attributes
    ----------
    key
        Snapshot key. ``HERO_TRUST_VOCAB`` / ``ENGINE_BUS_CHANNELS`` etc.
    values
        Live values pulled from the canonical module at test time.
    ordered
        ``True`` when element order is semantically load-bearing
        (e.g. Pine plot order). ``False`` for set-like vocabularies.
    kind
        ``"sequence"`` or ``"mapping"``. Mappings hash key+value.
    description
        One-line human explanation — printed on mismatch, not hashed.
    consumer_surfaces
        Downstream files that must be kept in sync when this entry
        changes. Shown in the pytest failure message so the author of
        a broken PR sees exactly where to look.
    """

    key: str
    values: Any
    kind: str  # "sequence" | "mapping"
    ordered: bool
    description: str
    consumer_surfaces: tuple[str, ...]


VOCAB_REGISTRY: tuple[VocabEntry, ...] = (
    # ── HERO_* field names ────────────────────────────────────────────
    VocabEntry(
        key="HERO_FIELD_NAMES",
        values=tuple(sorted(HERO_DEFAULTS.keys())),
        kind="sequence",
        ordered=False,
        description=(
            "Seven canonical HERO_* field names emitted by build_hero_state() "
            "and consumed as Pine const strings."
        ),
        consumer_surfaces=(
            "scripts/generate_smc_micro_profiles.py:1046-1052 (Pine const export)",
            "SMC_Dashboard.pine (Hero block, ~line 1728)",
            "SMC_Mobile_Dashboard.pine",
            "streamlit_terminal.py (Hero widgets)",
            "docs/BOUNDARY_CONTRACT.md",
        ),
    ),
    # ── HERO_TRUST vocabulary (F-2 / PR-BC-04) ────────────────────────
    VocabEntry(
        key="HERO_TRUST_VOCAB",
        values=tuple(sorted(HERO_TRUST_VOCAB)),
        kind="sequence",
        ordered=False,
        description=(
            "Hero-local trust vocabulary — superset of canonical TrustState."
        ),
        consumer_surfaces=(
            "SMC_Dashboard.pine:1753,1768,1774",
            "SMC_Mobile_Dashboard.pine:50,55",
            "scripts/smc_hero_state.project_trust_state_to_hero",
            "docs/BOUNDARY_CONTRACT.md (F-2)",
        ),
    ),
    # ── HERO_SETUP_QUALITY vocabulary (F-4 / PR-BC-04) ────────────────
    VocabEntry(
        key="HERO_SETUP_QUALITY_VOCAB",
        values=tuple(sorted(HERO_SETUP_QUALITY_VOCAB)),
        kind="sequence",
        ordered=False,
        description=(
            "Producer-A setup quality vocabulary (passthrough of "
            "SIGNAL_QUALITY_TIER). Producer-B lives in HERO_QUALITY_A_TO_B."
        ),
        consumer_surfaces=(
            "SMC_Dashboard.pine (SetupQuality tinting)",
            "scripts/smc_hero_setup_quality.py (Producer-B bridge)",
            "docs/BOUNDARY_CONTRACT.md (F-4)",
        ),
    ),
    # ── HERO_ACTION vocabulary (F-6 / PR-BC-04) ───────────────────────
    VocabEntry(
        key="HERO_ACTION_VOCAB",
        values=tuple(sorted(HERO_ACTION_VOCAB)),
        kind="sequence",
        ordered=False,
        description=(
            "Producer-A action verbs — uppercase ACTIVE/WATCH/AVOID/BLOCKED."
        ),
        consumer_surfaces=(
            "SMC_Dashboard.pine (~line 1728, read-passthrough)",
            "scripts/smc_hero_action._ACTION_TABLE (Producer-B, lowercase)",
            "docs/BOUNDARY_CONTRACT.md (F-6)",
        ),
    ),
    # ── Producer A-to-B quality bridge mapping ────────────────────────
    VocabEntry(
        key="HERO_QUALITY_A_TO_B",
        values=dict(HERO_QUALITY_A_TO_B),
        kind="mapping",
        ordered=False,
        description=(
            "Authoritative bridge between Producer-A (SIGNAL_QUALITY_TIER) "
            "and Producer-B (smc_hero_action) quality vocabularies."
        ),
        consumer_surfaces=(
            "scripts/smc_hero_action._ACTION_TABLE",
            "scripts/smc_hero_setup_quality.py",
        ),
    ),
    # ── SMC_BUS channels — ORDERED (plot-order-sensitive) ─────────────
    VocabEntry(
        key="ENGINE_BUS_CHANNELS",
        values=tuple(ENGINE_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description=(
            "Full BUS surface published by SMC_Core_Engine. Order IS "
            "semantic — Pine plot() order mirrors this tuple."
        ),
        consumer_surfaces=(
            "SMC_Core_Engine.pine (plot() block)",
            "SMC_Dashboard.pine (input bindings)",
            "SMC_Long_Strategy.pine",
            "scripts/smc_surface_matrix.py",
        ),
    ),
    VocabEntry(
        key="EXECUTABLE_BUS_CHANNELS",
        values=tuple(EXECUTABLE_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="Minimum executable surface for strategy-layer consumers.",
        consumer_surfaces=(
            "SMC_Long_Strategy.pine",
            "scripts/smc_strategy_router.py",
        ),
    ),
    VocabEntry(
        key="LITE_BUS_CHANNELS",
        values=tuple(LITE_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="Lite tier — stable subset of ENGINE_BUS_CHANNELS.",
        consumer_surfaces=(
            "SMC_Lite_Engine.pine",
            "tests/test_smc_bus_manifest_contract.test_lite_contract_stays_a_stable_engine_subset",
        ),
    ),
    VocabEntry(
        key="LITE_SURFACE_BUS_CHANNELS",
        values=tuple(LITE_SURFACE_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="Lite surface layout (read-only lean dashboard).",
        consumer_surfaces=("SMC_Lite_Dashboard.pine",),
    ),
    VocabEntry(
        key="PRO_ONLY_BUS_CHANNELS",
        values=tuple(PRO_ONLY_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="Pro-tier-only channels (ENGINE \\ LITE).",
        consumer_surfaces=(
            "SMC_Dashboard.pine (Pro tier sections)",
        ),
    ),
    VocabEntry(
        key="C9_REBUILD_BUS_CHANNELS",
        values=tuple(C9_REBUILD_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="C9 rebuild-required channels (currently empty).",
        consumer_surfaces=("ADR-0001 Structure Contract Normalization",),
    ),
    VocabEntry(
        key="C9_REDUCE_BUS_CHANNELS",
        values=tuple(C9_REDUCE_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="C9 reduction surface (diagnostic rows marked for reduce).",
        consumer_surfaces=("scripts/pine_apply_surface_reduction.py",),
    ),
    VocabEntry(
        key="C9_DETAIL_BUS_CHANNELS",
        values=tuple(C9_DETAIL_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="C9 detail channels (zone geometry + value-rail).",
        consumer_surfaces=("SMC_Dashboard.pine (Detail Surface group)",),
    ),
    VocabEntry(
        key="C9_LEGACY_COMPAT_BUS_CHANNELS",
        values=tuple(C9_LEGACY_COMPAT_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="C9 legacy-compat shims (currently empty).",
        consumer_surfaces=("ADR-0001",),
    ),
    VocabEntry(
        key="C9_STABLE_PRO_BUS_CHANNELS",
        values=tuple(C9_STABLE_PRO_BUS_CHANNELS),
        kind="sequence",
        ordered=True,
        description="Stable Pro subset after C9 partitioning.",
        consumer_surfaces=("SMC_Dashboard.pine (Pro tier)",),
    ),
    # ── Dashboard / Strategy group titles ─────────────────────────────
    VocabEntry(
        key="DASHBOARD_GROUP_TITLES",
        values=tuple(DASHBOARD_GROUP_TITLES),
        kind="sequence",
        ordered=True,
        description="Ordered group titles the dashboard renders.",
        consumer_surfaces=("SMC_Dashboard.pine (group() calls)",),
    ),
    VocabEntry(
        key="STRATEGY_GROUP_TITLES",
        values=tuple(STRATEGY_GROUP_TITLES),
        kind="sequence",
        ordered=True,
        description="Ordered group titles the strategy renders.",
        consumer_surfaces=("SMC_Long_Strategy.pine",),
    ),
    VocabEntry(
        key="DASHBOARD_GROUP_TITLES_BY_KEY",
        values=dict(DASHBOARD_GROUP_TITLES_BY_KEY),
        kind="mapping",
        ordered=False,
        description="Mapping group-key → display title for dashboard.",
        consumer_surfaces=("SMC_Dashboard.pine",),
    ),
    VocabEntry(
        key="STRATEGY_GROUP_TITLES_BY_KEY",
        values=dict(STRATEGY_GROUP_TITLES_BY_KEY),
        kind="mapping",
        ordered=False,
        description="Mapping group-key → display title for strategy.",
        consumer_surfaces=("SMC_Long_Strategy.pine",),
    ),
)


def _compute_fingerprint(entry: VocabEntry) -> str:
    if entry.kind == "mapping":
        return _mapping_fp(entry.values)
    if entry.ordered:
        return _ordered_fp(entry.values)
    return _sorted_fp(entry.values)


def _live_snapshot() -> dict[str, Any]:
    """Materialize the snapshot dict from the live registry."""
    snap: dict[str, Any] = {
        "_schema_version": "1.0",
        "_fingerprint_algorithm": "sha256 of canonical JSON (sort_keys=True, separators=(',', ':'))",
        "_guard": (
            "Do not edit this file by hand. Regenerate with "
            "`python tests/governance/test_boundary_vocab_fingerprint.py --regenerate-snapshot` "
            "after an approved vocabulary change, and update every consumer surface "
            "listed in VOCAB_REGISTRY in the same PR."
        ),
    }
    for entry in VOCAB_REGISTRY:
        values: Any
        if entry.kind == "mapping":
            values = dict(entry.values)
        elif entry.ordered:
            values = list(entry.values)
        else:
            values = sorted(entry.values)
        snap[entry.key] = values
        snap[f"{entry.key}_FINGERPRINT"] = _compute_fingerprint(entry)
    return snap


def _load_snapshot() -> dict[str, Any]:
    if not SNAPSHOT_PATH.exists():
        pytest.fail(
            f"Vocab fingerprint snapshot missing at {SNAPSHOT_PATH}. "
            "Run `python tests/governance/test_boundary_vocab_fingerprint.py "
            "--regenerate-snapshot` once to bootstrap it."
        )
    return json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_snapshot_file_present_and_schema_matches() -> None:
    """Snapshot exists and carries the expected schema version."""
    snap = _load_snapshot()
    assert snap.get("_schema_version") == "1.0", (
        "Snapshot schema version drift. The governance test understands "
        "schema 1.0 only; bump the test in the same commit as the schema bump."
    )


@pytest.mark.parametrize(
    "entry",
    VOCAB_REGISTRY,
    ids=[e.key for e in VOCAB_REGISTRY],
)
def test_vocab_values_match_snapshot(entry: VocabEntry) -> None:
    """Every registered vocab matches the pinned values exactly."""
    snap = _load_snapshot()
    pinned = snap.get(entry.key)
    assert pinned is not None, (
        f"Snapshot is missing key {entry.key!r}. "
        "If this vocabulary was newly added, regenerate the snapshot."
    )

    if entry.kind == "mapping":
        live = dict(entry.values)
        assert live == pinned, _drift_message(entry, pinned, live)
        return

    live_list = list(entry.values) if entry.ordered else sorted(entry.values)
    assert live_list == pinned, _drift_message(entry, pinned, live_list)


@pytest.mark.parametrize(
    "entry",
    VOCAB_REGISTRY,
    ids=[e.key for e in VOCAB_REGISTRY],
)
def test_vocab_fingerprint_matches_snapshot(entry: VocabEntry) -> None:
    """The SHA-256 fingerprint of each vocab matches the pinned value.

    This is a belt-and-suspenders check on top of the value test — if the
    fingerprint computation itself drifts (algo change, encoding bug),
    this test catches it before the silent-drift comparison above does.
    """
    snap = _load_snapshot()
    fp_key = f"{entry.key}_FINGERPRINT"
    pinned_fp = snap.get(fp_key)
    assert pinned_fp is not None, (
        f"Snapshot is missing fingerprint {fp_key!r}. Regenerate the snapshot."
    )
    live_fp = _compute_fingerprint(entry)
    assert live_fp == pinned_fp, (
        f"Fingerprint drift for {entry.key}:\n"
        f"  pinned : {pinned_fp}\n"
        f"  live   : {live_fp}\n"
        f"  values : {entry.values!r}\n\n"
        f"Consumer surfaces to re-check: {', '.join(entry.consumer_surfaces)}"
    )


def test_registry_covers_all_snapshot_keys() -> None:
    """No orphan keys in the snapshot (prevents stale-pin rot)."""
    snap = _load_snapshot()
    registry_keys = {e.key for e in VOCAB_REGISTRY}
    registry_keys |= {f"{e.key}_FINGERPRINT" for e in VOCAB_REGISTRY}
    meta_keys = {"_schema_version", "_fingerprint_algorithm", "_guard"}

    snapshot_keys = set(snap.keys()) - meta_keys
    orphan = sorted(snapshot_keys - registry_keys)
    missing = sorted(registry_keys - snapshot_keys)
    assert not orphan and not missing, (
        "Snapshot ↔ registry mismatch.\n"
        f"  orphan (in snapshot, not in registry): {orphan}\n"
        f"  missing (in registry, not in snapshot): {missing}\n"
        "Regenerate the snapshot."
    )


def test_hero_field_names_match_hero_defaults_keys() -> None:
    """Governance invariant: HERO_FIELD_NAMES == DEFAULTS.keys() of smc_hero_state.

    A new key in DEFAULTS without a corresponding bump here would otherwise
    reach Pine as a silent additional export.
    """
    from scripts.smc_hero_state import DEFAULTS

    entry = next(e for e in VOCAB_REGISTRY if e.key == "HERO_FIELD_NAMES")
    assert sorted(DEFAULTS.keys()) == sorted(entry.values)


def test_engine_bus_is_superset_of_lite_and_executable() -> None:
    """Tier hierarchy invariant (failsafe if the manifest test is skipped)."""
    engine = set(ENGINE_BUS_CHANNELS)
    assert set(LITE_BUS_CHANNELS).issubset(engine)
    assert set(EXECUTABLE_BUS_CHANNELS).issubset(engine)
    assert set(LITE_SURFACE_BUS_CHANNELS).issubset(engine)


def test_fingerprint_algorithm_is_stable_on_trivial_cases() -> None:
    """Unit-test the fingerprint primitive itself (regression pin)."""
    # Empty sorted list → canonical JSON "[]" → sha256 "…"
    assert _sorted_fp([]) == (
        "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
    # Ordered singleton
    assert _ordered_fp(["a"]) == (
        "sha256:0eb5b8d6f81bc677da8a08567cc4fa9a06a57e9ec8da85ed73a7f62727996002"
    )
    # Mapping — key order inside input must not affect the hash
    assert _mapping_fp({"b": 2, "a": 1}) == (
        "sha256:43258cff783fe7036d8a43033f830adfc60ec037382473548ac742b888292777"
    )


# ---------------------------------------------------------------------------
# Optional CLI: regenerate the snapshot in-place
# ---------------------------------------------------------------------------


def _regenerate() -> Path:
    snap = _live_snapshot()
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT_PATH.write_text(
        json.dumps(snap, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return SNAPSHOT_PATH


def _drift_message(entry: VocabEntry, pinned: Any, live: Any) -> str:
    pinned_set = set(pinned if isinstance(pinned, list) else pinned.keys())
    live_set = set(live if isinstance(live, list) else live.keys())
    added = sorted(live_set - pinned_set)
    removed = sorted(pinned_set - live_set)
    surfaces = "\n    - ".join(entry.consumer_surfaces)
    return (
        f"\nBoundary vocabulary drift detected for {entry.key}.\n"
        f"  description : {entry.description}\n"
        f"  pinned      : {pinned!r}\n"
        f"  live        : {live!r}\n"
        f"  added       : {added}\n"
        f"  removed     : {removed}\n"
        f"  ordered     : {entry.ordered}\n"
        f"  kind        : {entry.kind}\n"
        f"  consumer surfaces to re-check:\n    - {surfaces}\n\n"
        f"If this change is intentional, update every consumer surface above\n"
        f"in the same PR, then regenerate the snapshot:\n"
        f"  python tests/governance/test_boundary_vocab_fingerprint.py "
        f"--regenerate-snapshot\n"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--regenerate-snapshot",
        action="store_true",
        help="Overwrite vocab_fingerprint.json with the live snapshot.",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="Print the live snapshot to stdout without writing.",
    )
    args = parser.parse_args()

    if args.print:
        print(json.dumps(_live_snapshot(), indent=2, sort_keys=False))
    elif args.regenerate_snapshot:
        path = _regenerate()
        print(f"Wrote snapshot to {path}")
    else:
        parser.print_help()
