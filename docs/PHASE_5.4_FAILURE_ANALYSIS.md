# Phase 5.4 — Failure Analysis: Run #25752310158 + recurring SIGTERM pattern

**Status**: Diagnosis (root cause identified, fix deferred to PHASE_5.4_PLAN)
**Date**: 2026-05-13
**Companion to**: [PHASE_5.4_SCOPING.md](PHASE_5.4_SCOPING.md)
**Workflow**: `smc-databento-production-export.yml`

---

## TL;DR

Run **#25752310158** (and 6 of the 7 most recent runs) failed with **exit
code 143 (SIGTERM)** delivered by the GitHub Actions runner infrastructure
~2.5–3.5h into the job. This is **not a Python exception or in-process
error** — it is a runner-level shutdown signal.

F-V8-Q5b (oversized-sheet skip, landed 2026-05-12) was active in the
failed run (the workbook step explicitly logged the Q5a + Q5b skips at
20:33:04Z), but the runner was killed ~9 minutes later at 20:42:50Z. So
**Q5b reduced peak memory pressure but did not eliminate the SIGTERM
trigger**.

This blocks STEP 3 (fresh D-profile on main): if the production export
job reliably gets killed at ~2.5–3.5h, the D-profile won't complete
cleanly either. STEP 3 must therefore include a watchdog/short-circuit
strategy or use a smaller universe slice.

## Recurrence pattern

```text
RUN_ID         RESULT          EVENT     CREATED              DURATION  SHA
25752310158    failure         schedule  2026-05-12T17:53     170min    633662b
25738826438    failure         schedule  2026-05-12T13:50     216min    04c622a
25733577369    failure         dispatch  2026-05-12T12:11     150min    04c622a
25693860630    failure         dispatch  2026-05-11T19:57     141min    000bea3
25687318767    failure         schedule  2026-05-11T17:49     150min    bc399c5
25676061796    failure         schedule  2026-05-11T14:22     186min    de2459c
25675320709    SUCCESS         dispatch  2026-05-11T14:08      52min    de2459c  ← short slice
25568632083    failure         schedule  2026-05-08T17:04     216min    08a48a3
```

* **7 of 8 runs failed** across 4+ days and 5 different SHAs.
* The single success (#25675320709) completed in 52min — implying it ran a
  reduced universe / shorter window, not a full export.
* Failures span before AND after Q5b landed (F-V8-Q5b was on 2026-05-12);
  both 2026-05-12 runs failed despite Q5b being active.

## Root cause: SIGTERM (exit 143) at workbook stage

Tail of `gh run view 25752310158 --log-failed`:

```text
2026-05-12 20:33:04 INFO __main__: workbook: skipping
   full_universe_close_trade_detail (parquet retained via Step 10/10b,
   Q5a OOM mitigation)
2026-05-12 20:33:04 INFO __main__: workbook: skipping
   full_universe_second_detail_open + full_universe_second_detail_close
   (parquets retained via Step 10/10b, Q5b OOM mitigation)
2026-05-12 20:42:50 ##[error]Process completed with exit code 143.
2026-05-12 20:42:50 ##[error]The runner has received a shutdown signal.
   This can happen when the runner service is stopped, or a manually
   started runner is canceled.
```

Interpretation:

* Exit 143 = 128 + 15 = SIGTERM
* GitHub's diagnostic explicitly says "runner has received a shutdown
  signal" — the kill came from outside the Python process
* No Python traceback, no MemoryError, no AssertionError above the
  shutdown line in the failed-step log

Likely culprits, in order of probability:

1. **Larger-runner pool eviction** under sustained 30+GB resident
   memory (see Q5a/Q5b history — full-universe second-detail xlsx
   sheets used to push past 60GB; even with skips, parquet writes +
   the still-included sheets may be exceeding the runner's tolerance).
2. **GHA scheduled runner rotation** on the `ubuntu-latest-l` pool.
3. **OOMKiller** at the cgroup level (kernel SIGKILL would normally
   show as exit 137 not 143; SIGTERM with the runner's "shutdown"
   message points to the GHA agent itself sending SIGTERM rather than
   kernel OOMK).

## Why this blocks the original Phase 5.4 plan

Per [PHASE_5.4_SCOPING.md](PHASE_5.4_SCOPING.md) §3, the entry criteria
for promoting the scoping note to a fix plan included:

> 1. Fresh D-profile run … on current `main` (post-Q5b, post-Audit-L-1)
> 2. Step-lifetime tabulation of that run

If 7 of 8 runs are killed at 2.5–3.5h, a D-profile triggered as-is will
likely die in the workbook stage — **before** the per-step tabulation
can record an end timestamp. The collected log will only show start
events, not deltas.

## Adjusted STEP 3 protocol (next session)

Rather than a vanilla `gh workflow run smc-databento-production-export.yml`,
the fresh D-profile must include one of:

* **Option A — Guard with smaller window**: dispatch with a 1–2 day
  universe window via `workflow_dispatch` inputs (if available; check
  `gh workflow view smc-databento-production-export.yml --yaml`). Goal:
  complete inside 90min so we get clean step-lifetime data. Caveat:
  smaller window may shift bottleneck profile — annotate accordingly.
* **Option B — Add per-step `time.monotonic()` flushed-prints**: a
  surgical PR adding `print(..., flush=True)` after every numbered step
  with `MEM_RSS=` from `/proc/self/status`. Even if the run dies, we
  get partial step-lifetime + the last-completed step before SIGTERM.
* **Option C — Disable workbook stage**: `workflow_dispatch` with an
  env var `SKIP_WORKBOOK=1` (if supported) to confirm the workbook
  stage is the SIGTERM trigger. If a run completes without workbook,
  the diagnosis is confirmed and Phase 5.4 fix scope narrows to
  workbook (potentially: write parquet only, defer xlsx to a separate
  smaller job).

Option B is the safest: it's instrumentation-only, drops zero data, and
works regardless of which sub-stage triggers SIGTERM.

## Tracker update for PHASE_5.4_SCOPING.md

| Step | Status | Notes |
|---|---|---|
| Failure analysis Run #25752310158 | **DONE** | Root cause SIGTERM at workbook stage; recurring 7/8 |
| Fresh D-profile triggered on main | **BLOCKED** | Needs Option B (instrumented PR) before retrigger |
| Step-lifetime tabulation | blocked on profile | |
| Fix plan written (this file → PLAN) | blocked on tabulation | |
| **NEW**: Per-step `flush=True` instrumentation PR | **PENDING** | Prerequisite for any further D-profile attempt |

## Recommendation

The next actionable PR is **Option B instrumentation**, NOT a fresh
D-profile trigger. Triggering as-is is wasted compute given the 7/8
failure rate.
