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
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

# Bootstrap sys.path BEFORE any first-party import so that script-style
# invocation (`python scripts/databento_production_merge_shards.py`) can
# resolve the ``scripts`` package. The check is idempotent for the common
# `python -m` form. See Bug-Hunt F-01 / test_workflow_invoked_scripts_import_order.
_REPO_ROOT = str(Path(__file__).resolve().parents[1])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from scripts.smc_atomic_write import atomic_write_json

_LOG_PREFIX = "[merge-shards] "

# Canonical merged bundle basename. The matching manifest filename is
# `{MERGED_BASENAME}_manifest.json`; payload parquets emitted by
# `merge_shard_payloads` are named `{MERGED_BASENAME}__<frame>.parquet`
# so `load_databento_export_bundle.load_export_bundle` (which globs
# `{base_prefix}__*.parquet` next to the resolved manifest) finds the
# union-merged frames rather than any single shard's slice.
MERGED_BASENAME = "databento_volatility_production_merged"

# Columns used to deduplicate concatenated shard parquets, tried in order.
# Each tuple represents a candidate key; the first one whose columns are
# all present in the concatenated frame wins. The fallback (empty tuple)
# means "do not dedupe" — used when none of the candidates match, which is
# acceptable because the planner guarantees shard windows are calendar-
# day-disjoint, so cross-shard duplicates are not expected.
_DEDUPE_KEY_CANDIDATES: tuple[tuple[str, ...], ...] = (
    ("symbol", "trade_date"),
    ("symbol", "date"),
    ("symbol", "ts_event"),
    ("ts_event",),
    ("trade_date",),
    ("date",),
)

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
    # Partial-run telemetry (only set when --allow-partial+--expected-shard-count
    # is used and at least one expected shard is missing). Reserved here so a
    # producer that ever started emitting these names would be rejected before
    # silently colliding with reduce-step output.
    "partial_run",
    "failed_shard_ids",
    "expected_shard_count",
})

MERGE_SCRIPT_VERSION = "a9b.3.2"


