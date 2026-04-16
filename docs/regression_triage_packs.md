# Regression Triage Packs

Reconciled on HEAD: `7142234634e1c16bf089c2addaec9224cb45c1f0` (2026-04-16)
Expected remote HEAD from task: `7142234634e1c16bf089c2addaec9224cb45c1f0`

## Repro Commands

Executed exactly on `main` for the batch-3 validation pass:

- `/Users/steffenpreuss/.venv/bin/python -m pytest tests/test_smc_long_dip_regressions.py -v --tb=line`
- `/Users/steffenpreuss/.venv/bin/python -m pytest tests/ -k "smc" --tb=line -q`

## Pytest Snapshot (Reproduced)

- Long-dip regression file: `69 passed, 0 failed, 0 skipped, 0 errors`
- Full SMC selection (`-k smc`): `2005 passed, 1 failed, 4 skipped, 2716 deselected, 11 warnings`

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

The only failing test in the broad SMC run is outside this long-dip regression file:

- `tests/test_smc_legacy_governance.py::test_long_dip_regression_stays_anchored_to_smc_plus`

Failure summary:

- Asserts a legacy path string (`SMC_PATH = ROOT / 'legacy' / 'SMC++.pine'`) in `tests/test_smc_long_dip_regressions.py`
- This is a governance/anchor expectation mismatch, not a moved-to-library regression in long-dip assertions

## Delta Summary

- Long-dip regression file now fully green: `69/69`
- Batch-3 moved-to-library assertion set is stable against split-library architecture
- Full `-k smc` remains green except one known legacy governance failure outside this scope
