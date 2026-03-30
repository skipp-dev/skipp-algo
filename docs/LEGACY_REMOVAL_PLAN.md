# Legacy Removal Plan — SMC_Core_Engine.pine

Status: **Prepared for v5.6+**  
Prerequisite: All v5.5 lean fields verified as primary (AP1-AP7 complete).

---

## 1. Field Groups — Removal Candidates

### Phase A: Immediate — Read-only legacy, zero pipeline consumers

| Old Group | Lines (approx.) | v5.5 Replacement | Blocking? | Est. lines saved |
|-----------|-----------------|-------------------|-----------|------------------|
| Zone Intelligence (v5.1) | `lib_active_support_cnt` … `lib_zone_liq_imbalance` | Signal Quality, OB/FVG Light | No (BUS ModulePackE only) | ~14 |
| Reversal Context (v5.1) | `lib_reversal_active` … `lib_retrace_ok` | Signal Quality | No (BUS ModulePackE only) | ~12 |
| Zone Projection (v5.2) | `lib_zone_proj_*` | Signal Quality | No (BUS ModulePackF only) | ~10 |
| Profile Context (v5.2) | `lib_profile_*` | Signal Quality | No (BUS ModulePackF only) | ~18 |
| Range Regime (v5.3) | `lib_range_regime` … `lib_range_regime_score` | Signal Quality | No (BUS ModulePackG only) | ~11 |
| Range Profile Regime (v5.3) | `lib_rpr_*` | Signal Quality | No (BUS ModulePackG only) | ~20 |
| Session Structure (v5.3) | `lib_sess_*` | Session Context Light | No (BUS ModulePackG only) | ~15 |
| **total Phase A** | | | | **~100** |

### Phase B: Gated — Legacy context gates (declare-only, not in pipeline)

| Old Gate | v5.5 Replacement | Used by | Safe condition |
|----------|------------------|---------|----------------|
| `flow_quality_ok` | Signal Quality score | BUS ModulePackE | BUS removed or updated |
| `compression_entry_ok` | Signal Quality headroom | BUS ModulePackE | BUS removed or updated |
| `atr_regime_ok` | Signal Quality headroom | BUS ModulePackE | BUS removed or updated |
| `zone_context_long_ok` | Signal Quality score | BUS ModulePackE | BUS removed or updated |
| `reversal_context_boost` | Signal Quality score | BUS ModulePackE | BUS removed or updated |
| `session_context_ok` | `session_light_ok` | BUS ModulePackF | BUS removed or updated |
| `ob_context_long_ok` | `ob_light_bull_ok` | BUS ModulePackF | BUS removed or updated |
| `struct_state_ok` | `struct_light_trending` | BUS ModulePackG | BUS removed or updated |
| `imbalance_ok` | `fvg_light_active_ok` | BUS ModulePackG | BUS removed or updated |
| `session_struct_ok` | `session_light_ok` | BUS ModulePackG | BUS removed or updated |
| `range_regime_ok` | Signal Quality score | BUS ModulePackG | BUS removed or updated |
| `range_profile_ok` | Signal Quality score | BUS ModulePackG | BUS removed or updated |
| `session_struct_state_ok` | `session_light_ok` | BUS ModulePackG | BUS removed or updated |

### Phase C: Dashboard BUS compat — Old BUS ModulePacks E/F/G

| BUS Pack | Fields consumed | Safe condition |
|----------|----------------|----------------|
| `BUS ModulePackE` | Flow, Compression, Zone, Reversal | Dashboard migrated to LeanPack |
| `BUS ModulePackF` | Session, Sweep, OB, Profile | Dashboard migrated to LeanPack |
| `BUS ModulePackG` | Structure, Imbalance, Session Struct, Range | Dashboard migrated to LeanPack |

**Removal criteria**: SMC_Dashboard.pine updated to read `BUS LeanPackA/B` instead.

### Phase D: Old Event Risk broad fields

| Field | v5.5 Replacement | Blocking? |
|-------|-------------------|-----------|
| `lib_market_event_blocked` | `lib_erl_market_blocked` | No — AP1/AP4 already rewired |
| `lib_symbol_event_blocked` | `lib_erl_symbol_blocked` | No — AP1/AP4 already rewired |
| `lib_event_cooldown` | N/A (lean has no cooldown concept) | `event_risk_soft_block` still references |
| `event_risk_hard_block` | `event_risk_light_hard_block` | BUS EventRiskRow — already updated |
| `event_risk_soft_block` | `event_risk_state == "caution"` | BUS EventRiskRow — still references |

---

## 2. Removal Sequence

1. **Update SMC_Dashboard.pine** to read LeanPack A/B instead of ModulePack E/F/G
2. **Remove BUS ModulePackE/F/G** plot calls from Engine (saves ~3 plot slots)
3. **Remove old lib_* field reads** for Zone, Reversal, ZoneProj, Profile, Range, RPR, Session Struct
4. **Remove old context gate declarations** (v5.1/v5.2/v5.3 gates)
5. **Remove `event_risk_hard_block` / `event_risk_soft_block`** old derivations
6. **Update ENGINE_CONSUMED_FIELDS** in test contract
7. **Run full test suite** to confirm no regressions

---

## 3. Estimated Impact

- **Lines removed**: ~150-200 from Engine
- **Fields removed**: ~70 old broad fields
- **BUS plots freed**: 3 (ModulePackE/F/G)
- **Risk**: Dashboard compatibility — must update Dashboard first

---

## 4. Safe Removal Criteria (per field group)

Before removing any field group, verify:
- [ ] No `mp.FIELD_NAME` reference in Engine outside of the deprecated section
- [ ] No consumer in Dashboard reads the BUS pack carrying that field group
- [ ] TestV55DriftGuard tests still pass
- [ ] TestV55LeanContract tests still pass
- [ ] ENGINE_CONSUMED_FIELDS updated to remove field
- [ ] Full pytest suite green (all test files)
