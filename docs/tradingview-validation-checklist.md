# TradingView Validation Checklist

This checklist is for manual validation of the current split contract in TradingView without changing the implementation.

## Product-Surface Evidence Pack

Required screenshot set for release-quality validation:

1. Rendered Core first-run chart with the public decision surface visible.
2. Rendered Dashboard in `Decision Brief` view.
3. Rendered Dashboard in `Audit View`.
4. Rendered Strategy chart with `Entry Price`, `Stop Loss`, and `Profit Target` visible when a plan is active.

Invalid evidence for product review:

- Pine editor screenshots
- settings-only screenshots without the chart surface
- cropped screenshots that hide the actual user-facing surface

## Core Producer Plots To Bind

The producer exports the full hidden bus from [SMC_Core_Engine.pine](../SMC_Core_Engine.pine).

Current manual validation counts:

- Producer hidden series: `58`
- Dashboard bindings: `58`
- Strategy bindings: `8`

### Dashboard Needs These Bindings

The dashboard expects all `58` bindings declared in [SMC_Dashboard.pine](../SMC_Dashboard.pine) and governed by [../scripts/smc_bus_manifest.py](../scripts/smc_bus_manifest.py).

Lifecycle:

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

Diagnostic Rows:

- `BUS SessionGateRow`
- `BUS MarketGateRow`
- `BUS VolaGateRow`
- `BUS MicroSessionGateRow`
- `BUS MicroFreshRow`
- `BUS VolumeDataRow`
- `BUS QualityEnvRow`
- `BUS QualityStrictRow`
- `BUS CloseStrengthRow`
- `BUS EmaSupportRow`
- `BUS AdxRow`
- `BUS RelVolRow`
- `BUS VwapRow`
- `BUS ContextQualityRow`
- `BUS QualityCleanRow`
- `BUS QualityScoreRow`
- `BUS SdConfluenceRow`
- `BUS SdOscRow`
- `BUS VolRegimeRow`
- `BUS VolSqueezeRow`

Diagnostic Support:

- `BUS LtfDeltaState`
- `BUS SafeTrendState`
- `BUS MicroProfileCode`
- `BUS ReadyBlockerCode`
- `BUS StrictBlockerCode`
- `BUS VolExpansionState`
- `BUS DdviContextState`

These seven support channels replace the final packed transport layer. The
dashboard reconstructs `LTF Delta`, `Swing`, `Micro Profile`, `Ready Gate`,
`Strict Gate`, `Vol Expand`, and `DDVI` locally from the explicit support-code
surface.

Trade Plan:

- `BUS StopLevel`
- `BUS Target1`
- `BUS Target2`

Detail Surface:

- `BUS ZoneObTop`
- `BUS ZoneObBottom`
- `BUS ZoneFvgTop`
- `BUS ZoneFvgBottom`
- `BUS SessionVwap`
- `BUS AdxValue`
- `BUS RelVolValue`
- `BUS StretchZ`
- `BUS StretchSupportMask`
- `BUS LtfBullShare`
- `BUS LtfBiasHint`
- `BUS LtfVolumeDelta`
- `BUS ObjectsCountPack`

Lean Surface:

- `BUS LeanPackA`
- `BUS LeanPackB`

### Local Dashboard-Only Debug Mirrors

These controls live under `8. Operator Only - Local Debug Mirrors`. They are
not `source` bindings and are configured manually only when you want to
validate the `Debug Flags` or `Long Debug` rows against the core's effective
debug setup:

- `OB Debug Enabled`
- `FVG Debug Enabled`
- `Long Engine Debug Enabled`

### Strategy Needs These Bindings

