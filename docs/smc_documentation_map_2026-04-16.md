# SMC Documentation Map

Stand: 2026-04-16  
Branch: `main`  
Autorität: Canonical-Docs-Sweep nach Feature-Freeze-Beginn

---

## Start Here — Reihenfolge für neue Maintainer

| # | Dokument | Zweck |
|---|----------|-------|
| 1 | [SMC_PRODUCT_IDENTITY.md](SMC_PRODUCT_IDENTITY.md) | Was die Suite ist und nicht ist |
| 2 | [SMC_GETTING_STARTED.md](SMC_GETTING_STARTED.md) | Ersteinrichtung TradingView, erste Signale |
| 3 | [FEATURE_FREEZE.md](FEATURE_FREEZE.md) | Aktuell geltende Änderungssperre (15.04.–15.05.2026) |
| 4 | [smc_final_status_review_2026-04-16.md](smc_final_status_review_2026-04-16.md) | Systemweiter Statusreview — was bewiesen ist |
| 5 | [v5_5b_architecture.md](v5_5b_architecture.md) | Kanonische Zielarchitektur |
| 6 | [smc-mainline-setup-runbook.md](smc-mainline-setup-runbook.md) | Lokales Repo aufsetzen, Build, Tests |
| 7 | [TRADINGVIEW_STRATEGY_GUIDE.md](TRADINGVIEW_STRATEGY_GUIDE.md) | SMC_Long_Strategy Execution Guide |
| 8 | [SMC_Dashboard_Long_Dip_Guide_EN.md](SMC_Dashboard_Long_Dip_Guide_EN.md) | Dashboard-Bedienungsanleitung (EN) |

---

## Kanonische Dokumentation (Canonical Current)

### Architektur & Verträge

| Dokument | Inhalt |
|----------|--------|
| [v5_5b_architecture.md](v5_5b_architecture.md) | Kanonische Zielarchitektur v5.5b |
| [v5_5_lean_contract.md](v5_5_lean_contract.md) | Lean Contract (Schema 2.0.0) |
| [structure_contract_architecture.md](structure_contract_architecture.md) | Structure Contract Normalization |
| [adr/0001-structure-contract-normalization.md](adr/0001-structure-contract-normalization.md) | ADR: Structure Contract |
| [ADR-001-open-prep-integration-boundary.md](ADR-001-open-prep-integration-boundary.md) | ADR: Open Prep Boundary |
| [smc-snapshot-target-architecture.md](smc-snapshot-target-architecture.md) | Snapshot / TradingView Bridge Zielarchitektur |
| [schema_versioning.md](schema_versioning.md) | Schema-Versioning Policy |
| [NO_SHADOW_LOGIC_POLICY.md](NO_SHADOW_LOGIC_POLICY.md) | No-Shadow-Logic Regel |
| [ARTIFACT_STRATEGY.md](ARTIFACT_STRATEGY.md) | Artifact Strategie v5.5b |

### Produkt & Onboarding

| Dokument | Inhalt |
|----------|--------|
| [SMC_PRODUCT_IDENTITY.md](SMC_PRODUCT_IDENTITY.md) | Produktidentität — One-Liner, Zielgruppe |
| [SMC_GETTING_STARTED.md](SMC_GETTING_STARTED.md) | Getting Started Guide |
| [smc-lite-pro-product-cut.md](smc-lite-pro-product-cut.md) | Lite vs. Pro Product Cut |
| [SMC_Dashboard_Long_Dip_Guide_DE.md](SMC_Dashboard_Long_Dip_Guide_DE.md) | Dashboard Guide (DE) |
| [SMC_Dashboard_Long_Dip_Guide_EN.md](SMC_Dashboard_Long_Dip_Guide_EN.md) | Dashboard Guide (EN) |
| [TRADINGVIEW_STRATEGY_GUIDE.md](TRADINGVIEW_STRATEGY_GUIDE.md) | SMC Execution / Strategy Guide |

### Governance & Release

