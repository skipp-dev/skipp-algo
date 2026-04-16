# Regression Triage Packs

Reconciled on HEAD: `efbf7ecef1c100df3a4a27737eb7d6d18d192638` (2026-04-16)
Expected remote HEAD from task: `efbf7ecef1c100df3a4a27737eb7d6d18d192638`

## Repro Commands

Executed exactly on `main` after `git fetch origin && git checkout main && git pull origin main`:

- `python -m pytest tests/ -k "smc" --tb=line -q 2>&1 | tee /tmp/pytest_smc_full.txt`
- `python -m pytest tests/test_smc_long_dip_regressions.py -q --tb=line 2>&1 | tee /tmp/pytest_long_dip.txt`
- `python -m pytest tests/test_smc_core_engine_split.py -q --tb=line 2>&1 | tee /tmp/pytest_split.txt`

## Pytest Snapshot (Reproduced)

- Full SMC selection (`-k smc`): `1974 passed, 24 failed, 4 skipped, 0 errors, 2716 deselected`
- Long-dip regression file: `46 passed, 23 failed, 0 skipped, 0 errors`
- Split suite: `21 passed, 0 failed, 0 skipped, 0 errors`

## Reconciliation Notes (30 vs 23)

The previous version of this document captured a historical baseline of **30 failing tests** in `tests/test_smc_long_dip_regressions.py`.

Current reproduced state is **23 failing tests** in that same file because **7 entries are fixed** and now green:

- #2 `test_signal_and_long_state_contract_are_declared_for_safe_refactors`
- #5 `test_indicator_resource_caps_match_runtime_history_behavior`
- #14 `test_source_lock_decouples_setup_source_from_live_active_ranking`
- #15 `test_source_upgrade_is_explicit_and_quality_gated`
- #16 `test_script_text_is_english_only_for_known_long_lifecycle_regressions`
- #17 `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain`
- #26 `test_arm_setup_resolution_is_extracted_into_helpers`

Fix evidence for all seven: `fbe44e17` (`fix(tests): resolve batch-1 regression failures (signature changes)`).

Why other artifacts mentioned 23 while another run showed 24 failures:

- `23` refers to failures in `tests/test_smc_long_dip_regressions.py`.
- `24` in full `-k smc` run comes from those 23 plus one additional failure outside this file:
  - `tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus`

## Vollständige 30er-Tabelle (mit Status)

| # | Testname | Status | Evidenz/Kommentar |
|---|----------|--------|-------------------|
| 1 | `test_refactored_helpers_preserve_dependency_order` | OPEN | weiterhin failing auf HEAD |
| 2 | `test_signal_and_long_state_contract_are_declared_for_safe_refactors` | [FIXED] | gruen seit `fbe44e17` |
| 3 | `test_backing_zone_identity_and_touch_count_persist_after_arm` | OPEN | weiterhin failing auf HEAD |
| 4 | `test_invalidation_path_records_specific_reason_and_clears_setup_state` | OPEN | weiterhin failing auf HEAD |
| 5 | `test_indicator_resource_caps_match_runtime_history_behavior` | [FIXED] | gruen seit `fbe44e17` |
| 6 | `test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods` | OPEN | weiterhin failing auf HEAD |
| 7 | `test_invalidated_alert_has_single_preset_definition_without_failed_alias` | OPEN | weiterhin failing auf HEAD |
| 8 | `test_structure_signal_derivations_use_explicit_block_logic` | OPEN | weiterhin failing auf HEAD |
| 9 | `test_armed_stage_can_be_optionally_tightened` | OPEN | weiterhin failing auf HEAD |
| 10 | `test_user_presets_and_performance_modes_drive_effective_runtime_layers` | OPEN | weiterhin failing auf HEAD |
| 11 | `test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard` | OPEN | weiterhin failing auf HEAD |
| 12 | `test_clean_tier_is_renamed_as_a_quality_diagnostic` | OPEN | weiterhin failing auf HEAD |
| 13 | `test_cleanup_protection_does_not_mask_genuine_break_migration` | OPEN | weiterhin failing auf HEAD |
| 14 | `test_source_lock_decouples_setup_source_from_live_active_ranking` | [FIXED] | gruen seit `fbe44e17` |
| 15 | `test_source_upgrade_is_explicit_and_quality_gated` | [FIXED] | gruen seit `fbe44e17` |
| 16 | `test_script_text_is_english_only_for_known_long_lifecycle_regressions` | [FIXED] | gruen seit `fbe44e17` |
| 17 | `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain` | [FIXED] | gruen seit `fbe44e17` |
| 18 | `test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks` | OPEN | weiterhin failing auf HEAD |
| 19 | `test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation` | OPEN | weiterhin failing auf HEAD |
| 20 | `test_display_and_status_text_are_extracted_into_helpers` | OPEN | weiterhin failing auf HEAD |
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

