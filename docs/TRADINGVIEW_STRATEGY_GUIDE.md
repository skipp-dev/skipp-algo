# SMC Execution Guide

## Purpose

This guide documents `SMC_Long_Strategy.pine` as the `SMC Execution` surface of
the active SMC TradingView mainline.

The active mainline is:

1. [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) as the only active
  producer and the default `SMC Core` first-run surface.
2. [../SMC_Dashboard.pine](../SMC_Dashboard.pine) as the `SMC Decision Board`
  companion.
3. [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine) as the `SMC Execution`
  surface on the frozen 8-channel executable contract.

The product-cut background and the current guardrails are documented in
[smc-lite-pro-product-cut.md](smc-lite-pro-product-cut.md).

## What The Strategy Is

- A thin execution wrapper around linked core outputs, not a second producer.
- The TradingView execution surface for backtests, alerts, and execution-plan
  display.
- A surface with a small visible setup layer plus operator-only `input.source()`
  bindings.
- Bound to the executable subset of the core outputs rather than to the full
  dashboard transport.

## What The Strategy Is Not

- It is not a new Lite surface.
- It is not a second signal engine beside the core.
- It is not a replacement for `SMC_Core_Engine.pine` on a clean Lite chart.
- It does not auto-execute broker orders by itself; unattended execution still
  requires an external alert-to-broker bridge outside the default repo path.

## Required Chart Setup

1. Add [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) to the chart.
2. Add [../SMC_Dashboard.pine](../SMC_Dashboard.pine) only if Pro diagnostics
   are needed.
3. Add [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine) to the same chart.
4. Bind the strategy sources top-to-bottom against the matching core BUS plots.

The canonical binding source is
[../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py) and its
machine-readable artifact
[../artifacts/tradingview/smc_product_cut_manifest.json](../artifacts/tradingview/smc_product_cut_manifest.json).

## Frozen Executable Contract

`SMC_Long_Strategy.pine` binds exactly these eight channels:

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

This 8-channel wrapper contract stays frozen unless a separate product-cut
decision explicitly reopens it.

## Visible Wrapper Controls

The visible product surface of the strategy is intentionally small:

- `Entry Stage` (`entry_mode`) selects which already-exported execution
  tier the surface uses.
- `Minimum Setup Quality` (`min_quality_score`) adds a wrapper-level threshold
  before the linked core setup can stage an execution plan.
- `Profit Target (R)` (`take_profit_r`) controls the wrapper take-profit plan
  distance.
- `Enable Profit Target` (`use_take_profit`) toggles the wrapper take-profit
  behavior.

These controls change wrapper behavior only. They do not widen the linked core
output contract and do not introduce a second logic family.

In TradingView the settings surface should expose `Execution Setup` and
`Trade Plan` before the two `Expert Mapping` groups.

## Chart Outputs

The strategy exposes the current execution plan with product terminology on the
chart:

- `Entry Price`
- `Stop Loss`
- `Profit Target`

Those plots make the wrapper plan legible without turning the strategy into a
second diagnostics surface.

## Validation Path

Use the automated mainline gate first:

```bash
npm run tv:preflight:smc-mainline
```

That is the canonical repo-side TradingView check for the active mainline path
`SMC_Core_Engine.pine` + `SMC_Dashboard.pine` + `SMC_Long_Strategy.pine`.

For an external or independent cross-check, use:

- [tradingview-manual-validation-runbook.md](tradingview-manual-validation-runbook.md)
- [tradingview-validation-checklist.md](tradingview-validation-checklist.md)
- [smc-validation-status.md](smc-validation-status.md)

## Post-Cut Guardrails

- `SMC_Core_Engine.pine` remains the only Lite-primary surface.
- A dedicated Lite consumer is intentionally deferred until it can exist
  without a logic fork, a second producer, or a new binding workflow.
- `SMC_Long_Strategy.pine` remains the `SMC Execution` surface on the frozen
  8-channel contract.
- Dashboard-only or Pro-only cleanup work must not silently widen the Lite
  contract or mutate the strategy bindings.
- Any later Pro-only transport simplification belongs to the separate roadmap
  in [smc-bus-roadmap.md](smc-bus-roadmap.md), not to the active mainline
  release path.

## Operator Notes

- Bind sources strictly top-to-bottom; do not rename or reorder BUS labels.
- Use the dashboard for companion diagnostics and the strategy for
  execution/backtest.
- If binding drift is suspected, run the contract tests before touching source
  labels or guide text.
- The authoritative operator workflow is further detailed in
  [smc-tradingview-r1-1-migration-and-operator-guide.md](smc-tradingview-r1-1-migration-and-operator-guide.md).
