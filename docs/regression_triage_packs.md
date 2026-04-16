# Regression Triage Packs

Reconciled on HEAD: `5f7ec4fe2a39d45226b949a3f5c5602cc38417b7` (2026-04-16)
Expected remote HEAD from task: `5f7ec4fe2a39d45226b949a3f5c5602cc38417b7`

## Repro Commands

Executed exactly on `main` for the batch-2 validation pass:

- `python -m pytest tests/test_smc_long_dip_regressions.py -v --tb=line`
- `python -m pytest tests/test_smc_core_engine_split.py -v`

The full `-k smc` selection was **not** rerun in this batch. The last documented pre-batch snapshot remains available below for historical context only.

## Pytest Snapshot (Reproduced)

- Long-dip regression file: `52 passed, 17 failed, 0 skipped, 0 errors`
- Split suite: `21 passed, 0 failed, 0 skipped, 0 errors`
- Full SMC selection (`-k smc`): not rerun after batch-2; last documented pre-batch snapshot was `1974 passed, 24 failed, 4 skipped, 0 errors, 2716 deselected`

## Reconciliation Notes (30 vs 17)

The previous version of this document captured a historical baseline of **30 failing tests** in `tests/test_smc_long_dip_regressions.py`.

Current reproduced state is **17 failing tests** in that same file because **13 entries are fixed** and now green:

- #2 `test_signal_and_long_state_contract_are_declared_for_safe_refactors`
- #3 `test_backing_zone_identity_and_touch_count_persist_after_arm`
- #4 `test_invalidation_path_records_specific_reason_and_clears_setup_state`
- #5 `test_indicator_resource_caps_match_runtime_history_behavior`
- #13 `test_cleanup_protection_does_not_mask_genuine_break_migration`
- #14 `test_source_lock_decouples_setup_source_from_live_active_ranking`
- #15 `test_source_upgrade_is_explicit_and_quality_gated`
- #16 `test_script_text_is_english_only_for_known_long_lifecycle_regressions`
- #17 `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain`
- #18 `test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks`
- #19 `test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation`
- #20 `test_display_and_status_text_are_extracted_into_helpers`
- #26 `test_arm_setup_resolution_is_extracted_into_helpers`

Fix evidence:

- Batch 1: `fbe44e17` (`fix(tests): resolve batch-1 regression failures (signature changes)`)
- Batch 2: `5f7ec4fe` (`fix(tests): resolve batch-2 regression failures (state-resolution tuples)`)

Why other artifacts previously mentioned 23 while another run showed 24 failures:

- `23` referred to failures in `tests/test_smc_long_dip_regressions.py` before the batch-2 fix set landed.
- `24` in the last full `-k smc` run came from those 23 plus one additional failure outside this file:
  - `tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus`
- No new full-suite count is claimed here because that broader run was not repeated after batch-2.

## Vollständige 30er-Tabelle (mit Status)

