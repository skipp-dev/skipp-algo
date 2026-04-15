# Regression Triage Packs

**Baseline:** `778fbb64` (21 Split-Tests + 39 Regressionstests grün)
**Quelle:** `tests/test_smc_long_dip_regressions.py` — 39 bestanden, **30 fehlgeschlagen**
**Alle 30 sind vorbestehend** — keiner durch WP-SPLIT1–4 verursacht.
**Methode:** Statische Assertions gegen `SMC_Core_Engine.pine` (5 474 LOC) verifiziert.

---

## Vollständige Fehlertabelle

| # | Testname | Fehlertyp | Betroffenes Modul | Ursache | Priorität |
|---|----------|-----------|-------------------|---------|-----------|
| 1 | `test_refactored_helpers_preserve_dependency_order` | fn-removed | Helper-Dependency | `db_trend_text(` existiert nicht mehr | P1 |
| 2 | `test_signal_and_long_state_contract_are_declared_for_safe_refactors` | metadata-drift | Metadata | Indicator-Titel `"SMC++"` entfernt | P3 |
| 3 | `test_backing_zone_identity_and_touch_count_persist_after_arm` | refactored-code | Source-Lifecycle | `long_arm_locked_source_id = resolve_long_zone_id(` Signatur geändert | P1 |
| 4 | `test_invalidation_path_records_specific_reason_and_clears_setup_state` | refactored-code | Source-Lifecycle | `invalidation_reason := long_validation_source_text + ' source invalidated'` Body umgeschrieben | P1 |
| 5 | `test_indicator_resource_caps_match_runtime_history_behavior` | metadata-drift | Metadata | `max_labels_count = 500` → anderer Wert | P3 |
| 6 | `test_tuple_returned_ob_and_fvg_buffers_use_function_call_syntax_for_custom_methods` | fn-removed | Zone-Management | Draw-Call-Signatur grundlegend geändert | P1 |
| 7 | `test_invalidated_alert_has_single_preset_definition_without_failed_alias` | alert-overhaul | Alert-System | 0 Preset-Definitionen gefunden (erwartet 1) | P2 |
| 8 | `test_structure_signal_derivations_use_explicit_block_logic` | refactored-code | Structure-Signal | `show_chart_swing_levels := true` entfernt | P1 |
| 9 | `test_armed_stage_can_be_optionally_tightened` | literal-to-computed | Gate-Logic | `bool armed_prequality_ok = true` → computed | P2 |
| 10 | `test_user_presets_and_performance_modes_drive_effective_runtime_layers` | text-evolved | Inputs | Tooltip-Text geändert | P3 |
| 11 | `test_debug_telemetry_package_wires_inputs_helpers_logs_and_dashboard` | refactored-code | Debug-Telemetry | `string long_debug_mode_suffix = ' Compact'` entfernt | P1 |
| 12 | `test_clean_tier_is_renamed_as_a_quality_diagnostic` | literal-to-computed | Gate-Logic | `bool long_quality_clean_tier = false` → computed | P2 |
| 13 | `test_cleanup_protection_does_not_mask_genuine_break_migration` | literal-to-computed | Source-Lifecycle | `long_source_tracked := false` → `:= long_source_tracked_now` | P2 |
| 14 | `test_source_lock_decouples_setup_source_from_live_active_ranking` | renamed-var | Source-Lifecycle | `bool prev_locked_source_alive = false` → umbenannt | P2 |
| 15 | `test_source_upgrade_is_explicit_and_quality_gated` | renamed-var | Source-Lifecycle | `bool prev_locked_source_alive = false` → umbenannt | P2 |
| 16 | `test_script_text_is_english_only_for_known_long_lifecycle_regressions` | renamed-var | Display-Text | `fvg_source_upgrade_ok` → `helper_fvg_source_upgrade_ok` | P2 |
| 17 | `test_source_upgrade_stays_blocked_without_opt_in_or_quality_gain` | renamed-var | Source-Lifecycle | `ob_source_upgrade_ok` → `helper_ob_source_upgrade_ok` | P2 |
| 18 | `test_upgrade_rebinds_final_locked_source_before_alive_and_broken_checks` | literal-to-computed | Source-Lifecycle | `bool long_locked_source_alive_now = false` → computed | P2 |
| 19 | `test_entry_origin_and_validation_source_are_separated_for_display_and_invalidation` | refactored-code | Source-Lifecycle | `source_display := ... + ' -> ' + ...` Body geändert | P1 |
| 20 | `test_display_and_status_text_are_extracted_into_helpers` | text-evolved | Display-Text | `freshness_text := 'confirm stale'` String geändert | P3 |
| 21 | `test_confirm_and_ready_gate_logic_is_extracted_into_helpers` | text-evolved | Gate-Logic | `zone_quality_text := 'crowded'` String geändert | P3 |
| 22 | `test_setup_text_and_visual_state_are_extracted_into_helpers` | refactored-code | Display-Text | `resolve_long_state_code(` Parameteranzahl geändert | P1 |
| 23 | `test_watchlist_alert_level_follows_active_zone_preference` | literal-to-computed | Alert-System | `float long_watchlist_alert_level = na` → Funktionsparameter | P2 |
| 24 | `test_visual_text_dashboard_and_colors_are_extracted_into_helpers` | fn-removed | Display-Text | `resolve_long_visual_text(` existiert nicht mehr | P1 |
| 25 | `test_dashboard_long_zone_summary_uses_shared_zone_text_helper` | refactored-code | Display-Text | `compose_zone_summary_text(` Body-Assertions schlagen fehl | P1 |
| 26 | `test_arm_setup_resolution_is_extracted_into_helpers` | renamed-var | Source-Lifecycle | `int long_arm_locked_source_id = resolve_long_zone_id(` umbenannt | P2 |
| 27 | `test_long_alert_helpers_cover_close_safe_events_and_message_composition` | alert-overhaul | Alert-System | `compose_long_invalidated_alert` → `cr.compose_long_invalidated_alert_detail` | P2 |
| 28 | `test_intrabar_ready_and_watchlist_events_are_debounced_and_latched` | alert-overhaul | Alert-System | `bool can_draw_reclaim_marker = false` entfernt | P2 |
| 29 | `test_extracted_helpers_are_defined_before_first_call` | fn-removed | Helper-Dependency | `compute_overhead_context() =>` existiert nicht mehr | P1 |
| 30 | `test_extracted_helpers_reference_only_previously_declared_globals` | fn-removed | Helper-Dependency | `compute_overhead_context() =>` existiert nicht mehr | P1 |

