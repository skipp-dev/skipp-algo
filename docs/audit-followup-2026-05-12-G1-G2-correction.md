# Audit Follow-up Correction — G1 & G2 already implemented

Date: 2026-05-12
Audit refs: `_invest/fmp-usage-audit-2026-05-12.md` (G1, G2),
            `_invest/all-providers-audit-2026-05-12.md` (row 2, row 3 of next-steps)

## Context

While executing the action items from the provider-utilization audit
(2026-05-12) two of the recommendations turned out to be **false positives**:
the code/workflow change being recommended already exists on `main`. This
note records the verification trail so the audit reports can be amended.

## G1 / D2 — `smc-library-refresh` `workflow_run` trigger

**Recommendation (audit):** change `.github/workflows/smc-library-refresh.yml`
from an independent cron trigger to a `workflow_run`-triggered consumer of
`smc-databento-production-export` to eliminate the Q5b cascade race.

**Status (verified 2026-05-12):** already implemented on `main`. The workflow
declares **both** trigger types — `workflow_run` on producer success as the
primary fast path, *and* cron as a safety-net. Specifically:

```yaml
on:
  schedule:
    - cron: "0 16 * * 1-5"   # 16:00 UTC – 240 min after producer 12:00 tick
    - cron: "0 20 * * 1-5"   # 20:00 UTC – 240 min after producer 16:00 tick
  workflow_run:
    workflows: ["smc-databento-production-export"]
    types: [completed]
    branches: [main]
  workflow_dispatch:
```

(`.github/workflows/smc-library-refresh.yml` lines 53–73, refs F-V4-J3
2026-05-01 belt-and-suspenders + F-V8-C4 2026-05-06 cron-respacing.)

The `if:` guard on the `refresh` job (line 110) gates the workflow_run path
on producer success:

```yaml
if: ${{ github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success' }}
```

Tests `tests/test_workflow_databento_cron_respacing.py` already enforce the
≥60 min headroom between producer cron ticks and consumer cron ticks.

**Action:** none in code. Audit recommendation withdrawn; G1/D2 closed as
"already implemented." If the Q5b cascade race persists despite the
workflow_run trigger, the next investigation is on the *gate* in the
`if:` guard (e.g. is `github.event.workflow_run.conclusion == 'success'`
ever false when Step 7 of the producer eventually does complete?).

## G2 / D3 — Wire FMP `eod-bulk` + movers into `run_open_prep`

**Recommendation (audit):** wire the dormant `/stable/eod-bulk`,
`/stable/most-actives`, `/stable/biggest-gainers`, `/stable/biggest-losers`
methods from `open_prep/macro.py:FMPClient` into `open_prep/run_open_prep.py`
pre-market enrichment.

**Status (verified 2026-05-12):** all four endpoints are already consumed
by `run_open_prep`. Specifically:

- `_build_mover_seed(client, max_symbols)` (`open_prep/run_open_prep.py`
  line 829) extends the universe with rows from
  `client.get_premarket_movers()` (line 834 → `/stable/most-actives`),
  `client.get_biggest_gainers()` (line 835 → `/stable/biggest-gainers`),
  and `client.get_biggest_losers()` (line 836 → `/stable/biggest-losers`).
  It is invoked at line 2498 (extended-hours stage 1: mover seed + union
  symbol list) and line 3798 (FMP auto-universe blending in
  `_resolve_open_prep_universe`).
- `_incremental_atr_from_eod_bulk(client, symbols, as_of, atr_period)`
  (line 3023) consumes `client.get_eod_bulk(as_of)` (line 3035) to compute
  prior-day ATR from a single bulk call instead of N per-symbol candle
  fetches. It is invoked at line 3149.

So in fact, all four endpoints are *already* live in the daily cron
(`run-open-prep-daily.yml`); the audit's "dormant in cron" labelling for
these rows of the dormancy table is incorrect — they were classified as
dormant based on the `_log_feature_unavailable_once` log-suppression
pattern in `macro.py`, which is the no-op fallback when the endpoint is
*plan-tier-unavailable*, not "unused by callers".

**Action:** none in code. Audit recommendation withdrawn; G2/D3 closed
as "already implemented." Dormancy classification corrected: these
endpoints are *consumer-wired* but may be *plan-tier-suppressed* on
non-Ultimate plans (silent no-op via `_log_feature_unavailable_once`).
The G6 endpoint-usage-instrumentation work (commit f1792e73) will now
surface whether these calls actually return data per run.

## Updated FMP action-item status

| ID | Description | Status |
|---|---|---|
| G1 / D2 | `smc-library-refresh` workflow_run trigger | ✅ already implemented (this doc) |
| G2 / D3 | Wire eod-bulk + movers into run_open_prep | ✅ already implemented (this doc) |
| G3 / D4 | 13F-HR live probe + decide remove vs verify | ✅ commit `40e47997` (probe script + comment refresh) |
| G4 / D5 | Document political-trades gate in OPS_QUICK_REFERENCE | ✅ commit `5257a99c` |
| G5 | Remove stubbed Finnhub methods in `open_prep/macro.py` | ⏸ deferred — methods are actively called from `run_open_prep` (Finnhub wiring is the real follow-up) |
| G6 / D-OBS | Per-endpoint usage counter for FMPClient | ✅ commit `f1792e73` (8 new tests pass) |

## Verification reproducer

To re-verify these claims from a fresh clone:

```bash
# G1 verification: workflow_run trigger present on main
git -C skipp-algo show main:.github/workflows/smc-library-refresh.yml \
  | sed -n '50,75p'
# Expect: `workflow_run:` block with `workflows: ["smc-databento-production-export"]`

# G2 verification: helper call sites in run_open_prep
git -C skipp-algo grep -n "_build_mover_seed\|_incremental_atr_from_eod_bulk" \
  open_prep/run_open_prep.py
# Expect: 5 hits (1 def + 2 calls each for mover_seed; 1 def + 1 call for eod_bulk)
```
