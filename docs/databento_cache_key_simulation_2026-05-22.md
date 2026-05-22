# Cache-Key Simulation (Issue #2334) — 2026-05-22

**Type:** Offline re-analysis of Phase-B probe logs. No workflow runs spent.
**Inputs:** `baseline/run1/` + `baseline/run2/` JSONL probes (234 + 242 events).
**Script:** [`scripts/simulate_cache_redesign_2334.py`](../scripts/simulate_cache_redesign_2334.py)

## TL;DR

| Metric | Today | Content-addressed sim |
| --- | ---: | ---: |
| Lookup-weighted hit-rate | **12.4 %** | **86.8 %** |
| Set-overlap (unique paths ∩) | 11.6 % | **77.7 %** |

The redesign hypothesis from the Step-1 audit holds: stripping the daily
universe-scope token from `build_cache_path` is sufficient to clear the
**60 % Phase-C re-validation gate** on the existing Phase-B baseline data,
without prototyping or new workflow runs.

## Option 2 — Where do today's 12.4 % hits live?

All 42 baseline hits (21 per run) sit in **a single category**:
`full_universe_open_second_detail`. Every other universe-scoped category
shows 0 hits because the trailing universe-version digest in the filename
changes between runs.

| Category | r1 ev | r1 hit | r2 ev | r2 hit |
| --- | ---: | ---: | ---: | ---: |
| daily_bars | 6 | 0 | 6 | 0 |
| full_universe_close_outcome_minute_detail | 21 | 0 | 21 | 0 |
| full_universe_close_trade_detail | 21 | 0 | 21 | 0 |
| full_universe_open_second_detail | 126 | 21 | 132 | 21 |
| fundamental_reference | 6 | 0 | 6 | 0 |
| intraday_summary | 42 | 0 | 44 | 0 |
| symbol_detail_minute | 6 | 0 | 6 | 0 |
| symbol_detail_second | 6 | 0 | 6 | 0 |

The 21 hits in `full_universe_open_second_detail` are **within-run reuse**
(same shard probing the same path twice), not cross-day reuse. The
filesystem probe cannot distinguish the two — Option 1 below corrects for
this by simulating cross-run hits explicitly.

## Option 1 — Hit-rate if the universe-scope token is stripped

Simulation: parse each probe path, drop any part matching
`^\d+_[0-9a-f]{12}$` (the `_symbol_scope_token` shape), recompute the
trailing digest with the same `CACHE_VERSION_BY_CATEGORY` map, and
intersect Run 2 canonical keys against Run 1.

| Category | Run 2 ev | sim hit | sim % | Gate |
| --- | ---: | ---: | ---: | :-: |
| daily_bars | 6 | 0 | 0.0 % | FAIL |
| full_universe_close_outcome_minute_detail | 21 | 20 | 95.2 % | PASS |
| full_universe_close_trade_detail | 21 | 20 | 95.2 % | PASS |
| full_universe_open_second_detail | 132 | 120 | 90.9 % | PASS |
| fundamental_reference | 6 | 6 | 100.0 % | PASS |
| intraday_summary | 44 | 40 | 90.9 % | PASS |
| symbol_detail_minute | 6 | 2 | 33.3 % | FAIL |
| symbol_detail_second | 6 | 2 | 33.3 % | FAIL |
| **TOTAL** | **242** | **210** | **86.8 %** | **PASS** |

### Caveats by category

- **daily_bars (0 %)** — parts include the daily-bar lookback window
  (`20260408__20260424`), which is recomputed per run from "today − N
  trading days". Cross-day reuse requires either fixing the window or
  caching per single date. Out of scope for the minimum redesign.
- **symbol_detail_second / _minute (33 %)** — per-(date, symbol) cache;
  only symbols that get volatility-screened on both days overlap. The
  cache is doing what it should; the screener selection differs.
  Expected behavior, not a defect.
- **fundamental_reference (100 %)** — already content-addressed (single
  static "us_equity_profiles" part). The current hash-collision-avoidance
  digest is the only thing that matters and it's stable.
- The 5 universe-scoped categories (95+90 %) carry the vast majority of
  the work and are the targets the redesign actually needs to win.

## Verdict for Issue #2334

Step-1 (audit) verdict was "fundamental redesign required, multi-day
work". This simulation refines that:

- The redesign is **minimum-scope**: remove `_symbol_scope_token` from
  the 5 universe-keyed `build_cache_path` call sites. Filenames become
  invariant under daily universe rotation.
- Universe-version provenance must move out of the filename and into the
  parquet payload metadata, so we never serve a stale universe to a
  caller that expected a fresh one. This is the only non-trivial part.
- **No need to prototype before committing** — the simulated 86.8 %
  hit-rate is far above the 60 % gate with margin to spare for
  real-world drift (new symbols, missing days, runner churn).
- `daily_bars` lookback window is a separate, additive optimization and
  should not block the main redesign.

## Reproduce

PowerShell (Windows):

```powershell
& .venv\Scripts\python.exe scripts\simulate_cache_redesign_2334.py
```

Bash (macOS / Linux):

```bash
.venv/bin/python scripts/simulate_cache_redesign_2334.py
```
