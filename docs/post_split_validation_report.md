# Post-Split Validation Report — WP-SPLIT1–4

**Baseline frozen:** `ba308b06` (`test(smc): harden regression tests for post-split module boundaries`)  
**Split commit:** `7d769bfb` (`refactor(smc): split Core Engine into modular libraries (WP-SPLIT1–4)`)  
**Working tree:** clean  
**No broad regression cleanup was performed.** Only split-caused boundary failures were fixed.

---

## Split Status

The Core Engine was split from 6312 → 5474 LOC across 4 work packages:

| WP | Library | Alias | Content |
|----|---------|-------|---------|
| WP-SPLIT1 | `SMC++/smc_context_resolvers.pine` | `cr` | ~73 exported pure resolver and BUS packing functions |
| WP-SPLIT2 | `SMC++/smc_profile_engine.pine` | `pe` | Bucket, ProfileConfig, Profile types + methods (~372 LOC) |
| WP-SPLIT3 | `SMC++/smc_utils.pine` (extended) | `u` | 7 embedded helpers (smc_lib_atr, smc_lib_ehma, etc.) |
| WP-SPLIT4 | — | — | Deleted `legacy/SMC++.pine`, updated string refs `'SMC++'` → `'SMC'` |

---

## Test Results

| File | Tests | Passed | Failed |
|------|------:|-------:|-------:|
| `test_tradingview_decision_first_ui.py` | 22 | 22 | 0 |
| `test_smc_core_engine_split.py` | 19 | 19 | 0 |
| `test_smc_core_engine_semantic_contract.py` | 21 | 21 | 0 |
| `test_smc_bus_v2_semantics.py` | 15 | 15 | 0 |
| `test_smc_long_dip_regressions.py` | 69 | 39 | **30** |
| **Total** | **146** | **116** | **30** |

All 4 split-specific test files pass cleanly.  
All 30 remaining failures are in `test_smc_long_dip_regressions.py`.

---

## Split-Caused Failures — Fixed

3 failures were directly caused by WP-SPLIT extractions and have been resolved:

| Test | Root Cause | Fix Applied |
|------|-----------|-------------|
| `test_atr_helper_uses_deterministic_warmup_accumulator` | `smc_lib_atr` definition moved to `smc_utils.pine` (WP-SPLIT3) | Body assertions → `_read_utils_source()`, added `u.smc_lib_atr(` call-site check on core |
| `test_udt_render_and_draw_helpers_guard_na_before_field_access` | `Profile.delete` moved to `smc_profile_engine.pine` (WP-SPLIT2) | Profile assertions → `_read_profile_engine_source()`, OrderBlock assertions stay on core |
| `test_profile_and_track_obs_use_defensive_semantic_helpers` | 7 helper definitions moved to `smc_profile_engine.pine` (WP-SPLIT2) | Definition assertions → `_read_profile_engine_source()`, call-site assertions updated to `pe.` prefix |

Test helpers added (each reads exactly one file):
- `_read_resolver_source()` → `SMC++/smc_context_resolvers.pine`
- `_read_utils_source()` → `SMC++/smc_utils.pine`
- `_read_profile_engine_source()` → `SMC++/smc_profile_engine.pine`

---

## Pre-Existing Regression Debt — 30 Open

These assertions were already stale before WP-SPLIT1–4. They reflect Core Engine evolution since the legacy `SMC++.pine` snapshot the tests were written against. **None are split-caused.**

| Category | Count | Examples |
|----------|------:|---------|
| Variable renamed | 7 | `long_arm_locked_source_id` → `helper_long_arm_locked_source_id` |
| Function removed/renamed | 6 | `db_trend_text(`, `compute_overhead_context()`, `resolve_long_visual_text()` |
| Literal → computed | 5 | `bool armed_prequality_ok = true` → `compute_long_arm_prequality_ok(…)` |
| Code refactored | 5 | invalidation string patterns, arm_source_kind comparisons |
| Alert system overhauled | 3 | preset definitions, close-safe events, debounced events |
| Indicator/resource changed | 2 | title `"SMC++"` → `"SMC Long-Dip Suite v7"`, `max_labels_count` 500 → 300 |
| Text evolved | 2 | tooltip text, freshness/quality text strings |

---

## Next Steps

1. **Batch-update the 30 pre-existing failures** in a dedicated pass (separate from split work):
   - Group by evolution kind
   - Update assertions to match current Core Engine code
   - Delete tests whose contract is no longer relevant
2. **Add `test_profile_engine_exports_types_methods_and_helpers()`** to guard the `smc_profile_engine` export surface (WP-SPLIT2 audit finding R2)