| Dokument | Inhalt |
|----------|--------|
| [FEATURE_FREEZE.md](FEATURE_FREEZE.md) | Feature Freeze (aktiv 15.04.–15.05.2026) |
| [smc_branch_protection_and_release_gates.md](smc_branch_protection_and_release_gates.md) | Branch Protection & Release Gates |
| [smc_release_gate_validation_2026-04-16.md](smc_release_gate_validation_2026-04-16.md) | Validierung der 3 harten Measurement-Gates |
| [MEASUREMENT_LANE.md](MEASUREMENT_LANE.md) | Measurement Lane Beschreibung |
| [MEASUREMENT_CALIBRATION.md](MEASUREMENT_CALIBRATION.md) | Calibration Policy und Thresholds |

### TradingView Publish & Validation

| Dokument | Inhalt |
|----------|--------|
| [tradingview-manual-publish-checklist.md](tradingview-manual-publish-checklist.md) | Publish-Checkliste (aktuell) |
| [tradingview-manual-publish-evidence-2026-04-16.md](tradingview-manual-publish-evidence-2026-04-16.md) | Publish-Evidenz aktuell |
| [tradingview-manual-validation-runbook.md](tradingview-manual-validation-runbook.md) | Manuelle Validierung (DE) |
| [tradingview-manual-validation-runbook_EN.md](tradingview-manual-validation-runbook_EN.md) | Manuelle Validierung (EN) |
| [tradingview-manual-validation-report-template.md](tradingview-manual-validation-report-template.md) | Report Template (DE) |
| [tradingview-manual-validation-report-template_EN.md](tradingview-manual-validation-report-template_EN.md) | Report Template (EN) |
| [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md) | Micro Library Publish Runbook |
| [tradingview-status-model.md](tradingview-status-model.md) | Preflight Status Model |
| [tradingview-auth-modes.md](tradingview-auth-modes.md) | Auth / Session Model |
| [tradingview-runtime-validation.md](tradingview-runtime-validation.md) | Runtime Validation Layer |
| [tradingview-validation-checklist.md](tradingview-validation-checklist.md) | Validation Checklist |
| [split_library_compile_readiness.md](split_library_compile_readiness.md) | Split-Library Compile Readiness |

### Microstructure UI

| Dokument | Inhalt |
|----------|--------|
| [smc-microstructure-ui-architecture.md](smc-microstructure-ui-architecture.md) | UI-Architektur |
| [smc-microstructure-ui-operator-runbook.md](smc-microstructure-ui-operator-runbook.md) | Operator Runbook |
| [smc-microstructure-ui-audit.md](smc-microstructure-ui-audit.md) | UI Audit |

### Bus-Architektur

| Dokument | Inhalt |
|----------|--------|
| [smc-bus-v2-audit.md](smc-bus-v2-audit.md) | Bus v2 Audit |
| [smc-bus-target-matrix.md](smc-bus-target-matrix.md) | Bus Target Matrix |
| [smc-bus-roadmap.md](smc-bus-roadmap.md) | Bus Roadmap |

### Review & Status (aktuell)

| Dokument | Inhalt |
|----------|--------|
| [smc_final_status_review_2026-04-16.md](smc_final_status_review_2026-04-16.md) | Systemweiter Endstatus |
| [smc-owner-review-2026-04-14.md](smc-owner-review-2026-04-14.md) | Owner Review |
| [smc-copilot-work-packages-2026-04-14.md](smc-copilot-work-packages-2026-04-14.md) | Work Packages aus Owner Review |
| [smc-residual-program-completion.md](smc-residual-program-completion.md) | Residual Program — abgeschlossen |
| [smc-validation-status.md](smc-validation-status.md) | Validation Status |
| [regression_triage_packs.md](regression_triage_packs.md) | Regression Triage |

### Operational Runbooks

| Dokument | Inhalt |
|----------|--------|
| [smc-mainline-setup-runbook.md](smc-mainline-setup-runbook.md) | Mainline Setup |
| [smc_local_first_productive_run.md](smc_local_first_productive_run.md) | Erster lokaler produktiver Lauf |
| [SMC_SMOKE_TEST_PROTOCOL.md](SMC_SMOKE_TEST_PROTOCOL.md) | Smoke Test Protocol |
| [runbook-degraded-mode.md](runbook-degraded-mode.md) | Degraded Mode Runbook |

### Databento / Open Prep (operativ)

