# Split Library Compile Readiness

> **Canonical ops reference:** [`docs/tradingview_operational_publish_runbook_2026-04-17.md`](tradingview_operational_publish_runbook_2026-04-17.md)

Date: 2026-04-16 (updated — all 5 publish-verified)
Reviewed commit: `fce324b0`

## Purpose

This document distinguishes five different states for split Pine libraries:

1. file exists in git
2. import paths are statically consistent in the checked-in repo
3. TradingView compile is plausible but not rerun
4. TradingView compile is operationally evidenced
5. TradingView publish is operationally evidenced

All 5 manual-publish target libraries are now **publish-verified** via browser automation
(Chrome DevTools MCP → TradingView profile page + individual script pages).
See `docs/tradingview-manual-publish-evidence-2026-04-16.md` for the structured evidence record.

## Primary Targets

| Library file | Expected import path | TradingView URL | Repo presence | Static import consistency | Live compile evidence | Publish verified | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SMC++/smc_core_types.pine` | `preuss_steffen/smc_core_types/1` | [RsrGIOXB](https://www.tradingview.com/script/RsrGIOXB/) | yes | yes | yes (Pine Editor v4, Today 17:00) | **yes** | Profile + script page screenshot |
| `SMC++/smc_draw.pine` | `preuss_steffen/smc_draw/1` | [QewoNKHh](https://www.tradingview.com/script/QewoNKHh/) | yes | yes | yes (published with full description) | **yes** | Profile + script page screenshot |
| `SMC++/smc_utils.pine` | `preuss_steffen/smc_utils/1` | [REeaX6OF](https://www.tradingview.com/script/REeaX6OF/) | yes | yes | yes (preflight + published) | **yes** | Profile + script page screenshot |
| `SMC++/smc_profile_engine.pine` | `preuss_steffen/smc_profile_engine/1` | [MLVulTa9](https://www.tradingview.com/script/MLVulTa9/) | yes | yes | yes (preflight + published) | **yes** | Profile + script page screenshot |
| `SMC++/smc_context_resolvers.pine` | `preuss_steffen/smc_context_resolvers/1` | [xqizvhmk](https://www.tradingview.com/script/xqizvhmk/) | yes | yes | yes (preflight + CE10237 fixes + published) | **yes** | Profile + script page screenshot |

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

- All 5 target libraries are now **publish-verified** as of 2026-04-16 17:45 UTC+2.
- Verification method: Browser automation (Chrome DevTools MCP) navigated to the TradingView profile page and each individual script page.
- Each library confirmed as a published Pine Script® library (private/invite-only) under `preuss_steffen/` namespace.
- Profile-level screenshot: `automation/tradingview/reports/screenshots/publish-profile-all-libraries-2026-04-16.png`
- Individual screenshots in `automation/tradingview/reports/screenshots/publish-<library>-verified-2026-04-16.png`
- The acceptance bar "TradingView private publish/import path is operationally proven" is **fully met for all 5**.

## Evidence Gap — CLOSED

The evidence gap identified in the previous version of this document has been closed.
All 5 libraries have publish-verified screenshots captured via browser automation.

## Reproduction Command

The compile-only evidence in this document came from:

```bash
cd /Users/steffenpreuss/Downloads/skipp-algo
npm run tv:preflight:profile -- --no-open-existing --config /tmp/tv-split-library-preflight.json --out automation/tradingview/reports/preflight-split-library-2026-04-16-live.json
```
