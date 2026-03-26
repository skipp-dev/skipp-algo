# Strict SMC Data Lineage and Subscription Audit (2026-03-26)

## Phase 15 Update (Workbook Producer Unification)

- Canonical upstream artifact is now explicitly the Databento production export bundle.
- Production workbook is now a derived artifact produced by shared helper logic in [scripts/databento_production_workbook.py](scripts/databento_production_workbook.py).
- Authoritative producer path is daily export in [scripts/databento_production_export.py](scripts/databento_production_export.py#L3060), which now emits canonical workbook output at [artifacts/smc_microstructure_exports/databento_volatility_production_workbook.xlsx](artifacts/smc_microstructure_exports/databento_volatility_production_workbook.xlsx).
- SMC base run inherits this workbook via [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1384) and records workbook lineage in base manifest metadata.
- Streamlit remains a consumer: workbook write path in [databento_volatility_screener.py](databento_volatility_screener.py#L3565) delegates to the shared helper, rather than owning unique workbook-construction logic.
- Structure exporters now default to canonical workbook path with legacy fallback via [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L16) and [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L16).
- Base workbook writer now protects against Excel row-cap failures by splitting oversized `base_snapshot` exports across numbered sheets (`base_snapshot`, `base_snapshot_002`, ...) in [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1293).
- IBKR remains execution/preview only.
- L2/DOM requirement remains not evidenced in current producer path.

## A) Executive Answers (strict, evidence-backed)

1. Is the current structure path explicit BOS/CHOCH or still summary-only?
- Answer: Explicit BOS and CHOCH events are produced from last_event mapping in the structure artifact producers, but only for the BOS/CHOCH event family.
- Evidence: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L192), [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L208), [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L36), [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L111)

2. Are orderblocks, FVG, liquidity sweeps explicitly produced in the same producer path?
- Answer: No. In the currently implemented producer path they are explicitly emitted as empty lists.
- Evidence: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L195), [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L196), [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L197), [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L113)

