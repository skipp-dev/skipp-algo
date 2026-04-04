# SMC Bus Target Matrix

This matrix translates the audit in [smc-bus-v2-audit.md](smc-bus-v2-audit.md) into a binding planning table without changing the current implementation.

Consumer references:

- Dashboard bindings: [SMC_Dashboard.pine](../SMC_Dashboard.pine)
- Strategy bindings: [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14)
- Producer exports: [SMC_Core_Engine.pine](../SMC_Core_Engine.pine)

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
| `BUS QualityBoundsPack` | aktiv | score min/max support values | Dashboard | niedrig | behalten |
| `BUS SessionGateRow` | aktiv | direct session gate row | Dashboard | mittel | behalten |
| `BUS MarketGateRow` | aktiv | direct market gate row | Dashboard | mittel | behalten |
| `BUS VolaGateRow` | aktiv | direct vola gate row | Dashboard | mittel | behalten |
| `BUS MicroSessionGateRow` | aktiv | direct micro-session row | Dashboard | mittel | behalten |
| `BUS MicroFreshRow` | aktiv | direct micro-fresh row | Dashboard | mittel | behalten |
| `BUS VolumeDataRow` | aktiv | direct volume-data row | Dashboard | mittel | behalten |
| `BUS QualityEnvRow` | aktiv | direct environment-quality row | Dashboard | mittel | behalten |
| `BUS QualityStrictRow` | aktiv | direct strict-quality row | Dashboard | mittel | behalten |
| `BUS CloseStrengthRow` | aktiv | direct close-strength row | Dashboard | mittel | behalten |
| `BUS EmaSupportRow` | aktiv | direct ema-support row | Dashboard | mittel | behalten |
| `BUS AdxRow` | aktiv | direct adx verdict row | Dashboard | mittel | behalten |
| `BUS RelVolRow` | aktiv | direct relvol verdict row | Dashboard | mittel | behalten |
| `BUS VwapRow` | aktiv | direct vwap verdict row | Dashboard | mittel | behalten |
| `BUS ContextQualityRow` | aktiv | direct context-quality row | Dashboard | mittel | behalten |
| `BUS QualityCleanRow` | aktiv | direct quality-clean row | Dashboard | mittel | behalten |
| `BUS QualityScoreRow` | aktiv | direct quality-score row | Dashboard | mittel | behalten |
| `BUS SdConfluenceRow` | aktiv | direct SD-confluence row | Dashboard | mittel | behalten |
| `BUS SdOscRow` | aktiv | direct SD-osc row | Dashboard | mittel | behalten |
| `BUS VolRegimeRow` | aktiv | direct volatility-regime row | Dashboard | mittel | behalten |
| `BUS VolSqueezeRow` | aktiv | direct volatility-squeeze row | Dashboard | mittel | behalten |
| `BUS VolExpandRow` | aktiv | direct volatility-expansion row | Dashboard | mittel | ersetzen |
| `BUS DdviRow` | aktiv | direct DDVI row | Dashboard | mittel | ersetzen |
| `BUS ModulePackC` | aktiv | module row transport | Dashboard | mittel | ersetzen |
| `BUS LongTriggersRow` | aktiv | direct trigger-row transport | Dashboard | mittel | ersetzen |
| `BUS RiskPlanRow` | aktiv | direct risk-plan row transport | Dashboard | mittel | ersetzen |
| `BUS DebugFlagsRow` | aktiv | direct debug-flags row transport | Dashboard | mittel | ersetzen |
| `BUS StopLevel` | aktiv | stop level | Dashboard | niedrig | behalten |
| `BUS Target1` | aktiv | first target level | Dashboard | niedrig | behalten |
| `BUS Target2` | aktiv | second target level | Dashboard | niedrig | behalten |
| `BUS ZoneObTop` | aktiv | direct OB top level | Dashboard | mittel | behalten |
| `BUS ZoneObBottom` | aktiv | direct OB bottom level | Dashboard | mittel | behalten |
| `BUS ZoneFvgTop` | aktiv | direct FVG top level | Dashboard | mittel | behalten |
| `BUS ZoneFvgBottom` | aktiv | direct FVG bottom level | Dashboard | mittel | behalten |
| `BUS SessionVwap` | aktiv | direct vwap level | Dashboard | mittel | behalten |
| `BUS AdxValue` | aktiv | direct adx value | Dashboard | mittel | behalten |
| `BUS RelVolValue` | aktiv | direct relative-volume value | Dashboard | mittel | behalten |
| `BUS StretchZ` | aktiv | direct stretch z-score | Dashboard | mittel | behalten |
| `BUS StretchSupportMask` | aktiv | direct stretch support state | Dashboard | mittel | spaeter aufsplitten |
| `BUS LtfBullShare` | aktiv | direct ltf bull-share value | Dashboard | mittel | behalten |
| `BUS LtfBiasHint` | aktiv | direct ltf bias threshold | Dashboard | niedrig | behalten |
| `BUS LtfVolumeDelta` | aktiv | direct ltf delta value | Dashboard | mittel | behalten |

## Interpretation Rules

`behalten`

- stable enough to remain part of the current and likely future contract

`später aufsplitten`

- useful today, but internally combines more than one business concept

`ersetzen`

- current value is mainly tied to dashboard row transport and should be replaced rather than extended if a later domain bus is introduced

`entfernen`

- not currently assigned to any active consumer in the present contract and only retained temporarily for compatibility

Previously retained legacy-compat channels have been retired from the current producer contract and are no longer part of this matrix.
