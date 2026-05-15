# SMC Documentation Index

> **Canonical documentation map:**
> [smc_documentation_map_2026-04-16.md](smc_documentation_map_2026-04-16.md)
>
> Start there for the recommended reading order, document classification,
> and the full inventory of canonical vs. historical docs.

This index anchors the current producer/consumer contract documentation for the SMC split.

Additional implementation guides for the current Python runtime layers:

- [`../ml/README.md`](../ml/README.md) — synthetic ML family research, SHAP,
	Optuna, and requested-vs-resolved device semantics
- [`../rl/README.md`](../rl/README.md) — synthetic RL execution research,
	CUDA torch override contract, and workflow artifact shape
- [`OPEN_PREP_OPS_QUICK_REFERENCE.md`](OPEN_PREP_OPS_QUICK_REFERENCE.md) —
	operator quick reference for the recurring Open-Prep outputs

Start here for the canonical mainline setup path:

- [smc-mainline-setup-runbook.md](smc-mainline-setup-runbook.md)

Use these files as the starting point before changing the split architecture or the bus contract:

- [smc-lite-pro-product-cut.md](smc-lite-pro-product-cut.md)
- [TRADINGVIEW_STRATEGY_GUIDE.md](TRADINGVIEW_STRATEGY_GUIDE.md)
- [smc-owner-review-2026-04-14.md](smc-owner-review-2026-04-14.md)
- [smc-copilot-work-packages-2026-04-14.md](smc-copilot-work-packages-2026-04-14.md)
- [smc-residual-program-completion.md](smc-residual-program-completion.md)
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
- [../artifacts/tradingview/smc_product_cut_manifest.json](../artifacts/tradingview/smc_product_cut_manifest.json)

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
- `npm run tv:preflight:smc-mainline` for the canonical SMC mainline gate
- `npm run tv:smoke-readonly` for non-writing existing-script smoke validation

Current workspace caveat:

- the TradingView automation layer, reports path, and auth artifacts are present in this checkout, so the documented preflight and micro-library publish paths are reproducible locally again; inspect the latest staged report before assuming every run covered binding and runtime scopes
- latest fully green SMC mainline evidence: `automation/tradingview/reports/preflight-2026-04-08T12-37-12-028Z.json`

Current deep-review planning documents:

- [smc_deep_review_2026-04-20_improvement_plan.md](smc_deep_review_2026-04-20_improvement_plan.md)
- [engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md](engineering-program/smc_deep_review_2026-04-20_engineering_backlog.md)
- [smc_deep_review_2026-04-20_hero_surface_plan.md](smc_deep_review_2026-04-20_hero_surface_plan.md)
- [smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md](smc_deep_review_2026-04-20_pine_evidence_first_ticketset.md)
- [smc_deep_review_2026-04-20_hero_surface_implementation_preparation.md](smc_deep_review_2026-04-20_hero_surface_implementation_preparation.md)