The strategy expects only the 8 bindings declared in [SMC_Long_Strategy.pine](../SMC_Long_Strategy.pine#L7-L14):

- `BUS Armed`
- `BUS Confirmed`
- `BUS Ready`
- `BUS EntryBest`
- `BUS EntryStrict`
- `BUS Trigger`
- `BUS Invalidation`
- `BUS QualityScore`

## Public Label Checks

Before validating any scenarios, confirm the visible product copy is aligned:

1. Core uses `Trading Style`, `Focus View`, and `Show Decision Brief`, starts with `Core Setup`, `Output`, `Trade Plan`, `Session Gate`, and `Runtime Budget` before any advanced groups, and in `Focus View` shows one hero card with no default swing-level or standalone warning-label duplicates before `Ready` trade lines appear.
2. Dashboard uses `View`, `Decision Brief`, `Audit View`, `Show Brief Panel`, `Show Trade Plan`, and `Highlight Live Setup`, with `Product Surface` appearing before the operator-only binding groups.
3. Strategy uses `Entry Stage`, `Minimum Setup Quality`, `Profit Target (R)`, and `Enable Profit Target`, with `Execution Setup` and `Trade Plan` appearing before the two `Expert Mapping` groups.
4. Strategy chart outputs read `Entry Price`, `Stop Loss`, and `Profit Target`.

## Manual Validation Scenarios

### 1. Neutral / Keine Zone

Expected core state:

- `BUS ZoneActive = 0`
- `BUS Armed = 0`
- `BUS Confirmed = 0`
- `BUS Ready = 0`
- `BUS EntryBest = 0`
- `BUS EntryStrict = 0`

Expected dashboard cues:

- `Pullback Zone` shows `No Long Zone`
- `Long Setup` shows `No Setup`
- `Exec Tier` shows `n/a`
- `Long Visual` shows `Neutral`

If this fails:

- `MetaPack` decoding, local zone-row derivation, direct trigger/risk row binding, or local debug mirror settings are wrong
- `StateCode` mapping is wrong
- one or more dashboard `input.source()` bindings point to the wrong producer plot

### 2. Armed

Expected core state:

- `BUS Armed = 1`
- `BUS Confirmed = 0`
- `BUS Ready = 0`
- `BUS EntryBest = 0`
- `BUS EntryStrict = 0`

Expected dashboard cues:

- `Long Setup` shows `Armed | <source>`
- `Exec Tier` shows `Armed`
- `Setup Age` shows `armed fresh` or `armed stale`

If this fails:

- `StateCode` to `setup_text()` mapping in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L182-L197) is wrong
- `MetaPack.freshness_code` mapping is wrong

### 3. Confirmed

Expected core state:

- `BUS Confirmed = 1`
- `BUS Ready = 0`

Expected dashboard cues:

- `Long Setup` shows `Confirmed | <source>`
- `Exec Tier` shows `Confirmed`
- `Setup Age` shows `confirm fresh` or `confirm stale`

If this fails:

- `StateCode` mapping is wrong
- `SourceKind` binding is wrong
- `MetaPack.freshness_code` mapping is wrong

### 4. Ready

Expected core state:

- `BUS Ready = 1`
- optional `BUS EntryBest = 1` or `BUS EntryStrict = 1` only if upgrades are also active

Expected dashboard cues:

- `Long Visual` shows `Ready`
- `Exec Tier` shows `Ready`, `Best`, or `Strict` depending on `StateCode`
- `Ready Gate` shows `Ready`
- `Trigger`, `Stop`, and targets are coherent if a plan is active

If this fails:

- `ReadyBlockerCode` binding, local blocker-to-row reconstruction, or `decode_ready_gate_text()` mapping is wrong
- `StateCode` mapping is wrong
- `Trigger`, `StopLevel`, `Target1`, or `Target2` are wired incorrectly

### 5. Invalidated

Expected core state:

- `BUS StateCode = -1`
- `BUS Ready = 0`
- `BUS EntryBest = 0`
- `BUS EntryStrict = 0`

Expected dashboard cues:

- `Long Setup` shows `Invalidated`
- `Long Visual` shows `Fail`
- `Strict Gate` is not shown as passed

If this fails:

- `StateCode` binding is wrong
- lifecycle decoder mapping in [SMC_Dashboard.pine](../SMC_Dashboard.pine#L162-L197) is wrong

## Signs That Decoder Or Source Mapping Is Wrong

1. `Trend` and `HTF Trend` show impossible combinations relative to the core trend state.
2. `Long Setup` and `Exec Tier` contradict each other for the same bar.
3. `Setup Age` shows `n/a` while setup rows indicate armed or confirmed.
4. `Session`, `Market Gate`, or `Vola Regime` show a state that does not match the underlying hard-gate booleans.
5. `Quality Score` min/max text is inconsistent with the actual quality score threshold.
6. The strategy stages entries while dashboard lifecycle rows still show no active entry tier.
7. Dashboard risk lines do not match the strategy trigger/invalidation levels.
8. `Vol Expand` or `DDVI` disagree with the core even though the blocker-code
   support channels still decode plausibly.

## Manual Cross-Check Order

1. Add `SMC_Core_Engine.pine` to the chart and capture a rendered first-run Core screenshot.
2. Add `SMC_Dashboard.pine`, set `View = Decision Brief`, and bind all 58 sources to the core plots. Capture the rendered brief surface.
3. Switch the Dashboard to `Audit View` and capture the rendered expert surface.
4. Add `SMC_Long_Strategy.pine`, bind its 8 sources to the core plots, and capture a rendered execution screenshot when a plan is active.
5. Validate the five scenarios above on the same symbol and timeframe.
6. If dashboard and strategy disagree, treat the core plots as the source of truth first and inspect source bindings before changing any logic.
