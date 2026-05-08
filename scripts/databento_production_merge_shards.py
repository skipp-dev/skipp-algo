"""A9b.3 — Reduce-step for matrix-sharded Databento production export.

Merges N per-shard manifest JSON files (one per producer matrix entry from
``smc-databento-production-export-sharded.yml``) into a single canonical
manifest equivalent to the monolithic-cron output.

Field-classification (auto-determined per key, with explicit overrides
captured at the top of this module):

* identical-across       — all shards must agree, take shard-1 value;
                           drift raises ``ManifestMergeError``.
* per-shard dict         — collected as ``{<key>_per_shard: {1: v1, 2: v2}}``;
                           applies to per-shard timestamps + identifying
                           sample picks (basename, selected_*).
* sum-across (int)       — blind summation; legitimate because the planner
                           guarantees disjoint calendar-day windows and we
                           additionally assert ``trade_dates_covered`` is
                           pairwise-disjoint across shards.
* set-union sorted       — list-typed fields; ``trade_dates_covered`` gets
                           a ``set(merged) == sum(per-shard, [])``
                           subset-equivalence assertion (drift detector).
* recursive merge (dict) — applies the same classifier per nested key.

This module is pure-stdlib and consumes nothing from the producer code path.
The reduce-job in YAML (A9b.2b-v2) is a thin wrapper that downloads each
shard artifact, locates its manifest, and invokes ``merge_manifests`` on
the parsed JSON list.

Spec lives in session memory ``f2-rolling-bench-rootcause.md`` (A9b.3).
"""

from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Bootstrap sys.path BEFORE the first first-party import so that script-style
# invocation (`python scripts/databento_production_merge_shards.py`) can
# resolve the ``scripts`` package. The check is idempotent for the common
# `python -m` form. See Bug-Hunt F-01 / test_workflow_invoked_scripts_import_order.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.smc_atomic_write import atomic_write_json  # noqa: E402

# ---------------------------------------------------------------------------
# Override table — single source of truth for classification deviations
# from the auto-classifier.
# ---------------------------------------------------------------------------

# Keys (or fnmatch globs) whose differing values must be preserved per-shard
# rather than reduced. Emitted as ``<base>_per_shard: {<shard_id>: value}``.
PER_SHARD_GLOBS: tuple[str, ...] = (
    # Per-shard timestamps
    "*_fetched_at",
    "export_generated_at",
    "exported_at",
    # Per-shard sample identifiers
    "basename",
    "selected_symbol",
    "selected_trade_date",
    # Per-shard sample-debug nested dicts. Empirically (2026-05-08 N=2 probe):
    # ``batl_debug`` carries the per-shard chosen-symbol BATL eligibility
    # breakdown (bool ``is_eligible``, string ``eligibility_reason``,
    # nullable ``rank_within_trade_date``) — drift on ALL non-config children.
    # ``core_vs_benzinga_news_source`` carries a per-shard ``trade_date``
    # alongside otherwise-identical config fields. Treating the whole dict
    # as per-shard keeps merged output internally consistent (no half-merged
    # debug record where some children come from one shard and some from
    # another) at the cost of duplicating the few identical config keys
    # under each shard's bucket.
    "batl_debug",
    "core_vs_benzinga_news_source",
    # Nested twin of ``batl_debug`` living under ``output_checks.batl`` —
    # per-shard sample's BATL eligibility snapshot (bool/string/None drift).
    "batl",
)

# List-typed fields whose merged set must equal the disjoint-union of inputs
# (i.e. no element appears in more than one shard). Drift here = producer bug.
DISJOINT_UNION_FIELDS: frozenset[str] = frozenset({"trade_dates_covered"})

# Top-level keys injected into the merged manifest by ``merge_manifests``.
_INJECTED_KEYS: frozenset[str] = frozenset({
    "shard_count",
    "shard_ids",
    "merged_at",
    "merge_script_version",
})

MERGE_SCRIPT_VERSION = "a9b.3.0"


