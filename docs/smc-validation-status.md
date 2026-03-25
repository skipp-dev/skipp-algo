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

## Current Decision Status

- validation/reporting layer: updated
- latest historical live TradingView pass: [../automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json](../automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json)
- first staged-format preflight artifact: [../automation/tradingview/reports/preflight-2026-03-24T05-44-44-193Z.json](../automation/tradingview/reports/preflight-2026-03-24T05-44-44-193Z.json)
- latest staged-format authenticated preflight artifact: [../automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json](../automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json)
- latest staged-format auth result in this shell: `storage_state`, with UI, compile, binding, and runtime scopes green
- library publish tracking artifact: present
- automated micro-library publish path: available via the Streamlit base-generator UI, with post-publish contract and core validation

## Read This Next

- [tradingview-status-model.md](tradingview-status-model.md)
- [tradingview-auth-modes.md](tradingview-auth-modes.md)
- [tradingview-runtime-validation.md](tradingview-runtime-validation.md)
- [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md)
