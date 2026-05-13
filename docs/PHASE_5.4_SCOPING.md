# Phase 5.4 Scoping — post-Q5b bottleneck disambiguation

**Status**: Scoping note (NOT a fix plan yet — data-gathering phase)
**Date**: 2026-05-13
**Prerequisite**: F-V8-Q5b landed (`scripts/databento_production_export.py`
oversized-sheet skip), all Audit-L-1 PRs (#2167–#2172) merged on `main`
**References**: [AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md](AUDIT_L1_REVIEW_RETROSPECTIVE_2026-05-12.md),
[OPEN_PREP_OPS_QUICK_REFERENCE.md](OPEN_PREP_OPS_QUICK_REFERENCE.md)

---

## 1. Why a scoping note (not a fix plan)

Per project debugging discipline (see commit history, `~/.claude/memory`):

> A step-lifetime profile only reveals the DOMINANT bottleneck. Sub-dominant
> bottlenecks are HIDDEN behind it and become visible only AFTER the dominant
> one is fixed. Each refactor phase therefore needs a FRESH profile, not the
> previous one.

The most recent baseline data is from D-profile **Run #25422978658** (post-A6,
2026-05-06), which identified Step 8/10c (35.5min, 76.5M rows) as the new
dominant bottleneck after Steps 6+6b were optimised in P5.3-A6.

Two events have since potentially changed that picture:

1. **F-V8-Q5b** (2026-05-12) — `_write_canonical_production_workbook` now
   omits `full_universe_second_detail_open` and `…_close` from the canonical
   xlsx workbook (oversized-sheet OOM in openpyxl). The two series remain
   available as parquet artifacts. This MAY have already removed a
   significant portion of the Step 10/10c work.
