# TradingView Runtime Validation

## Scope

This document tracks only the TradingView automation validation layer:

- auth reuse
- chart access
- Pine editor access
- compile/save success when the run is mutating
- script-on-chart visibility
- settings/input binding verification
- minimal runtime smoke checks

It does not declare new producer, dashboard, strategy, or bus behavior.

## Current Evidence

Historical live green TradingView evidence was captured before the staged status model was introduced.
Those report files are not present in the current checkout, so they remain historical documentation rather than locally re-runnable artifacts.

- Historical report path: `automation/tradingview/reports/preflight-2026-03-24T04-39-33-983Z.json`
- Result scope in that legacy report:
  - SMC Core Engine compiled
  - SMC Dashboard compiled and its 26 input bindings were visible
  - SMC Long Strategy compiled and its 8 input bindings were visible

That report is still valid as historical runtime evidence, but it predates the new staged fields:

- `execution_mode`
- `auth_ok`
- `chart_ok`
- `editor_ok`
- `compile_ok`
- `script_found_on_chart_ok`
- `settings_open_ok`
- `inputs_tab_ok`
- `bindings_count_ok`
- `bindings_names_ok`
- `runtime_smoke_ok`
- `overall_preflight_ok`

First staged-format report emitted from the new implementation:

- Historical report path: `automation/tradingview/reports/preflight-2026-03-24T05-44-44-193Z.json`
- Observed auth state in that shell: `fresh_login`
- Result: explicit fail-fast report with `auth_ok = false` and the remaining scopes marked `not_run`

Latest staged-format authenticated report:

- Historical report path: `automation/tradingview/reports/preflight-2026-03-24T09-10-25-787Z.json`
- Observed auth state in this shell: `storage_state`
- Result: `execution_mode = mutating`, `auth_ok = true`, `ui_green = true`, `compile_green = true`, `binding_green = true`, `runtime_green = true`, `overall_preflight_ok = true`

That latest green report used a portable storage-state artifact regenerated from the persistent profile with IndexedDB included, and the runtime layer now also clears TradingView's read-only historical-script editor state before writing.

## Current Workspace Refresh

Refresh date: 2026-04-03

The current workspace contains the documented entry scripts:

- `scripts/tv_preflight.ts`
- `scripts/tv_publish_micro_library.ts`
- `scripts/create_tradingview_storage_state.ts`

But it does not currently contain:

- the shared TradingView automation layer imported from `automation/tradingview/lib/...`
- the `automation/tradingview/reports` directory referenced by the historical docs
- a reusable auth artifact such as `automation/tradingview/auth/storage-state.json`

That means a fresh live TradingView validation run is blocked in this checkout. The active repo signal is therefore static contract validation plus the external manual runbook, not a locally reproducible preflight pass.

## Current Status Interpretation

- Validation implementation status: updated to staged reporting
- Last emitted live report status: staged format
- Latest proven live UI/compile/binding/runtime pass: historical yes, but not locally reproducible from the current checkout
- Latest emitted staged-format live report in this checkout: none, because the automation prerequisites are missing

## Execution Modes

The TradingView validation layer now has two explicit modes:

- `mutating`: opens the repo source, writes it into the Pine editor, saves it, waits for compile settlement, then continues with chart/input/runtime checks
- `readonly`: opens the existing TradingView script and runs UI/chart/input/runtime checks without overwriting editor content or saving

The report now carries `execution_mode` at report and target level so readonly smoke runs are not misread as repo-source compile evidence.

## Runtime Smoke Definition

`runtime_smoke_ok` is intentionally minimal. It means:

1. the script is still visible on the chart after add-to-chart
2. no sign-in modal is blocking the chart surface
3. no visible compile error marker is present on the page

It is not a strategy-behavior or trading-logic certification.

## Binding Verification Definition

The preflight now separates binding verification into two explicit checks:

- `bindings_count_ok`: the expected number of source bindings is visible
- `bindings_names_ok`: the expected binding names are visible

If a check is not applicable, the report uses `not_run`.
If a check was intentionally skipped or could not be asserted with confidence, the report uses `not_verified`.

Neither `not_run` nor `not_verified` count as success.

## Auth Prerequisite

The automation now resolves auth sources in this order:

1. valid `TV_STORAGE_STATE`
2. `TV_PERSISTENT_PROFILE_DIR` as explicit fallback
3. `fresh_login` only as a documented non-reusable state

When the run lands in `fresh_login`, preflight writes a failed report instead of attempting a misleading UI flow.

See [tradingview-auth-modes.md](tradingview-auth-modes.md) for the exact resolution rules.
