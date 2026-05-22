# Databento cache-key audit — Step 1 of #2334

Date: 2026-05-22
Owner: cache redesign exploration (#2334)
Status: Audit complete; verdict = **fundamental redesign**, not a 1-day refactor.

## Goal

Per #2334 step 1: confirm where the daily-changing universe-version hash is
embedded in the cache layout, and classify the effort required to re-key from
`(universe-snapshot, …)` to `(symbol, date, venue, window)` for cross-day
sharing.

## How filenames are built

Primary chokepoint: `build_cache_path` in `databento_utils.py`. Note that
`databento_volatility_screener.py` defines a **second** `build_cache_path`
(line 382) used by its own bulk-category call sites; any redesign must
update both copies in lock-step or one of them will silently drift.

```python
# databento_utils.py, lines 74-92 (essential lines; trailing branches elided)
def build_cache_path(cache_dir, category, *, dataset, parts, suffix=".parquet"):
    safe_dataset = dataset.replace(".", "_").replace("/", "_")
    normalized = [
        str(part).replace(":", "-").replace("/", "_").replace(" ", "_")
        for part in parts
    ]
    cache_version = CACHE_VERSION_BY_CATEGORY.get(category, CACHE_VERSION)
    digest = hashlib.sha1(
        "|".join([cache_version, category, dataset, *normalized]).encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()[:12]
    filename = "__".join([*normalized, digest]) + suffix
    # ... directory join + return elided ...
```

The universe hash leaks into the filename via two paths:

1. **Human-readable prefix**: every element of `parts` is joined with `__` and
   placed at the front of the filename.
2. **Opaque digest suffix**: the same `parts` (plus version/category/dataset)
   are hashed into the trailing 12-char sha1.

So if `parts` contains a universe-derived token, **both** prefix and digest
change daily. There is no separation of stable vs. volatile dimensions.

## Where the universe-hash enters `parts`

The token comes from `_symbol_scope_token` in `databento_volatility_screener.py`
(lines 528–535): `f"{count}_{sha1(joined_symbols)[:12]}"`. Or
`_symbol_day_scope_token` for per-day scope, which is even more volatile.

| Category                                    | parts include scope? | call site (line) |
|---------------------------------------------|----------------------|------------------|
| `daily_bars`                                | **yes** (`symbol_scope`)         | 1498 |
| `intraday_summary`                          | **yes** (`symbol_scope`)         | 1861 |
| `full_universe_open_second_detail`          | **yes** (`symbol_scope`)         | 2318 |
| `full_universe_close_trade_detail`          | **yes** (`symbol_scope`)         | 2787 |
| `full_universe_close_outcome_minute_detail` | **yes** (`symbol_scope`)         | 2911 |
| `symbol_detail_second`                      | no — keyed on single symbol      | 2089 |
| `symbol_detail_minute`                      | no — keyed on single symbol      | 2095 |
| `symbol_support`                            | no — static literal              | universe.py:95 / vol_screener.py:619 |
| `fundamental_reference`                     | no — static literal              | scripts/databento_production_export.py:1289 (`_fundamental_reference_cache_path`) |

This matches the Phase-B baseline observation that the 12.40 % hit-rate is
carried almost entirely by `full_universe_open_second_detail` (the universe
membership of which happens to overlap day-to-day for many symbols even when
the snapshot id differs) and the always-stable narrow slices.

## Why this is not a 1-day refactor

The 5 universe-keyed categories don't just *name* a file with the snapshot id —
they **store one parquet per bulk-fetch key (typically a (date, window) tuple,
or a (start_date, end_date, symbol_scope) range for `daily_bars`) containing
data for the entire universe**. The snapshot id in the filename is not
cosmetic; it faithfully describes the file's content (which symbols are
inside).

To re-key from `(snapshot, date, window)` to `(symbol, date, window)` you must
change one of two things:

### Option A — storage redesign (clean, expensive)

Split each bulk parquet into one file per `(symbol, trade_date, window)`. Read
path becomes `glob + concat` over up to ~|universe| files; write path becomes N
atomic writes inside a single fetch.

Cost:
- File-count inflation: from O(days × windows) ≈ 10² to
  O(symbols × days × windows) ≈ 10⁵ – 10⁶. Affects filesystem listing speed,
  parquet open overhead, GHA upload-artifact wallclock (artifact zips one file
  per entry).
