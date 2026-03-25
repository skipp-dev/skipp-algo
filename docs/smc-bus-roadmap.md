# SMC Bus Roadmap

This document frames the architecture choice after the current bus-v2 audit in [smc-bus-v2-audit.md](smc-bus-v2-audit.md).

No implementation decision is taken here. This is a decision template.

## Option A: Keep Bus v2 As A Dashboard Transport

### Definition

Bus v2 remains what it currently is:

- a producer-exported transport layer for the current dashboard shape
- row-code and packed-state oriented
- optimized for reconstructing the current display in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L719-L768)

### Advantages

1. No immediate redesign pressure.
2. The current dashboard continues to reconstruct its rows from the existing packs.
3. The strategy remains unaffected because it does not use the dashboard packs.
4. The current test surface is easier to keep stable because the contract is tied to concrete row outputs.

### Disadvantages

1. Producer and dashboard remain tightly coupled.
2. Future dashboard wording or layout changes will continue to force producer changes.
3. Other consumers cannot reuse most packed channels without duplicating dashboard semantics.
4. The current row packs blur domain logic, UI wording, and display grouping.
5. The row packs preserve category results but not the richer numeric detail that existed in [SMC++.pine](../SMC++.pine#L5968-L6264).

### Channels That Fit Option A Well

These already behave acceptably as transport for the current UI:

- `BUS HardGatesPackA`
- `BUS HardGatesPackB`
- `BUS QualityPackA`
- `BUS QualityPackB`
- `BUS ModulePackA`
- `BUS ModulePackB`
- `BUS ModulePackC`
- `BUS ModulePackD`
- `BUS EnginePack`

### Risk Envelope Under Option A

The main risk is not strategy breakage. The main risk is that every dashboard iteration hardens UI coupling into the producer.

## Option B: Later Introduce Bus v3 As A Domain Bus

### Definition

A later bus-v3 would export domain states and levels rather than dashboard rows. The dashboard would own more of the final presentation mapping.

That means:

- keep stable booleans, enums, numeric levels, and directly interpretable metrics on the bus
- stop exporting row-specific `status + reason` bundles as the primary contract
- let the consumer derive row wording and grouping from domain signals

### Advantages

1. Cleaner producer/consumer separation.
2. Multiple consumers can reuse the same domain channels for different UIs or strategies.
3. Dashboard redesigns become cheaper because the producer no longer encodes row layouts.
4. Numeric and level-rich information can be preserved instead of flattened to category text.
5. The resulting contract is easier to reason about as a business interface.

### Disadvantages

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
- `BUS QualityBoundsPack`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

These would likely survive in concept but should be reviewed for shape:

- `BUS StateCode`
- `BUS MetaPack`

### UI-Near Packs That Option B Would Eventually Replace

These are the strongest replacement candidates because they are row-oriented transport rather than reusable business channels:

- `BUS HardGatesPackA`
- `BUS HardGatesPackB`
- `BUS QualityPackA`
- `BUS QualityPackB`
- `BUS ModulePackA`
- `BUS ModulePackB`
- `BUS ModulePackC`
- `BUS ModulePackD`
- `BUS EnginePack`

## Recommendation

The recommended path is:

1. Treat the current bus-v2 explicitly as a dashboard transport layer.
2. Freeze the current transport contract and secure it with semantic tests.
3. Do not expand the row packs further.
4. If additional consumers or richer dashboard parity are needed later, design a separate domain-first bus-v3 instead of continuing to grow UI packs.

This recommendation avoids churn now while keeping the architecture honest.