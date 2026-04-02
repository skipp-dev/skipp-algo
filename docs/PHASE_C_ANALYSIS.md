# Phase C Analysis — Rebased After AP1-AP5

**Status**: Prepared, but not execution-ready on stale evidence  
**Date**: 2026-04-02  
**Prerequisite**: AP1-AP5 complete  
**References**: [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md), [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md), [smc_deep_research_migration_plan_copilot.md](smc_deep_research_migration_plan_copilot.md)

---

## 1. Why This Document Was Rebased

The previous Phase C write-up assumed the next best move was immediate dead-input
deletion. That assumption is now stale.

The repo has since completed a higher-leverage architecture-faithfulness wave:

1. Signal Quality is now the primary long-engine interpretation layer.
2. Lean field names are canonical across generator, artifacts, tests, and Pine consumers.
3. The measurement lane is operationalized in scripts and CI workflows.
4. Event IDs are ticksize-/session-aware end-to-end, including liquidity IDs.
5. The service bundle exposes bias, vol-regime, and measurement summary visibly.

Result: Phase C should now be treated as **non-behavioural cleanup only**.
It should not reopen AP1-AP5 class changes under a cleanup label.

---

## 2. Closed Before Phase C

These are no longer valid Phase C targets:

1. Signal-quality primacy rewiring
2. Lean contract naming cleanup
3. Measurement-lane operationalization
4. Ticksize-/session-aware ID hardening
5. Service-bundle context visibility for bias / vol / measurement

Any future Phase C work must preserve these results and remain strictly additive
or subtractive at the display/debug layer.

---

## 3. Rebased Phase C Scope

### C1 — Refresh the Dead-Input Audit

The old dead-input list is still a useful candidate queue, but it should no longer
be treated as auto-approved removal work. We now have a current regression guard
for the candidate set, and deletion should happen only after a fresh compile-safe audit.

Current candidate queue in `SMC_Core_Engine.pine`:

| # | Variable | Current Line | Current Status |
| --- | --- | --- | --- |
| 1 | `show_mtf_trend` | 3184 | declaration-only candidate |
| 2 | `show_risk_levels` | 3212 | declaration-only candidate |
| 3 | `show_reclaim_markers` | 3404 | declaration-only candidate |
| 4 | `show_long_confirmation_markers` | 3405 | declaration-only candidate |
| 5 | `show_long_background` | 3408 | declaration-only candidate |
| 6 | `color_long_bars` | 3409 | declaration-only candidate |
| 7 | `show_accel_debug` | 3506 | declaration-only candidate |
| 8 | `show_sd_debug` | 3522 | declaration-only candidate |
| 9 | `show_vol_regime_debug` | 3544 | declaration-only candidate |
| 10 | `show_stretch_overlay` | 3558 | declaration-only candidate |
| 11 | `show_lower_extreme_bg` | 3560 | declaration-only candidate |

Deletion preconditions:

1. Current full-file proof remains declaration-only.
2. No split-core dashboard/alert consumer depends on the variable indirectly.
3. No compact-mode or rendering regression appears after removal.
4. TradingView compile/save check is run after the actual deletion batch.

### C2 — Extract Display-/Debug-Only Helpers

These remain good lightweighting candidates because they are formatting or display
helpers rather than trade-state owners:

1. `resolve_long_source_text`
2. `compose_zone_summary_text`
3. `compose_enabled_debug_modules_text`
4. `resolve_long_ready_blocker_text`
5. `resolve_long_strict_blocker_text`
6. `compose_long_engine_debug_label_text`
7. `compose_long_engine_event_log`
8. `compose_long_setup_text`
9. `resolve_long_visual_text`

Guardrails for C2:

1. No state transitions, gates, or lifecycle variables may move.
2. No alert eligibility logic may move.
3. Only string/display composition is in scope.

### C3 — Decide the Legacy Parallel Path Explicitly

One important repo fact now needs to be carried into Phase C planning:

1. `tests/test_smc_long_dip_regressions.py` targets `SMC++.pine`, not `SMC_Core_Engine.pine`.
2. Split-core assertions belong in split-core tests only.
3. Future cleanup must decide whether `SMC++.pine` is still maintained, frozen, or headed for deprecation.

That decision should happen before broad cleanup work starts crossing both engines again.

---

## 4. Not In Scope For Phase C

The following should be treated as closed and regression-only:

1. Signal-quality gate semantics
2. Lean contract field naming
3. Measurement-lane behavior and governance
4. Vol-regime model behavior
5. Service-bundle context exposure
6. Any new quality/blocking rewiring in Pine

If a task changes long-engine behavior, it is almost certainly **not** Phase C anymore.

---

## 5. Readiness Verdict

| Item | Status | Notes |
| --- | --- | --- |
| Dead-input deletion batch | Yellow | candidate list is current, but actual removal still needs compile-safe execution |
| Display/debug extraction | Green-after-C1 | low-risk once the candidate audit is refreshed |
| Legacy parallel-path cleanup | Yellow | requires explicit ownership decision for `SMC++.pine` |
| Full Phase C execution now | Yellow | do not execute from the old plan blindly |

---

## 6. Preparation Outputs Landed

This AP6 re-evaluation leaves Phase C in a materially better state than the old note:

1. The scope is rebased away from AP1-AP5 topics.
2. The dead-input candidate list has a fresh current-line inventory.
3. `tests/test_smc_core_engine_phase_c_audit.py` guards the current declaration-only candidate set.
4. The legacy split-core vs. `SMC++.pine` boundary is explicitly documented as a planning constraint.

---

## 7. Recommended First Execution Order

1. Remove only the declaration-only candidates in one isolated commit.
2. Re-run Pine compile/save plus the Phase C audit test after that deletion batch.
3. Perform display/debug helper extraction in a separate no-logic-change commit.
4. Decide whether `SMC++.pine` remains a maintained parallel engine before broader cleanup resumes.