2. **Audit-L-1 train** (PRs #2167–#2172, 2026-05-12 → 2026-05-13) — touched
   probe scripts, feature flags, citation guards, secret-leakage AST.
   Unlikely to affect runtime hot-paths but the merge reshuffled module
   imports in `open_prep/streamlit_monitor.py` and
   `newsstack_fmp/ingest_opra_options_flow.py` (both module-import-time
   `int(getenv())` parsing now defensive).

**Conclusion**: We do NOT yet have empirical evidence about the current
dominant bottleneck. Writing a fix plan against the stale Step 8/10c profile
would risk a Bundle-B-style miss (P5.2 PR #2058: 4 edits shipped against a
mechanistic source-lookup chain; D1 profile post-merge proved the real
bottleneck was elsewhere — only 1 of 4 edits was wired).

## 2. Candidate hypotheses (to be falsified by fresh D-profile)

Listed with the file/region to inspect AFTER the next D-profile run pins
which one is dominant. **Do NOT pre-emptively fix any of these.**

### H1 — Step 8/10b close-window second detail collection (post-Q5b residual)

* **Where**: `scripts/databento_production_export.py` around Step 8/10b
  (close-window second detail collection — see
  `Step 8/10b complete:` log line, currently around line 3618). This was
  the ~76.5M-row scan in D-profile #25422978658, NOT OPRA UOA —
  `grep -nE 'opra|uoa' scripts/databento_production_export.py` returns
  zero matches, so the prior OPRA UOA framing was wrong.
* **Hypothesis**: Even after Q5b skips the second-detail xlsx writes,
  the underlying close-window second detail _collection_ over the full
  Databento second-bar feed still loads ~76.5M rows into memory before
  the parquet/skipped-xlsx fan-out. Memory peak from this collection is
  the proximate trigger for the SIGTERM kill documented in
  `docs/PHASE_5.4_FAILURE_ANALYSIS.md`. Streaming the second-bar window
  through a per-symbol generator (instead of a single concat) could cut
  peak RSS by ~60%.
* **Falsifier**: Fresh D-profile shows Step 8/10b < 10min wall AND peak
  RSS < 20 GiB — H1 is dead.
* **Cost if pursued**: ~1 day, requires regression test against current
  parquet output (numerical equivalence, not just shape).

### H2 — Step 10/10b parquet write fan-out (vs Step 10/10c workbook)

* **Where**: `scripts/databento_production_export.py` Step 10/10b is the
  parquet write loop; Step 10/10c is the canonical xlsx workbook write
  (the latter already has Q5a + Q5b skips for oversized sheets). For
  this hypothesis the focus is Step 10/10b (parquet) — even with the
  workbook largely skipped, the parquet writes still fan out across
  many per-day files. Confirm line range with `grep -nE 'Step 10/10b complete:' scripts/databento_production_export.py`.
* **Hypothesis**: PyArrow's per-file fsync overhead on the larger-runner
  pool (network-mounted `/home/runner/work`) dominates. Batching into a
  single multi-file dataset directory could amortise.
* **Falsifier**: D-profile shows Step 10/10b parquet writes < 5% of cap.
* **Cost if pursued**: ~½ day, mostly test surface (the parquet readers
  on the consumer side need to accept the new directory shape).

### H3 — Step 6/6b sequential per-day loops re-emerging

* **Where**: `scripts/databento_production_export.py` Steps 6 + 6b
  (per-day fetch loops). P5.3-A6 collapsed these from sequential into
  bounded-concurrency, but the larger-runner pool's network jitter
  (109min cron delay on 2026-05-11, see CHANGELOG) might be re-serialising
  via Databento rate limits.
* **Falsifier**: D-profile shows Steps 6+6b combined < 25% of cap (i.e.
  they didn't regress).
* **Cost if pursued**: investigation only — the fix would be Databento
  rate-limit tuning, not code.

### H4 — New bottleneck unmasked by Q5b

* **Where**: unknown until D-profile.
* **Hypothesis**: Q5b removed a large constant; the next dominant step
  could be anywhere (Step 7 cleanup, Step 11 parquet validate, Step 12
  artifact upload).
* **Falsifier**: top step in fresh D-profile is one of the above
  candidates (H1-H3).

## 3. Data-gathering plan (Phase 5.4 entry criteria)

Before writing a fix plan, the following must be in hand:

1. **Fresh D-profile run** of `smc-databento-production-export.yml` on
   current `main` (post-Q5b, post-Audit-L-1). Triggered manually or via
   the cron + watchdog. Run ID recorded here once available.
2. **Step-lifetime tabulation** of that run: `(step name, start, end, delta, % of 240-min cap)`. After PR #2176 the progress lines carry a
   `[t+Xs rss=peak/current MiB]` prefix, so the tabulation pipeline is:
   ```bash
   # GHA log lines are already in temporal order; preserve that order
   # (lex-sort on the `[t+Xs]` prefix would order t+100s before t+99s).
   gh run view <id> --log \
     | grep -E 'Step [0-9]+/[0-9]+[a-z]?(:| complete)'
   ```
   For each step, the difference between the `Step N/10x:` start line
   and the matching `Step N/10x complete:` line gives the wall delta.
   Step labels actually emitted by the exporter:
   `Step 1/10` through `Step 8/10` plus `Step 8/10[a-e]` sub-stages, and
   `Step 9/10`, `Step 10/10b` (parquet), `Step 10/10c` (workbook).
3. **Failure analysis of Run #25752310158** (failed 2026-05-12 17:53→20:42
   UTC) — see `docs/PHASE_5.4_FAILURE_ANALYSIS.md`. Confirms the failure
   is a runner-level SIGTERM at the workbook stage, recurring on 7 of 8
   most recent runs. Blocks naive D-profile retrigger; PR #2176 shipped
   the prerequisite `_progress()` instrumentation so even a SIGTERM-
   killed run yields recoverable step-lifetime data.

Only when steps 1-3 are complete should this scoping note be promoted to a
`docs/PHASE_5.4_PLAN.md` with concrete fix selection.

## 4. Out of scope for Phase 5.4

* Re-opening Audit-L-1 R-items (all 14 closed in PRs #2167–#2172).
* Re-opening Bundle-B streaming-layer changes (P5.2). The fresh profile
  will tell us whether Step 8 was actually a streaming-layer issue all
  along; deferring to data.
* Provider rationalisation (UW decommissioning is complete; no remaining
  consumer).

## 5. Tracker

| Step | Status | Notes |
|---|---|---|
| Failure analysis Run #25752310158 | pending | session 2026-05-13 |
| Fresh D-profile triggered on main | pending | post-failure-analysis |
| Step-lifetime tabulation | blocked on profile | |
| Fix plan written (this file → PLAN) | blocked on tabulation | |
