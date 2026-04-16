# Regression Triage Packs

Reconciled on HEAD: `5fda7d27` (2026-04-16)

## Repro Commands

- `/Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_long_dip_regressions.py -v --tb=line`
- `/Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_legacy_governance.py -v --tb=short`
- `/Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "smc" --tb=line -q`

## Pytest Snapshot (Final Sweep)

- Long-dip regression file: `69 passed, 0 failed, 0 skipped, 0 errors`
- Legacy governance file: `5 passed, 0 failed`
- Full SMC selection (`-k smc`): `2006 passed, 0 failed, 4 skipped, 2716 deselected, 11 warnings`

## Batch-3 Moved-To-Library Focus

This batch targets regression assertions that still expected monolithic locations in `SMC_Core_Engine.pine` although code has moved to split libraries.

### Verified moved locations used by tests

- Alert detail composers:
  - `compose_long_*_alert_detail(...)` in `SMC++/smc_context_resolvers.pine`
  - Core call-sites use `cr.compose_long_*_alert_detail(...)`
- Profile engine helpers:
  - `normalize_profile_*`, `profile_data_ready`, `is_*_candle_now`, `profile_features_enabled` in `SMC++/smc_profile_engine.pine`
  - Core call-sites use `pe.*`
- Embedded utility helpers:
  - `smc_lib_*` in `SMC++/smc_utils.pine`
  - Core call-sites use `u.smc_lib_*`
- Observability helpers:
  - `emit_long_engine_debug_logs(...)`, `resolve_long_ready_signal_state(...)` in `SMC++/smc_observability_private.pine`
  - Core call-sites use `obv.*`

### Batch-3 assertion updates reflected in tests

- Repointed stale inline alert/detail expectations to resolver + observability library exports and alias call-sites.
- Removed obsolete monolith-only assumptions where dynamic/product-state alert architecture replaced old static preset checks.
- Simplified brittle inline checks to architecture-faithful contracts:
  - verify function exists in target split library
  - verify core references it via correct import alias

## Open Failures After Batch-3

No open failures remain. The previously failing governance test was resolved in the final sweep:

- `test_long_dip_regression_stays_anchored_to_smc_plus` → renamed to
  `test_long_dip_regression_anchors_to_active_core_engine`
- **Reason:** The governance assertion expected `SMC_PATH = ROOT / 'legacy' / 'SMC++.pine'`
  but the completed split-library migration moved the long-dip regression anchor to
  `SMC_Core_Engine.pine`. No `legacy/` directory or root-level `SMC++.pine` exist.
  The assertion was updated to match the actual, documented architecture.

## Delta Summary

- Long-dip regression file: `69/69` green
- Legacy governance file: `5/5` green (was `4/5` before final sweep)
- Full SMC (`-k smc`): `2006/2006` green, `0 failed`
- All batches (1–3 + final sweep) complete — no deferred failures remain
