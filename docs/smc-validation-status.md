# SMC Validation Status

## Current Scope

The current completed work is limited to the TradingView validation, reporting, and runtime-assurance layer.

It does not change:

- [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
- [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
- [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)

## What Changed In This Phase

- preflight reporting moved from one coarse `ok` flag to staged status fields
- auth source selection is now explicit and documented
- binding verification is split into count and name checks
- runtime smoke validation is explicit and minimal
- library release tracking now has a machine-readable manifest under [../artifacts/tradingview/library_release_manifest.json](../artifacts/tradingview/library_release_manifest.json)
- focused contract tests cover schema, aggregation, auth priority, and manifest requirements

## What Remains Unchanged

- producer logic
- dashboard logic
- strategy logic
- bus versioning
- explicit TradingView library owner/version contract

## Current Workspace Status

Refresh date: 2026-04-03

- live TradingView validation is currently blocked in this checkout
- present locally: `scripts/tv_preflight.ts`, `scripts/tv_publish_micro_library.ts`, `scripts/create_tradingview_storage_state.ts`
- missing locally: the shared TradingView automation layer imported from `automation/tradingview/lib/...`, the `automation/tradingview/reports` folder, and a reusable auth artifact such as `automation/tradingview/auth/storage-state.json`
- consequence: the historical TradingView passes documented below are not reproducible from this workspace snapshot until those prerequisites are restored
- static split-contract validation for the active SMC path remains the current source of truth in this checkout

## Current Decision Status

- validation/reporting layer: updated
- historical live TradingView evidence: previously documented at `automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json`, but the artifact is not present locally anymore
- first staged-format preflight artifact: previously documented at `automation/tradingview/reports/preflight-2026-03-24T05-44-44-193Z.json`, but the artifact is not present locally anymore
- latest staged-format authenticated preflight artifact: previously documented at `automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json`, but the artifact is not present locally anymore
- current shell auth result: no reusable TradingView auth artifact is present in this workspace snapshot
- current live validation decision in this checkout: blocked pending restoration of the automation layer, reports path, and auth artifact
- library publish tracking artifact: present
- automated micro-library publish path: documented, but not reproducible from this workspace snapshot while the TradingView automation prerequisites are absent

## Read This Next

- [tradingview-status-model.md](tradingview-status-model.md)
- [tradingview-auth-modes.md](tradingview-auth-modes.md)
- [tradingview-runtime-validation.md](tradingview-runtime-validation.md)
- [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md)
