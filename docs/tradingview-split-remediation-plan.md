# TradingView Split Remediation Plan

Date: 2026-04-05
Reviewed: 2026-04-16

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

## Current Status

- Status: `closed`.
  Git close-out is complete on `main`.
  Evidence:
  - `SMC++/smc_lifecycle_private.pine` is tracked in git.
  - `SMC++/smc_bus_private.pine` is tracked in git.
  - `SMC++/smc_observability_private.pine` is tracked in git.
  - `scripts/tv_publish_lifecycle_library.ts` is tracked in git.
  - `scripts/tv_publish_observability_library.ts` is tracked in git.
  - `automation/tradingview/preflight-core-dashboard.json` is tracked in git.
  - The active consumer still imports the split libraries on `/1`:
    - `SMC_Core_Engine.pine` imports `preuss_steffen/smc_lifecycle_private/1 as ll`
    - `SMC_Core_Engine.pine` imports `preuss_steffen/smc_bus_private/1 as bp`
    - `SMC_Core_Engine.pine` imports `preuss_steffen/smc_observability_private/1 as obv`
    - `SMC++/smc_context_resolvers.pine` imports `preuss_steffen/smc_bus_private/1 as bp`
- Status: `open`.
  Exact current-code TradingView proof is missing.
  Reason:
  - The latest publish/preflight artifacts in this document were generated on `2026-04-05`.
  - The latest commit touching the split surfaces and active consumers is `7d769bfb` on `2026-04-15` (`refactor(smc): split Core Engine into modular libraries (WP-SPLIT1–4)`).
  - Therefore the documented publish/compile/binding/runtime evidence is historical evidence, not exact proof for the current checked-in code on `main`.
  - Separate helper-library compile readiness for `smc_context_resolvers`, `smc_profile_engine`, and `smc_utils` is now tracked in `docs/split_library_compile_readiness.md`; that document contains fresh `2026-04-16` live compile evidence, but not publish proof.
- Status: `open`.
  The full local SMC pytest sweep is not green.
  Evidence:
  - `python -m pytest tests/ -k "smc" --tb=short -q` -> `23 failed, 46 passed`
  - The failures are concentrated in `tests/test_smc_long_dip_regressions.py`

## Red

- No currently reproduced TradingView blocker is documented in-repo for the split lanes themselves.
- The blocking issue is evidentiary, not a newly confirmed product-code failure:
  - fresh current-code TradingView publish/preflight evidence has not been rerun after the latest split-surface changes
  - the full local `pytest -k "smc"` sweep is not currently clean

## Historical Green Evidence

The following artifacts still exist and remain useful as historical remediation evidence, but they do not by themselves close the migration on the current `main` branch because they predate the latest split-surface commit.

- Bus publish lane was green on the validated `2026-04-05` code state.
  Evidence:
  - `automation/tradingview/reports/publish-bus-library-remediation-rerun16-20260405-222011.json`
  - `publishOk: true`
  - `identityVerificationMode: script_context`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Core/dashboard preflight was green on the validated `2026-04-05` code state.
  Evidence:
  - `automation/tradingview/reports/preflight-core-dashboard-remediation-20260405-222204.json`
  - `compile_green: true`
  - `binding_green: true`
  - `runtime_green: true`
  - `overall_preflight_ok: true`
  - `bindings_refresh_attempted: true`
  - `bindings_refresh_recovered: true`
- Lifecycle publish lane was green on the validated `2026-04-05` code state.
  Evidence:
  - `automation/tradingview/reports/publish-lifecycle-library-remediation-20260405-222456.json`
  - `publishOk: true`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Observability publish lane was green on the validated `2026-04-05` code state.
  Evidence:
  - `automation/tradingview/reports/publish-observability-library-remediation-20260405-222625.json`
  - `publishOk: true`
  - `versionVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
- Micro publish lane was green on the validated `2026-04-05` code state.
  Evidence:
  - `automation/tradingview/reports/publish-micro-library-remediation-20260405-222755.json`
  - `publishOk: true`
  - `publishVerificationMode: idempotent_no_change`
  - `publishedVersion: 1`
  - `repoCoreValidationOk: true`
- Local regression checks were green on that same `2026-04-05` code state.
  Evidence:
  - `python3 -m pytest tests/test_smc_bus_v2_semantics.py tests/test_smc_core_engine_semantic_contract.py tests/test_smc_core_engine_split.py -q` -> `51 passed`
  - `npm run tv:test` -> `71 passed`
  - `npm run tsc:check` -> clean

## Remediation Outcome

- The bus lane was not fixed by a single syntax tweak; the decisive change was reducing the `smc_bus_private` export surface and moving non-essential late-stage wrappers back into `SMC_Core_Engine.pine`.
- The final working split keeps lifecycle and observability logic in dedicated private libraries while leaving the active consumer contract intact for `SMC_Dashboard.pine` and `SMC_Long_Strategy.pine`.
- TradingView automation now surfaces hidden compile overlays and can recover from stale dashboard bindings by refreshing the chart instance before re-checking the input contract.

## Close-Out Item Status

1. Status: `closed`.
  Commit the validated split/remediation changes.
  Reason:
  - The split libraries and helper lanes are tracked on `main`.

2. Status: `closed`.
  Push the resulting commit on `main`.
  Reason:
  - The repository is synced with `origin/main` and no local-only split-remediation close-out remains.

3. Status: `open`.
  Refresh TradingView validation on current `main`.
  Reason:
  - Current publish/import/runtime evidence in this document is from `2026-04-05` and predates the latest split-surface commit on `2026-04-15`.
  Required evidence:
  - rerun bus publish validation
  - rerun lifecycle publish validation
  - rerun observability publish validation
  - rerun dashboard/core preflight covering compile, binding, and runtime smoke

4. Status: `open`.
  Refresh repo-side automated validation for the broader SMC scope.
  Reason:
  - `python -m pytest tests/ -k "smc" --tb=short -q` is currently not green (`23 failed, 46 passed`).

## Closure Criteria

The split migration is only considered closed when all of the following are true at the same time:

- split source files are tracked in git
- bus publish report has exact current-code proof
- dashboard binding report shows the expected current-code consumer surface
- repo-side preflight for the active split scope is positive end-to-end
- docs match the current report evidence rather than historical assumptions

Current review against these criteria:

- `closed`: split source files are tracked in git
- `open`: bus publish report has exact current-code proof
- `open`: dashboard binding report shows the expected current-code consumer surface for the current checked-in code
- `open`: repo-side preflight for the active split scope is positive end-to-end on current code
- `open`: docs still rely on historical TradingView evidence until a fresh rerun is recorded