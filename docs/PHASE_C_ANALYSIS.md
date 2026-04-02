# Phase C Analysis — Fresh Inventory on Current v5.5b Main

**Status**: Supporting planning note  
**Date**: 2026-04-02  
**Prerequisite**: v5.5b canonical state on `main`  
**Role**: Fresh Phase C inventory for post-v5.5b cleanup only  
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

### C1 — Declaration-Only Visual Inputs Removed

The first split-core cleanup batch has now been executed. The following
declaration-only visual/debug inputs were removed from `SMC_Core_Engine.pine`
because they had no gate, lifecycle, dashboard, or alert consumer:

| # | Removed Input | Former Line | Former Default |
| --- | --- | --- | --- |
| 1 | `show_mtf_trend` | 3184 | `true` |
| 2 | `show_risk_levels` | 3212 | `true` |
| 3 | `show_reclaim_markers` | 3404 | `true` |
| 4 | `show_long_confirmation_markers` | 3405 | `true` |
| 5 | `show_long_background` | 3408 | `true` |
| 6 | `color_long_bars` | 3409 | `false` |
| 7 | `show_accel_debug` | 3506 | `false` |
| 8 | `show_sd_debug` | 3522 | `false` |
| 9 | `show_vol_regime_debug` | 3544 | `false` |
| 10 | `show_stretch_overlay` | 3558 | `true` |
| 11 | `show_lower_extreme_bg` | 3560 | `false` |

Post-removal guards:

1. `tests/test_smc_core_engine_phase_c_audit.py` asserts the removed names stay absent.
2. `docs/RUNTIME_BUDGET.md` records the C1 batch as executed cleanup.
3. Any future Phase C work should start at C2, not re-open this batch.

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

## 4. Fresh Inventory by Execution Surface

### Runtime Core Only — Stay Local

These areas remain bar-state owners or direct decision-path inputs and should
stay local to `SMC_Core_Engine.pine` during Phase C:

| Area | Current Anchors | Why It Stays Local |
| --- | --- | --- |
| Signal-quality primacy and lean gates | `primary_quality_gate_ok`, `best_signal_quality_gate_ok`, `strict_signal_quality_gate_ok`, lean 2-of-4 consensus | Directly controls Ready / Best / Strict semantics |
| Long lifecycle state machine | `long_state.arm(...)`, `long_state.confirm(...)`, `compute_long_ready_state(...)` | Owns setup progression and invalidation timing |
| Source tracking and upgrades | `stage_locked_source_transition(...)`, locked-source touch tracking | Tightly coupled to runtime state and bar-by-bar invalidation |
| Overhead / environment gating | `compute_overhead_context(...)`, `compute_long_environment_context(...)` | Influences trade eligibility, not just presentation |
| Context-quality telemetry support | `compute_context_quality(...)`, `htf_alignment_ok`, `strict_entry_ltf_ok` | Diagnostic-first, but still feeds strict-entry support outputs |

### Dashboard / Decoder Only — Extract When It Reduces Coupling

These helpers are strong future extraction candidates because they primarily
translate runtime state into text or compact decoder semantics:

| Helper | Current Line | Recommendation |
| --- | --- | --- |
| `resolve_long_source_text` | 1425 | Safe decoder/helper extraction candidate |
| `compose_zone_summary_text` | 1550 | Safe display-summary extraction candidate |
| `compose_long_setup_text` | 1881 | Safe decoder/helper extraction candidate if inputs stay explicit |
| `resolve_long_visual_text` | 1906 | Safe decoder/helper extraction candidate |

### Debug / Display Only — Lowest-Risk Cleanup Lane

These items are the best Phase C candidates because they do not own lifecycle
transitions or decision thresholds:

| Kind | Current Anchors | Recommendation |
| --- | --- | --- |
| Declaration-only visual inputs | `show_mtf_trend`, `show_risk_levels`, `show_reclaim_markers`, `show_long_confirmation_markers`, `show_long_background`, `color_long_bars`, `show_accel_debug`, `show_sd_debug`, `show_vol_regime_debug`, `show_stretch_overlay`, `show_lower_extreme_bg` | Removed in C1; keep absent |
| Debug module summary | `compose_enabled_debug_modules_text` | Extract or localize with no logic change |
| Ready / strict blocker strings | `resolve_long_ready_blocker_text`, `resolve_long_strict_blocker_text` | Keep semantics fixed; extraction is fine if inputs remain plain values |
| Debug label / event-log composition | `compose_long_engine_debug_label_text`, `compose_long_engine_event_log` | Extract in a visual-only commit once C1 is settled |

### Explicit Do-Not-Touch Set

The following areas should remain outside Phase C execution:

1. Signal Quality thresholds or tier semantics
2. Lean field names / generated artifact naming
3. Measurement / scoring behavior
4. Vol-regime classification rules
5. Service-bundle measurement / bias / vol exposure
6. Ticksize- / session-aware ID behavior

---

## 5. Not In Scope For Phase C

The following should be treated as closed and regression-only:

1. Signal-quality gate semantics
2. Lean contract field naming
3. Measurement-lane behavior and governance
4. Vol-regime model behavior
5. Service-bundle context exposure
6. Any new quality/blocking rewiring in Pine

If a task changes long-engine behavior, it is almost certainly **not** Phase C anymore.

---

## 6. Readiness Verdict

| Item | Status | Notes |
| --- | --- | --- |
| Dead-input deletion batch | Green | C1 executed; removed inputs are now guarded as absent |
| Display/debug extraction | Green | next low-risk cleanup lane after C1 |
| Legacy parallel-path cleanup | Yellow | requires explicit ownership decision for `SMC++.pine` |
| Full Phase C execution now | Yellow | do not execute from the old plan blindly |

---

## 7. Preparation Outputs Landed

This AP6 re-evaluation leaves Phase C in a materially better state than the old note:

1. The scope is rebased away from AP1-AP5 topics.
2. C1 removed 11 declaration-only visual inputs from the split core.
3. `tests/test_smc_core_engine_phase_c_audit.py` guards the continued absence of the removed C1 inputs.
4. The current inventory is separated into runtime-core, dashboard/decoder, and debug/display lanes.
5. The legacy split-core vs. `SMC++.pine` boundary is explicitly documented as a planning constraint.

---

## 8. Recommended Next Execution Order

1. Keep the C1 removal batch compile-clean and absence-guarded after nearby edits.
2. Perform display/debug helper extraction in a separate no-logic-change commit.
3. Decide whether `SMC++.pine` remains a maintained parallel engine before broader cleanup resumes.
