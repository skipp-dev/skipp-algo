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

### H1 — Step 8 OPRA UOA detection (post-Q5b residual)

* **Where**: `newsstack_fmp/opra_uoa.py::detect_unusual_options_activity`
  (~76.5M rows scanned per run in #25422978658)
* **Hypothesis**: Even after Q5b skips the second-detail xlsx writes, the
  Step 8 detection scan over the OPRA.PILLAR feed remains O(N) over the
  full UOA candidate window. Vectorising the per-symbol z-score loop
  (`for sym in candidates:` → groupby) could cut wall by ≥50%.
* **Falsifier**: Fresh D-profile shows Step 8 < 10min wall — H1 is dead and
  Q5b alone fixed it.
* **Cost if pursued**: ~1 day, requires regression test against current
  detector output (numerical equivalence, not just shape).

### H2 — Step 10/10c parquet write fan-out

* **Where**: `scripts/databento_production_export.py` parquet write loop
  (post-Q5b: still writes the second-detail series as parquet, just not
  xlsx). Confirm the line range with `grep -nE "second_detail.*parquet"
  scripts/databento_production_export.py`.
* **Hypothesis**: PyArrow's per-file fsync overhead on the larger-runner
  pool (network-mounted `/home/runner/work`) dominates. Batching into a
  single multi-file dataset directory could amortise.
* **Falsifier**: D-profile shows parquet writes < 5% of cap.
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
2. **Step-lifetime tabulation** of that run: `(step name, start, end,
   delta, % of 240-min cap)`. Generated via
   `gh run view <id> --log | grep -E "STEP [0-9]+|Step [0-9]+ (start|end)"`
   piped into a sort/awk pipeline (see `~/.claude/memory/debugging.md`
   "Concrete protocol").
3. **Failure analysis of Run #25752310158** (failed 2026-05-12 17:53→20:42
   UTC) — needed to confirm the failure mode is unrelated to whichever
   step the new D-profile fingers as dominant. If the failure is in the
   same step, the fix plan must address both.

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
