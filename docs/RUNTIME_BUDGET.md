# Runtime Budget - SMC_Core_Engine.pine v5.5d

**Status**: Active inventory  
**Last updated**: 2026-04-04 - DebugStateRow retired

---

## 1. Engine Metrics

| Metric | Count |
| --- | --- |
| Total lines | ~6650 |
| `var` declarations | ~420 |
| `input.*` declarations | ~249 |
| `plot()` calls | 63 |
| `request.security()` | 3 |
| `request.security_lower_tf()` | 2 |
| `ta.*` / `math.*` usages | ~236 |

### Plot Budget

TradingView allows max 64 plots per script. Current usage: **63 / 64**.
The active BUS export surface now consumes 63 hidden plots, so one free plot
slot is available again for the next transport cleanup slice.

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
The active dashboard now reads all 63 producer channels: ModulePackC, direct
row/detail channels, and LeanPackA/B.

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
**Changed**: the dashboard now derives `Long Debug` state locally from `DebugFlagsRow` plus lifecycle state
**Current plot budget**: 63 / 64

This cut removed a redundant debug-state transport row and restored exactly one
free producer plot slot without changing the rendered `Long Debug` summary.

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

**Prerequisite**: BUS EventRiskRow uses lean-only  
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
