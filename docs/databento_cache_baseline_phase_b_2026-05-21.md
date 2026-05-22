# Phase B — Databento file-cache baseline (2026-05-20/21)

## Verdict

**NO-GO for Phase C as originally scoped.**

The measured cross-run cache hit-rate is **12.40 %** (lookup-weighted), well
below the Phase-C gate of **>= 60 %**. A persistent `actions/cache@v4`-style
shard cache would not produce the >=30 % wallclock win that motivates Phase C.

## Numbers

| Metric                                                | Value     |
| ----------------------------------------------------- | --------- |
| Run 1 lookups / unique paths                          | 234 / 208 |
| Run 2 lookups / unique paths                          | 242 / 215 |
| Path-set intersection (R1 ∩ R2)                       | 25        |
| Hit-rate (set-overlap, conservative)                  | 11.63 %   |
| Hit-rate (lookup-weighted, realistic)                 | 12.40 %   |
| Phase-C gate (>= 60 % lookup-weighted)                | **FAIL**  |
| Intra-run hit-rate (within Run 2 only)                |  8.7 %    |

**Definitions**

- *Hit-rate (lookup-weighted)*: (# probe lines in Run 2 whose `path` also
  appears in any Run-1 probe line) / (total Run-2 probe lines). Computed by
  `scripts/baseline_cache_probe.py` over the per-shard JSONLs; ignores the
  per-line `hit` flag (which is intra-run only).
- *Hit-rate (set-overlap)*: |unique R1 paths ∩ unique R2 paths| /
  |unique R2 paths|. Same script, deduplicated.
- *Intra-run hit-rate (within Run 2 only)*: lines with `hit=true` /
  total lines, restricted to Run-2 shards. This counts the producer's own
  within-shard reuse and is **not** emitted by `baseline_cache_probe.py`;
  compute as `jq -s '[.[] | select(.hit==true)] | length' baseline/run2/**/*.jsonl`
  divided by total Run-2 line count.

## Run metadata

| Run | ID            | Dispatched (UTC)        | Duration (slowest shard) | All probe artifacts |
| --- | ------------- | ----------------------- | ------------------------ | ------------------- |
| 1   | 26179953028   | 2026-05-20 17:49        | 46 min (shard 5)         | 6/6 ✓               |
| 2   | 26243919882   | 2026-05-21 18:01        | 46 min (shard 2)         | 6/6 ✓               |

Producer wallclocks (sorted):
- Run 1: 27 / 31 / 34 / 40 / 40 / 46 min
- Run 2: 29 / 29 / 29 / 32 / 38 / 46 min

## Root cause

Cache filenames embed a **universe-version hash** that changes day-over-day.
Example:

- Run 1 (2026-05-20): `daily_bars/XNAS_ITCH/...__6870_2ed3c3010420__<contenthash>.parquet`
- Run 2 (2026-05-21): `daily_bars/XNAS_ITCH/...__6877_f0e462b9a455__<contenthash>.parquet`

The 25 shared paths come almost exclusively from `XASE_PILLAR` slices whose
universe hash (`280_da722703946c`) is small and stable. The bulk universe
buckets (`full_universe_*`, `intraday_summary`, `daily_bars`) regenerate
filenames whenever the universe snapshot changes.

Hits-by-bucket in Run 2 (a *hit* here = a Run-2 probe line whose `path` is
also present in Run 1, grouped by the first subdirectory under
`artifacts/databento_volatility_cache/`):

- `full_universe_open_second_detail`: 21
- everything else: 0

## Implications

1. A naive persistent file-cache keyed on existing filenames will reuse
   ~12 % of lookups across days. Wallclock win is bounded by the same
   fraction; well below the **>=30 % wallclock-win bar** that motivates
   Phase C (separate from the >=60 % hit-rate gate above — the wallclock
   bar is the downstream business target, the hit-rate gate is the upstream
   precondition for reaching it).
2. The current wallclock baseline (median ~34 min, max 46 min) is already
   reasonable on `ubuntu-latest`. Cache work is not the highest-leverage
   optimization right now.
3. The universe-version hash is **the** lever. If it can be split out so that
   per-symbol slices are addressable by stable (symbol, date, venue, window)
   keys — independent of which universe snapshot triggered the fetch —
   cache reuse jumps dramatically. That is a content-addressing redesign,
   not a workflow change.

## Recommendation

- **Close Phase C as scoped.** Do not wire `actions/cache@v4` against the
  current filename scheme.
- **Open a follow-up exploration** to evaluate splitting the universe hash
  out of the cache filename (or layering a per-symbol cache index). Gate
  any new Phase C on a redesigned hit-rate >= 60 %.
- **Keep the cache-probe scaffolding** (`DATABENTO_CACHE_PROBE_LOG` env, the
  workflow input, the analyzer at `scripts/baseline_cache_probe.py`). Cost
  is near zero and it is the only way to re-validate after any cache redesign.

## Reproduce

```bash
gh run download 26179953028 --dir baseline/run1 -p "cache-probe-shard-*"
gh run download 26243919882 --dir baseline/run2 -p "cache-probe-shard-*"
python scripts/baseline_cache_probe.py baseline/run1 baseline/run2
```

## Open follow-ups

- Issue #2320 (reduce job pandas import) — already fixed in this run cycle.
- New reduce-job failure on Run 2 (`No shard manifests found under shard-artifacts/`)
  — separate from Phase B; track in a fresh issue.
