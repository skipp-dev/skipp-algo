# ModulePackB Plot-Neutral Path

## Goal

This note defines what would count as a safe plot-neutral replacement of
`BUS ModulePackB`.

Status: historical pre-cut analysis. `BUS ModulePackB` has since been retired
through the executed path in
[smc-module-pack-b-direct-cut-design.md](smc-module-pack-b-direct-cut-design.md).

The current pack still owns four dashboard module rows:

- `Vol Expand`
- `Stretch`
- `DDVI`
- `LTF Bias`

## Current Row Ownership

Before the cut, `SMC_Core_Engine.pine` published `ModulePackB` through these helpers:

- `resolve_bus_vol_expand_row(...)`
- `resolve_bus_stretch_row(...)`
- `resolve_bus_ddvi_row(...)`
- `resolve_bus_ltf_bias_row(...)`

Before the cut, the dashboard unpacked those four row codes from a single hidden plot.

## Existing Reusable Bus Material

Some of the `ModulePackB` display already has detail companions on the bus:

- `Stretch` already has `BUS StretchZ`
- `LTF Bias` already has `BUS LtfBullShare`
- `LTF Bias` also overlaps partially with `LTF Delta` and `Volume Data`

That overlap is useful, but it is not yet enough for a clean full cut.

## Exact Blockers

### Vol Expand

There is no equivalent domain/detail channel for `Vol Expand` on the active
bus.

`BUS VolaGateRow` and `BUS VolRegimeRow` are not substitutes:

- `VolaGateRow` describes the volatility gate state
- `VolRegimeRow` describes regime safety
- `Vol Expand` needs the separate momentum/spread expansion verdict from
  `resolve_bus_vol_expand_row(...)`

### Stretch

`BUS StretchZ` exports the numeric z-score, but the row semantics still depend
on hidden runtime decisions that are not on the bus:

- `use_stretch_context`
- `in_lower_extreme`
- `lower_extreme_recent`
- `anti_chase_ok_entry_best`
- `anti_chase_ok_ready`

Deriving the row from `StretchZ` alone would recreate engine logic in the
dashboard and would drift if the stretch thresholds or recent-extreme settings
change.

### DDVI

There is no equivalent domain/detail channel for `DDVI` on the active bus.

The current row needs producer-owned state that is not exported separately:

- `use_ddvi_context`
- `ddvi_bias_ok`
- `ddvi_bull_divergence_any`
- `ddvi_lower_extreme_context`

### LTF Bias

`BUS LtfBullShare` is useful, but it is still not sufficient for exact row
reconstruction.

The current row also depends on:

- `show_dashboard_ltf_eff`
- `ltf_sampling_active`
- `ltf_price_ok`
- `ltf_price_only`
- `ltf_bias_hint`

Some of that context leaks through existing channels:

- `ModulePackC.slot0` (`LTF Delta`) distinguishes `off`, `n/a`, `price-only`,
  and signed delta cases
- `BUS VolumeDataRow` distinguishes `LTF no-vol` and `price-only LTF`

But the exact bullish-vs-balanced threshold still depends on `ltf_bias_hint`,
which is not exported independently.

## Rejected Shortcuts

These shortcuts are intentionally out of scope because they would weaken the
split contract:

1. Do not derive `Stretch` from `StretchZ` alone.
2. Do not derive `LTF Bias` from `LtfBullShare` alone.
3. Do not treat `VolaGateRow` as a synonym for `Vol Expand`.
4. Do not infer `DDVI` from Ready/Strict blockers or other downstream gates.

## Safe Paths

### 1. Plot-Neutral Preparation Only

Keep `ModulePackB` active, but treat `StretchZ` and `LtfBullShare` as the
canonical detail companions that already enrich the dashboard.

This improves interpretation, but it is not yet a cut.

### 2. Plot-Neutral Structural Replacement

A true plot-neutral replacement requires one-for-one transport of the missing
semantics that are not already covered by active detail channels.

With the current bus, that shape does not exist yet.

At minimum, the producer would still need an explicit owner for:

- `Vol Expand`
- `DDVI`
- the missing `Stretch` support state
- the missing `LTF Bias` threshold/support state

### 3. Direct-Row Cut After New Savings

If more producer plots are retired later, the clean direct-row option becomes:

- export `VolExpandRow` directly
- export `DdviRow` directly
- decide whether `Stretch` and `LTF Bias` get explicit support channels or stay
  packed until a later domain-first pass

The current best candidate for that follow-up now lives in
[smc-module-pack-b-direct-cut-design.md](smc-module-pack-b-direct-cut-design.md).
It uses the three visible overlay plots as the budget-recovery path and keeps
the new producer surface to `VolExpandRow`, `DdviRow`, `StretchSupportMask`,
and `LtfBiasHint`.

## Historical Decision

At the time of this note, `ModulePackB` was still the next C9 candidate, but it
was not yet a safe full cut. The blocker was missing domain/support material on
the current bus, not decoder effort.

That blocker set has since been resolved by the executed direct-cut path:

- visible overlay `plot()` usage was recovered first
- `ModulePackB` was replaced by `VolExpandRow`, `DdviRow`,
  `StretchSupportMask`, and `LtfBiasHint`
- the dashboard now rebuilds `Stretch` and `LTF Bias` from explicit
  producer-owned support channels instead of ad-hoc consumer inference