- Atomicity loss: a bulk fetch must be turned into N atomic per-symbol writes
  to preserve crash-safety; otherwise a partial result poisons the cache.
- Read-path TTL semantics change: today a single mtime governs the whole
  universe-day; per-symbol files all carry their own mtime and need a
  consistent "all-or-nothing" age check or the cache returns partial frames.
- All 5 callers of `build_cache_path` for these categories need updates plus
  the `_read_cached_frame`/`_write_cached_frame` abstraction has to learn
  multi-file groups.

### Option B — sidecar index / symlink (compromise)

Keep the bulk file. Write a sidecar JSON mapping `(symbol, date, window)` to
a bulk-file pointer plus row-offset. On read, before fetching, check sidecar
for an existing
bulk file that already contains the symbol's row, and `pd.read_parquet` only
that file.

Cost:
- Sidecar write must be atomic and consistent with bulk parquet write.
- Read path becomes "scan sidecar → maybe-hit → read bulk + filter" — only a
  win if the sidecar lookup is much cheaper than the bulk parquet open.
  At ~2 MB per bulk parquet and pyarrow's lazy column reads, this is not
  obviously a win.
- Doesn't shrink cache footprint (still storing the same bulk file per day).
- Eviction policy gets harder: a bulk file referenced from many sidecars
  cannot be deleted while any of its symbol-rows are still wanted.

## A cheap intermediate (not in #2334 scope but worth flagging)

The cross-day hash flip is driven by `_symbol_scope_token` recomputing the
universe digest from a fresh universe snapshot every cron. If the producer
were to **stabilize the universe snapshot to a weekly rolling window** (or
quantize the hash by membership-change-threshold), the hash would flip
~1×/week instead of 1×/day. That alone should multiply the cross-day hit-rate
by ~5–7× without touching storage layout.

Failure mode: a day where the universe materially changes (IPO listings,
delistings, halts) will produce stale data until the next snapshot quantum.
Whether that's acceptable is a product-correctness question, not a cache one.
Filing this as a separate consideration; not blocking #2334.

## Verdict

- **Step 1 outcome**: `parts`-borne universe-hash leaks into both filename
  prefix and digest at a single chokepoint (`build_cache_path`), but the
  *underlying parquet stores entire-universe rows per file*. So the cache key
  cannot be redesigned without also redesigning the cache **storage shape**.
- **Effort class**: fundamental redesign, multi-day. Not a 1-day refactor.
- **Recommendation for #2334 step 2 (prototype)**: scope strictly to
  `daily_bars` (smallest, simplest, lowest blast radius) and use Option A
  (per-symbol files). Gate any expansion to `intraday_summary` and the three
  `full_universe_*` categories on:
  1. Re-probe via existing `enable_cache_probe` scaffolding (Phase-B tooling
     is still wired).
  2. ≥60 % hit-rate on `daily_bars` alone, sustained across two
     ≥24h-apart runs.
  3. Measured GHA artifact upload wallclock delta < +20 % vs current baseline
     (guards against the file-count inflation tax).
- **If those gates fail**: close #2334, accept current cache as final, and
  consider the cheap intermediate (weekly-quantized universe snapshot) as a
  separate ticket.
- **Do not pursue Option B** (sidecar index) without first measuring that
  bulk-parquet open dominates total read cost in the current Phase-B traces.
  Current evidence does not support that assumption.

## Pointers

- `databento_utils.py::build_cache_path` (line 74) — primary filename
  chokepoint.
- `databento_volatility_screener.py::build_cache_path` (line 382) — second
  in-tree implementation used by the bulk-category call sites; redesign
  must touch both.
- `databento_volatility_screener.py::_symbol_scope_token` (line 528) and
  `_symbol_day_scope_token` (line 538) — where the volatile token is minted.
- `databento_volatility_screener.py::_read_cached_frame` /
  `_write_cached_frame` — the read/write abstraction that would need to learn
  multi-file groups under Option A.
- Phase-B raw data: `baseline/run1/`, `baseline/run2/`.
- Phase-B verdict doc: `docs/databento_cache_baseline_phase_b_2026-05-21.md`.
- Re-validation runbook: `docs/databento_cache_baseline_runbook.md`.
