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

Refresh date: 2026-04-05

- live TradingView automation prerequisites are present in this checkout
- present locally: `scripts/tv_preflight.ts`, `scripts/tv_publish_micro_library.ts`, `scripts/create_tradingview_storage_state.ts`, the shared automation layer under `automation/tradingview/lib/...`, the `automation/tradingview/reports` folder, and auth artifacts under `automation/tradingview/auth/...`
- consequence: repo-side mutating preflight and automated micro-library publish runs are reproducible from this workspace snapshot again
- caveat: staged preflight artifacts must still be read per-scope; some runs only prove auth/ui/compile and leave binding/runtime scopes as `not_run`
- static split-contract validation for the active SMC path remains the code-level source of truth in this checkout

## Current Decision Status

- validation/reporting layer: updated
- latest staged-format authenticated preflight artifact: `automation/tradingview/reports/preflight-micro-library-2026-04-04T07-50-33-373Z.json`
- latest automated micro-library publish artifact: `automation/tradingview/reports/publish-micro-library-2026-04-04T07-50-33-372Z.json`
- current shell auth result: reusable TradingView auth artifacts are present in this workspace snapshot
- current repo-side preflight reading: auth/ui/compile are green for the active core target; report-root `overall_preflight_ok` remains false on that pass because binding/runtime scopes were not run
- current live validation decision in this checkout: repo-side preflight and publish evidence are present; full binding/runtime confidence still depends on running those scopes explicitly
- library publish tracking artifact: present
- automated micro-library publish path: reproducible from this workspace snapshot

## Read This Next

- [tradingview-status-model.md](tradingview-status-model.md)
- [tradingview-auth-modes.md](tradingview-auth-modes.md)
- [tradingview-runtime-validation.md](tradingview-runtime-validation.md)
- [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md)
