# TradingView Split Remediation Plan

Date: 2026-04-05

## Scope

This document tracks the remaining work for the active split of SMC Core logic into:

- `smc_lifecycle_private`
- `smc_bus_private`
- `smc_observability_private`

It separates three things that had been conflated before:

1. successful publish of an individual library
2. successful repo-side compile of the active core consumer
3. successful TradingView binding/runtime verification of the split consumer surface

Only the third point closes the split migration.

## WIP

- The validated split/remediation set is still only closed at working-tree level until it is committed and pushed.
- The split source files and TradingView helper lanes now exist and validate on current code, but repo closure is still pending:
  - `SMC++/smc_lifecycle_private.pine`
  - `SMC++/smc_bus_private.pine`
  - `SMC++/smc_observability_private.pine`
  - `scripts/tv_publish_lifecycle_library.ts`
  - `scripts/tv_publish_observability_library.ts`
  - `automation/tradingview/preflight-core-dashboard.json`

## Red

- None on the currently validated TradingView split path.
- The earlier bus publish blocker, hidden compile-overlay failure, and dashboard partial-binding failure are retired by the current remediation evidence below.

## Green

- Bus publish lane is green on current code.
  Evidence:
  - `automation/tradingview/reports/publish-bus-library-remediation-rerun16-20260405-222011.json`
  - `publishOk: true`
  - `identityVerificationMode: script_context`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Core/dashboard preflight is green on current code.
  Evidence:
  - `automation/tradingview/reports/preflight-core-dashboard-remediation-20260405-222204.json`
  - `compile_green: true`
  - `binding_green: true`
  - `runtime_green: true`
  - `overall_preflight_ok: true`
  - `bindings_refresh_attempted: true`
  - `bindings_refresh_recovered: true`
- Lifecycle publish lane is green on current code.
  Evidence:
  - `automation/tradingview/reports/publish-lifecycle-library-remediation-20260405-222456.json`
  - `publishOk: true`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Observability publish lane is green on current code.
  Evidence:
  - `automation/tradingview/reports/publish-observability-library-remediation-20260405-222625.json`
  - `publishOk: true`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Micro publish lane is green on current code.
  Evidence:
  - `automation/tradingview/reports/publish-micro-library-remediation-20260405-222755.json`
  - `publishOk: true`
  - `publishVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
  - `repoCoreValidationOk: true`
- Local regression checks are green on the same code state.
  Evidence:
  - `python3 -m pytest tests/test_smc_bus_v2_semantics.py tests/test_smc_core_engine_semantic_contract.py tests/test_smc_core_engine_split.py -q` -> `51 passed`
  - `npm run tv:test` -> `71 passed`
  - `npm run tsc:check` -> clean

## Remediation Outcome

- The bus lane was not fixed by a single syntax tweak; the decisive change was reducing the `smc_bus_private` export surface and moving non-essential late-stage wrappers back into `SMC_Core_Engine.pine`.
- The final working split keeps lifecycle and observability logic in dedicated private libraries while leaving the active consumer contract intact for `SMC_Dashboard.pine` and `SMC_Long_Strategy.pine`.
- TradingView automation now surfaces hidden compile overlays and can recover from stale dashboard bindings by refreshing the chart instance before re-checking the input contract.

## Remaining Close-Out

1. Commit the validated split/remediation changes.
2. Push the resulting commit on `main`.

## Closure Criteria

The split migration is only considered closed when all of the following are true at the same time:

- split source files are tracked in git
- bus publish report has exact current-code proof
- dashboard binding report shows the expected current-code consumer surface
- repo-side preflight for the active split scope is positive end-to-end
- docs match the current report evidence rather than historical assumptions