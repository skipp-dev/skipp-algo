# Legacy Removal Plan — SMC_Core_Engine.pine

Status: **Phase A executed (AP6 v5.5), shadow logic removed (AP5 v5.5a), Phase B executed (AP6 v5.5b)**  
Last updated: AP6 v5.5b — Phase B complete: ModulePackE/F/G + 33 BUS compat fields + 12 resolvers removed  
See also: [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md)

---

## 1. Completed in AP6

### Dead code removed (~173 declarations)

| Action | Removed / Kept | Lines saved |
|--------|---------------|-------------|
| Zone Intelligence (v5.1) dead fields | 11 removed, 2 kept (BUS PackE) | ~11 |
| Reversal Context (v5.1) dead fields | 8 removed, 4 kept (BUS PackE) | ~8 |
| Session Context (v5.2+v5.3) dead fields | 13 removed, 3 kept (BUS PackF) | ~13 |
| Liquidity Sweeps (v5.2) dead fields | 5 removed, 4 kept (BUS PackF) | ~5 |
| Liquidity Pools (v5.2) — ALL | 11 removed (zero consumers) | ~11 |
| Order Blocks (v5.2) dead fields | 10 removed, 3 kept (BUS PackF) | ~10 |
| Zone Projection (v5.2) — ALL | 10 removed (zero consumers) | ~10 |
| Profile Context (v5.2) dead fields | 16 removed, 2 kept (BUS PackF) | ~16 |
| Structure State (v5.3) dead fields | 10 removed, 4 kept (BUS PackG) | ~10 |
| Imbalance Lifecycle (v5.3) dead fields | 19 removed, 4 kept (BUS PackG) | ~19 |
| Session Structure (v5.3) dead fields | 10 removed, 4 kept (BUS PackG) | ~10 |
| Range Regime (v5.3) dead fields | 8 removed, 3 kept (BUS PackG) | ~8 |
| Range Profile Regime (v5.3) — ALL | 22 removed (zero consumers) | ~22 |
| Legacy context gates (v5.1/v5.2/v5.3) | 17 removed (never consumed) | ~20 |
| **Total** | **~173 removed, 33 kept** | **~173 lines** |

### Remaining BUS compat fields (33 total)

| BUS Pack | Fields kept |
|----------|------------|
| PackE (6) | `lib_zone_context_bias`, `lib_active_zone_cnt`, `lib_reversal_active`, `lib_setup_score`, `lib_confirm_score`, `lib_follow_through_score` |
| PackF (12) | `lib_session_context`, `lib_in_killzone`, `lib_session_ctx_score`, `lib_recent_bull_sweep`, `lib_recent_bear_sweep`, `lib_sweep_reclaim`, `lib_sweep_quality`, `lib_bull_ob_fvg_conf`, `lib_ob_bias`, `lib_ob_context_score`, `lib_profile_grade`, `lib_profile_ctx_score` |
| PackG (15) | `lib_struct_state`, `lib_struct_bull_active`, `lib_struct_bear_active`, `lib_struct_fresh`, `lib_imbalance_state`, `lib_bpr_active`, `lib_liq_void_bull`, `lib_liq_void_bear`, `lib_sess_struct_score`, `lib_sess_or_break`, `lib_sess_pdh_swept`, `lib_sess_pdl_swept`, `lib_range_regime`, `lib_range_regime_score`, `lib_range_balance` |

---

## 2. Remaining Work (v5.6+)

### Phase B: Remove BUS ModulePackE/F/G + remaining 33 fields

**Status**: UNBLOCKED — Dashboard reads LeanPackA/B (AP5 v5.5b).  
Dashboard never consumed ModulePackE/F/G; only PackA-D are still in use.

| Step | Status |
|------|--------|
| Update SMC_Dashboard.pine → read LeanPack A/B | ✅ DONE (AP5 v5.5b) |
| Verify Dashboard does NOT read ModulePackE/F/G | ✅ Confirmed — only PackA-D consumed |
| Remove BUS ModulePackE/F/G plot calls (lines 6398-6400) | ✅ DONE (AP6 v5.5b) |
| Remove 33 BUS compat field declarations (lines ~3454-3551) | ✅ DONE (AP6 v5.5b) |
| Remove 12 BUS E/F/G resolver functions (lines ~2166-2320) | ✅ DONE (AP6 v5.5b) |
| Free 3 plot slots (35→32 of 64) | ✅ DONE (AP6 v5.5b) |

**Concrete removal inventory (Phase B)**:

| Category | Items | Lines saved |
|----------|-------|-------------|
| BUS compat field declarations | 33 fields (PackE 6, PackF 12, PackG 15) | ~107 |
| BUS E/F/G resolver functions | 12 functions: `resolve_bus_{flow_qualifier,compression,zone_context,reversal_context,session_context,sweep,ob_context,profile,struct_state,imbalance,session_struct,range_regime}_row` | ~155 |
| BUS plot calls | 3 plots: ModulePackE/F/G | 3 |
| **Total** | **48 items** | **~265 lines** |

**Usage verification** (all 33 BUS compat fields):
- Each field appears exactly **2× in Engine**: 1 declaration + 1 BUS pack call
- **Zero** internal Engine consumption (no gate, no condition, no other plot)
- All 12 resolver functions are called **only** from PackE/F/G pack lines
- `pack_bus_row` / `pack_bus_four` helpers are shared with PackA-D → stay

### Phase C: Old Event Risk broad core aliases

| Field | v5.5 Replacement | Blocking? |
|-------|-------------------|-----------|
| `lib_market_event_blocked` | `lib_erl_market_blocked` | No — AP1 already rewired |
| `lib_symbol_event_blocked` | `lib_erl_symbol_blocked` | No — AP1 already rewired |
| `lib_event_cooldown` | N/A | No — `event_risk_soft_block` removed in AP5 v5.5a |
| ~~`event_risk_hard_block`~~ | ~~`event_risk_light_hard_block`~~ | **Removed** — AP5 v5.5a (No Shadow Logic) |
| ~~`event_risk_soft_block`~~ | ~~`event_risk_state == "caution"`~~ | **Removed** — AP5 v5.5a (No Shadow Logic) |

**Status**: ✅ done — the remaining broad event-risk aliases have been removed from `SMC_Core_Engine.pine`; the generated library still exports broader event metadata for non-core consumers like the overlay and alerting.

---

## 3. Safe Removal Criteria (per field group)

Before removing any remaining field group, verify:
- [ ] No `mp.FIELD_NAME` reference in Engine outside of the deprecated section
- [ ] No consumer in Dashboard reads the BUS pack carrying that field group
- [ ] TestV55DriftGuard tests still pass
- [ ] TestV55LeanContract tests still pass
- [ ] ENGINE_CONSUMED_FIELDS updated to remove field
- [ ] Full pytest suite green (all test files)