3. Is the integration service consuming source-specific raw inputs via a composite domain plan?
- Answer: Yes. Structure, volume, technical, and news are selected through composite domain routing, then assembled into snapshot/dashboard/pine payloads.
- Evidence: [smc_integration/repo_sources.py](smc_integration/repo_sources.py#L73), [smc_integration/repo_sources.py](smc_integration/repo_sources.py#L259), [smc_integration/repo_sources.py](smc_integration/repo_sources.py#L286), [smc_integration/repo_sources.py](smc_integration/repo_sources.py#L322), [smc_integration/service.py](smc_integration/service.py#L31), [smc_integration/service.py](smc_integration/service.py#L98)

4. Which vendors are physically evidenced in current repo artifacts consumed by integration right now?
- Answer: Databento is evidenced by a present watchlist CSV consumed by integration. FMP/TradingView/Benzinga source adapters exist in code, but their expected snapshot files are not present in the current reports folder. IBKR is evidenced as an execution/preview consumer of Databento watchlists, not as an SMC integration source adapter.
- Evidence (Databento present): [smc_integration/sources/databento_watchlist_csv.py](smc_integration/sources/databento_watchlist_csv.py#L10), [reports/databento_watchlist_top5_pre1530.csv](reports/databento_watchlist_top5_pre1530.csv#L1)
- Evidence (FMP expected but missing file now): [smc_integration/sources/fmp_watchlist_json.py](smc_integration/sources/fmp_watchlist_json.py#L10), [smc_integration/sources/fmp_watchlist_json.py](smc_integration/sources/fmp_watchlist_json.py#L31)
- Evidence (TradingView expected but missing file now): [smc_integration/sources/tradingview_watchlist_json.py](smc_integration/sources/tradingview_watchlist_json.py#L10), [smc_integration/sources/tradingview_watchlist_json.py](smc_integration/sources/tradingview_watchlist_json.py#L31)
- Evidence (Benzinga expected but missing file now): [smc_integration/sources/benzinga_watchlist_json.py](smc_integration/sources/benzinga_watchlist_json.py#L10), [smc_integration/sources/benzinga_watchlist_json.py](smc_integration/sources/benzinga_watchlist_json.py#L31)
- Evidence (IBKR path): [scripts/execute_ibkr_watchlist.py](scripts/execute_ibkr_watchlist.py#L26), [reports/ibkr_watchlist_preview_2026-03-06.json](reports/ibkr_watchlist_preview_2026-03-06.json#L1)

5. Does the Databento production pipeline generate full-universe daily and premarket window feature artifacts used by downstream watchlist/scanner logic?
- Answer: Yes in code path. The production export builds both tables and writes them as export frames; downstream watchlist and bullish scanner loaders consume those exact frame names (or manifest fallback).
- Evidence: [scripts/databento_production_export.py](scripts/databento_production_export.py#L3049), [scripts/databento_production_export.py](scripts/databento_production_export.py#L3294), [scripts/databento_production_export.py](scripts/databento_production_export.py#L3395), [scripts/databento_production_export.py](scripts/databento_production_export.py#L3647), [scripts/databento_production_export.py](scripts/databento_production_export.py#L3655), [scripts/generate_databento_watchlist.py](scripts/generate_databento_watchlist.py#L157), [scripts/generate_bullish_quality_scanner.py](scripts/generate_bullish_quality_scanner.py#L34)

6. Is there runtime evidence in this workspace of a current manifest+parquet Databento export bundle directory?
- Answer: Unresolved in current filesystem snapshot. Loader and runtime code expect such artifacts and default locations, but no manifest file matching export bundle naming was found during this audit run.
- Evidence: [scripts/load_databento_export_bundle.py](scripts/load_databento_export_bundle.py#L45), [scripts/load_databento_export_bundle.py](scripts/load_databento_export_bundle.py#L73), [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1322), [scripts/generate_smc_micro_base_from_databento.py](scripts/generate_smc_micro_base_from_databento.py#L251)

7. Is batch snapshot export wired to produce structure artifacts first and then snapshot bundles?
- Answer: Yes.
- Evidence: [scripts/export_smc_snapshot_watchlist_bundles.py](scripts/export_smc_snapshot_watchlist_bundles.py#L33), [scripts/export_smc_snapshot_watchlist_bundles.py](scripts/export_smc_snapshot_watchlist_bundles.py#L41), [smc_integration/batch.py](smc_integration/batch.py#L186), [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L261)

## B) Data Lineage (Producer -> Artifact -> Consumer)

### B1) Databento full-universe export path
- Producer function: run_production_export_pipeline
- Code anchor: [scripts/databento_production_export.py](scripts/databento_production_export.py#L3049)
- Output frames (in export payload): daily_symbol_features_full_universe, premarket_window_features_full_universe
- Frame registration anchors: [scripts/databento_production_export.py](scripts/databento_production_export.py#L3647), [scripts/databento_production_export.py](scripts/databento_production_export.py#L3655)
- Bundle loader contract: [scripts/load_databento_export_bundle.py](scripts/load_databento_export_bundle.py#L73)
- Consumers:
  - Watchlist builder loads daily+premarket frames: [scripts/generate_databento_watchlist.py](scripts/generate_databento_watchlist.py#L157)
  - Bullish quality scanner loads same frame names: [scripts/generate_bullish_quality_scanner.py](scripts/generate_bullish_quality_scanner.py#L34)

### B2) SMC microstructure base snapshot path
- Producer orchestration: run_databento_base_scan_pipeline
- Code anchor: [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1384)
- Pulls production export, loads bundle, builds base snapshot:
  - [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1408)
  - [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1423)
  - [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1311)
- Writes artifacts:
  - base csv: [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1336)
  - symbol-day parquet: [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1337)
  - session minute parquet: [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1483)
  - base manifest: [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1266), [scripts/smc_microstructure_base_runtime.py](scripts/smc_microstructure_base_runtime.py#L1360)
- Entry CLI wrapper:
  - run scan path: [scripts/generate_smc_micro_base_from_databento.py](scripts/generate_smc_micro_base_from_databento.py#L270)
  - bundle path: [scripts/generate_smc_micro_base_from_databento.py](scripts/generate_smc_micro_base_from_databento.py#L289)

### B3) Structure artifact path (explicit BOS/CHOCH only)
- Single-file export producer: [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L69)
- Batch producer: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L261)
- Event derivation logic used by producer: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L208)
- Explicit currently-empty categories in producer payload: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L195)
- Consumer adapter:
  - structure source files: [smc_integration/sources/structure_artifact_json.py](smc_integration/sources/structure_artifact_json.py#L10), [smc_integration/sources/structure_artifact_json.py](smc_integration/sources/structure_artifact_json.py#L214)

### B4) Snapshot bundle path for integration payloads
- Single symbol bundle export script: [scripts/export_smc_snapshot_bundle.py](scripts/export_smc_snapshot_bundle.py#L18)
- Watchlist batch export script: [scripts/export_smc_snapshot_watchlist_bundles.py](scripts/export_smc_snapshot_watchlist_bundles.py#L41)
- Bundle build service:
  - composite source planning: [smc_integration/service.py](smc_integration/service.py#L106)
  - structure status discovery: [smc_integration/service.py](smc_integration/service.py#L107)
  - dashboard and pine payload assembly: [smc_integration/service.py](smc_integration/service.py#L114), [smc_integration/service.py](smc_integration/service.py#L119)

## C) Vendor/Subscription Matrix (current run evidence)

### C1) Databento
- Code integration source registered: yes
- Physical source artifact present now: yes
- Current evidence:
  - source adapter points to reports csv: [smc_integration/sources/databento_watchlist_csv.py](smc_integration/sources/databento_watchlist_csv.py#L10)
  - csv exists and has rows: [reports/databento_watchlist_top5_pre1530.csv](reports/databento_watchlist_top5_pre1530.csv#L1)

### C2) FMP
- Code integration source registered: yes
- Physical source artifact present now: not evidenced
- Expected artifact path in adapter: [smc_integration/sources/fmp_watchlist_json.py](smc_integration/sources/fmp_watchlist_json.py#L10)
- Missing-file behavior proves requirement: [smc_integration/sources/fmp_watchlist_json.py](smc_integration/sources/fmp_watchlist_json.py#L31)

### C3) TradingView
- Code integration source registered: yes
- Physical source artifact present now: not evidenced
- Expected artifact path in adapter: [smc_integration/sources/tradingview_watchlist_json.py](smc_integration/sources/tradingview_watchlist_json.py#L10)
- Missing-file behavior proves requirement: [smc_integration/sources/tradingview_watchlist_json.py](smc_integration/sources/tradingview_watchlist_json.py#L31)

### C4) Benzinga
- Code integration source registered: yes
- Physical source artifact present now: not evidenced
- Expected artifact path in adapter: [smc_integration/sources/benzinga_watchlist_json.py](smc_integration/sources/benzinga_watchlist_json.py#L10)
- Missing-file behavior proves requirement: [smc_integration/sources/benzinga_watchlist_json.py](smc_integration/sources/benzinga_watchlist_json.py#L31)

### C5) IBKR
- Role: execution consumer, not SMC integration source adapter
- Watchlist input dependency: [scripts/execute_ibkr_watchlist.py](scripts/execute_ibkr_watchlist.py#L26)
- Preview artifact present now: [reports/ibkr_watchlist_preview_2026-03-06.json](reports/ibkr_watchlist_preview_2026-03-06.json#L1)
- Current preview source points to Databento watchlist csv: [reports/ibkr_watchlist_preview_2026-03-06.json](reports/ibkr_watchlist_preview_2026-03-06.json#L4)

## D) Missing Categories and Root Cause

1. Missing structure categories in current producer output
- Missing now: orderblocks, fvg, liquidity_sweeps
- Immediate cause: producer payload initializes these categories as empty arrays in current mapping path.
- Evidence: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L195), [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L113)

2. Why BOS/CHOCH appear but others do not
- BOS/CHOCH are synthesized from structure_last_event and close/asof in producer mapping.
- Evidence: [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L57), [smc_integration/structure_batch.py](smc_integration/structure_batch.py#L176), [scripts/export_smc_structure_artifact.py](scripts/export_smc_structure_artifact.py#L36)

3. Current artifact reality check in reports
- Legacy single artifact exists and shows mostly none/partial with empty non-BOS categories.
- Evidence: [reports/smc_structure_artifact.json](reports/smc_structure_artifact.json#L5), [reports/smc_structure_artifact.json](reports/smc_structure_artifact.json#L14), [reports/smc_structure_artifact.json](reports/smc_structure_artifact.json#L37), [reports/smc_structure_artifact.json](reports/smc_structure_artifact.json#L54)
- Batch structure directory currently empty in this workspace snapshot.

## E) Hard Conclusions and Unresolved Items

Hard conclusions:
- Composite source routing for structure/volume/technical/news is implemented and active in integration service calls.
- Structure artifact producers currently deliver explicit BOS/CHOCH only; orderblocks/FVG/sweeps are not produced in current mapping path.
- Databento watchlist artifact is present and actively consumable by integration and IBKR preview flow.
- FMP/TradingView/Benzinga adapters are implemented but not currently evidenced by present snapshot files in reports.

Unresolved items requiring additional runtime evidence:
- Presence of current Databento manifest+parquet bundle directory in the filesystem for this exact workspace run.
- Presence of current FMP/TradingView/Benzinga snapshot artifacts in reports at audit time.

Scope note:
- This audit is based on direct producer/consumer code-path inspection plus current on-disk artifacts available in this workspace snapshot.
