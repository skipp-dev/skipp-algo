# SMC Documentation Index

> **Repo-wide entry point:**
> [../README.md](../README.md)
>
> This file is intentionally SMC / TradingView focused. For the broader
> platform surfaces (terminal, Open-Prep, Databento, ML, RL), start with the
> root README and then branch into the topic-specific docs below.

## Repo-wide starting points

- [../README.md](../README.md) — top-level platform overview and operator quick starts
- [OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md](OPEN_PREP_SUITE_TECHNICAL_REFERENCE.md)
- [DATABENTO_VOLATILITY_SUITE.md](DATABENTO_VOLATILITY_SUITE.md)
- [../ml/README.md](../ml/README.md)
- [../rl/README.md](../rl/README.md)
- [../artifacts/open_prep/outcomes/feature_importance/README.md](../artifacts/open_prep/outcomes/feature_importance/README.md)

The ML/RL READMEs above describe the implementation layers that are already
checked into mainline. The routed GPU research workflows and their dedicated
entrypoints currently live on the parallel branch
`fix/live-runner-routing-unblock-ml-rl-gpu`, so keep mainline docs free of
links to those branch-only workflow files until they actually merge.

> **Canonical documentation map:**
> [smc_documentation_map_2026-04-16.md](smc_documentation_map_2026-04-16.md)
>
> Start there for the recommended reading order, document classification,
> and the full inventory of canonical vs. historical docs.

This index anchors the current producer/consumer contract documentation for the SMC split.

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
