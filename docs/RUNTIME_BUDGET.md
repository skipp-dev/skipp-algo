# Runtime Budget — SMC_Core_Engine.pine v5.5a

**Status**: Active inventory  
**Last updated**: AP7 v5.5b — Phase B unblocked

---

## 1. Engine Metrics

| Metric | Count |
|--------|-------|
| Total lines | ~6155 |
| `var` declarations | ~371 |
| `input.*` declarations | ~260 |
| `plot()` calls | ~32 |
| `request.security()` | 5 |
| `request.security_lower_tf()` | 2 |
| `ta.*` / `math.*` usages | ~191 |

### Plot Budget

TradingView allows max 64 plots per script. Current usage: **32 / 64**.
BUS protocol consumes ~9 plots (ModulePackA–D + LeanPackA/B + EventRisk).

---

## 2. Field Categories

### Primary (lean-only, no fallback needed)
These fields are read from lean families and drive the engine directly.

| Family | Fields | Consumer |
|--------|--------|----------|
| Event Risk Light | 7 | event_risk gate, dashboard |
| Session Context Light | 4 required + 1 optional | session gate, dashboard |
| OB Context Light | 5 | OB gate, dashboard |
| FVG Lifecycle Light | 6 | FVG gate, dashboard |
| Structure State Light | 4 | structure gate, dashboard |
| Signal Quality | 5 | quality scoring, dashboard |
| **Total** | **32** | |

### BUS Backward Compat (broad fields, Dashboard only)
All BUS PackE/F/G fields, resolvers, and plot calls **removed in Phase B (AP6 v5.5b)**.
Dashboard reads only PackA-D + LeanPackA/B.

### Dead Inputs (declared, never consumed)
These `input.bool` variables are defined but never referenced by any gate or plot.
Safe to remove — saves ~10 input slots.

| Input | Line | Default |
|-------|------|---------|
| `show_mtf_trend` | 3331 | true |
| `show_risk_levels` | 3359 | true |
| `show_reclaim_markers` | 3653 | true |
| `show_long_confirmation_markers` | 3654 | true |
| `show_long_background` | 3657 | true |
| `show_accel_debug` | 3755 | false |
| `show_sd_debug` | 3771 | false |
| `show_vol_regime_debug` | 3793 | false |
| `show_stretch_overlay` | 3807 | true |
| `show_lower_extreme_bg` | 3809 | false |

---

## 3. Removal Roadmap

### Phase B: BUS compat fields (33 fields, 3 plot slots)
**Status**: ✅ DONE (AP6 v5.5b)  
**Removed**: 33 field declarations, 12 resolver functions, 3 plot calls, ~265 lines total  
**Plot budget**: 32 / 64

### Phase C: Dead inputs cleanup (10 inputs)
**Prerequisite**: None — all verified dead  
**Effort**: Low  
**Runtime savings**: 10 input declarations (~10 lines)

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

## 5. Principles (v5.5a)

1. **Pine Runtime Budget** is architectural, not incidental (Principle 12)
2. **Support Family Admission Rule** — new families must prove value vs. runtime cost (Principle 14)
3. Every new `request.security` call requires explicit budget justification
4. Dead fields/inputs discovered during refactoring should be logged here for next cleanup wave