## Reale offene Long-Dip-Failures auf HEAD (23)

1. `tests/test_smc_long_dip_regressions.py::test_refactored_helpers_preserve_dependency_order`
2. `tests/test_smc_long_dip_regressions.py::test_backing_zone_identity_and_touch_count_persist_after_arm`
3. `tests/test_smc_long_dip_regressions.py::test_invalidation_path_records_specific_reason_and_clears_setup_state`
4. `tests/test_smc_long_dip_regressions.py::test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods`
5. `tests/test_smc_long_dip_regressions.py::test_invalidated_alert_has_single_preset_definition_without_failed_alias`
6. `tests/test_smc_long_dip_regressions.py::test_structure_signal_derivations_use_explicit_block_logic`
7. `tests/test_smc_long_dip_regressions.py::test_armed_stage_can_be_optionally_tightened`
8. `tests/test_smc_long_dip_regressions.py::test_user_presets_and_performance_modes_drive_effective_runtime_layers`
9. `tests/test_smc_long_dip_regressions.py::test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard`
10. `tests/test_smc_long_dip_regressions.py::test_clean_tier_is_renamed_as_a_quality_diagnostic`
11. `tests/test_smc_long_dip_regressions.py::test_cleanup_protection_does_not_mask_genuine_break_migration`
12. `tests/test_smc_long_dip_regressions.py::test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks`
13. `tests/test_smc_long_dip_regressions.py::test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation`
14. `tests/test_smc_long_dip_regressions.py::test_display_and_status_text_are_extracted_into_helpers`
15. `tests/test_smc_long_dip_regressions.py::test_confirm_and_ready_gate_logic_is_extracted_into_helpers`
16. `tests/test_smc_long_dip_regressions.py::test_setup_text_and_visual_state_are_extracted_into_helpers`
17. `tests/test_smc_long_dip_regressions.py::test_watchlist_alert_level_follows_active_zone_preference`
18. `tests/test_smc_long_dip_regressions.py::test_visual_text_dashboard_and_colors_are_extracted_into_helpers`
19. `tests/test_smc_long_dip_regressions.py::test_dashboard_long_zone_summary_uses_shared_zone_text_helper`
20. `tests/test_smc_long_dip_regressions.py::test_long_alert_helpers_cover_close_safe_events_and_message_composition`
21. `tests/test_smc_long_dip_regressions.py::test_intrabar_ready_and_watchlist_events_are_debounced_and_latched`
22. `tests/test_smc_long_dip_regressions.py::test_extracted_helpers_are_defined_before_first_call`
23. `tests/test_smc_long_dip_regressions.py::test_extracted_helpers_reference_only_previously_declared_globals`

## Reale Failure außerhalb der 30er-Packs (im Full SMC Run)

Diese Failure war in der alten 30er-Tabelle nicht enthalten, ist aber real im aktuellen `-k smc` Lauf:

- `tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus`

## Delta Summary

- Historisch dokumentiert: `30` long-dip Failures
- Auf HEAD reproduziert (long-dip): `23` long-dip Failures
- Bereits gefixt in den 30er-Packs: `7`
- Full `-k smc` Failures: `24` (=`23` long-dip + `1` legacy-governance)
