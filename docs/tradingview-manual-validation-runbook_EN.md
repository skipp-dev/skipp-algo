# TradingView Manual Validation Runbook (EN)

English companion to [tradingview-manual-validation-runbook.md](tradingview-manual-validation-runbook.md).

## Purpose

This runbook describes the external manual TradingView runtime validation for the current split-state.

The validation covers:

1. Producer: [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
2. Dashboard consumer: [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
3. Strategy consumer: [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)

The goal is a clear pass/fail decision for the current TradingView contract state without making ad-hoc changes to production logic.

## Required Files

1. [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine)
2. [../SMC_Dashboard.pine](../SMC_Dashboard.pine)
3. [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine)
4. [tradingview-validation-checklist.md](tradingview-validation-checklist.md)
5. [tradingview-manual-validation-report-template_EN.md](tradingview-manual-validation-report-template_EN.md)

## Companion Release-Layer References

1. [../scripts/tv_publish_micro_library.ts](../scripts/tv_publish_micro_library.ts)
2. [../scripts/tv_preflight.ts](../scripts/tv_preflight.ts)
3. [../automation/tradingview/lib/tv_shared.ts](../automation/tradingview/lib/tv_shared.ts)

## Recommended Order In TradingView

1. Open and compile the core.
2. Add the dashboard and bind all 26 `source` inputs to the core.
3. Add the strategy and bind all 8 `source` inputs to the core.
4. Execute the five validation scenarios on the same symbol and timeframe.
5. Record all observations directly in the report template.

## Producer Validation

### Producer Steps

1. Open [../SMC_Core_Engine.pine](../SMC_Core_Engine.pine) in TradingView.
2. Compile the script on the target chart.
3. Confirm that the script remains loaded without compile-time or runtime errors.
4. In the `source` picker of a downstream consumer, confirm that the hidden bus series are selectable.

### Producer Expected Observations

1. The script compiles without errors.
2. No visible runtime errors remain in the chart overlay.
3. The following 26 series are selectable as sources:

- `BUS ZoneActive`
- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`
- `BUS SourceKind`
- `BUS StateCode`
- `BUS TrendPack`
- `BUS MetaPack`
- `BUS HardGatesPackA`
- `BUS HardGatesPackB`
- `BUS QualityPackA`
- `BUS QualityPackB`
- `BUS QualityBoundsPack`
- `BUS ModulePackA`
- `BUS ModulePackB`
- `BUS ModulePackC`
- `BUS ModulePackD`
- `BUS EnginePack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

### Producer Pass/Fail Criteria

Pass:

1. Core compiles.
2. No runtime error is visible.
3. All 26 series are selectable.

Fail:

1. Compile error.
2. Runtime error.
3. Missing or incorrectly named bus series.

## Dashboard Validation

### Dashboard Steps

1. Add [../SMC_Dashboard.pine](../SMC_Dashboard.pine) to the same chart.
2. Bind all 26 `input.source()` fields exactly to the core series.
3. Check visibility and response of the following sections:

- Lifecycle
- Hard Gates
- Quality
- Modules
- Engine

1. Check the five scenarios from [tradingview-validation-checklist.md](tradingview-validation-checklist.md) in order.

### Dashboard Expected Observations

1. The dashboard compiles without errors.
2. All 26 bindings are fully selectable.
3. The dashboard remains visible.
4. The sections respond plausibly to the core state.

### Dashboard Scenario Validation

- Neutral / no zone

Expected:

`Pullback Zone = No Long Zone`
`Long Setup = No Setup`
`Exec Tier = n/a`
`Long Visual = Neutral`

- Armed

Expected:

`Long Setup = Armed | <source>`
`Exec Tier = Armed`
`Setup Age = armed fresh` or `armed stale`

- Confirmed

Expected:

`Long Setup = Confirmed | <source>`
`Exec Tier = Confirmed`
`Setup Age = confirm fresh` or `confirm stale`

- Ready

Expected:

`Long Visual = Ready`
`Exec Tier = Ready`, `Best`, or `Strict`
`Ready Gate = Ready`
Risk-plan levels are plausible when active

- Invalidated

Expected:

`Long Setup = Invalidated`
`Long Visual = Fail`
`Strict Gate` is not shown as passed

### Dashboard Pass/Fail Criteria

Pass:

1. Dashboard compiles.
2. All 26 bindings can be assigned.
3. All five scenarios show the expected response.
4. No internal contradictions exist between lifecycle, exec tier, setup age, and risk lines.

Fail:

1. Missing binding.
2. Binding points to the wrong series.
3. A section is missing or does not respond.
4. Scenario behavior is inconsistent with the checklist.

## Strategy Validation

### Strategy Steps

1. Add [../SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine) to the same chart.
2. Bind the 8 `input.source()` fields exactly to the core series.
3. Validate `Entry Mode`, `Trigger`, `Invalidation`, `Stop`, and `Targets` against the documented contract.

### Strategy Expected Observations

1. The strategy compiles without errors.
2. The following 8 bindings are fully selectable:

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

1. The strategy depends only on these 8 channels.
2. Trigger and invalidation are consistent.
3. Stop and take-profit behavior is consistent with the risk structure.

### Strategy Pass/Fail Criteria

Pass:

1. Strategy compiles.
2. All 8 bindings can be assigned.
3. Entry-mode behavior is consistent with the respective lifecycle channel.
4. Trigger, invalidation, stop, and target logic are plausible and internally consistent.

Fail:

1. Strategy does not compile.
2. An expected binding is missing.
3. Entry-mode behavior is inconsistent with the core.
4. Risk levels are contradictory.

## Operator Notes

1. Validate all three scripts on the same symbol and timeframe.
2. Record deviations as observations only; do not make ad-hoc logic changes during the run.
3. Save a screenshot after each fail when possible.
4. Close the run using [tradingview-manual-validation-report-template_EN.md](tradingview-manual-validation-report-template_EN.md).
