# SMC Bus Target Matrix

This matrix translates the audit in [smc-bus-v2-audit.md](smc-bus-v2-audit.md) into a binding planning table without changing the current implementation.

Consumer references:

- Dashboard bindings: [SMC_Dashboard.pine](../SMC_Dashboard.pine#L7-L29)
- Strategy bindings: [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14)
- Producer exports: [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5526-L5551)

| Channel | Current Status | Fachliche Rolle | Abhängige Consumer | Risiko bei Änderung | Geplanter Zielstatus |
| --- | --- | --- | --- | --- | --- |
| `BUS ZoneActive` | aktiv | Zone context boolean | Dashboard | mittel | behalten |
| `BUS Armed` | aktiv | lifecycle boolean | Dashboard, Strategy | hoch | behalten |
| `BUS Confirmed` | aktiv | lifecycle boolean | Dashboard, Strategy | hoch | behalten |
| `BUS Ready` | aktiv | lifecycle boolean | Dashboard, Strategy | hoch | behalten |
| `BUS EntryBest` | aktiv | entry tier boolean | Dashboard, Strategy | hoch | behalten |
| `BUS EntryStrict` | aktiv | entry tier boolean | Dashboard, Strategy | hoch | behalten |
| `BUS Trigger` | aktiv | executable trigger level | Dashboard, Strategy | hoch | behalten |
| `BUS Invalidation` | aktiv | executable invalidation level | Dashboard, Strategy | hoch | behalten |
| `BUS QualityScore` | aktiv | numeric quality metric | Dashboard, Strategy | hoch | behalten |
| `BUS SourceKind` | aktiv | setup provenance enum | Dashboard | mittel | behalten |
| `BUS StateCode` | aktiv | compressed lifecycle summary | Dashboard | mittel | später aufsplitten |
| `BUS TrendPack` | aktiv | current plus HTF trend states | Dashboard | mittel | behalten |
| `BUS MetaPack` | aktiv | freshness, source-state, reclaim, zone classes | Dashboard | mittel | später aufsplitten |
| `BUS HardGatesPackA` | aktiv | hard-gate row transport | Dashboard | mittel | ersetzen |
| `BUS HardGatesPackB` | aktiv | hard-gate and quality row transport | Dashboard | mittel | ersetzen |
| `BUS QualityPackA` | aktiv | quality row transport | Dashboard | mittel | ersetzen |
| `BUS QualityPackB` | aktiv | quality row transport | Dashboard | mittel | ersetzen |
| `BUS QualityBoundsPack` | aktiv | score min/max support values | Dashboard | niedrig | behalten |
| `BUS ModulePackA` | aktiv | module row transport | Dashboard | mittel | ersetzen |
| `BUS ModulePackB` | aktiv | module row transport | Dashboard | mittel | ersetzen |
| `BUS ModulePackC` | aktiv | module row transport | Dashboard | mittel | ersetzen |
| `BUS ModulePackD` | aktiv | module and debug row transport | Dashboard | mittel | ersetzen |
| `BUS EnginePack` | aktiv | engine blocker and debug transport | Dashboard | mittel | ersetzen |
| `BUS StopLevel` | aktiv | stop level | Dashboard | niedrig | behalten |
| `BUS Target1` | aktiv | first target level | Dashboard | niedrig | behalten |
| `BUS Target2` | aktiv | second target level | Dashboard | niedrig | behalten |

## Interpretation Rules

`behalten`

- stable enough to remain part of the current and likely future contract

`später aufsplitten`

- useful today, but internally combines more than one business concept

`ersetzen`

- current value is mainly tied to dashboard row transport and should be replaced rather than extended if a later domain bus is introduced

`entfernen`

- not currently assigned to any active channel in the present contract

No current channel is marked `entfernen` because every exported channel is used by at least one active consumer today.