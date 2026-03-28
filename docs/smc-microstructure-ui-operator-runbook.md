# SMC Microstructure UI Operator Runbook

## Purpose

This runbook is the short operational companion to the detailed audit document:

- [smc-microstructure-ui-audit.md](smc-microstructure-ui-audit.md)

Use this file for day-to-day operation of the Streamlit UI.

Use the audit document for architecture review, control validation, and implementation details.

For the canonical target contract of the SMC snapshot, layering semantics, and TradingView bridge payloads, use:

- [smc-snapshot-target-architecture.md](smc-snapshot-target-architecture.md)

If implementation behavior and that target architecture disagree, the target architecture takes precedence.

## Entry Point

Start the UI with the project’s Streamlit entry script:

- [../streamlit_smc_micro_base_generator.py](../streamlit_smc_micro_base_generator.py)

The Streamlit app delegates all runtime behavior to:

- [../scripts/smc_microstructure_base_runtime.py](../scripts/smc_microstructure_base_runtime.py)

## What The UI Does

The UI supports four operator actions:

1. `Run SMC Base Scan`
2. `Refresh Data`
3. `Generate Pine Library`
4. `Publish To TradingView`

The normal operating sequence is:

1. run the base scan
2. generate the Pine library
3. review the generated manifest contract and configured owner/version
4. publish to TradingView only when the publish guard is green

## Required Inputs

The sidebar collects the following inputs:

1. Databento API key
2. FMP API key, optional
3. export directory
4. Databento dataset
5. trading days lookback
6. bullish score profile
7. SMC base-only export mode
8. XLSX output toggle
9. TradingView owner
10. TradingView library version
11. base snapshot selection for Pine generation

## Dataset Guidance

For broad US-universe base generation with signals expected to work at the open and early regular hours, the practical default is:

- `DBEQ.BASIC`

Use venue-specific alternatives only when that is intentional:

1. `XNAS.BASIC`
   - use when you want a more Nasdaq-focused open behavior bias
2. `XNAS.ITCH`
   - use when you want an even more Nasdaq-specific venue-aligned feed and you accept the narrower scope
3. `XNYS.PILLAR`
   - use when you are deliberately operating a NYSE-focused setup

## Daily Operating Procedure

### Step 1: Configure Inputs

Set:

1. Databento API key
2. export directory, or keep the default under `artifacts/smc_microstructure_exports`
3. dataset
4. lookback window
5. choose whether the export should stay in `SMC base-only export mode`
6. owner/version for the TradingView library

Important:

Owner and version should be treated as release inputs, not cosmetic metadata.

For the SMC microstructure base generator, keep `SMC base-only export mode` enabled unless you intentionally want the broader research/export behavior.

When enabled, the export skips:

1. the separate 04:00 preopen seed selection
2. the fixed 10:00 ET outcome snapshot

If you change owner or version after generating the library, regenerate before publish.

If multiple generated base CSV snapshots exist, you must explicitly select the exact base snapshot before `Generate Pine Library` becomes meaningful. The UI no longer defaults silently to the newest file.

### Step 2: Run SMC Base Scan

Click:

- `Run SMC Base Scan`

This will:

1. run the Databento production export
2. derive the full-session minute detail needed for the base snapshot
3. generate the normalized base CSV
4. generate the optional workbook
5. generate the base manifest and mapping reports

In the default SMC base-only mode, the run does not spend time on the dedicated 04:00 seed scope or the fixed 10:00 ET outcome snapshot.

It still collects full-universe symbol-day detail for open-window, close-window, and close-trade behavior because those fields feed the exported daily symbol features that the SMC base derivation consumes downstream.

Expected result:

- the UI shows `SMC base snapshot created from a fresh Databento export run`
- the `Base Artifacts` table is populated

### Step 3: Refresh Cached Data When Needed

Click:

- `Refresh Data`

Use this when you intentionally want to bypass cached Databento day artifacts and refetch the base inputs for the current run.

### Step 4: Review Base Artifacts

Review at minimum:

1. the base CSV
2. the base manifest
3. the mapping report
4. the optional XLSX workbook if manual spot-checking is needed

Typical artifact types written by the base scan:

1. CSV
2. XLSX
3. Parquet
4. JSON
5. Markdown

### Step 5: Generate Pine Library

Click:

- `Generate Pine Library`

This will:

1. read the explicitly selected generated base CSV
2. validate it against the schema
3. update persistent membership state with hysteresis
4. apply overrides if present
5. write list CSVs and diff report
6. run v4 enrichment: query the provider policy matrix (FMP, Benzinga, TradingView, Databento) for market regime, news, calendar, and technical data
7. write the generated Pine library with all 37 `export const` fields
8. write the generated import snippet
9. write the generated library manifest (includes `library_field_version: "v4"` and `enrichment_blocks`)

If any enrichment provider is unreachable, the library is still generated with all 37 fields — affected enrichment fields receive safe neutral defaults (e.g. `UNKNOWN` regime, empty event strings, `provider_count = 0`).

Expected result:

- the UI shows `Pine library artifacts generated`
- the `Pine Artifacts` table is populated

### Step 6: Check Publish Guard

Before publish, inspect the read-only UI lines:

1. `Configured publish target`
2. `Generated manifest contract`
3. `Publish guard status`
4. `Generated manifest path`

Publish should only be attempted when:

1. the UI shows a green publish-ready message
2. configured owner matches generated owner
3. configured version matches generated version
4. the import path shown in the generated manifest contract is the expected release path
5. `owner_version_ready=True`
6. `full_contract_ready=True`

If publish is blocked, the normal fix is:

1. correct owner/version in the sidebar
2. rerun `Generate Pine Library`
3. retry publish

### Step 7: Publish To TradingView

Click:

- `Publish To TradingView`

This triggers the dedicated TradingView automation runner:

- [../scripts/tv_publish_micro_library.ts](../scripts/tv_publish_micro_library.ts)

The runner performs:

1. contract verification between manifest, generated snippet, and core import
2. TradingView upload and private publish of the generated library
3. post-publish reopen and script-context version verification
4. post-publish core-only TradingView validation
5. release-manifest status update

Expected result:

- the UI shows a completed publish state
- the `TradingView Publish Result` table is populated
- publish remains failed or `not_verified` if only generic body text mentions a version without exact reopened script-context proof

## Key Artifacts To Inspect

### Base Layer

Typical files in the export directory:

1. `__smc_microstructure_base_<asof_date>.csv`
2. `__smc_microstructure_base_<asof_date>.xlsx`
3. `__smc_microstructure_symbol_day_features.parquet`
4. `__smc_microstructure_mapping_<asof_date>.md`
5. `__smc_microstructure_mapping_<asof_date>.json`
6. `__smc_microstructure_base_manifest.json`

Runtime notes for the base export:

- the base runtime now emits a warning when the selected `asof_date` is more than 5 days old
- the base runtime also warns per symbol when the trailing window has fewer than 5 trade dates, because the derived 20d metrics become less stable
- these are operator warnings only; they do not change the output file schema

### Generator Layer

Generated by the Pine generator:

1. [../pine/generated/smc_micro_profiles_generated.pine](../pine/generated/smc_micro_profiles_generated.pine)
2. [../pine/generated/smc_micro_profiles_generated.json](../pine/generated/smc_micro_profiles_generated.json)
3. [../pine/generated/smc_micro_profiles_core_import_snippet.pine](../pine/generated/smc_micro_profiles_core_import_snippet.pine)
4. [../state/microstructure_membership_state.csv](../state/microstructure_membership_state.csv)
5. [../data/output](../data/output)
6. [../reports](../reports)

### Release Validation Layer

Inspect after publish:

1. [../artifacts/tradingview/library_release_manifest.json](../artifacts/tradingview/library_release_manifest.json)
2. latest publish report under [../automation/tradingview/reports](../automation/tradingview/reports)
3. latest core-only preflight report under [../automation/tradingview/reports](../automation/tradingview/reports)

## Release Status Interpretation

The release manifest can report these statuses:

1. `manual_publish_required`
   - local artifacts exist, but the library is not yet released or not yet attempted
2. `not_verified`
   - publish may have been attempted, but post-publish validation did not pass cleanly
3. `published`
   - publish succeeded and the focused core validation also succeeded

Only `published` should be treated as release-complete.

## Operator Rules

These rules should be followed strictly:

1. never change owner/version and publish without regenerating the Pine library first
2. never treat a local Pine generation as equivalent to a validated publish
3. always inspect the generated manifest contract before publish
4. always inspect the release manifest after publish
5. treat `not_verified` as a failure requiring investigation

## Recovery Guide

### Publish Button Disabled

Likely reasons:

1. no generated library manifest exists yet
2. generated owner/version does not match configured owner/version

Recovery:

1. run `Generate Pine Library`
2. ensure configured owner/version are correct
3. regenerate again if necessary

### TradingView Publish Failed

Likely reasons:

1. reusable TradingView auth state missing or stale
2. contract mismatch between manifest, snippet, and core import
3. version mismatch detected after publish

Recovery:

1. refresh TradingView storage state
2. rerun the contract verifier
3. inspect the publish report and release manifest

### Post-Publish Validation Failed

Likely reason:

1. the core no longer compiles or resolves the published library import path correctly

Recovery:

1. inspect the focused core-only preflight report
2. inspect the generated manifest and snippet
3. inspect the import line in [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
4. fix drift and regenerate before attempting another publish

## Commands

Relevant commands are:

1. `npm run smc:verify-micro-publish`
2. `npm run tv:publish-micro-library`
3. `npm run tv:storage-state`
4. `npm run tv:preflight`
5. `npm run tv:publish-micro-library`

## Escalation Path

If an operator run fails and the cause is not obvious, escalate in this order:

1. inspect the generated manifest
2. inspect the generated import snippet
3. inspect the core import line
4. inspect the publish report
5. inspect the library release manifest
6. consult the full audit document