| # | Testname | Status | Evidenz/Kommentar |
|---|----------|--------|-------------------|
| 1 | `test_refactored_helpers_preserve_dependency_order` | OPEN | weiterhin failing auf HEAD |
| 2 | `test_signal_and_long_state_contract_are_declared_for_safe_refactors` | [FIXED] | gruen seit `fbe44e17` |
| 3 | `test_backing_zone_identity_and_touch_count_persist_after_arm` | [FIXED] | gruen seit `5f7ec4fe` |
| 4 | `test_invalidation_path_records_specific_reason_and_clears_setup_state` | [FIXED] | gruen seit `5f7ec4fe` |
| 5 | `test_indicator_resource_caps_match_runtime_history_behavior` | [FIXED] | gruen seit `fbe44e17` |
| 6 | `test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods` | OPEN | weiterhin failing auf HEAD |
| 7 | `test_invalidated_alert_has_single_preset_definition_without_failed_alias` | OPEN | weiterhin failing auf HEAD |
| 8 | `test_structure_signal_derivations_use_explicit_block_logic` | OPEN | weiterhin failing auf HEAD |
| 9 | `test_armed_stage_can_be_optionally_tightened` | OPEN | weiterhin failing auf HEAD |
| 10 | `test_user_presets_and_performance_modes_drive_effective_runtime_layers` | OPEN | weiterhin failing auf HEAD |
| 11 | `test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard` | OPEN | weiterhin failing auf HEAD |
| 12 | `test_clean_tier_is_renamed_as_a_quality_diagnostic` | OPEN | weiterhin failing auf HEAD |
| 13 | `test_cleanup_protection_does_not_mask_genuine_break_migration` | [FIXED] | gruen seit `5f7ec4fe` |
| 14 | `test_source_lock_decouples_setup_source_from_live_active_ranking` | [FIXED] | gruen seit `fbe44e17` |
| 15 | `test_source_upgrade_is_explicit_and_quality_gated` | [FIXED] | gruen seit `fbe44e17` |
| 16 | `test_script_text_is_english_only_for_known_long_lifecycle_regressions` | [FIXED] | gruen seit `fbe44e17` |
| 17 | `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain` | [FIXED] | gruen seit `fbe44e17` |
| 18 | `test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks` | [FIXED] | gruen seit `5f7ec4fe` |
| 19 | `test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation` | [FIXED] | gruen seit `5f7ec4fe` |
| 20 | `test_display_and_status_text_are_extracted_into_helpers` | [FIXED] | gruen seit `5f7ec4fe` |
| 21 | `test_confirm_and_ready_gate_logic_is_extracted_into_helpers` | OPEN | weiterhin failing auf HEAD |
| 22 | `test_setup_text_and_visual_state_are_extracted_into_helpers` | OPEN | weiterhin failing auf HEAD |
| 23 | `test_watchlist_alert_level_follows_active_zone_preference` | OPEN | weiterhin failing auf HEAD |
| 24 | `test_visual_text_dashboard_and_colors_are_extracted_into_helpers` | OPEN | weiterhin failing auf HEAD |
| 25 | `test_dashboard_long_zone_summary_uses_shared_zone_text_helper` | OPEN | weiterhin failing auf HEAD |
| 26 | `test_arm_setup_resolution_is_extracted_into_helpers` | [FIXED] | gruen seit `fbe44e17` |
| 27 | `test_long_alert_helpers_cover_close_safe_events_and_message_composition` | OPEN | weiterhin failing auf HEAD |
| 28 | `test_intrabar_ready_and_watchlist_events_are_debounced_and_latched` | OPEN | weiterhin failing auf HEAD |
| 29 | `test_extracted_helpers_are_defined_before_first_call` | OPEN | weiterhin failing auf HEAD |
| 30 | `test_extracted_helpers_reference_only_previously_declared_globals` | OPEN | weiterhin failing auf HEAD |

## Reale offene Long-Dip-Failures auf HEAD (17)

1. `tests/test_smc_long_dip_regressions.py::test_refactored_helpers_preserve_dependency_order`
2. `tests/test_smc_long_dip_regressions.py::test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods`
3. `tests/test_smc_long_dip_regressions.py::test_invalidated_alert_has_single_preset_definition_without_failed_alias`
4. `tests/test_smc_long_dip_regressions.py::test_structure_signal_derivations_use_explicit_block_logic`
5. `tests/test_smc_long_dip_regressions.py::test_armed_stage_can_be_optionally_tightened`
6. `tests/test_smc_long_dip_regressions.py::test_user_presets_and_performance_modes_drive_effective_runtime_layers`
7. `tests/test_smc_long_dip_regressions.py::test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard`
8. `tests/test_smc_long_dip_regressions.py::test_clean_tier_is_renamed_as_a_quality_diagnostic`
9. `tests/test_smc_long_dip_regressions.py::test_confirm_and_ready_gate_logic_is_extracted_into_helpers`
10. `tests/test_smc_long_dip_regressions.py::test_setup_text_and_visual_state_are_extracted_into_helpers`
11. `tests/test_smc_long_dip_regressions.py::test_watchlist_alert_level_follows_active_zone_preference`
12. `tests/test_smc_long_dip_regressions.py::test_visual_text_dashboard_and_colors_are_extracted_into_helpers`
13. `tests/test_smc_long_dip_regressions.py::test_dashboard_long_zone_summary_uses_shared_zone_text_helper`
14. `tests/test_smc_long_dip_regressions.py::test_long_alert_helpers_cover_close_safe_events_and_message_composition`
15. `tests/test_smc_long_dip_regressions.py::test_intrabar_ready_and_watchlist_events_are_debounced_and_latched`
16. `tests/test_smc_long_dip_regressions.py::test_extracted_helpers_are_defined_before_first_call`
17. `tests/test_smc_long_dip_regressions.py::test_extracted_helpers_reference_only_previously_declared_globals`

## Reale Failure außerhalb der 30er-Packs (letzter Full SMC Run)

Diese Failure war in der alten 30er-Tabelle nicht enthalten und war real im letzten dokumentierten `-k smc` Lauf. Der Full Run wurde nach Batch 2 nicht erneut ausgefuehrt:

- `tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus`

## Delta Summary

- Historisch dokumentiert: `30` long-dip Failures
- Auf HEAD reproduziert (long-dip, Batch 2): `17` long-dip Failures
- Bereits gefixt in den 30er-Packs: `13`
- Split suite auf HEAD: `21 passed, 0 failed`
- Full `-k smc` Failures: nach Batch 2 nicht neu reproduziert; letzter dokumentierter Stand war `24` (=`23` long-dip + `1` legacy-governance)
