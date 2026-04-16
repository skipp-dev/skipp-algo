# TradingView Manual Publish Evidence — 2026-04-16

Stand: 2026-04-16 (updated 17:45 UTC+2 — publish verified via profile page)
Branch: `main`
Reviewed commit: `fce324b0` (evidence docs), verification via browser automation

## Purpose

This document records the evidence state for the 5 split libraries that were
intended for manual TradingView publish on 2026-04-16. It is the single source
of truth for what is repo-verified vs. what remains unverified.

## Evidence Summary

| Library | Import Path | TradingView URL | Publish Verified | Screenshot File |
|---------|-------------|-----------------|------------------|-----------------|
| `smc_core_types` | `preuss_steffen/smc_core_types/1` | https://www.tradingview.com/script/RsrGIOXB/ | **yes** | `screenshots/publish-smc_core_types-verified-2026-04-16.png` |
| `smc_draw` | `preuss_steffen/smc_draw/1` | https://www.tradingview.com/script/QewoNKHh/ | **yes** | `screenshots/publish-smc_draw-verified-2026-04-16.png` |
| `smc_utils` | `preuss_steffen/smc_utils/1` | https://www.tradingview.com/script/REeaX6OF/ | **yes** | `screenshots/publish-smc_utils-verified-2026-04-16.png` |
| `smc_profile_engine` | `preuss_steffen/smc_profile_engine/1` | https://www.tradingview.com/script/MLVulTa9/ | **yes** | `screenshots/publish-smc_profile_engine-verified-2026-04-16.png` |
| `smc_context_resolvers` | `preuss_steffen/smc_context_resolvers/1` | https://www.tradingview.com/script/xqizvhmk/ | **yes** | `screenshots/publish-smc_context_resolvers-verified-2026-04-16.png` |

All screenshots relative to `automation/tradingview/reports/`.

## Verification Method

Publish was verified via browser automation (Chrome DevTools MCP):

1. Navigated to `https://www.tradingview.com/u/preuss_steffen/#published-scripts`
2. Profile Scripts tab shows all 5 libraries as published Pine Script® libraries (private/invite-only)
3. Full-page screenshot saved: `screenshots/publish-profile-all-libraries-2026-04-16.png`
4. Each library's individual script page was visited and screenshotted, confirming:
   - Page title: `<library_name> — Library by preuss_steffen — TradingView`
   - Library description with exported functions/types visible
   - Private idea access level

## Detailed Evidence Per Library

### 1. smc_core_types

- **File:** `SMC++/smc_core_types.pine`
- **Import path:** `preuss_steffen/smc_core_types/1`
- **TradingView URL:** https://www.tradingview.com/script/RsrGIOXB/
- **Publish verified:** Yes — profile page shows "smc_core_types" as Pine Script® library
- **Screenshots:** `publish-smc_core_types-verified-2026-04-16.png` (script page), `publish-profile-all-libraries-2026-04-16.png` (profile overview)
- **Verdict:** `verified`

### 2. smc_draw

- **File:** `SMC++/smc_draw.pine`
- **Import path:** `preuss_steffen/smc_draw/1`
- **TradingView URL:** https://www.tradingview.com/script/QewoNKHh/
- **Publish verified:** Yes — profile page shows "smc_draw" as Pine Script® library with description
- **Screenshots:** `publish-smc_draw-verified-2026-04-16.png` (script page), `publish-profile-all-libraries-2026-04-16.png` (profile overview)
- **Verdict:** `verified`

### 3. smc_utils

- **File:** `SMC++/smc_utils.pine`
- **Import path:** `preuss_steffen/smc_utils/1`
- **TradingView URL:** https://www.tradingview.com/script/REeaX6OF/
- **Publish verified:** Yes — profile page shows "smc_utils" as Pine Script® library with description
- **Screenshots:** `publish-smc_utils-verified-2026-04-16.png` (script page), `publish-profile-all-libraries-2026-04-16.png` (profile overview)
- **Verdict:** `verified`

### 4. smc_profile_engine

- **File:** `SMC++/smc_profile_engine.pine`
- **Import path:** `preuss_steffen/smc_profile_engine/1`
- **TradingView URL:** https://www.tradingview.com/script/MLVulTa9/
- **Publish verified:** Yes — profile page shows "smc_profile_engine" as Pine Script® library, published 36 min before verification
- **Screenshots:** `publish-smc_profile_engine-verified-2026-04-16.png` (script page), `publish-profile-all-libraries-2026-04-16.png` (profile overview)
- **Verdict:** `verified`

### 5. smc_context_resolvers

- **File:** `SMC++/smc_context_resolvers.pine`
- **Import path:** `preuss_steffen/smc_context_resolvers/1`
- **TradingView URL:** https://www.tradingview.com/script/xqizvhmk/
- **Publish verified:** Yes — profile page shows "smc_context_resolvers" as Pine Script® library, published 37 min before verification
- **Screenshots:** `publish-smc_context_resolvers-verified-2026-04-16.png` (script page), `publish-profile-all-libraries-2026-04-16.png` (profile overview)
- **Verdict:** `verified`

## Additional Libraries Confirmed on Profile

The profile page also confirmed these previously-published libraries:

| Library | URL | Updated |
|---------|-----|---------|
| `smc_observability_private` | https://www.tradingview.com/script/Pk1mf5ut-smc-observability-private/ | Apr 5 |
| `smc_bus_private` | https://www.tradingview.com/script/aaxpWQEV-smc-bus-private/ | 43 min ago |
| `smc_lifecycle_private` | https://www.tradingview.com/script/4van2T9D-smc-lifecycle-private/ | 44 min ago |
| `smc_micro_profiles_generated` | https://www.tradingview.com/script/3q50DUTi-smc-micro-profiles-generated/ | 1 hour ago |

## Related Artifacts

- Profile overview screenshot: `automation/tradingview/reports/screenshots/publish-profile-all-libraries-2026-04-16.png`
- Compile preflight report: `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json`
- Manual batch tracker (JSON): `automation/tradingview/reports/publish-manual-batch-2026-04-16.json`
- Manual publish checklist: `docs/tradingview-manual-publish-checklist.md`
- Compile readiness doc: `docs/split_library_compile_readiness.md`
- Remediation plan: `docs/tradingview-split-remediation-plan.md`
