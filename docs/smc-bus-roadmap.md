# SMC Bus Roadmap

This document records the architecture decision after the current bus-v2 audit in [smc-bus-v2-audit.md](smc-bus-v2-audit.md).

Current repo state is already partway through that transition:

- the old compat exports (`HardGatesPackA/B`, `QualityPackA/B`, `EnginePack`) have been retired from the producer
- the active dashboard now binds the full 64-channel producer contract directly
- `ModulePackA` has already been cut into direct rows (`SdConfluenceRow`, `SdOscRow`, `VolRegimeRow`, `VolSqueezeRow`)
- `ModulePackB` has already been retired into `VolExpandRow`, `DdviRow`, `StretchSupportMask`, and `LtfBiasHint`
- `ModulePackC`, `ModulePackD`, and `ReadyStrictPack` have now been retired from the active producer contract
- `DebugStateRow` has already been retired because the dashboard now derives that state locally
- the remaining dashboard-oriented transport is now concentrated in explicit support-code channels (`LtfDeltaState`, `SafeTrendState`, `MicroProfileCode`, `ReadyBlockerCode`, `StrictBlockerCode`, `VolExpansionState`, `DdviContextState`)

This document therefore records the active bus-v2 endpoint and the trigger conditions for any later bus-v3 work, not an open redesign backlog.

## Current Decision

The current support-code surface is the terminal bus-v2 endpoint for this repo state.

- Freeze the active 64-channel bus-v2 contract as the supported dashboard transport.
- Do not add new packs or widen the support-code surface just to preserve old dashboard shapes.
- Treat a later bus-v3 as a separate architecture track that opens only if a second real consumer or richer parity requirement appears.

## Option A: Keep Bus v2 As A Dashboard Transport

### Option A Definition

Bus v2 remains what it currently is:

- a producer-exported transport layer for the current dashboard shape
- row-code and support-code oriented
- optimized for reconstructing the current display in [SMC_Long_Dip_Dashboard.pine](../SMC_Long_Dip_Dashboard.pine#L719-L768)

### Option A Advantages

1. No immediate redesign pressure.
2. The current dashboard continues to reconstruct its rows from direct rows and explicit support-code channels.
3. The strategy remains unaffected because it does not use the dashboard packs.
4. The current test surface is easier to keep stable because the contract is tied to concrete row outputs.

### Option A Disadvantages

1. Producer and dashboard remain tightly coupled.
2. Future dashboard wording or layout changes will continue to force producer changes.
3. Other consumers cannot reuse most packed channels without duplicating dashboard semantics.
4. The explicit support-code surface still blurs domain logic, UI wording, and display grouping.
5. The support codes preserve category results but not the richer numeric detail that existed in [SMC++.pine](../SMC++.pine#L5968-L6264).

### Channels That Fit Option A Well

These already behave acceptably as transport for the current UI:

- `BUS SdConfluenceRow`
- `BUS SdOscRow`
- `BUS VolRegimeRow`
- `BUS VolSqueezeRow`
- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`

The previous compat exports and pack-retirement cuts have already landed. Since
that cut the producer has re-grown to `64 / 64` plots exporting a full
`64`-channel hidden bus: `LeanPackA`, `LeanPackB`, and the five `Preset*`
Quickstart-contract channels (`PresetClassCode`, `PresetRvolMin`,
`PresetHtfBiasMin`, `PresetFvgQualGate`, `PresetVolRegimeDef`) were added after
this document first recorded `58 / 64`. The engine bus is therefore now at the
TradingView 64-plot cap with **zero** free producer slots. The executed
`ModulePackB` replacement path is documented in
[smc-module-pack-b-direct-cut-design.md](smc-module-pack-b-direct-cut-design.md).
The exact 64-channel surface is frozen by
[test_smc_bus_v2_freeze.py](../tests/test_smc_bus_v2_freeze.py).

### Risk Envelope Under Option A

The main risk is not strategy breakage. The main risk is that every dashboard iteration hardens UI coupling into the producer.

## Option B: Later Introduce Bus v3 As A Domain Bus

### Option B Definition

A later bus-v3 would export domain states and levels rather than dashboard rows. The dashboard would own more of the final presentation mapping.

That means:

- keep stable booleans, enums, numeric levels, and directly interpretable metrics on the bus
- stop exporting row-specific `status + reason` bundles as the primary contract
- let the consumer derive row wording and grouping from domain signals

### Option B Advantages

1. Cleaner producer/consumer separation.
2. Multiple consumers can reuse the same domain channels for different UIs or strategies.
3. Dashboard redesigns become cheaper because the producer no longer encodes row layouts.
4. Numeric and level-rich information can be preserved instead of flattened to category text.
5. The resulting contract is easier to reason about as a business interface.

### Option B Disadvantages

1. Requires a deliberate redesign rather than incremental patching.
2. Dashboard reconstruction logic becomes more substantial on the consumer side.
3. A transition phase must be managed carefully to avoid accidental parity regressions.
4. Semantic tests become more important because parity will depend on consumer derivation rules.

### Channels That Would Safely Survive Into Option B

These are already suitable as domain channels and should remain stable even if a later bus-v3 is introduced:

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
- `BUS TrendPack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

These would likely survive in concept but should be reviewed for shape:

- `BUS StateCode`
- `BUS MetaPack`

### UI-Near Support Channels That Option B Would Eventually Replace

These are the strongest replacement candidates because they are row-oriented transport rather than reusable business channels:

- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`

`ModulePackA`, `ModulePackB`, `ModulePackC`, `ModulePackD`, and
`ReadyStrictPack` have already been retired in favor of direct rows and
support/detail channels. `StretchSupportMask`, `LtfBiasHint`, and
`ObjectsCountPack` still cover producer-owned support state, while the final
module and blocker semantics now travel as explicit support codes rather than
as packed dashboard transport.
`MicroProfileCode` carries modifier presence inline, so no separate micro
modifier support channel remains on the active bus.
`Debug Flags` and `Long Debug` are now derived locally from dashboard mirror
toggles, and `Long Triggers` and `Risk Plan` are now derived locally from
executable and plan-level channels instead of traveling over dedicated transport rows.

### Concrete Next Slice

1. No further bus-v2 slice is active
   The packed rebuild lane is complete and the remaining support-code channels
   are now frozen as the bus-v2 endpoint.
2. Bus-v3 is now scheduled, not conditional (trigger met — see below).

## Bus v3 (Context Bus) — Trigger Met, Scope Reserved

The bus-v3 opening condition from Option B ("a second real consumer needs the
same producer data without dashboard wording") is now **met**, on two counts:

- **A second real consumer already exists.** `SMC_Breakout_Overlay.pine` binds
  the engine bus directly (`BUS SchemaVersion`/`ZoneActive`/`Trigger`/
  `Invalidation` plus the zone/plan/quality detail channels) as of #3631/#3634/
  #3636 — an independent consumer that is not the dashboard.
- **Richer domain parity is now wanted.** Four context overlays
  (`SMC_Structure_Context`, `SMC_Imbalance_Context`, `SMC_Liquidity_Context`,
  `SMC_Liquidity_Structure`) currently read a dead per-symbol snapshot library
  and need live, numeric, per-bar domain state (structure, FVG/BPR/void,
  zones/sweeps/pools) that the row-oriented v2 bus does not carry.

Critically, the engine bus is at the **64/64 TradingView plot cap** with zero
free slots, so v3 **cannot** widen v2 even in principle. Bus v3 is therefore a
**separate domain-first producer**, not an extension of the engine bus.

### Reserved scope (contract NOT yet frozen)

These identifiers are reserved now so nothing collides; the channel contract
itself is defined later, consumer-driven, from validated library frames — not
frozen up front.

| Item | Reserved name |
|------|---------------|
| Producer script | `SMC_Context_Bus.pine` |
| Live context library | `SMC++/smc_context_engine_private.pine` (imports `smc_engine_private`) |
| Schema version | `8001` (distinct from engine `7001`) |
| Channel label prefix | `CTX ` (e.g. `CTX StructureState`) — must never appear on the v2 engine bus |
| Channel budget | ≤ 60 direct channels, ≥ 4 reserve slots (of the 64 cap) |

The v2 engine + strategy surface is byte-frozen by
[test_smc_bus_v2_freeze.py](../tests/test_smc_bus_v2_freeze.py) for the entire
duration of the v3 build, including a guard that no `CTX ` label leaks into v2.

## Recommendation

The recommended path is:

1. Freeze the current bus-v2 explicitly as a dashboard transport layer.
2. Treat the `ModulePackA`, `ModulePackB`, `ModulePackC`, `ModulePackD`, and
   `ReadyStrictPack` retirement plus the local `DebugFlagsRow`,
   `LongTriggersRow`, `RiskPlanRow`, and `QualityBoundsPack` localization as
   the completed transport cleanup that reshaped the contract, which has since
   re-grown to the frozen `64 / 64` endpoint.
3. Keep semantic tests pinned to the manifest so retired exports do not drift back into the contract.
4. Do not add new packs, new standalone support rows, or wider bus-v2 transport just to preserve old shapes.
5. If additional consumers or richer dashboard parity are needed later, start a separate domain-first bus-v3 instead of continuing to grow bus-v2.

This recommendation avoids churn now while keeping the architecture honest.