| Dokument | Inhalt |
|----------|--------|
| [DATABENTO_VOLATILITY_SUITE.md](DATABENTO_VOLATILITY_SUITE.md) | Databento Suite Overview |
| [DATABENTO_STRUCTURE_FEATURES.md](DATABENTO_STRUCTURE_FEATURES.md) | Databento Structure Features |
| [DATABENTO_DECOMPOSITION_PLAN.md](DATABENTO_DECOMPOSITION_PLAN.md) | Databento Decomposition Plan |
| [OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md](OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md) | Open Prep Technische Referenz |
| [OPEN_PREP_OPS_QUICK_REFERENCE.md](OPEN_PREP_OPS_QUICK_REFERENCE.md) | Open Prep Ops Quick Reference |
| [OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md](OPEN_PREP_INCIDENT_RUNBOOK_ONEPAGE.md) | Open Prep Incident On-Call |
| [OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md](OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md) | Open Prep Incident Matrix |
| [OPEN_CHECKLIST.md](OPEN_CHECKLIST.md) | US-Open Execution Checklist |
| [API_BUDGET_CALCULATIONS.md](API_BUDGET_CALCULATIONS.md) | API Budget Calculations |
| [live-news-first-arrival.md](live-news-first-arrival.md) | Live News Architektur |
| [CLOSE_IMBALANCE_IMPLEMENTATION_BLUEPRINT.md](CLOSE_IMBALANCE_IMPLEMENTATION_BLUEPRINT.md) | Close Imbalance Blueprint |

### Pine Input Surface

| Dokument | Inhalt |
|----------|--------|
| [PINE_INPUT_SURFACE.md](PINE_INPUT_SURFACE.md) | Input Surface Reduction |
| [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md) | Runtime Budget Inventory |
| [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md) | Legacy Removal Plan |

---

## Historische Referenz (Historical Reference)

Diese Dokumente haben Audit-/Revisions-Wert, sind aber nicht mehr die
aktuelle Wahrheit. Nicht ändern, nicht löschen.

### Architektur-Evolution

| Dokument | Ersetzt durch / Kontext |
|----------|------------------------|
| [SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md](SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md) | Superseded by [v5_5b_architecture.md](v5_5b_architecture.md) |
| [v5_5a_lean_contract_refinement_en.md](v5_5a_lean_contract_refinement_en.md) | Superseded by v5.5b contract |
| [SMC_TARGET_ARCHITECTURE_REFERENCE_2026-03-26.md](SMC_TARGET_ARCHITECTURE_REFERENCE_2026-03-26.md) | Historischer Snapshot 2026-03-26, abgelöst durch v5.5b |
| [SMC_STRICT_DATA_LINEAGE_SUBSCRIPTION_AUDIT_2026-03-26.md](SMC_STRICT_DATA_LINEAGE_SUBSCRIPTION_AUDIT_2026-03-26.md) | Historischer Audit-Snapshot |
| `smc_unified_target_architecture_v5_5_de.md` (Root) | Superseded by [v5_5b_architecture.md](v5_5b_architecture.md) |
| [v4-enrichment-migration.md](v4-enrichment-migration.md) | Superseded by [v5-enrichment-architecture.md](v5-enrichment-architecture.md) |
| [v5-enrichment-architecture.md](v5-enrichment-architecture.md) | Historisch — v5.3 Enrichment Spec |

### Deep Reviews & Action Plans

| Dokument | Kontext |
|----------|---------|
| `smc_deep_review_v5.md` (Root) | Historischer externer Review v5 (2026-04-08) |
| `smc_deep_review_v7.md` (Root) | Historischer verifizierter Follow-up Review v7 (2026-04-12) |
| [smc_deep_review_v5_verified_action_plan.md](smc_deep_review_v5_verified_action_plan.md) | Verifizierter Action Plan zu v5 |
| [smc_deep_review_v6_verified_action_plan.md](smc_deep_review_v6_verified_action_plan.md) | Verifizierter Action Plan zu v6 |
| [smc_deep_review_v9_verified_action_plan.md](smc_deep_review_v9_verified_action_plan.md) | Verifizierter Action Plan zu v9 |
| [smc_deep_research_migration_plan_copilot.md](smc_deep_research_migration_plan_copilot.md) | Migrationsplan-Rest-Deltas post v5.5b |
| [deep-research-report.md](deep-research-report.md) | Externer Deep Research Report |
| [smc_review_remediation_plan.md](smc_review_remediation_plan.md) | Review & Remediation Plan |
| [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md) | Phase C Planning Note |

### Historische Projekt-Planung & Delivery

