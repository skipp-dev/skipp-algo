# Phase C Analysis — Dead Input & Lightweight Cleanup

**Status**: Ready for execution  
**Date**: 2026-04-01  
**Prerequisite**: Phase B ✅ done  
**Reference**: [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md), [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md)

---

## 1. Scope

Phase C removes declared-but-never-consumed `input.bool` variables from
`SMC_Core_Engine.pine`. These inputs occupy UI slots and settings rows but
have zero runtime effect — no gate, plot, or export references them.

---

## 2. Dead Inputs — Confirmed (11 variables)

All verified with full-file grep: each appears exactly once (declaration only).

| # | Variable | Line | Default | Original Group |
|---|----------|------|---------|----------------|
| 1 | `show_mtf_trend` | 3175 | true | MTF Trend overlay |
| 2 | `show_risk_levels` | 3203 | true | Risk level overlays |
| 3 | `show_reclaim_markers` | 3396 | true | Reclaim/lifecycle markers |
| 4 | `show_long_confirmation_markers` | 3397 | true | Confirmation markers |
| 5 | `show_long_background` | 3400 | true | Background coloring |
| 6 | `color_long_bars` | 3401 | — | Bar coloring |
| 7 | `show_accel_debug` | 3498 | false | Acceleration debug |
| 8 | `show_sd_debug` | 3514 | false | Standard deviation debug |
| 9 | `show_vol_regime_debug` | 3536 | false | Volatility regime debug |
| 10 | `show_stretch_overlay` | 3550 | true | Stretch overlay |
| 11 | `show_lower_extreme_bg` | 3552 | false | Lower extreme background |

**Note**: `color_long_bars` (#6) was discovered during this audit and is
not listed in the original RUNTIME_BUDGET.md dead inputs table.

---

## 3. Impact Assessment

| Metric | Before | After |
|--------|--------|-------|
| `input.*` declarations | ~260 | ~249 |
| UI settings rows saved | — | 11 |
| Lines removed | — | ~11 (declarations only) |
| Runtime behavior change | — | **None** |
| Plot budget change | — | **None** (32/64 unchanged) |

---

## 4. Risk Assessment

| Risk | Level | Mitigation |
|------|-------|------------|
| Breaking existing charts | **None** | Inputs are never read; removing them removes a settings row but no chart behavior changes. |
| Compile error | **None** | No code references these variables. |
| User confusion (missing setting) | **Low** | All 11 were vestigial — removing them simplifies the settings panel. |
| Pine version compatibility | **None** | Removing unused `input.bool` is backward-safe in Pine v6. |

---

## 5. Execution Checklist

- [ ] Remove 11 `input.bool` declarations from SMC_Core_Engine.pine
- [ ] Update RUNTIME_BUDGET.md: Phase C status → ✅ done, input count → ~249
- [ ] Update `color_long_bars` into the dead inputs table in RUNTIME_BUDGET.md
- [ ] Run Pine compiler check (TradingView save)
- [ ] Verify dashboard and lifecycle markers still render correctly
- [ ] Commit with message: `Phase C: remove 11 dead input.bool declarations`

---

## 6. Phase D Preview

After Phase C, the next cleanup target is **Phase D**: old broad event risk
fields. Prerequisites:

- BUS EventRiskRow must read from lean fields only (not broad `lib_event_*`)
- Fields: `lib_event_cooldown`, remaining broad event risk references
- See [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md) Phase C (labeled "Phase C"
  in that document but corresponds to Phase D here)

---

## 7. Live Input Inventory

After Phase C: **~249 `input.*` declarations**, of which:
- 78 live `input.bool` variables with active references
- Remaining `input.int`, `input.float`, `input.string`, `input.source`, etc.

No further dead `input.bool` variables were found during this audit.
