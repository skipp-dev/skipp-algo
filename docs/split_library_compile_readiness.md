# Split Library Compile Readiness

Date: 2026-04-16
Reviewed commit: `1ed7bc61`

## Purpose

This document distinguishes five different states for split Pine libraries:

1. file exists in git
2. import paths are statically consistent in the checked-in repo
3. TradingView compile is plausible but not rerun
4. TradingView compile is operationally evidenced
5. TradingView publish is operationally evidenced

For `smc_context_resolvers`, `smc_profile_engine`, and `smc_utils`, the current `main` branch now has direct live TradingView compile evidence from this checkout, but still does not have direct publish evidence.

## Primary Targets

| Library file | Expected import path | Repo presence | Static import consistency | Live TradingView compile evidence | Direct publish evidence | Manual action still required? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SMC++/smc_context_resolvers.pine` | `preuss_steffen/smc_context_resolvers/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `cr` | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_context_resolvers` has `compile_ok: true` and `overall_preflight_ok: true` | no direct publish report or publish script found on current `main` | yes, if publish proof is required | compile-only live run used reusable TradingView profile auth and emitted a compiled screenshot |
| `SMC++/smc_profile_engine.pine` | `preuss_steffen/smc_profile_engine/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `pe` | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_profile_engine` has `compile_ok: true` and `overall_preflight_ok: true` | no direct publish report or publish script found on current `main` | yes, if publish proof is required | compile-only live run opened/saved the TradingView script and reached compile settlement |
| `SMC++/smc_utils.pine` | `preuss_steffen/smc_utils/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `u` and by split helper libraries | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_utils` has `compile_ok: true` and `overall_preflight_ok: true` | no direct publish report or publish script found on current `main` | yes, if publish proof is required | compile-only live run saved a fresh library draft and reached compile settlement |

## Compile-Only Report Caveat

The report root in `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` shows `overall_preflight_ok: false` even though all three target entries are green.

That top-level `false` should not be read as a compile failure for these libraries. In this run, `addToChart` and `checkInputs` were intentionally disabled, so binding and runtime stages remained `not_run`. Each target entry is the authoritative compile result for this compile-only pass.

Top-level evidence from the same report:

- `auth_mode: persistent_profile`
- `auth_reused_ok: true`
- `auth_ok: true`
- `ui_green: true`
- `compile_green: true`

Target-level evidence from the same report:

- `smc_context_resolvers`: `compile_ok: true`, `overall_preflight_ok: true`
- `smc_profile_engine`: `compile_ok: true`, `overall_preflight_ok: true`
- `smc_utils`: `compile_ok: true`, `overall_preflight_ok: true`

## Other Split Libraries

The repo still contains historical direct publish evidence for some other split or helper library lanes:

| Library/script | Direct publish evidence in repo | Current tracked publish entrypoint on `main` | Notes |
| --- | --- | --- | --- |
| `smc_bus_private` | yes; `automation/tradingview/reports/publish-bus-library-remediation-rerun16-20260405-222011.json` | no dedicated publish script located on current `main` | historical publish proof exists, but it predates current reviewed commit |
| `smc_lifecycle_private` | yes; `automation/tradingview/reports/publish-lifecycle-library-remediation-20260405-222456.json` | yes; `scripts/tv_publish_lifecycle_library.ts` | historical publish proof exists, but it predates current reviewed commit |
| `smc_observability_private` | yes; `automation/tradingview/reports/publish-observability-library-remediation-20260405-222625.json` | yes; `scripts/tv_publish_observability_library.ts` | historical publish proof exists, but it predates current reviewed commit |
| `smc_micro_profiles_generated` | yes; `automation/tradingview/reports/publish-micro-library-remediation-20260405-222755.json` and `artifacts/tradingview/library_release_manifest.json` | yes; `scripts/tv_publish_micro_library.ts` | this is a generated library path, not one of the three helper libraries above |
| `smc_core_types` | none located in this review | none located in this review | tracked in git, but no direct TradingView evidence was established here |
| `smc_draw` | none located in this review | none located in this review | tracked in git, but no direct TradingView evidence was established here |

## Honest Readout

- `smc_context_resolvers`, `smc_profile_engine`, and `smc_utils` are no longer only "statically plausible". They have direct live TradingView compile evidence from the current workspace snapshot.
- They are still not publish-proven on the current reviewed commit.
- If the acceptance bar is "TradingView can compile these exact library files today", that bar is met.
- If the acceptance bar is "TradingView private publish/import path for these exact libraries is operationally proven", that bar is still not met.

## Manual Publish / Verification Runbook

Use this only if you need exact publish proof for these three helper libraries.

1. Open TradingView with the reusable auth profile already present under `automation/tradingview/auth/chromium-profile`.
2. Open a fresh Pine library draft, paste the exact checked-in library source, and save it under the exact script name:
   - `smc_context_resolvers`
   - `smc_profile_engine`
   - `smc_utils`
3. Publish each script privately and verify the resulting import path and version remain exactly `/1`:
   - `preuss_steffen/smc_context_resolvers/1`
   - `preuss_steffen/smc_profile_engine/1`
   - `preuss_steffen/smc_utils/1`
4. Reopen the published script identity in TradingView and capture proof of the exact script name and version.
5. Save the resulting screenshots and any JSON or text notes under `automation/tradingview/reports/` and update this document with the exact artifact paths.

## Reproduction Command

The compile-only evidence in this document came from:

```bash
cd /Users/steffenpreuss/Downloads/skipp-algo
npm run tv:preflight:profile -- --no-open-existing --config /tmp/tv-split-library-preflight.json --out automation/tradingview/reports/preflight-split-library-2026-04-16-live.json
```
