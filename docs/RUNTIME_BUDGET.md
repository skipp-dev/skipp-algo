# Runtime Budget - SMC_Core_Engine.pine v5.5d

**Status**: Active inventory  
**Last updated**: 2026-04-04 - final pack retirement to explicit support-code channels

---

## 1. Engine Metrics

| Metric | Count |
| --- | --- |
| Total lines | ~6650 |
| `var` declarations | ~420 |
| `input.*` declarations | ~249 |
| `plot()` calls | 58 |
| `request.security()` | 3 |
| `request.security_lower_tf()` | 2 |
| `ta.*` / `math.*` usages | ~236 |

### Plot Budget

TradingView allows max 64 plots per script. Current usage: **58 / 64**.
The active BUS export surface now consumes 58 hidden plots, so six free plot
slots remain available after the final pack-retirement slice.

The previous visible overlay plots (`Session VWAP`, `EMA Fast`, `EMA Slow`)
have already moved to object-based line tails. The producer now spends its
active `plot()` budget on the hidden BUS contract instead of on visible overlay
`plot()` calls. See
[smc-module-pack-b-direct-cut-design.md](smc-module-pack-b-direct-cut-design.md).

---

## 2. Field Categories

### Primary (lean-only, no fallback needed)

These fields are read from lean families and drive the engine directly.

| Family | Fields | Consumer |
| --- | --- | --- |
| Event Risk Light | 7 | event_risk gate, dashboard |
| Session Context Light | 4 required + 1 optional | session gate, dashboard |
| OB Context Light | 5 | OB gate, dashboard |
| FVG Lifecycle Light | 6 | FVG gate, dashboard |
| Structure State Light | 4 | structure gate, dashboard |
| Signal Quality | 5 | quality scoring, dashboard |
| **Total** | **32** | |

### BUS Backward Compat (broad fields, Dashboard only)

All BUS PackE/F/G fields, resolvers, and plot calls **removed in Phase B (AP6 v5.5b)**.
The active dashboard now reads all 58 producer channels: explicit support-code
channels (`LtfDeltaState`, `SafeTrendState`, `MicroProfileCode`,
`ReadyBlockerCode`, `StrictBlockerCode`, `VolExpansionState`,
`DdviContextState`), direct diagnostic/detail channels, and LeanPackA/B while
deriving `Debug Flags` and `Long Debug` locally from dashboard mirror toggles,
`Long Triggers` and `Risk Plan` locally from existing plan levels, `Signal
Quality` bounds locally as the fixed `25 / 100` display policy, and `Event
Risk` locally from `LeanPackA.slot2`.

### Phase C C1: Declaration-Only Visual Input Cleanup (11 inputs)

This cleanup batch has been executed in `SMC_Core_Engine.pine`. These inputs
were removed because they were declared but never consumed by any gate, plot,
dashboard, or alert path in the split core.

| Removed input | Former line | Former default |
| --- | --- | --- |
| `show_mtf_trend` | 3184 | true |
| `show_risk_levels` | 3212 | true |
| `show_reclaim_markers` | 3404 | true |
| `show_long_confirmation_markers` | 3405 | true |
| `show_long_background` | 3408 | true |
| `color_long_bars` | 3409 | false |
| `show_accel_debug` | 3506 | false |
| `show_sd_debug` | 3522 | false |
| `show_vol_regime_debug` | 3544 | false |
| `show_stretch_overlay` | 3558 | true |
| `show_lower_extreme_bg` | 3560 | false |

Audit coverage now asserts these names remain absent from the split core.

### Phase C C2: ModulePackB direct cut

**Status**: DONE
**Removed**: `BUS ModulePackB`, 3 visible overlay `plot()` calls
**Added**: `BUS VolExpandRow`, `BUS DdviRow`, `BUS StretchSupportMask`, `BUS LtfBiasHint`
**Current plot budget**: 63 / 64

The direct cut stayed plot-neutral by moving the visible `Session VWAP`,
`EMA Fast`, and `EMA Slow` overlays to line-object tails before the new BUS
channels were published.

### Phase C C3: ModulePackC first cut

**Status**: DONE
**Added**: `BUS SwingRow`, `BUS ObjectsCountPack`
**Changed**: `BUS ModulePackC` now carries only `LTF Delta` and `Micro Profile`
**Current plot budget**: 63 / 64

This cut restored producer-owned `Swing` transport and exact `Objects` counts,
while a later `DebugStateRow` retirement reopened one free plot slot for the
next cleanup slice.

### Phase C C4: DebugStateRow retirement

**Status**: DONE
**Removed**: `BUS DebugStateRow`
**Changed**: the dashboard now derives `Long Debug` state locally from debug-module state plus lifecycle state
**Current plot budget**: 63 / 64

This cut removed a redundant debug-state transport row and restored exactly one
free producer plot slot without changing the rendered `Long Debug` summary.

### Phase C C9: ModulePackC retirement

**Status**: DONE
**Removed**: `BUS ModulePackC`
**Added**: `BUS LtfDeltaRow`, `BUS MicroProfileRow`
**Post-cut plot budget**: 64 / 64

This cut retired the last packed dashboard module transport. `LTF Delta` and
`Micro Profile` now travel as dedicated direct rows, so no packed UI transport
remains on the active producer surface.

### Phase C C10: Plan-row local derivation

**Status**: DONE
**Removed**: `BUS LongTriggersRow`, `BUS RiskPlanRow`
**Changed**: the dashboard now derives `Long Triggers` from `Trigger` + `Invalidation` and `Risk Plan` from `Trigger` + `StopLevel` + `Target1` + `Target2`
**Post-cut plot budget**: 62 / 64

This cut retired two redundant plan-transport rows without changing the
dashboard text surface. The plan status colors now reconstruct locally from the
already exported executable and plan levels.