| Dokument | Kontext |
|----------|---------|
| [smc-product-rescue-playbook.md](smc-product-rescue-playbook.md) | Product Rescue Playbook (delivered) |
| [smc-tradingview-decision-first-prd.md](smc-tradingview-decision-first-prd.md) | UX PRD (draft) |
| [smc-tradingview-decision-first-backlog.md](smc-tradingview-decision-first-backlog.md) | UX Backlog (draft) |
| [smc-tradingview-first-release-ticketset.md](smc-tradingview-first-release-ticketset.md) | First Release Ticketset (released) |
| [smc-tradingview-first-ui-cut-implementation.md](smc-tradingview-first-ui-cut-implementation.md) | First UI Cut (implemented) |
| [smc-tradingview-r1-1-migration-and-operator-guide.md](smc-tradingview-r1-1-migration-and-operator-guide.md) | R1.1 Migration Guide (released) |
| [smc-tradingview-r1-2-ticketset.md](smc-tradingview-r1-2-ticketset.md) | R1.2 Ticketset (delivered) |
| [smc-tradingview-screen-spec.md](smc-tradingview-screen-spec.md) | Screen Spec (released) |
| [smc-module-pack-b-direct-cut-design.md](smc-module-pack-b-direct-cut-design.md) | Module Pack B Design |
| [smc-module-pack-b-plot-neutral-path.md](smc-module-pack-b-plot-neutral-path.md) | Module Pack B Plot Path |
| [smc_bundle_to_library_recovery_plan_2026-04-09.md](smc_bundle_to_library_recovery_plan_2026-04-09.md) | Bundle-to-Library Recovery (completed) |
| [smc_github_hosted_larger_runner_pilot.md](smc_github_hosted_larger_runner_pilot.md) | GitHub Runner Pilot (completed) |
| [smc-ingest-strategy.md](smc-ingest-strategy.md) | Ingest Strategy |
| [tradingview-split-remediation-plan.md](tradingview-split-remediation-plan.md) | Split Remediation Plan |
| [post_split_validation_report.md](post_split_validation_report.md) | Post-Split Validation Report |
| [smc-databento-change-note-2026-04-09.md](smc-databento-change-note-2026-04-09.md) | Databento Change Note |

### SkippALGO v6.x Legacy (pre-SMC)

| Dokument | Kontext |
|----------|---------|
| [SkippALGO_Deep_Technical_Documentation.md](SkippALGO_Deep_Technical_Documentation.md) | v6.1–v6.2 Deep Technical Doc |
| [SkippALGO_Deep_Technical_Documentation_v6.2.22.md](SkippALGO_Deep_Technical_Documentation_v6.2.22.md) | v6.2.22 Deep Technical Doc |
| [SkippALGO_Market_Structure.md](SkippALGO_Market_Structure.md) | v6.2 Market Structure |
| [SkippALGO_Roadmap_Enhancements.md](SkippALGO_Roadmap_Enhancements.md) | v6.x Roadmap |
| [SkippALGO_Tuning_Guide.md](SkippALGO_Tuning_Guide.md) | v6.x Tuning Guide |
| [SkippALGO_Kurzfassung_Fuer_Nutzer.md](SkippALGO_Kurzfassung_Fuer_Nutzer.md) | v6.x Kurzfassung DE |

### Historische CHANGELOGs & Updates

| Dokument | Kontext |
|----------|---------|
| [CHANGELOG_v6.2.md](CHANGELOG_v6.2.md) | v6.2 Changelog |
| [CHANGELOG_v6.2.7.md](CHANGELOG_v6.2.7.md) | v6.2.7 Changelog |
| [CHANGELOG_v6.2.11_improvements.md](CHANGELOG_v6.2.11_improvements.md) | v6.2.11 |
| [CHANGELOG_v6.2.18_entry_labels.md](CHANGELOG_v6.2.18_entry_labels.md) | v6.2.18 |
| [CHANGELOG_v6.2.21_strict_mode_ux.md](CHANGELOG_v6.2.21_strict_mode_ux.md) | v6.2.21 |
| [CHANGELOG_v6.2.25.md](CHANGELOG_v6.2.25.md) | v6.2.25 |
| [CHANGELOG_v6.2_EvalBaselines.md](CHANGELOG_v6.2_EvalBaselines.md) | v6.2 Eval Baselines |
| [CHANGELOG_v6.2_RepaintFix.md](CHANGELOG_v6.2_RepaintFix.md) | v6.2 Repaint Fix |
| [CHANGELOG_v6.2.X_USI_Premium.md](CHANGELOG_v6.2.X_USI_Premium.md) | USI Premium |
| [CHANGELOG_CHOCH_recent.md](CHANGELOG_CHOCH_recent.md) | CHoCH Changelog |
| [RELEASE_SUMMARY_v6.3.9.md](RELEASE_SUMMARY_v6.3.9.md) | v6.3.9 Release |
| [UPDATE_v6.1.1.md](UPDATE_v6.1.1.md) | v6.1.1 Update |
| [UPDATE_v6.2_Infinite_TP_ATR.md](UPDATE_v6.2_Infinite_TP_ATR.md) | v6.2 Infinite TP |
| [UPDATE_v6.2_Reversal_Fix.md](UPDATE_v6.2_Reversal_Fix.md) | v6.2 Reversal Fix |

