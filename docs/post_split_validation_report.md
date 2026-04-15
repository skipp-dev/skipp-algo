# Post-Split Validation Report — WP-SPLIT1–4

**Date:** 2025-07-13  
**HEAD:** `7d769bfb` (refactor(smc): split Core Engine into modular libraries (WP-SPLIT1–4))  
**Working tree:** dirty — `tests/test_smc_long_dip_regressions.py` has uncommitted recovery-pass changes

---

## Summary

| File | Tests | Passed | Failed |
|------|------:|-------:|-------:|
| `test_tradingview_decision_first_ui.py` | 22 | 22 | 0 |
| `test_smc_core_engine_split.py` | 19 | 19 | 0 |
| `test_smc_core_engine_semantic_contract.py` | 21 | 21 | 0 |
| `test_smc_bus_v2_semantics.py` | 15 | 15 | 0 |
| `test_smc_long_dip_regressions.py` | 69 | 36 | **33** |
| **Total** | **146** | **113** | **33** |

All 4 split-specific test files pass cleanly.  
All 33 failures are in `test_smc_long_dip_regressions.py`.

---

## Failure Classification

### Split-caused (3)

These assertions break because WP-SPLIT moved the target definition out of the Core Engine.

| # | Test | Root Cause | Split |
|---|------|-----------|-------|
| 1 | `test_atr_helper_uses_deterministic_warmup_accumulator` | `smc_lib_atr` definition moved to `smc_utils.pine` — test reads Core Engine only | WP-SPLIT3 |
| 2 | `test_udt_render_and_draw_helpers_guard_na_before_field_access` | `method delete(Profile this)` moved to `smc_profile_engine.pine` | WP-SPLIT2 |
| 3 | `test_profile_and_track_obs_use_defensive_semantic_helpers` | `normalize_profile_resolution` moved to `smc_profile_engine.pine` | WP-SPLIT2 |

**Fix pattern:** add a reader for the extracted library and redirect the assertion to its source.

### Pre-existing (30)

These assertions were already stale before WP-SPLIT1–4. They reflect Core Engine evolution since the legacy `SMC++.pine` snapshot the tests were written against.

| # | Test | First Failing Assertion | Evolution Kind |
|---|------|------------------------|---------------|
| 1 | `test_refactored_helpers_preserve_dependency_order` | `db_trend_text(` not found | function removed/renamed |
| 2 | `test_signal_and_long_state_contract_are_declared_for_safe_refactors` | indicator title `"SMC++"` → now `"SMC Long-Dip Suite v7"` | indicator renamed |
| 3 | `test_backing_zone_identity_and_touch_count_persist_after_arm` | `long_arm_locked_source_id` → `helper_long_arm_locked_source_id` | variable renamed |
| 4 | `test_invalidation_path_records_specific_reason_and_clears_setup_state` | old invalidation string pattern | code refactored |
| 5 | `test_indicator_resource_caps_match_runtime_history_behavior` | `max_labels_count = 500` → now `300` | resource caps changed |
| 6 | `test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods` | draw call signature changed | function evolved |
| 7 | `test_invalidated_alert_has_single_preset_definition_without_failed_alias` | 0 preset defs found (expected 1) | alert system overhauled |
| 8 | `test_structure_signal_derivations_use_explicit_block_logic` | `show_chart_swing_levels := true` gone | code refactored |
| 9 | `test_armed_stage_can_be_optionally_tightened` | `bool armed_prequality_ok = true` → now `compute_long_arm_prequality_ok(…)` | literal → computed |
| 10 | `test_user_presets_and_performance_modes_drive_effective_runtime_layers` | tooltip text changed | text evolved |
| 11 | `test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard` | `long_debug_mode_suffix = ' Compact'` gone | debug mode evolved |
| 12 | `test_clean_tier_is_renamed_as_a_quality_diagnostic` | `bool long_quality_clean_tier = false` → `resolve_long_clean_tier(…)` | literal → computed |
| 13 | `test_cleanup_protection_does_not_mask_genuine_break_migration` | `long_source_tracked := false` → `:= long_source_tracked_now` | literal → computed |
| 14 | `test_source_lock_decouples_setup_source_from_live_active_ranking` | `bool long_locked_source_alive_now = false` → destructured return | refactored to function |
| 15 | `test_source_upgrade_is_explicit_and_quality_gated` | `bool prev_locked_source_alive = false` → destructured return | refactored to function |
| 16 | `test_script_text_is_english_only_for_known_long_lifecycle_regressions` | `fvg_source_upgrade_ok` → `helper_fvg_source_upgrade_ok` | variable renamed |
| 17 | `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain` | `ob_source_upgrade_ok` → `helper_ob_source_upgrade_ok` | variable renamed |
| 18 | `test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks` | `bool long_locked_source_alive_now = false` → destructured return | refactored to function |
| 19 | `test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation` | `source_display` string pattern changed | code refactored |
| 20 | `test_display_and_status_text_are_extracted_into_helpers` | `freshness_text := 'confirm stale'` gone | text evolved |
| 21 | `test_confirm_and_ready_gate_logic_is_extracted_into_helpers` | `zone_quality_text := 'crowded'` gone | text evolved |
| 22 | `test_setup_text_and_visual_state_are_extracted_into_helpers` | `resolve_long_state_code` call param count changed | function signature evolved |
| 23 | `test_watchlist_alert_level_follows_active_zone_preference` | `float long_watchlist_alert_level = na` → function param | refactored to function param |
| 24 | `test_visual_text_dashboard_and_colors_are_extracted_into_helpers` | `resolve_long_visual_text` definition gone | function removed/renamed |
| 25 | `test_dashboard_long_zone_summary_uses_shared_zone_text_helper` | zone_text format string changed | code refactored |
| 26 | `test_arm_setup_resolution_is_extracted_into_helpers` | arm_source_kind comparison pattern changed | code refactored |
| 27 | `test_long_alert_helpers_cover_close_safe_events_and_message_composition` | `bool long_arm_close_safe = false` gone | code refactored |
| 28 | `test_intrabar_ready_and_watchlist_events_are_debounced_and_latched` | `bool can_draw_reclaim_marker = false` gone | code refactored |
| 29 | `test_extracted_helpers_are_defined_before_first_call` | `compute_overhead_context() =>` not found | function removed/renamed |
| 30 | `test_extracted_helpers_reference_only_previously_declared_globals` | `compute_overhead_context() =>` not found | function removed/renamed |

---

## Recommended Next Steps

1. **Fix the 3 split-caused failures first** (small, surgical):
   - Add `_read_profile_engine_source()` and `_read_utils_source()` readers
   - Redirect the 3 affected assertions to the correct library source

2. **Batch-update the 30 pre-existing failures** in a separate pass:
   - Group by evolution kind (variable renames, literal→computed, function removed, etc.)
   - Update assertions to match current Core Engine code
   - Consider deleting tests whose contract is no longer relevant

3. **Commit the recovery-pass changes** once the 3 split-caused fixes are applied.
