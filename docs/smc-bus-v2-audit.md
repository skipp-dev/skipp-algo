# SMC Bus v2 Audit

## Scope

This document audits the current split between the producer in [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5526-L5551), the dashboard consumer in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L7-L29), and the strategy consumer in [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14).

The current contract is a 62-channel hidden plot bus.

- The producer exports 62 hidden plots in [SMC_Core_Engine.pine](../SMC_Core_Engine.pine).
- The dashboard binds 62 `input.source()` channels in [SMC_Dashboard.pine](../SMC_Dashboard.pine).
- The strategy binds 8 `input.source()` channels from the original contract in [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14).
- The row-code transport format is defined in [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L1670-L1682) and decoded in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L42-L84).

The audit question is not whether the packed bus compiles. It does. The question is whether each channel is a stable domain contract or only a serialized dashboard row.

## Current Producer/Consumer Cut

### Producer

The producer exports:

- 14 Lite/executable channels.
- 48 Pro-only channels spanning direct diagnostic rows, support/detail levels, and the remaining packed dashboard transport.

The producer does not render dashboard UI and does not emit alert transport in its active split form, as verified by [tests/test_smc_core_engine_split.py](../tests/test_smc_core_engine_split.py).

### Dashboard Consumer

The dashboard reconstructs display rows by:

- unpacking four-slot row packs with `pack_slot()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L42-L53)
- decoding row state with `row_status()` and `row_reason()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L81-L85)
- mapping row codes back to display strings with helpers such as `decode_session_text()` and `decode_quality_strict_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L241-L340)
- rendering sections in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L714-L768)

### Strategy Consumer

The strategy does not consume any of the new dashboard packs. It uses only:

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

See [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14).

## Focused Channel Inventory

Classification meanings:

- `Domain`: stable business signal or level that can be shared by multiple consumers without UI assumptions.
- `Hybrid`: compacted domain information that is still reusable, but already shaped for dashboard interpretation.
- `UI-Transport`: serialized row or display-state transport designed primarily to rebuild the current dashboard.

| Channel | Producer Reference | Dashboard/Strategy Use | Classification | Keep / Reduce / Rebuild | Notes |
| --- | --- | --- | --- | --- | --- |
| `BUS ZoneActive` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5526) | Dashboard lifecycle | Domain | Keep | Stable boolean for active long-zone context. |
| `BUS Armed` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5527) | Dashboard, Strategy | Domain | Keep | Core lifecycle stage. |
| `BUS Confirmed` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5528) | Dashboard, Strategy | Domain | Keep | Core lifecycle stage. |
| `BUS Ready` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5529) | Dashboard, Strategy | Domain | Keep | Core lifecycle stage. |
| `BUS EntryBest` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5530) | Dashboard, Strategy | Domain | Keep | Strategy-relevant entry tier. |
| `BUS EntryStrict` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5531) | Dashboard, Strategy | Domain | Keep | Strategy-relevant entry tier. |
| `BUS Trigger` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5532) | Dashboard, Strategy | Domain | Keep | Executable entry stop level. |
| `BUS Invalidation` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5533) | Dashboard, Strategy | Domain | Keep | Executable invalidation level. |
| `BUS QualityScore` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5534) | Dashboard, Strategy | Domain | Keep | Numeric score consumed directly by strategy threshold logic. |
| `BUS SourceKind` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5535) | Dashboard lifecycle | Domain | Keep | Stable source enum for OB/FVG/Swing/Internal provenance. |
| `BUS StateCode` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5536) | Dashboard lifecycle | Hybrid | Keep | Reusable, but already compresses multiple lifecycle tiers into one visual state. |
| `BUS TrendPack` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5537) | Dashboard lifecycle | Domain | Keep | Compact transport of current and HTF trend states. |
| `BUS MetaPack` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5538) | Dashboard lifecycle and hard gates | Hybrid | Keep | Packs freshness, source-state, reclaim class, zone class. Reusable but dashboard-oriented. |
| `BUS QualityBoundsPack` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5543) | Dashboard quality | Domain | Keep | Stable support channel for `QualityScore` min/max interpretation. |
| `BUS SdConfluenceRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Keep | Direct row transport replacing `ModulePackA.slot0`. |
| `BUS SdOscRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Keep | Direct row transport replacing `ModulePackA.slot1`. |
| `BUS VolRegimeRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Keep | Direct row transport replacing `ModulePackA.slot2`. |
| `BUS VolSqueezeRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Keep | Direct row transport replacing `ModulePackA.slot3`. |
| `BUS VolExpandRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Rebuild | Direct row transport replacing former `ModulePackB.slot0`. |
| `BUS DdviRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules | UI-Transport | Rebuild | Direct row transport replacing former `ModulePackB.slot2`. |
| `BUS StretchSupportMask` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules with `StretchZ` | Hybrid | Keep | Producer-owned support mask for reconstructing `Stretch` without copying hidden engine settings into the dashboard. |
| `BUS LtfBiasHint` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules with `LtfBullShare` | Domain | Keep | Numeric threshold export replacing the missing `ModulePackB.slot3` support input. |
| `BUS ModulePackC` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5546) | Dashboard modules | UI-Transport | Rebuild | Dashboard row transport for LTF Delta, Objects, Swing, Micro Profile. |
| `BUS LongTriggersRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules and plan | UI-Transport | Rebuild | Direct row transport for trigger availability and execution-tier state. |
| `BUS RiskPlanRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules and plan | UI-Transport | Rebuild | Direct row transport for plan completeness while levels stay on dedicated channels. |
| `BUS DebugFlagsRow` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine) | Dashboard modules and engine | UI-Transport | Rebuild | Direct row transport for enabled debug-module flags. |
| `BUS StopLevel` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5549) | Dashboard risk plan | Domain | Keep | Stable risk level. |
| `BUS Target1` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5550) | Dashboard risk plan | Domain | Keep | Stable target level. |
| `BUS Target2` | [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5551) | Dashboard risk plan | Domain | Keep | Stable target level. |

## Section Parity Against SMC++.pine

Reference sections are rendered in the monolith here:

- Lifecycle: [SMC++.pine](../SMC++.pine#L6380-L6389)
- Hard Gates: [SMC++.pine](../SMC++.pine#L6392-L6399)
- Quality: [SMC++.pine](../SMC++.pine#L6339-L6352)
- Modules: [SMC++.pine](../SMC++.pine#L6354-L6371)
- Engine: [SMC++.pine](../SMC++.pine#L6373-L6378)

The current dashboard consumer renders the parallel sections here: [SMC_Dashboard.pine](../SMC_Dashboard.pine#L719-L768).

| Section | Parity Verdict | Evidence |
| --- | --- | --- |
| Lifecycle | `weitgehend voll` | Trend, HTF, setup, visual state, and exec tier are reconstructed from `StateCode`, `TrendPack`, `SourceKind`, and `MetaPack` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L719-L727). Pullback Zone and Setup Age are reconstructed as classes, not as the original richer texts from [SMC++.pine](../SMC++.pine#L6266-L6323). |
| Hard Gates | `weitgehend voll` | Session, Market, Vola, Micro Session, Micro Fresh, and Volume Data map cleanly through row-code decoders in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L241-L309) and are rendered in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L728-L734). |
| Quality | `teilweise` | The gate verdicts survive, but ADX, Rel Volume, and VWAP no longer expose the same raw detail strings as [SMC++.pine](../SMC++.pine#L5968-L6046). |
| Modules | `teilweise` | The dashboard rebuilds row labels, but several original rows in [SMC++.pine](../SMC++.pine#L6048-L6264) contained values, counts, or formatted levels that are now reduced to categories. |
| Engine | `teilweise` | Ready and Strict blocker rows remain informative, but the debug summary is compressed relative to [SMC++.pine](../SMC++.pine#L6325-L6337). |

## Row-by-Row Parity

Verdict meanings:

- `voll`: same business meaning and same effective display detail.
- `weitgehend voll`: same business meaning, but slightly reduced display detail.
- `teilweise`: same area is represented, but important detail is compressed or altered.
- `schwach`: only a coarse summary survives.

| Monolith Row | Reference | Current Bus Reconstruction | Verdict | Known Difference |
| --- | --- | --- | --- | --- |
| Trend | [SMC++.pine](../SMC++.pine#L6382) | `TrendPack` -> `trend_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L118-L123) | voll | None. |
| HTF Trend | [SMC++.pine](../SMC++.pine#L6383) | `TrendPack` slots 1-3 in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L656-L659) | voll | None. |
| Pullback Zone | [SMC++.pine](../SMC++.pine#L6384) | `MetaPack.zone_code` plus local `zone_row_code()` derivation in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | teilweise | Monolith used `long_zone_text` and `compose_zone_summary_text(...)`; current dashboard shows only zone class text. |
| Reclaim | [SMC++.pine](../SMC++.pine#L6385) | `MetaPack.reclaim_code` -> `reclaim_reason_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L149-L160) | weitgehend voll | No numeric/level context, but class meaning is preserved. |
| Long Setup | [SMC++.pine](../SMC++.pine#L6386) | `StateCode` and `SourceKind` -> `setup_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L182-L197) | voll | None. |
| Setup Age | [SMC++.pine](../SMC++.pine#L6387) | `StateCode` and `MetaPack.freshness_code` -> `setup_age_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L229-L236) | teilweise | Monolith included age counts like `confirmed N`; current split keeps only freshness class. |
| Long Visual | [SMC++.pine](../SMC++.pine#L6388) | `StateCode` -> `long_visual_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L162-L173) | voll | None. |
| Exec Tier | [SMC++.pine](../SMC++.pine#L6389) | `StateCode` -> `exec_tier_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L175-L180) | voll | None. |
| Session | [SMC++.pine](../SMC++.pine#L6394) | `SessionGateRow` -> `decode_session_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L241-L249) | weitgehend voll | Same business blocker classes, but encoded as row codes. |
| Market Gate | [SMC++.pine](../SMC++.pine#L6395) | `MarketGateRow` -> `decode_market_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L252-L262) | weitgehend voll | Same blocker classes. |
| Vola Regime | [SMC++.pine](../SMC++.pine#L6396) | `VolaGateRow` -> `decode_vola_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L265-L274) | weitgehend voll | Same gate categories, no raw component flags. |
| Micro Session | [SMC++.pine](../SMC++.pine#L6397) | `MicroSessionGateRow` -> `decode_micro_session_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L276-L286) | weitgehend voll | Same blocker classes. |
| Micro Fresh | [SMC++.pine](../SMC++.pine#L6398) | `MicroFreshRow` plus `MetaPack` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L288-L293) | weitgehend voll | Same freshness/source-state classes, no extra context. |
| Volume Data | [SMC++.pine](../SMC++.pine#L6399) | `VolumeDataRow` -> `decode_volume_data_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L295-L308) | weitgehend voll | Same feed quality categories. |
| Quality Env | [SMC++.pine](../SMC++.pine#L6343) | `QualityEnvRow` -> `decode_quality_env_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L310-L319) | voll | Same business meaning. |
| Quality Strict | [SMC++.pine](../SMC++.pine#L6344) | `QualityStrictRow` -> `decode_quality_strict_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L321-L340) | weitgehend voll | Same blocker sequence except the monolith still had richer implicit context from live flags. |
| Close Strength | [SMC++.pine](../SMC++.pine#L6345) | `CloseStrengthRow` -> `decode_close_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L342-L344) | voll | None. |
| EMA Support | [SMC++.pine](../SMC++.pine#L6346) | `EmaSupportRow` -> `decode_ema_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L346-L348) | voll | None. |
| ADX | [SMC++.pine](../SMC++.pine#L6347) | `AdxRow` -> `decode_adx_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L350-L363) | teilweise | Monolith exposed `adx_value` and `adx_state_text`; split keeps only categorical text. |
| Rel Volume | [SMC++.pine](../SMC++.pine#L6348) | `RelVolRow` -> `decode_relvol_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L365-L377) | teilweise | Monolith exposed `relvol_text`; split uses coarse categories. |
| VWAP Filter | [SMC++.pine](../SMC++.pine#L6349) | `VwapRow` -> `decode_vwap_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L379-L390) | teilweise | Monolith used `vwap_state_text`; split compresses to categories. |
| Context Quality | [SMC++.pine](../SMC++.pine#L6350) | `ContextQualityRow` -> `decode_context_quality_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L392-L394) | voll | Same business meaning. |
| Quality Score | [SMC++.pine](../SMC++.pine#L6351) | `QualityScore` plus `QualityBoundsPack` -> `quality_bounds_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L619-L623) | voll | Numeric score plus min/max remain available. |
| Quality Clean | [SMC++.pine](../SMC++.pine#L6352) | `QualityCleanRow` -> `decode_quality_clean_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L396-L396) | voll | None. |
| SD Confluence | [SMC++.pine](../SMC++.pine#L6356) | `SdConfluenceRow` -> `decode_sd_confluence_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L398-L410) | weitgehend voll | Same support classes. |
| SD Osc | [SMC++.pine](../SMC++.pine#L6357) | `SdOscRow` -> `decode_sd_osc_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L412-L427) | teilweise | Monolith displayed `sd_value`; split does not. |
| Vol Regime | [SMC++.pine](../SMC++.pine#L6358) | `VolRegimeRow` -> `decode_vol_regime_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L429-L431) | weitgehend voll | Same regime class. |
| Vol Squeeze | [SMC++.pine](../SMC++.pine#L6359) | `VolSqueezeRow` -> `decode_vol_squeeze_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L433-L446) | weitgehend voll | Same stage classes. |
| Vol Expand | [SMC++.pine](../SMC++.pine#L6360) | `VolExpandRow` -> `decode_vol_expand_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L448-L450) | weitgehend voll | Same expansion class. |
| Stretch | [SMC++.pine](../SMC++.pine#L6361) | `StretchZ` plus `StretchSupportMask` -> `resolve_stretch_row_code()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | teilweise | Monolith displayed `distance_to_mean_z`; split keeps only category text plus a producer-owned support mask. |
| DDVI | [SMC++.pine](../SMC++.pine#L6362) | `DdviRow` -> `decode_ddvi_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L467-L480) | weitgehend voll | Same DDVI support class. |
| LTF Bias | [SMC++.pine](../SMC++.pine#L6363) | `ModulePackC.slot0` (`LTF Delta`) plus `LtfBullShare` plus `LtfBiasHint` -> `resolve_ltf_bias_row_code()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | teilweise | Monolith displayed percentage and price-only suffix; split keeps only class text. |
| LTF Delta | [SMC++.pine](../SMC++.pine#L6364) | `ModulePackC.slot0` -> `decode_ltf_delta_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L497-L510) | teilweise | Monolith displayed formatted percent if available; split keeps only sign/state category. |
| Objects | [SMC++.pine](../SMC++.pine#L6365) | `ModulePackC.slot1` -> `decode_objects_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L512-L521) | teilweise | Monolith displayed actual OB/FVG counts; split keeps only presence classes. |
| Swing H/L | [SMC++.pine](../SMC++.pine#L6366) | `ModulePackC.slot2` -> `decode_swing_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L523-L525) | schwach | Monolith displayed four concrete levels; split keeps only bullish/bearish/neutral class. |
| Long Zones | [SMC++.pine](../SMC++.pine#L6367) | local `zone_row_code()` plus `zone_reason_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | schwach | Monolith displayed a zone summary string with levels. Split shows only zone class. |
| Long Triggers | [SMC++.pine](../SMC++.pine#L6368) | `LongTriggersRow` plus `Trigger` and `Invalidation` in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | voll | Levels remain available. |
| Micro Profile | [SMC++.pine](../SMC++.pine#L6369) | `ModulePackC.slot3` plus `MicroModifierMask` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L527-L544) | teilweise | Monolith displayed full modifier text; split reduces modifiers to a mask and renders only a trailing `mod` marker. |
| Risk Plan | [SMC++.pine](../SMC++.pine#L6370) | `RiskPlanRow` plus Stop/Target channels in [SMC_Dashboard.pine](../SMC_Dashboard.pine) | voll | Levels remain available. |
| Ready Gate | [SMC++.pine](../SMC++.pine#L6374) | `ReadyGateRow` -> `decode_ready_gate_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L558-L586) | weitgehend voll | Same dominant blocker classes. |
| Strict Gate | [SMC++.pine](../SMC++.pine#L6375) | `StrictGateRow` -> `decode_strict_gate_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L588-L606) | weitgehend voll | Same dominant blocker classes. |
| Debug Flags | [SMC++.pine](../SMC++.pine#L6376) | `DebugFlagsRow` -> `decode_debug_flags_text()` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L546-L556) | teilweise | Same enabled-module list, but no debug mode detail. |
| Long Debug | [SMC++.pine](../SMC++.pine#L6377) | `DebugStateRow` plus `StateCode`, `SourceKind`, `MetaPack` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L707-L707) | schwach | Monolith used `long_debug_summary_text`; split uses a shorter derived summary. |

## Known Deviations From The Monolith

1. `Setup Age` no longer carries bar-count detail from [SMC++.pine](../SMC++.pine#L6300). It is reduced to freshness classes in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L229-L236).
2. `ADX`, `Rel Volume`, `VWAP Filter`, `SD Osc`, `Stretch`, `LTF Bias`, and `LTF Delta` no longer expose the original numeric or formatted detail strings from [SMC++.pine](../SMC++.pine#L5968-L6264).
3. `Objects` no longer exposes exact OB/FVG counts from [SMC++.pine](../SMC++.pine#L6207).
4. `Swing H/L` no longer exposes concrete swing and internal levels from [SMC++.pine](../SMC++.pine#L6226).
5. `Long Zones` no longer exposes the full `compose_zone_summary_text(...)` output from [SMC++.pine](../SMC++.pine#L6233).
6. `Micro Profile` no longer exposes the full modifier text. The dashboard only knows whether modifiers exist via a bitmask from [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L2070) and renders `| mod` in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L527-L544).
7. `Long Debug` is not the monolith summary string from [SMC++.pine](../SMC++.pine#L5247) and [SMC++.pine](../SMC++.pine#L6334). It is a reconstructed compact summary from [SMC_Dashboard.pine](../SMC_Dashboard.pine#L707).
8. The row-transport channels encode a current dashboard row schema. That means a dashboard wording or section redesign would require producer changes, which is a UI-coupled contract.

## Strategy Compatibility

### Current Strategy Usage

`SMC_Long_Strategy.pine` uses only these channels, all bound in [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14):

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

### New Bus-v2 Pro Channels The Strategy Does Not Use

The strategy does not bind any of the following:

- `BUS StateCode`
- `BUS TrendPack`
- `BUS MetaPack`
- `BUS QualityBoundsPack`
- `BUS SdConfluenceRow`
- `BUS SdOscRow`
- `BUS VolRegimeRow`
- `BUS VolSqueezeRow`
- `BUS VolExpandRow`
- `BUS DdviRow`
- `BUS StretchSupportMask`
- `BUS LtfBiasHint`
- `BUS ModulePackC`
- `BUS LongTriggersRow`
- `BUS RiskPlanRow`
- `BUS DebugFlagsRow`
- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

### Why Bus v2 Is Not An Immediate Strategy Risk

The strategy still runs entirely on the original entry-state booleans, trigger/invalidation levels, and quality score. Those channels are still exported directly and with the same labels from [SMC_Core_Engine.pine](../SMC_Core_Engine.pine#L5527-L5534).

### What Would Be Strategy-Breaking

The following changes would be strategy-breaking:

1. Renaming any of the eight bound source labels in [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14).
2. Changing the boolean semantics of `BUS Armed`, `BUS Confirmed`, `BUS Ready`, `BUS EntryBest`, or `BUS EntryStrict`.
3. Changing `BUS Trigger` or `BUS Invalidation` away from executable price levels.
4. Replacing `BUS QualityScore` with a packed or categorical value.
5. Reordering or removing those legacy channels without updating strategy bindings.

## Current Decision Boundary

The current bus-v2 is acceptable as a dashboard transport layer. It is not yet a clean domain bus.

The next architecture decision is therefore:

- keep bus-v2 as an explicitly UI-shaped dashboard transport and stop treating it as a general domain contract
- or preserve only the domain-safe channels and later replace the row packs with a true domain-oriented bus revision
