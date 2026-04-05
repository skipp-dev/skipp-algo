# SMC Split Validation Docs

This index anchors the current producer/consumer contract documentation for the SMC split.

Use these files as the starting point before changing the split architecture or the bus contract:

- [smc-validation-status.md](smc-validation-status.md)
- [structure_contract_architecture.md](structure_contract_architecture.md)
- [adr/0001-structure-contract-normalization.md](adr/0001-structure-contract-normalization.md)
- [tradingview-status-model.md](tradingview-status-model.md)
- [tradingview-auth-modes.md](tradingview-auth-modes.md)
- [smc-bus-v2-audit.md](smc-bus-v2-audit.md)
- [smc-bus-target-matrix.md](smc-bus-target-matrix.md)
- [smc-bus-roadmap.md](smc-bus-roadmap.md)
- [smc_branch_protection_and_release_gates.md](smc_branch_protection_and_release_gates.md)
- [tradingview-validation-checklist.md](tradingview-validation-checklist.md)
- [tradingview-manual-validation-runbook.md](tradingview-manual-validation-runbook.md)
- [tradingview-manual-validation-runbook_EN.md](tradingview-manual-validation-runbook_EN.md)
- [tradingview-manual-validation-report-template.md](tradingview-manual-validation-report-template.md)
- [tradingview-manual-validation-report-template_EN.md](tradingview-manual-validation-report-template_EN.md)
- [tradingview-runtime-validation.md](tradingview-runtime-validation.md)
- [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md)
- [smc-microstructure-ui-audit.md](smc-microstructure-ui-audit.md)
- [smc-microstructure-ui-operator-runbook.md](smc-microstructure-ui-operator-runbook.md)
- [smc-microstructure-ui-architecture.md](smc-microstructure-ui-architecture.md)
- [v4-enrichment-migration.md](v4-enrichment-migration.md)

Machine-readable TradingView release tracking artifact:

- [../artifacts/tradingview/library_release_manifest.json](../artifacts/tradingview/library_release_manifest.json)

Authoritative code references for the current contract:

- [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
- [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
- [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)

Authoritative TradingView release-layer code references:

- [../scripts/tv_publish_micro_library.ts](../scripts/tv_publish_micro_library.ts)
- [../scripts/tv_preflight.ts](../scripts/tv_preflight.ts)
- [../scripts/create_tradingview_storage_state.ts](../scripts/create_tradingview_storage_state.ts)

Primary TradingView automation entry points:

- `npm run tv:preflight` for mutating repo-source validation
- `npm run tv:smoke-readonly` for non-writing existing-script smoke validation

Current workspace caveat:

- the TradingView automation layer, reports path, and auth artifacts are present in this checkout, so the documented preflight and micro-library publish paths are reproducible locally again; inspect the latest staged report before assuming every run covered binding and runtime scopes
