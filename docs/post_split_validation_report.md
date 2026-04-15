# Post-Split Validation Report — WP-SPLIT1–4

**Split commit:** [`7d769bfb`](https://github.com/skippALGO/skipp-algo/commit/7d769bfbebc0) (`refactor(smc): split Core Engine into modular libraries (WP-SPLIT1–4)`)  
**Report generated against:** HEAD after rebase onto `9a5b2c4f`  
**Working tree:** clean

---

## Summary

The SMC Core Engine (`SMC_Core_Engine.pine`) was split from **6 312 LOC → 5 474 LOC** (−838 lines extracted) across four work packages. All extracted code was moved into dedicated Pine Script v6 libraries under `SMC++/`. The Core Engine retains all runtime logic; extracted modules contain pure helper types, methods, and resolver functions.

No production-logic changes were made during the split. All modifications were mechanical extraction + import wiring.

---

## Modules Created

| WP | Library | Import Alias | Content |
|----|---------|:------------:|---------|
| WP-SPLIT1 | `SMC++/smc_context_resolvers.pine` | `cr` | ~73 exported pure context-resolver and BUS-packing functions |
| WP-SPLIT2 | `SMC++/smc_profile_engine.pine` | `pe` | `Bucket`, `ProfileConfig`, `Profile` types + 8 methods + 8 standalone helpers (~372 LOC) |
| WP-SPLIT3 | `SMC++/smc_utils.pine` (extended) | `u` | 7 embedded helpers added: `smc_lib_atr`, `smc_lib_ehma`, `smc_lib_thma`, `smc_lib_get_ma`, `smc_lib_bb`, `smc_lib_dmi`, `smc_lib_detect_divergence` |
| WP-SPLIT4 | *(cleanup)* | — | Deleted `legacy/SMC++.pine`, updated string refs `'SMC++'` → `'SMC'` |

---

## Test Results

Verified by running `pytest` against the current working tree:

| File | Tests | Passed | Failed |
|------|------:|-------:|-------:|
| `test_tradingview_decision_first_ui.py` | 22 | 22 | 0 |
| `test_smc_bus_v2_semantics.py` | 15 | 15 | 0 |
| `test_smc_core_engine_semantic_contract.py` | 21 | 21 | 0 |
| `test_smc_core_engine_split.py` | 21 | 21 | 0 |
| **Split-impacted total** | **79** | **79** | **0** |

All 79 split-impacted tests pass. The split-test file grew from 19 → 21 tests after two export-surface tests were added post-split (`test_profile_engine_exports_types_and_methods`, `test_utils_exports_moved_helpers`).

Three tests that initially broke due to WP-SPLIT extractions were fixed by adding architecture-aware library readers and redirecting assertions to the owning library source (commit `60b016ec`).

---

## Known Gaps

`tests/test_smc_long_dip_regressions.py` — **30 failed, 39 passed** (69 total):

All 30 failures are **pre-existing**. They reflect Core Engine evolution since the legacy `SMC++.pine` snapshot the regression tests were originally written against. None are caused by WP-SPLIT1–4.

| Root Cause | Count |
|------------|------:|
| Variable renamed (e.g. `helper_` prefix) | 7 |
| Function removed / renamed | 6 |
| Literal → computed (inline bool → function call) | 5 |
| Code refactored (pattern restructured) | 5 |
| Alert system overhauled | 3 |
| Metadata / indicator identity changed | 2 |
| Text evolved (tooltips, debug strings) | 2 |

A detailed triage with 6 proposed follow-up packs is tracked in [`docs/regression_triage_packs.md`](regression_triage_packs.md).

---

## Open Items

The following private libraries are validated at working-tree level but their split migration is not yet closed in the repo:

| Library | Status | Remediation Tracked In |
|---------|--------|----------------------|
| `SMC++/smc_lifecycle_private.pine` | Source exists, TradingView binding pending | [`tradingview-split-remediation-plan.md`](tradingview-split-remediation-plan.md) |
| `SMC++/smc_bus_private.pine` | Bus publish lane green on current code | [`tradingview-split-remediation-plan.md`](tradingview-split-remediation-plan.md) |
| `SMC++/smc_observability_private.pine` | Source exists, publish lane pending | [`tradingview-split-remediation-plan.md`](tradingview-split-remediation-plan.md) |

These are tracked separately because they require TradingView-side publish + binding verification, which is outside the scope of the code-level split validated here.
