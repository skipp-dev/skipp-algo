# SMC Mainline Setup Runbook

## Purpose

One document, one path: set up the complete SMC mainline on a TradingView chart.

After completing this runbook, three surfaces are active:

1. **SMC Core** — the decision-first signal engine and only producer.
2. **SMC Decision Board** — the linked companion dashboard.
3. **SMC Execution** — the execution and backtest wrapper.

Nothing else is needed for the standard mainline experience.

## Prerequisites

- A TradingView account with Pine Script v6 support.
- Access to the published or local copies of:
  - [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) (SMC Core)
  - [../SMC_Dashboard.pine](../SMC_Dashboard.pine) (SMC Decision Board)
  - [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine) (SMC Execution)
- A chart open on the intended symbol and timeframe.

## Step 1 — Add SMC Core

1. Open the Pine Script editor in TradingView.
2. Load or paste `SMC_Core_Engine.pine`.
3. Compile and add to chart.
4. Confirm: the chart shows the **Focus View** hero card with Action, Bias,
   Quality, Why now, and Main risk.

No settings changes are needed. The defaults are production-ready:

| Setting | Default | Purpose |
| --- | --- | --- |
| Focus View | on | Decision-first hero surface |
| All BUS exports | active (hidden) | Transport for Dashboard and Strategy |

SMC Core is the only producer. The remaining two scripts are consumers.

## Step 2 — Add SMC Decision Board

1. In TradingView, add a second indicator to the same chart.
2. Select `SMC Dashboard` from the published scripts or the editor.
3. After adding, open the indicator settings.
4. Navigate to the six **Operator Only** source-binding groups.

### Binding order

Bind all 58 `input.source(...)` channels **top-to-bottom** against the
matching Core BUS exports. The groups appear in this order:

| # | Group | Channels |
| --- | --- | --- |
| 1 | Lifecycle BUS | 13 |
| 2 | Diagnostic Rows | 20 |
| 3 | Diagnostic Support | 7 |
| 4 | Trade Plan | 3 |
| 5 | Detail Surface | 13 |
| 6 | Lean Surface | 2 |

Every channel maps to exactly one Core BUS export with the same label name.
Bind them strictly in the order they appear — top-to-bottom, group by group.

### After binding

- The **Decision Brief** surface is the default view. Use it for quick
  decision context.
- **Audit View** is available via settings for deeper diagnostics.

## Step 3 — Add SMC Execution

1. Add a third script to the same chart.
2. Select `SMC Long Strategy` from the published scripts or the editor.
3. Open the strategy settings.
4. Navigate to the two **Expert Mapping** source-binding groups.

### Binding order

Bind all 8 `input.source(...)` channels **top-to-bottom**:

| # | Group | Channels |
| --- | --- | --- |
| 1 | Entry States | 6 |
| 2 | Trade Plan | 2 |

The labels match the same Core BUS exports that appear in the Dashboard
lifecycle and plan groups.

### After binding

The visible wrapper controls are:

| Setting | Default | Purpose |
| --- | --- | --- |
| Execution Stage | Strict | Selects which execution tier is used |
| Minimum Quality Score | (default) | Wrapper-level quality threshold |
| Take Profit (R) | (default) | Take-profit distance as risk multiple |
| Use Take Profit | on | Enables the wrapper take-profit plan |

The chart shows three plan lines: **Execution Trigger**, **Execution
Invalidation**, and **Execution Take Profit**.

## Step 4 — Verify

### Quick check

- Core shows the Focus View hero card.
- Dashboard shows at least the lifecycle and quality rows.
- Strategy shows the execution plan lines on the chart.
- No compile errors or missing-source warnings.

### Automated check

Run the canonical repo-side gate:

```bash
npm run tv:preflight:smc-mainline
```

This validates auth, UI state, compile, binding count, binding labels, and
runtime for all three surfaces against the
[product-cut manifest](../artifacts/tradingview/smc_product_cut_manifest.json).

## Troubleshooting

### Sources show `close` or a wrong series

Every binding channel defaults to `close` until explicitly connected. If any
Dashboard or Strategy row shows flat or unexpected data, check that the
`input.source(...)` channel is bound to the correct Core BUS export — not to
`close` or to another indicator.

### Binding count mismatch

The preflight gate reports the expected and actual binding count. If the
Dashboard reports fewer than 58 or the Strategy fewer than 8, some channels
are still on their default source. Rebind the missing channels top-to-bottom.

### Binding order drift

Renaming or reordering BUS labels manually can break the manifest contract.
If binding drift is suspected, run the contract tests first:

```bash
python -m pytest tests/test_smc_bus_manifest_contract.py tests/test_smc_bus_v2_semantics.py -v
```

Do not rename source labels in Pine code without updating the manifest.

### Recompile after settings changes

Some TradingView changes (timeframe, symbol) require a recompile. If outputs
freeze, remove and re-add the affected script and rebind.

## What Is Not Part Of This Setup

- **Legacy monolith (`SMC++.pine`):** frozen compatibility anchor, separate
  regression path. Not part of the active mainline.
- **Context and Overlay scripts** (`SMC_*_Context`, `SMC_*_Overlay`,
  `SMC_HTF_Confluence`, `SMC_Liquidity_Structure`): companion or internal
  layers, not required for the mainline.
- **Micro-library publish workflow:** covered in
  [tradingview-micro-library-publish.md](tradingview-micro-library-publish.md).
- **TradingView automation setup** (Playwright, storage state, auth): covered
  in the [project README](../README.md).

## Canonical References

| Resource | Path |
| --- | --- |
| Binding manifest (Python) | [../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py) |
| Product-cut manifest (JSON) | [../artifacts/tradingview/smc_product_cut_manifest.json](../artifacts/tradingview/smc_product_cut_manifest.json) |
| Strategy guide | [TRADINGVIEW_STRATEGY_GUIDE.md](TRADINGVIEW_STRATEGY_GUIDE.md) |
| Product-cut background | [smc-lite-pro-product-cut.md](smc-lite-pro-product-cut.md) |
| R1.1 migration details | [smc-tradingview-r1-1-migration-and-operator-guide.md](smc-tradingview-r1-1-migration-and-operator-guide.md) |
| Manual validation runbook | [tradingview-manual-validation-runbook.md](tradingview-manual-validation-runbook.md) |
| Validation status | [smc-validation-status.md](smc-validation-status.md) |