class ManifestMergeError(ValueError):
    """Raised when shard manifests violate a merge invariant."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_per_shard_key(key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in PER_SHARD_GLOBS)


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _all_equal(values: Sequence[Any]) -> bool:
    first = values[0]
    return all(v == first for v in values[1:])


def _assert_homogeneous_types(key: str, values: Sequence[Any]) -> None:
    types = {type(v).__name__ for v in values}
    if len(types) > 1:
        raise ManifestMergeError(
            f"Type drift on key {key!r}: shards report mixed types {sorted(types)}"
        )


# ---------------------------------------------------------------------------
# Per-key reducers
# ---------------------------------------------------------------------------

def _reduce_int(key: str, values: Sequence[int], shard_ids: Sequence[int]) -> int:
    return sum(values)


def _reduce_list(
    key: str, values: Sequence[Sequence[Any]], shard_ids: Sequence[int]
) -> list[Any]:
    if key in DISJOINT_UNION_FIELDS:
        seen: set[Any] = set()
        for sid, lst in zip(shard_ids, values):
            for item in lst:
                if item in seen:
                    raise ManifestMergeError(
                        f"Disjoint-union violation on key {key!r}: value {item!r} "
                        f"appears in shard {sid} but already seen in earlier shard. "
                        f"Producer/planner contract: shard windows must be disjoint."
                    )
                seen.add(item)
        return sorted(seen, key=lambda x: (str(type(x).__name__), x))
    # Permissive set-union (e.g. detail_exclusion_reasons — free strings).
    union: set[Any] = set()
    for lst in values:
        union.update(lst)
    return sorted(union, key=lambda x: (str(type(x).__name__), x))


def _reduce_dict(
    key: str, values: Sequence[Mapping[str, Any]], shard_ids: Sequence[int]
) -> dict[str, Any]:
    # Recursive merge using the same classifier, scoped to the union of keys.
    return _merge_field_set(values, shard_ids, parent=key)


# ---------------------------------------------------------------------------
# Core merge engine
# ---------------------------------------------------------------------------

def _merge_field_set(
    shards: Sequence[Mapping[str, Any]],
    shard_ids: Sequence[int],
    parent: str | None = None,
) -> dict[str, Any]:
    """Merge a list of homogeneous mappings into one mapping.

    Used both at the top level and recursively for nested dict fields.
    ``parent`` is purely diagnostic (appears in error messages).
    """
    if not shards:
        return {}
    all_keys: list[str] = sorted({k for s in shards for k in s.keys()})
    out: dict[str, Any] = {}
    for key in all_keys:
        present_pairs = [(sid, s) for sid, s in zip(shard_ids, shards) if key in s]
        present_ids = [sid for sid, _ in present_pairs]
        present_vals = [s[key] for _, s in present_pairs]

        # Missing-in-some-shard handling: preserve as per-shard so reviewers
        # can see exactly which shard lacked the field.
        if len(present_pairs) != len(shards):
            missing = [sid for sid in shard_ids if sid not in present_ids]
            out[f"{key}_per_shard_partial"] = {
                "present": dict(zip(present_ids, present_vals)),
                "missing_shard_ids": missing,
            }
            continue

        if _is_per_shard_key(key):
            out[f"{key}_per_shard"] = dict(zip(present_ids, present_vals))
            continue

        # Disjoint-union fields must run their reducer even when every shard
        # reports an identical list — identical non-empty inputs are
        # themselves a violation (the same trade date claimed by two shards).
        if key in DISJOINT_UNION_FIELDS:
            out[key] = _reduce_list(key, present_vals, present_ids)
            continue

        if _all_equal(present_vals):
            out[key] = present_vals[0]
            continue

        _assert_homogeneous_types(_qualify(parent, key), present_vals)
        v0 = present_vals[0]
        if isinstance(v0, bool):
            # Bool drift on a non-per-shard field is unexpected.
            raise ManifestMergeError(
                f"Boolean drift on key {_qualify(parent, key)!r}: {dict(zip(present_ids, present_vals))}"
            )
        if isinstance(v0, int):
            out[key] = _reduce_int(key, present_vals, present_ids)
            continue
        if isinstance(v0, float):
            # Floats are not currently emitted by the producer manifest
            # outside of identical-across status fields; treat drift as bug.
            raise ManifestMergeError(
                f"Float drift on key {_qualify(parent, key)!r}: "
                f"{dict(zip(present_ids, present_vals))}. Add an explicit "
                f"override (per-shard or sum) if this is now legitimate."
            )
        if isinstance(v0, str):
            raise ManifestMergeError(
                f"String drift on key {_qualify(parent, key)!r} which is not in "
                f"PER_SHARD_GLOBS. Add to override table if this drift is legitimate. "
                f"Values: {dict(zip(present_ids, present_vals))}"
            )
        if isinstance(v0, list):
            out[key] = _reduce_list(key, present_vals, present_ids)
            continue
        if isinstance(v0, dict):
            out[key] = _reduce_dict(key, present_vals, present_ids)
            continue
        if v0 is None:
            # All-None handled by _all_equal above; mixed-None caught here.
            raise ManifestMergeError(
                f"None/non-None drift on key {_qualify(parent, key)!r}"
            )
        raise ManifestMergeError(
            f"Unsupported value type {type(v0).__name__} on key {_qualify(parent, key)!r}"
        )
    return out


def _qualify(parent: str | None, key: str) -> str:
    return f"{parent}.{key}" if parent else key


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def merge_manifests(
    shards: Sequence[Mapping[str, Any]],
    shard_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Reduce N shard manifests into one canonical merged manifest.

    Parameters
    ----------
    shards
        Parsed manifest dicts in shard order (id ascending).
    shard_ids
        Optional explicit shard ids. Defaults to ``range(1, len+1)``. Must
        match ``len(shards)`` and be unique-positive when supplied.

    Raises
    ------
    ManifestMergeError
        On any drift the auto-classifier cannot resolve, missing override,
        disjoint-union violation, or invalid input.
    """
    if not shards:
        raise ManifestMergeError("merge_manifests requires at least one shard")
    if shard_ids is None:
        shard_ids = list(range(1, len(shards) + 1))
    else:
        shard_ids = list(shard_ids)
        if len(shard_ids) != len(shards):
            raise ManifestMergeError(
                f"shard_ids length {len(shard_ids)} != shards length {len(shards)}"
            )
        if len(set(shard_ids)) != len(shard_ids):
            raise ManifestMergeError(f"shard_ids contain duplicates: {shard_ids}")
        if any(sid <= 0 for sid in shard_ids):
            raise ManifestMergeError(
                f"shard_ids must be positive 1-based ids; got {shard_ids}"
            )

    merged = _merge_field_set(shards, shard_ids)
    # Inject reduce-step provenance fields (do not collide with payload).
    for k in _INJECTED_KEYS:
        if k in merged:
            raise ManifestMergeError(
                f"Reserved key {k!r} already present in shard manifest; "
                f"reduce-step cannot inject provenance without clobbering."
            )
    merged["shard_count"] = len(shards)
    merged["shard_ids"] = sorted(shard_ids)
    merged["merged_at"] = _now_utc_iso()
    merged["merge_script_version"] = MERGE_SCRIPT_VERSION
    return merged


