# Split Library Compile Readiness

Date: 2026-04-16 (updated)
Reviewed commit: `45858132`

## Purpose

This document distinguishes five different states for split Pine libraries:

1. file exists in git
2. import paths are statically consistent in the checked-in repo
3. TradingView compile is plausible but not rerun
4. TradingView compile is operationally evidenced
5. TradingView publish is operationally evidenced

For `smc_context_resolvers`, `smc_profile_engine`, and `smc_utils`, the current `main` branch has direct live TradingView compile evidence.

For all 5 manual-publish target libraries (`smc_core_types`, `smc_draw`, `smc_utils`, `smc_profile_engine`, `smc_context_resolvers`), the user reported manual publish on 2026-04-16 but no post-publish screenshot was captured. All 5 remain publish-unverified in the repo. See `docs/tradingview-manual-publish-evidence-2026-04-16.md` for the structured evidence record.

## Primary Targets

| Library file | Expected import path | Repo presence | Static import consistency | Live TradingView compile evidence | Direct publish evidence | Manual action still required? | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SMC++/smc_core_types.pine` | `preuss_steffen/smc_core_types/1` | yes | yes; imported by `smc_utils` | no; existing screenshot shows CE10013 compile error (paste-induced indentation) | no; user reported manual publish — unverified | yes, publish screenshot needed | see `docs/tradingview-manual-publish-evidence-2026-04-16.md` |
| `SMC++/smc_draw.pine` | `preuss_steffen/smc_draw/1` | yes | yes; imported by `smc_profile_engine` | no compile screenshot in repo | no; user reported manual publish — unverified | yes, compile + publish screenshot needed | see `docs/tradingview-manual-publish-evidence-2026-04-16.md` |
| `SMC++/smc_utils.pine` | `preuss_steffen/smc_utils/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `u` and by split helper libraries | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_utils` has `compile_ok: true` and `overall_preflight_ok: true` | no; user reported manual publish — unverified | yes, publish screenshot needed | compile-only live run saved a fresh library draft and reached compile settlement |
| `SMC++/smc_profile_engine.pine` | `preuss_steffen/smc_profile_engine/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `pe` | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_profile_engine` has `compile_ok: true` and `overall_preflight_ok: true` | no; user reported manual publish — unverified | yes, publish screenshot needed | compile-only live run opened/saved the TradingView script and reached compile settlement |
| `SMC++/smc_context_resolvers.pine` | `preuss_steffen/smc_context_resolvers/1` | yes | yes; imported by `SMC_Core_Engine.pine` as `cr` | yes; `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` target `smc_context_resolvers` has `compile_ok: true` and `overall_preflight_ok: true` | no; user reported manual publish — unverified | yes, publish screenshot needed | compile-only live run used reusable TradingView profile auth; CE10237 warnings fixed in session |

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

## Honest Readout

- `smc_context_resolvers`, `smc_profile_engine`, and `smc_utils` have direct live TradingView compile evidence from the 2026-04-16 preflight run.
- `smc_core_types` has a screenshot showing a compile error (CE10013) — no clean compile evidence in repo.
- `smc_draw` has no compile or publish evidence in repo.
- All 5 libraries were user-reported as manually published on 2026-04-16, but **none have a post-publish screenshot** in the repo.
- All 5 remain `publish_verified: no`. See `docs/tradingview-manual-publish-evidence-2026-04-16.md` for the structured record.
- If the acceptance bar is "TradingView can compile these exact library files today", that bar is met for 3 of 5 (utils, profile_engine, context_resolvers).
- If the acceptance bar is "TradingView private publish/import path is operationally proven", that bar is **not met for any of the 5**.

## What Would Close the Evidence Gap

For each of the 5 libraries, capture a post-publish screenshot in TradingView showing:

1. Pine Editor header with correct script name
2. Published state (version indicator visible, no "Publish script" button)
3. Import path matching `preuss_steffen/<library>/1`
4. No compile errors

Save screenshots as `automation/tradingview/reports/publish-<library>-manual-verified-2026-04-16.png` and update this document and `docs/tradingview-manual-publish-evidence-2026-04-16.md`.

## Reproduction Command

The compile-only evidence in this document came from:

```bash
cd /Users/steffenpreuss/Downloads/skipp-algo
npm run tv:preflight:profile -- --no-open-existing --config /tmp/tv-split-library-preflight.json --out automation/tradingview/reports/preflight-split-library-2026-04-16-live.json
```
