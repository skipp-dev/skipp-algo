# SMC Validation Status

## Current Scope

The current completed work now covers the TradingView validation/reporting layer plus the canonical SMC Lite/Pro product-cut contract.

It now anchors and propagates product metadata across:

- [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
- [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
- [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)
- [../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py)
- [../artifacts/tradingview/smc_product_cut_manifest.json](../artifacts/tradingview/smc_product_cut_manifest.json)
- [../artifacts/tradingview/library_release_manifest.json](../artifacts/tradingview/library_release_manifest.json)

## What Changed In This Phase

- the residual-program closeout and the published senior-review follow-up are now tracked in [smc-residual-program-completion.md](smc-residual-program-completion.md), including the additive `volume_provenance` boundary and the published follow-up commit `8c6652db`
- the active SMC core/dashboard path now carries library volatility + ensemble context through the existing lean BUS transport and renders it in the audit surface
- the refresh workflow now restores known runtime artifacts before commit/push and verifies the generated library import bump explicitly
- provider-health and release-gate reports now expose `domain_alerts` for fallback-used and domain-status cases so operator reports can show missing-subscription / no-data root causes without digging through raw payloads
- release-health news resolution now follows the productive live-news artifact via `live_news_snapshot_json` instead of assuming legacy static watchlist snapshots
- the refresh workflow summary now separates `Provider Domain Alerts` from `Provider Health Warnings`, and end-of-run notifications escalate on real provider warnings
- preflight reporting moved from one coarse `ok` flag to staged status fields
- auth source selection is now explicit and documented
- binding verification is split into count and name checks
- runtime smoke validation is explicit and minimal
- library release tracking now has a machine-readable manifest under [../artifacts/tradingview/library_release_manifest.json](../artifacts/tradingview/library_release_manifest.json)
- the SMC product boundary now has a machine-readable artifact under [../artifacts/tradingview/smc_product_cut_manifest.json](../artifacts/tradingview/smc_product_cut_manifest.json)
- preflight scopes now resolve from the canonical product-cut artifact, including the mainline path `SMC_Core_Engine.pine` + `SMC_Dashboard.pine` + `SMC_Long_Strategy.pine`
- dashboard, strategy, companion, bridge, and legacy surfaces are explicitly classified in code and artifact form
- dashboard/pine payloads and the delivery bundle now carry `product_cut` metadata
- the long-strategy wrapper now separates visible setup from operator-only BUS bindings and exposes entry-price, stop-loss, and profit-target outputs with public terminology
- focused contract tests cover schema, aggregation, auth priority, and manifest requirements

## What Remains Unchanged

- producer trading logic
- dashboard decision logic
- strategy order logic
- bus versioning
- explicit TradingView library owner/version contract

## Current Workspace Status

Refresh date: 2026-04-14

- live TradingView automation prerequisites are present in this checkout
- present locally: `scripts/tv_preflight.ts`, `scripts/tv_publish_micro_library.ts`, `scripts/create_tradingview_storage_state.ts`, the shared automation layer under `automation/tradingview/lib/...`, the `automation/tradingview/reports` folder, and auth artifacts under `automation/tradingview/auth/...`
- consequence: repo-side mutating preflight and automated micro-library publish runs are reproducible from this workspace snapshot again
- canonical mainline preflight scope is now available through `npm run tv:preflight:smc-mainline`
- caveat: older staged artifacts can still represent partial scopes; the current mainline report is the authoritative live read for full auth/ui/compile/binding/runtime status
- static split-contract validation for the active SMC path remains the code-level source of truth in this checkout

## Current Decision Status

- validation/reporting layer: updated
- product-cut contract layer: updated
- latest staged-format authenticated preflight artifact: `automation/tradingview/reports/preflight-2026-04-07T19-12-02-524Z.json`
- latest automated micro-library publish artifact: `automation/tradingview/reports/publish-micro-library-2026-04-04T07-50-33-372Z.json`
- latest full `smc-library-refresh` success on GitHub Actions: run `24342288092` (`2026-04-13T12:02:36Z`), including readonly preflight, publish, post-release validation, commit/push, and alerts
- current shell auth result: reusable TradingView auth artifacts are present in this workspace snapshot
- latest authenticated live artifact details: `auth_mode = persistent_profile`, `execution_mode = mutating`, all three mainline targets reached `overall_preflight_ok = true`
- current repo-side preflight reading: the canonical `tv:preflight:smc-mainline` path is green across auth, ui, compile, binding, runtime, and report-root `overall_preflight_ok`
- current live validation decision in this checkout: the active SMC mainline path is fully green and review-ready in TradingView live automation
- library publish tracking artifact: present
- current checked-in library release manifest: `productivityGate.publishReady = true`, `publishedVersion = 1`, `inputPath = artifacts/smc_microstructure_exports/databento_volatility_production_incremental_20260413_121643__smc_microstructure_base_2026-04-10.csv`, `universeSize = 6854`
- current checked-in generated library manifest: `productivity_gate.publish_ready = true`, `fixture_input_detected = false`, `default_event_risk_detected = false`, `placeholder_symbols = []`
- product-cut artifact: present
- automated micro-library publish path: reproducible from this workspace snapshot
- provider fallback / no-data root causes: visible via `domain_alerts` + `meta_domain_diagnostics` in provider-health and release-gate reports, plus summary-level `Provider Health Warnings` in `smc-library-refresh`
- latest scheduled failure after the green run: `24344229616`, caused by tracked Databento runtime-cache churn during commit/push rather than by a red productivity gate; the workflow now restores those paths before staging and aborts early on remaining tracked drift

## Read This Next

- [smc-residual-program-completion.md](smc-residual-program-completion.md)
- [tradingview-status-model.md](tradingview-status-model.md)
- [tradingview-auth-modes.md](tradingview-auth-modes.md)
- [tradingview-runtime-validation.md](tradingview-runtime-validation.md)
- [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md)