### Phase C C11: Micro modifier fold-in

**Status**: DONE
**Removed**: `BUS MicroModifierMask`
**Changed**: `BUS MicroProfileRow` now carries an inline `has modifiers` flag in its reason code
**Post-cut plot budget**: 61 / 64

This cut retired a redundant micro-profile support channel without changing the
rendered `Micro Profile` summary. The dashboard still shows `| mod`, but the
signal now comes directly from `MicroProfileRow` instead of from a second BUS
series.

### Phase C C12: Debug-flags localization

**Status**: DONE
**Removed**: `BUS DebugFlagsRow`
**Changed**: the dashboard now derives `Debug Flags` and `Long Debug` from local debug mirror toggles plus lifecycle state
**Current plot budget**: 60 / 64

This cut retired the last debug-only transport row from the producer. The
dashboard keeps the same compact debug summaries, but the operator now mirrors
the relevant debug toggles locally instead of binding a dedicated BUS series.

### Phase C C13: Ready/Strict pack consolidation

**Status**: DONE
**Removed**: `BUS ReadyGateRow`, `BUS StrictGateRow`
**Added**: `BUS ReadyStrictPack`
**Current plot budget**: 59 / 64

This cut preserved the existing ready/strict reason-code semantics while
packing both engine blocker rows into one BUS channel. The dashboard now
unpacks slots 0 and 1 locally instead of binding two separate row sources.

### Phase C C14: Quality-bounds localization

**Status**: DONE
**Removed**: `BUS QualityBoundsPack`
**Changed**: the dashboard now renders `Signal Quality` against the fixed `25 / 100` bounds locally
**Post-cut plot budget**: 58 / 64

This cut retired a redundant support channel that only published the constant
quality bounds `25 / 100`. The rendered `Signal Quality` text stays unchanged,
but the dashboard now formats that fixed policy locally instead of binding a
dedicated BUS series.

### Phase C C15: Event-risk row retirement

**Status**: DONE
**Removed**: `BUS EventRiskRow`
**Changed**: the dashboard and event overlay now derive event-risk diagnostics locally from `LeanPackA.slot2`
**Current plot budget**: 57 / 64

This cut retired a lean-only transport row that no longer carried unique
producer-owned semantics. The visible event-risk summaries stay aligned with
the lean event-risk state while the producer regains one more free plot slot.

### Phase C C16: ReadyStrictPack slot reuse

**Status**: DONE
**Removed**: `BUS VolExpandRow`, `BUS DdviRow`
**Changed**: `BUS ReadyStrictPack` now carries `Ready Gate`, `Strict Gate`,
`Vol Expand`, and `DDVI` in slots `0` through `3`
**Current plot budget**: 55 / 64

This cut reused the spare capacity inside `ReadyStrictPack` to retire two more
standalone UI-transport rows without changing the producer-owned row-code
semantics consumed by the dashboard.

### Phase C C17: ModulePackD consolidation

**Status**: DONE
**Removed**: `BUS LtfDeltaRow`, `BUS SwingRow`, `BUS MicroProfileRow`
**Added**: `BUS ModulePackD`
**Changed**: `BUS ModulePackD` now carries `LTF Delta`, `Swing`, and `Micro Profile`
in slots `0` through `2`
**Current plot budget**: 53 / 64

This cut keeps the remaining producer-owned module row semantics intact while
retiring three standalone transport rows into a single packed channel.

### Phase C C18: Final pack retirement

**Status**: DONE
**Removed**: `BUS ModulePackD`, `BUS ReadyStrictPack`
**Added**: `BUS LtfDeltaState`, `BUS SafeTrendState`, `BUS MicroProfileCode`,
`BUS ReadyBlockerCode`, `BUS StrictBlockerCode`, `BUS VolExpansionState`,
`BUS DdviContextState`
**Current plot budget**: 58 / 64

This final slice removes the last packed BUS transports entirely. The producer
now exports explicit support-code channels for the former module and blocker
surfaces, and the dashboard reconstructs the row semantics locally without any
remaining packed transport on the active contract.

---

## 3. Removal Roadmap

### Phase B: BUS compat fields (33 fields, 3 plot slots)

**Status**: ✅ DONE (AP6 v5.5b)  
**Removed**: 33 field declarations, 12 resolver functions, 3 plot calls, ~265 lines total  
**Current plot budget**: 63 / 64

### Phase C C1: Declaration-only visual input cleanup (11 inputs)

**Status**: ✅ DONE  
**Removed**: 11 unused input declarations (~11 lines)  
**Guard**: `tests/test_smc_core_engine_phase_c_audit.py` asserts the removed names stay absent

### Phase D: Old broad event risk fields

**Prerequisite**: satisfied via LeanPackA event-risk transport  
**Effort**: Low  
**Fields**: `lib_event_cooldown`, remaining broad event risk references  
**See**: [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md) Phase C

---

## 4. Runtime Constraints

- **`request.security`**: 5 calls (3 HTF + 2 data-check). TradingView limit: 40.
- **`request.security_lower_tf`**: 2 calls. These are the most expensive operations.
- **Performance modes**: Light/Pro/Debug adjust `max_ltf_samples_per_bar_eff` and disable LTF dashboard.
- **Compact mode**: Suppresses 9+ visual overlays. No runtime savings (inputs still evaluated),
  but reduces chart rendering load.

## 5. Principles (v5.5d)

1. **Pine Runtime Budget** is architectural, not incidental (Principle 12)
2. **Support Family Admission Rule** — new families must prove value vs. runtime cost (Principle 14)
3. Every new `request.security` call requires explicit budget justification
4. Dead fields/inputs discovered during refactoring should be logged here for next cleanup wave