class ManifestMergeError(ValueError):
    """Raised when shard manifests violate a merge invariant."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_per_shard_key(key: str) -> bool:
    return any(fnmatch.fnmatchcase(key, pat) for pat in PER_SHARD_GLOBS)


def _now_utc_iso() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


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
    all_keys: list[str] = sorted({k for s in shards for k in s})
    out: dict[str, Any] = {}
    for key in all_keys:
        present_pairs = [(sid, s) for sid, s in zip(shard_ids, shards) if key in s]
        present_ids = [sid for sid, _ in present_pairs]
        present_vals = [s[key] for _, s in present_pairs]

        # Missing-in-some-shard handling: preserve as per-shard so reviewers
        # can see exactly which shard lacked the field.
        # NOTE: shard-id keys are stringified before emit so the on-disk JSON
        # schema matches the in-memory dict after a json.load() round-trip
        # (JSON object keys are always strings).
        if len(present_pairs) != len(shards):
            missing = [sid for sid in shard_ids if sid not in present_ids]
            out[f"{key}_per_shard_partial"] = {
                "present": {str(sid): val for sid, val in zip(present_ids, present_vals)},
                "missing_shard_ids": missing,
            }
            continue

        if _is_per_shard_key(key):
            out[f"{key}_per_shard"] = {
                str(sid): val for sid, val in zip(present_ids, present_vals)
            }
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
    expected_shard_count: int | None = None,
    allow_partial: bool = False,
) -> dict[str, Any]:
    """Reduce N shard manifests into one canonical merged manifest.

    Parameters
    ----------
    shards
        Parsed manifest dicts in shard order (id ascending).
    shard_ids
        Optional explicit shard ids. Defaults to ``range(1, len+1)``. Must
        match ``len(shards)`` and be unique-positive when supplied.
    expected_shard_count
        Total number of producer shards that were dispatched. When set, the
        function compares ``shard_ids`` against ``range(1, expected+1)`` and
        either raises (default) or annotates the result with partial-run
        telemetry (see ``allow_partial``).
    allow_partial
        When ``True`` and ``expected_shard_count`` is set and at least one
        expected shard id is missing from ``shard_ids``, the merge succeeds
        and the returned manifest carries ``partial_run=True`` plus the
        ``failed_shard_ids`` list. When ``False`` (default), missing shards
        raise ``ManifestMergeError``.

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

    missing_ids: list[int] = []
    if expected_shard_count is not None:
        if expected_shard_count < 1:
            raise ManifestMergeError(
                f"expected_shard_count must be >= 1; got {expected_shard_count}"
            )
        if any(sid > expected_shard_count for sid in shard_ids):
            raise ManifestMergeError(
                f"shard_ids {sorted(shard_ids)} contains id(s) outside the "
                f"expected 1..{expected_shard_count} range"
            )
        missing_ids = sorted(set(range(1, expected_shard_count + 1)) - set(shard_ids))
        if missing_ids and not allow_partial:
            raise ManifestMergeError(
                f"Missing shard(s) {missing_ids} of expected "
                f"{expected_shard_count}; pass --allow-partial to emit a "
                f"partial merged manifest with telemetry instead."
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
    if expected_shard_count is not None:
        merged["expected_shard_count"] = expected_shard_count
        merged["partial_run"] = bool(missing_ids)
        merged["failed_shard_ids"] = missing_ids
    return merged


def discover_shard_manifests(shard_dirs: Iterable[Path]) -> list[tuple[int, Path]]:
    """Locate one ``*_manifest.json`` per shard directory.

    Returns ``[(shard_id, manifest_path), ...]`` sorted by ``shard_id``.
    The shard_id is parsed from the directory name suffix ``shard-<i>`` /
    ``shard-<i>-of-<N>``; when no such suffix is present, directories are
    enumerated 1-based after sorting by basename (NOT full path, so
    behaviour is stable across temp roots).
    """
    shard_dirs = list(shard_dirs)
    pairs: list[tuple[int, Path]] = []
    # Stable enumeration fallback: sort by basename, not full path.
    enum_sorted = sorted(shard_dirs, key=lambda d: d.name)
    for idx, d in enumerate(enum_sorted, start=1):
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
    # Sort by parsed shard_id so 'shard-2' precedes 'shard-10'.
    pairs.sort(key=lambda p: p[0])
    return pairs


def _parse_shard_id_from_dir(name: str) -> int | None:
    # Match patterns like 'shard-1' or 'a9b-2b-shard-3-of-6'
    parts = name.split("-")
    for i, p in enumerate(parts):
        if p == "shard" and i + 1 < len(parts) and parts[i + 1].isdigit():
            return int(parts[i + 1])
    return None


# ---------------------------------------------------------------------------
# Payload merge (frame-level parquet concat across shards)
# ---------------------------------------------------------------------------

def _discover_shard_parquets(
    manifest_paths: Sequence[Path],
) -> dict[str, list[Path]]:
    """Group per-shard parquet payloads by frame name.

    For every manifest at ``{dir}/{basename}_manifest.json`` we look up the
    sibling files matching ``{basename}__*.parquet`` and bucket them by the
    frame suffix (the part after ``__``). Returns ``{frame: [path, ...]}``
    sorted by frame name; per-frame lists preserve manifest order so a
    deterministic concat order can be applied downstream.
    """
    by_frame: dict[str, list[Path]] = {}
    for manifest_path in manifest_paths:
        basename = manifest_path.name.removesuffix("_manifest.json")
        for parquet in sorted(manifest_path.parent.glob(f"{basename}__*.parquet")):
            frame = parquet.stem.split("__", 1)[1]
            by_frame.setdefault(frame, []).append(parquet)
    return dict(sorted(by_frame.items()))


def _dedupe_frame(frame_name: str, df):  # type: ignore[no-untyped-def]
    """Drop_duplicates on the first matching key candidate; return df.

    Falls back to no dedupe (with a stdout note) when no candidate matches
    the frame's columns.
    """
    cols = set(df.columns)
    for key in _DEDUPE_KEY_CANDIDATES:
        if key and all(col in cols for col in key):
            before = len(df)
            df = df.drop_duplicates(subset=list(key), keep="last")
            after = len(df)
            if before != after:
                print(
                    f"{_LOG_PREFIX}{frame_name}: dropped {before - after} "
                    f"duplicate row(s) on key={list(key)}"
                )
            return df.sort_values(list(key), kind="mergesort").reset_index(drop=True)
    print(
        f"{_LOG_PREFIX}{frame_name}: no dedupe key matched columns "
        f"{sorted(cols)[:8]}…; keeping all rows (planner contract: shards "
        f"are calendar-day-disjoint, so cross-shard duplicates are unexpected)"
    )
    return df.reset_index(drop=True)


def merge_shard_payloads(
    manifest_paths: Sequence[Path],
    output_dir: Path,
    *,
    merged_basename: str = MERGED_BASENAME,
) -> dict[str, int]:
    """Concat per-shard frame parquets into a canonical merged bundle.

    For each frame found across the supplied shards, loads every sibling
    parquet, concatenates them, dedupes by the first matching key in
    :data:`_DEDUPE_KEY_CANDIDATES`, and writes the result to
    ``{output_dir}/{merged_basename}__{frame}.parquet``.

    Returns ``{frame: row_count}`` so the caller can log a summary. Frames
    that exist in some shards but not others are still merged (best-effort:
    union of what's available); the missing shards simply contribute zero
    rows.

    Memory profile (WF-026 OOM fix, 2026-06-24)
    --------------------------------------------
    Old implementation loaded every shard file into a separate pandas
    DataFrame (``[pd.read_parquet(p) for p in paths]``) and then called
    ``pd.concat()``, holding N DataFrames + the concatenated copy + the
    deduped copy simultaneously — peak ≈ 3× total frame size.  On the
    standard 7 GB GitHub runner with 6 shards this triggered OOM /
    swap-thrash on 2026-06-22 (swap_used peaked at 5 750 MB / 9 215 MB).

    New implementation uses ``pyarrow.dataset`` to read all shard files
    in a single streaming pass into one Arrow table (column-oriented,
    more compact than N pandas DataFrames).  The Arrow table is released
    before ``_dedupe_frame`` allocates its sorted copy, giving a peak of
    ≈ 2× total frame size.

    Heavy deps (``pyarrow``, parquet engine) are imported lazily so the
    manifest-only merge path stays import-cheap.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    by_frame = _discover_shard_parquets(manifest_paths)
    if not by_frame:
        print(
            f"{_LOG_PREFIX}no per-shard parquet payloads discovered; "
            "merged bundle will contain only the manifest. Downstream "
            "consumers using load_export_bundle(required_frames=...) will "
            "raise FileNotFoundError, which is the correct behaviour for "
            "a manifest-only bundle."
        )
        return {}

    # Lazy imports — keep CLI startup cheap when operating in manifest-only
    # mode.  pyarrow is a transitive dep via pandas' parquet engine so it
    # is always available without an extra install step.
    from scripts.smc_atomic_write import atomic_write_parquet
    import pyarrow.dataset as _pa_ds  # noqa: PLC0415

    summary: dict[str, int] = {}
    for frame, paths in by_frame.items():
        # ------------------------------------------------------------------
        # STREAMING READ — WF-026 OOM fix (2026-06-24)
        # ------------------------------------------------------------------
        # Previous: [pd.read_parquet(p) for p in paths] + pd.concat(...)
        #   Peak ≈ 3× total frame size: N DataFrames simultaneously in RAM,
        #   then the concatenated copy, then the deduped/sorted copy.
        #   On a 7 GB runner with 6 shards → swap_used > 5 GB → OOM.
        #
        # New: pyarrow.dataset reads all shard files in one streaming pass
        #   into a single Arrow table (column-oriented, ~2× more compact
        #   than equivalent pandas DataFrames).  Explicit del before
        #   _dedupe_frame frees the buffer before pandas allocates the
        #   sorted copy.
        #   Peak ≈ 2× total frame size (Arrow table → pandas → deduped).
        # ------------------------------------------------------------------
        _dataset = _pa_ds.dataset([str(p) for p in paths], format="parquet")
        _arrow_table = _dataset.to_table()
        concat_df = _arrow_table.to_pandas()
        del _arrow_table  # release Arrow buffer before sort/dedup allocates
        deduped = _dedupe_frame(frame, concat_df)
        del concat_df  # release pre-dedup copy
        out_path = output_dir / f"{merged_basename}__{frame}.parquet"
        atomic_write_parquet(deduped, out_path, index=False)
        row_count = len(deduped)
        del deduped  # release before next frame iteration

        summary[frame] = row_count
        print(
            f"{_LOG_PREFIX}{frame}: merged {len(paths)} shard(s) → "
            f"{row_count} row(s) → {out_path.name}"
        )
    return summary


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
    p.add_argument(
        "--expected-shard-count",
        type=int,
        default=None,
        help=(
            "Total number of producer shards that were dispatched. When set, "
            "the reducer compares the discovered shard ids against "
            "range(1, N+1) and either raises (default) or emits partial-run "
            "telemetry when --allow-partial is also given."
        ),
    )
    p.add_argument(
        "--allow-partial",
        action="store_true",
        help=(
            "When set together with --expected-shard-count, succeed even if "
            "some expected shards are missing. The merged manifest will then "
            "carry partial_run=True and failed_shard_ids=[...] so downstream "
            "consumers (and the reduce-job log) can detect degraded output."
        ),
    )
    p.add_argument(
        "--payload-output-dir",
        type=Path,
        default=None,
        help=(
            "When set, concatenate per-shard frame parquets and write a "
            "canonical merged bundle (manifest sibling files named "
            f"`{MERGED_BASENAME}__<frame>.parquet`) into this directory. "
            "Without this flag, only the merged manifest JSON is emitted; "
            "downstream consumers that load via load_export_bundle("
            "required_frames=...) would then resolve a per-shard manifest "
            "covering only one date slice, silently halving coverage."
        ),
    )
    return p


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_argparser().parse_args(argv)
    if args.allow_partial and args.expected_shard_count is None:
        print(
            "ERROR: --allow-partial requires --expected-shard-count to be set; "
            "otherwise missing shards cannot be detected.",
            file=sys.stderr,
        )
        return 2
    try:
        pairs = discover_shard_manifests(args.shard_dir)
        shards = [json.loads(p.read_text(encoding="utf-8")) for _, p in pairs]
        shard_ids = [sid for sid, _ in pairs]
        merged = merge_manifests(
            shards,
            shard_ids=shard_ids,
            expected_shard_count=args.expected_shard_count,
            allow_partial=args.allow_partial,
        )
    except ManifestMergeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    atomic_write_json(merged, args.output, indent=2, sort_keys=True)
    if args.payload_output_dir is not None:
        try:
            merge_shard_payloads(
                [p for _, p in pairs],
                args.payload_output_dir,
                merged_basename=MERGED_BASENAME,
            )
        except Exception as exc:
            print(
                f"ERROR: payload merge failed: {exc}",
                file=sys.stderr,
            )
            return 2
    if merged.get("partial_run"):
        # Emit a clearly-greppable WARNING line so the reduce-job log makes
        # partial outputs unmistakable. Stdout (not stderr) keeps argparse
        # error semantics clean.
        print(
            f"WARNING: partial_run=True; missing shard ids "
            f"{merged['failed_shard_ids']} of expected "
            f"{merged['expected_shard_count']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