def discover_shard_manifests(shard_dirs: Iterable[Path]) -> list[tuple[int, Path]]:
    """Locate one ``*_manifest.json`` per shard directory.

    Returns ``[(shard_id, manifest_path), ...]`` sorted by shard_id. The
    shard_id is parsed from the directory name suffix ``shard-<i>`` /
    ``shard-<i>-of-<N>``; if no such suffix is present the directory is
    enumerated 1-based by sorted name.
    """
    pairs: list[tuple[int, Path]] = []
    for idx, d in enumerate(sorted(shard_dirs), start=1):
        sid = _parse_shard_id_from_dir(d.name) or idx
        candidates = sorted(d.rglob("*_manifest.json"))
        if not candidates:
            raise ManifestMergeError(f"No *_manifest.json found under {d}")
        if len(candidates) > 1:
            raise ManifestMergeError(
                f"Multiple manifests under {d}: {[c.name for c in candidates]}; "
                f"reduce-step expects exactly one manifest per shard."
            )
        pairs.append((sid, candidates[0]))
    return pairs


def _parse_shard_id_from_dir(name: str) -> int | None:
    # Match patterns like 'shard-1' or 'a9b-2b-shard-3-of-6'
    parts = name.split("-")
    for i, p in enumerate(parts):
        if p == "shard" and i + 1 < len(parts) and parts[i + 1].isdigit():
            return int(parts[i + 1])
    return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="databento_production_merge_shards",
        description=(
            "Merge N per-shard Databento production-export manifests into "
            "one canonical manifest (A9b.3 reduce-step)."
        ),
    )
    p.add_argument(
        "--shard-dir",
        type=Path,
        action="append",
        required=True,
        help=(
            "Path to one shard's artifact directory (containing exactly one "
            "*_manifest.json somewhere beneath it). Repeat for each shard."
        ),
    )
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination path for merged manifest JSON.",
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    try:
        pairs = discover_shard_manifests(args.shard_dir)
        shards = [json.loads(p.read_text(encoding="utf-8")) for _, p in pairs]
        shard_ids = [sid for sid, _ in pairs]
        merged = merge_manifests(shards, shard_ids=shard_ids)
    except ManifestMergeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    atomic_write_json(merged, args.output, indent=2, sort_keys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