---

## Gruppierung nach Ursache

### refactored-code — 7 Tests (P1)

Funktions-Bodies oder Call-Sites grundlegend umgeschrieben; Assertions müssen an neuen Code angepasst werden.

| Tests | Modul |
|-------|-------|
| #3, #4, #19 | Source-Lifecycle |
| #8 | Structure-Signal |
| #11 | Debug-Telemetry |
| #22, #25 | Display-Text |

### fn-removed — 5 Tests (P1)

Helper-Funktionen entfernt, umbenannt oder zusammengeführt; Tests ggf. obsolet oder auf Nachfolger umleiten.

| Tests | Modul |
|-------|-------|
| #1, #29, #30 | Helper-Dependency |
| #6 | Zone-Management |
| #24 | Display-Text |

### renamed-var — 5 Tests (P2)

Variablen umbenannt (z. B. `helper_`-Prefix); mechanischer Search-Replace.

| Tests | Modul |
|-------|-------|
| #14, #15, #17, #26 | Source-Lifecycle |
| #16 | Display-Text |

### literal-to-computed — 5 Tests (P2)

Literale Initialisierung (`= true`, `= false`, `= na`) durch berechnete Ausdrücke ersetzt.

| Tests | Modul |
|-------|-------|
| #13, #18 | Source-Lifecycle |
| #9, #12 | Gate-Logic |
| #23 | Alert-System |

### alert-overhaul — 3 Tests (P2)

Alert-Helper verlagert oder umstrukturiert.

| Tests | Modul |
|-------|-------|
| #7, #27, #28 | Alert-System |

### text-evolved — 3 Tests (P3)

String-Literale in Helper-Bodies geändert; Assertions an neue Texte anpassen.

| Tests | Modul |
|-------|-------|
| #10 | Inputs |
| #20 | Display-Text |
| #21 | Gate-Logic |

### metadata-drift — 2 Tests (P3)

Indicator-Metadaten geändert (Titel, Ressourcen-Limits); triviale Assertion-Updates.

| Tests | Modul |
|-------|-------|
| #2, #5 | Metadata |

---

## Empfohlene Fix-Reihenfolge

| Reihenfolge | Pack | Tests | Anzahl | Begründung |
|------------:|------|-------|-------:|------------|
| 1 | **Pack A — Metadata** | #2, #5 | 2 | Trivial, null Risiko, Aufwärm-Pack |
| 2 | **Pack B — Renamed Vars** | #14, #15, #16, #17, #26 | 5 | Mechanischer Search-Replace, geringes Risiko |
| 3 | **Pack C — Literal→Computed** | #9, #12, #13, #18, #23 | 5 | Assertions auf berechnete Form umstellen |
| 4 | **Pack D — Text & Strings** | #10, #20, #21 | 3 | String-Erwartungen aktualisieren |
| 5 | **Pack E — Alert-System** | #7, #27, #28 | 3 | Modul-Prefixe und Preset-Logik updaten |
| 6 | **Pack F — Refactored Code** | #3, #4, #8, #11, #19, #22, #25 | 7 | Assertions an neue Bodies anpassen, größter Pack |
| 7 | **Pack G — Removed Functions** | #1, #6, #24, #29, #30 | 5 | Entscheidung: Tests löschen oder auf Nachfolger umleiten |

**Gesamtaufwand:** 30 Fixes in `tests/test_smc_long_dip_regressions.py`. Kein Produktionscode betroffen.

---

## Prioritäts-Zusammenfassung

| Priorität | Anzahl | Packs |
|-----------|-------:|-------|
| **P1** — Analyse erforderlich | 12 | Pack F (7) + Pack G (5) |
| **P2** — Mechanische Fixes | 13 | Pack B (5) + Pack C (5) + Pack E (3) |
| **P3** — Triviale Updates | 5 | Pack A (2) + Pack D (3) |