### Historische Reviews & Test Reports

| Dokument | Kontext |
|----------|---------|
| [REVIEW_v6.1.md](REVIEW_v6.1.md) | v6.1 Review |
| [REVIEW_v6.3.md](REVIEW_v6.3.md) | v6.3.0 Review |
| [REVIEW_v6.3.4.md](REVIEW_v6.3.4.md) | v6.3.4 Review |
| [REVIEW_open_prep_suite.md](REVIEW_open_prep_suite.md) | Open Prep Suite Review |
| [REVIEW_open_prep_v2_post_fixes.md](REVIEW_open_prep_v2_post_fixes.md) | Open Prep v2 Post-Fix Review |
| [REVIEW_NewsAPI_Production_Readiness.md](REVIEW_NewsAPI_Production_Readiness.md) | NewsAPI Readiness Review |
| [TEST_REPORT_v6.1.md](TEST_REPORT_v6.1.md) | v6.1 Test Report |
| [TEST_REPORT_v6.3.md](TEST_REPORT_v6.3.md) | v6.3 Test Report |
| [PR_v6.2.21_strict_mode_ux.md](PR_v6.2.21_strict_mode_ux.md) | v6.2.21 PR Draft |
| [REPAIR_REPORT_v6.2.md](REPAIR_REPORT_v6.2.md) | v6.2 Repair Report |
| [AUDIT_R5_CAT7_12.md](AUDIT_R5_CAT7_12.md) | Audit Round 5 |
| [AUDIT_REPORT_Comprehensive.md](AUDIT_REPORT_Comprehensive.md) | Comprehensive Audit 2025-06 |

### Historische Troubleshooting

| Dokument | Kontext |
|----------|---------|
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | v6.1 Troubleshooting |
| [TROUBLESHOOTING_GHOST_SIGNALS.md](TROUBLESHOOTING_GHOST_SIGNALS.md) | Ghost Signals |
| [TROUBLESHOOTING_v6.2_Exits.md](TROUBLESHOOTING_v6.2_Exits.md) | v6.2 Exits |
| [TROUBLESHOOTING_v6.2.11_RevBuy.md](TROUBLESHOOTING_v6.2.11_RevBuy.md) | v6.2.11 RevBuy |
| [TROUBLESHOOTING_v6.2.34_RevBuy_1530Bar.md](TROUBLESHOOTING_v6.2.34_RevBuy_1530Bar.md) | v6.2.34 RevBuy |

---

## Operative Evidenz (Operational Evidence)

Einmal-Artefakte, die einen bestimmten Zustand zu einem bestimmten Zeitpunkt festhalten.

| Dokument | Kontext |
|----------|--------|
| [tradingview-manual-publish-evidence-2026-04-16.md](tradingview-manual-publish-evidence-2026-04-16.md) | Publish-Evidenz 2026-04-16 |
| [smc_release_gate_validation_2026-04-16.md](smc_release_gate_validation_2026-04-16.md) | Gate Validation Evidence |
| [OPEN_PREP_SPEC_COMPLIANCE_REPORT.md](OPEN_PREP_SPEC_COMPLIANCE_REPORT.md) | Open Prep Spec Compliance |
| [OPEN_PREP_BENZINGA_NEWS_WIRING.md](OPEN_PREP_BENZINGA_NEWS_WIRING.md) | Benzinga News Wiring |
| [OPEN_PREP_REPOSITORY_NOTES.md](OPEN_PREP_REPOSITORY_NOTES.md) | Open Prep Repo Notes |
| [live-news-local-vs-remote-diff.md](live-news-local-vs-remote-diff.md) | News Local vs Remote Diff |
| [parity_harness.md](parity_harness.md) | Parity Harness Description |
| [FUNCTIONAL_TEST_MATRIX.md](FUNCTIONAL_TEST_MATRIX.md) | Functional Test Matrix |

