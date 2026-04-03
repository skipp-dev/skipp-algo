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

C2 is now active and one visual-only slice is already landed in the split-core.
The executed helper extractions in that slice are:

1. `compose_long_alert_text_suffixes`
2. `resolve_long_debug_event_values`
3. `resolve_event_risk_state`
4. `compose_health_badge_text`
5. `resolve_health_badge_color`
6. `compose_long_debug_primary_line`
7. `compose_long_debug_full_summary_text`
8. `compose_long_debug_label_header_text`
9. `compose_long_debug_event_header_text`
10. `compose_zone_range_text`
11. `compose_combined_zone_summary_text`
12. `resolve_long_debug_mode_suffix`
13. `append_debug_module_text`
14. `compose_long_debug_module_label`
15. `resolve_long_setup_state_label`
16. `long_setup_state_has_source_display`
17. `compose_long_setup_state_text`
18. `resolve_long_visual_state_label`
19. `resolve_long_zone_source_label`
20. `resolve_long_anchor_source_label`
21. `compose_passed_status_text`
22. `compose_eligible_status_text`
23. `compose_awaiting_status_text`
24. `compose_blocked_status_text`
25. `compose_need_ready_status_text`
26. `compose_long_source_invalidated_text`
27. `compose_long_backing_zone_lost_text`
28. `compose_long_setup_expired_text`
29. `compose_long_confirm_expired_text`
30. `resolve_long_environment_focus_text`
31. `compose_long_debug_last_invalid_text`
32. `compose_long_debug_reason_text`
33. `resolve_long_upgrade_edge_text`
34. `compose_long_upgrade_reason_text`
35. `resolve_long_confirm_freshness_text`
36. `resolve_long_armed_freshness_text`
37. `resolve_long_source_state_text`
38. `resolve_long_zone_quality_text`
39. `resolve_long_overhead_alert_text`
40. `compose_long_score_detail_suffix`
41. `resolve_long_strict_alert_suffix`
42. `compose_long_environment_alert_suffix`
43. `compose_long_micro_alert_suffix`
44. `compose_long_debug_pipe_upgrade_text`
45. `compose_long_debug_pipe_reason_text`
46. `compose_long_debug_newline_upgrade_text`
47. `compose_long_debug_newline_last_invalid_text`
48. `compose_long_debug_label_full_mode_text`
49. `compose_long_debug_event_state_text`
50. `append_enabled_debug_module_text`
51. `compose_ob_zone_summary_text`
52. `compose_fvg_zone_summary_text`
53. `resolve_long_source_fallback_text`
54. `compose_long_source_transition_text`
55. `resolve_long_primary_source_text`
56. `resolve_long_source_display_text`
57. `resolve_long_setup_state_code`
58. `resolve_long_visual_state_code`
59. `resolve_long_zone_summary_display_text`
60. `resolve_enabled_debug_modules_display_text`
61. `resolve_long_setup_display_text`
62. `resolve_long_source_label_text`
63. `resolve_long_strict_blocker_display_text`
64. `resolve_long_ready_blocker_display_text`
65. `resolve_long_engine_debug_label_display_text`
66. `resolve_long_engine_event_log_display_text`

Those changes stay covered by split-core structural assertions. These remaining
pre-existing helpers are still good lightweighting candidates because they are
formatting or display helpers rather than trade-state owners:

There are no further meaningful C2 extraction candidates left in this helper
block. The bookkeeping alias `resolve_long_visual_text` was retired, and the
single call site now uses `resolve_long_visual_state_label` directly.

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
| `resolve_long_source_text` | 1425 | Internal source-label mapping localized in C2; outer helper remains safe decoder surface |
| `compose_zone_summary_text` | 1550 | Internal range formatting localized in C2; outer helper remains safe display-summary surface |
| `compose_long_setup_text` | 1881 | Internal state-label composition localized in C2; outer helper remains safe decoder surface |
| `resolve_long_visual_text` (retired) | n/a | Redundant alias removed in bookkeeping cleanup; call site now uses `resolve_long_visual_state_label` directly |

### Debug / Display Only — Lowest-Risk Cleanup Lane

These items are the best Phase C candidates because they do not own lifecycle
transitions or decision thresholds:

| Kind | Current Anchors | Recommendation |
| --- | --- | --- |
| Declaration-only visual inputs | `show_mtf_trend`, `show_risk_levels`, `show_reclaim_markers`, `show_long_confirmation_markers`, `show_long_background`, `color_long_bars`, `show_accel_debug`, `show_sd_debug`, `show_vol_regime_debug`, `show_stretch_overlay`, `show_lower_extreme_bg` | Removed in C1; keep absent |
| Alert/debug/badge composition helpers | `compose_long_alert_text_suffixes`, `resolve_long_debug_event_values`, `resolve_event_risk_state`, `compose_health_badge_text`, `resolve_health_badge_color`, `compose_long_debug_primary_line`, `compose_long_debug_full_summary_text`, `compose_long_debug_label_header_text`, `compose_long_debug_event_header_text`, `resolve_long_debug_mode_suffix`, `append_debug_module_text`, `append_enabled_debug_module_text`, `compose_long_debug_module_label`, `resolve_long_setup_state_label`, `long_setup_state_has_source_display`, `compose_long_setup_state_text`, `resolve_long_setup_state_code`, `resolve_long_visual_state_code`, `resolve_long_visual_state_label`, `resolve_long_zone_source_label`, `resolve_long_anchor_source_label`, `resolve_long_primary_source_text`, `resolve_long_source_fallback_text`, `compose_long_source_invalidated_text`, `compose_long_backing_zone_lost_text`, `compose_long_setup_expired_text`, `compose_long_confirm_expired_text`, `resolve_long_environment_focus_text`, `compose_long_debug_last_invalid_text`, `compose_long_debug_reason_text`, `resolve_long_upgrade_edge_text`, `compose_long_upgrade_reason_text`, `resolve_long_confirm_freshness_text`, `resolve_long_armed_freshness_text`, `resolve_long_source_state_text`, `resolve_long_zone_quality_text`, `resolve_long_overhead_alert_text`, `compose_long_score_detail_suffix`, `resolve_long_strict_alert_suffix`, `compose_long_environment_alert_suffix`, `compose_long_micro_alert_suffix`, `compose_long_debug_pipe_upgrade_text`, `compose_long_debug_pipe_reason_text`, `compose_long_debug_newline_upgrade_text`, `compose_long_debug_newline_last_invalid_text`, `compose_long_debug_label_full_mode_text`, `compose_long_debug_event_state_text`, `compose_ob_zone_summary_text`, `compose_fvg_zone_summary_text`, `compose_long_source_transition_text`, `resolve_long_source_display_text`, `resolve_long_zone_summary_display_text` | Executed in C2 visual-only slice; keep pinned by split-core assertions |
| Debug module summary | `compose_enabled_debug_modules_text` | Internal module-label composition localized in C2; outer helper remains visual-only |
| Ready / strict blocker strings | `resolve_long_ready_blocker_text`, `resolve_long_strict_blocker_text` | Internal status phrase composition localized in C2; keep gate priority semantics fixed |
| Debug label / event-log composition | `compose_long_engine_debug_label_text`, `compose_long_engine_event_log` | Keep visual-only; further extraction is fine if it reduces coupling without moving runtime state |

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
