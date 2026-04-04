# ModulePackB Direct-Cut Design

## Goal

This note turns the current `ModulePackB` blocker analysis into a concrete
replacement shape.

It answers two follow-up questions:

1. Where can the producer recover the missing plot budget?
2. What is the smallest safe replacement surface for `ModulePackB`?

## Status

Implemented in the active split contract.

- Visible `Session VWAP`, `EMA Fast`, and `EMA Slow` overlays now render
   through line tails instead of `plot()`.
- `BUS ModulePackB` is retired.
- The producer now exports `BUS VolExpandRow`, `BUS DdviRow`,
   `BUS StretchSupportMask`, and `BUS LtfBiasHint`.
- The live producer/dashboard contract is now `62` hidden BUS channels and
   remains at `62 / 64` total `plot()` calls.

## Budget Recovery Candidate

The pre-cut producer used:

- `62` total `plot()` calls
- `59` hidden BUS plots
- `3` visible overlay plots

Those three visible plots are:

- `Session VWAP`
- `EMA Fast`
- `EMA Slow`

They are the cleanest recovery target because:

- they are presentation-only overlays, not transport channels
- compact mode already treats them as suppressible secondary visuals
- their gating logic stays active even if the chart overlay moves off
  `plot()`
- `BUS SessionVwap` already preserves the VWAP value on the detail surface

Those three overlays have now moved to object-based visuals. After the cut, the
producer uses:

- `62` total `plot()` calls
- `62` hidden BUS plots
- `2` free plot slots

No current hidden BUS channel offers an equally low-risk savings path. The
remaining hidden plots all belong to the active producer contract, the dashboard
detail surface, or the lean transport.

## Minimal Replacement Surface

After the 3-plot recovery, the active producer replaced `BUS ModulePackB` with these four producer
channels:

- `BUS VolExpandRow`
- `BUS DdviRow`
- `BUS StretchSupportMask`
- `BUS LtfBiasHint`

That keeps row ownership with the producer wherever the semantics still depend
on producer-local state:

- `Vol Expand` stays a direct producer row
- `DDVI` stays a direct producer row
- `Stretch` gets a compact producer-owned support mask
- `LTF Bias` reuses existing detail channels and only exports the missing
  threshold input

## Why These Four Channels

### VolExpandRow

`Vol Expand` has no equivalent active detail channel.

`BUS VolaGateRow` and `BUS VolRegimeRow` are related context, but neither one
publishes the expansion verdict from `resolve_bus_vol_expand_row(...)`.

The clean fix is a direct row export.

### DdviRow

`DDVI` also has no equivalent active detail channel.

Its current semantics still belong to the producer through
`resolve_bus_ddvi_row(...)`, so the clean fix is another direct row export.

### StretchSupportMask

`BUS StretchZ` already provides the numeric companion for the dashboard, but it
does not carry the state needed to rebuild the row safely.

The missing producer-owned state can fit into one compact mask:

- bit 0: `use_stretch_context`
- bit 1: `in_lower_extreme`
- bit 2: `lower_extreme_recent`
- bit 3: `anti_chase_ok_ready`
- bit 4: `anti_chase_ok_entry_best`

With `BUS StretchZ` plus this mask, the dashboard can reproduce the current row
without reimplementing hidden producer settings.

### LtfBiasHint

`LTF Bias` does not need a full second support mask if `ModulePackC.slot0`
(`LTF Delta`) stays on the bus.

The current bus already covers most of the support state:

- `off` through `LTF Delta` reason `1`
- `n/a` through `LTF Delta` reasons `2` and `4`
- `price-only` through `LTF Delta` reason `3`
- the measured bullish share through `BUS LtfBullShare`

The only missing producer-owned input for exact row reconstruction is the
threshold in `ltf_bias_hint`.

The smallest safe addition is therefore a direct numeric export:

- `BUS LtfBiasHint`

## Consumer Reconstruction Rules

### Stretch

Keep `BUS StretchZ` as the numeric detail channel and derive the row from the
new support mask:

1. If bit `0` is clear, render `off`.
2. Else if `StretchZ` is `na`, render `n/a`.
3. Else if bit `4` and bit `1` are set, render `lower extreme`.
4. Else if bit `4` and bit `2` are set, render `recent extreme`.
5. Else if bit `3` is set, render `anti-chase ok`.
6. Else render `chasing`.

This reproduces the current row-state ladder from
`resolve_bus_stretch_row(...)`.

### LTF Bias

Keep `BUS LtfBullShare` as the numeric detail channel and reuse the existing
`LTF Delta` row from `ModulePackC`:

1. If `LTF Delta` is `off`, render `off`.
2. Else if `LTF Delta` is `n/a`, render `n/a`.
3. Else if `LTF Delta` is `no-vol` and `LtfBullShare >= LtfBiasHint`, render
   the bullish price-only state.
4. Else if `LtfBullShare >= LtfBiasHint`, render the bullish state.
5. Else if `LtfBullShare >= 0.50`, render the balanced state.
6. Else render the bearish state.

This preserves the producer-owned threshold while reusing the existing LTF
support surface.

## Budget Math

Starting point:

- `62` total plots
- `59` hidden BUS plots

Step 1: retire the three visible overlay `plot()` calls.

- `59` total plots
- `59` hidden BUS plots

Step 2: remove `BUS ModulePackB`.

- `58` total plots
- `58` hidden BUS plots

Step 3: add `BUS VolExpandRow`, `BUS DdviRow`, `BUS StretchSupportMask`, and
`BUS LtfBiasHint`.

- `62` total plots
- `62` hidden BUS plots

Net result:

- `ModulePackB` is retired
- the producer stays within TradingView's `64`-plot limit
- two free plot slots remain after the cut

## Guardrails

1. Do not repurpose `BUS VolaGateRow` as `Vol Expand`.
2. Do not infer `DDVI` from downstream Ready/Strict gate outcomes.
3. Do not derive `Stretch` from `StretchZ` alone.
4. Do not derive `LTF Bias` from `LtfBullShare` alone.
5. Keep `BUS SessionVwap` active even if the visible VWAP overlay moves off
   `plot()`.

## Executed Implementation Order

1. Replaced the visible `Session VWAP`, `EMA Fast`, and `EMA Slow` overlays
   with non-plot visuals.
2. Added `BUS VolExpandRow`, `BUS DdviRow`, `BUS StretchSupportMask`, and
   `BUS LtfBiasHint` to the producer and manifest.
3. Taught the dashboard to rebuild `Stretch` and `LTF Bias` from the new
   support surface.
4. Removed `BUS ModulePackB` from the producer, manifest, and dashboard inputs.
5. Reran manifest, consumer, and semantic regression for the new contract.