---

## Transitional / Superseded

Diese Dokumente sind durch neuere Fassungen ersetzt, aber noch
für Referenz und Audit vorhanden.

| Dokument | Ersetzt durch |
|----------|---------------|
| [v5_5a_lean_contract_refinement_en.md](v5_5a_lean_contract_refinement_en.md) | [v5_5b_architecture.md](v5_5b_architecture.md) |
| [SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md](SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md) | [v5_5b_architecture.md](v5_5b_architecture.md) |
| [SMC_TARGET_ARCHITECTURE_REFERENCE_2026-03-26.md](SMC_TARGET_ARCHITECTURE_REFERENCE_2026-03-26.md) | [v5_5b_architecture.md](v5_5b_architecture.md) |
| [v4-enrichment-migration.md](v4-enrichment-migration.md) | [v5-enrichment-architecture.md](v5-enrichment-architecture.md) |
| [v5_5b_architecture.md](v5_5b_architecture.md) | — (**aktuell kanonisch**) |

---

## Weitere kanonische Dokumente (Nicht-SMC-Scope)

| Dokument | Inhalt |
|----------|--------|
| [BLOOMBERG_TERMINAL_PLAN.md](BLOOMBERG_TERMINAL_PLAN.md) | Terminal Architecture Plan |
| [TRADERSPOST_INTEGRATION.md](TRADERSPOST_INTEGRATION.md) | TradersPost Integration Guide |
| [VWAP_Long_Reclaim_Kurzguide.md](VWAP_Long_Reclaim_Kurzguide.md) | VWAP Long Reclaim Guide (DE) |
| [VWAP_Long_Reclaim_Technical_Documentation.md](VWAP_Long_Reclaim_Technical_Documentation.md) | VWAP Long Reclaim Tech Doc |
| [USI-CHOCH_Onboarding.md](USI-CHOCH_Onboarding.md) | USI-CHoCH Onboarding |
| [RFC_BULLISH_QUALITY_PREMARKET_SCANNER.md](RFC_BULLISH_QUALITY_PREMARKET_SCANNER.md) | RFC: Premarket Scanner |
| [RFC_v6.4_AdaptiveZeroLag_RegimeClassifier.md](RFC_v6.4_AdaptiveZeroLag_RegimeClassifier.md) | RFC: v6.4 Adaptive Zero-Lag (Draft) |
| [ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md](ANBIETER_VERGLEICH_Finnhub_TwelveData_Alpaca.md) | Provider Vergleich (2026-02) |
| [FMP_ENDPOINT_GAP_ANALYSE.md](FMP_ENDPOINT_GAP_ANALYSE.md) | FMP Endpoint Gap-Analyse |
| [TRADINGVIEW_TEST_CHECKLIST.md](TRADINGVIEW_TEST_CHECKLIST.md) | TradingView Test Checklist (v6.1) |

---

## Fehlende Dokumentation (Identified Gaps)

| Thema | Status | Empfehlung |
|-------|--------|------------|
| Pine Library Dependency Graph (9 libs) | Implizit in `smc_final_status_review` | Eigenständiges Diagram wäre nützlich |
| CI/CD Workflow-Dokumentation (GitHub Actions) | Nur in Code + `smc_branch_protection_and_release_gates.md` | Ausreichend für jetzt |
| Databento Ingest End-to-End Runbook | Verteilt auf mehrere Docs | Könnte konsolidiert werden |

---

## Konventionen

- **Canonical current** = Maßgeblich für aktuelle Implementierung. Darf geändert werden.
- **Historical reference** = Dokumentiert einen vergangenen Zustand. Nicht inhaltlich ändern.
- **Operational evidence** = Einmal-Snapshot für Audit-Zwecke. Nicht ändern.
- **Transitional / superseded** = Durch neuere Version ersetzt. Hinweis im Dokument selbst.
