# TradingView Manual Publish Evidence — 2026-04-16

Stand: 2026-04-16
Branch: `main`
Reviewed commit: `45858132`

## Purpose

This document records the evidence state for the 5 split libraries that were
intended for manual TradingView publish on 2026-04-16. It is the single source
of truth for what is repo-verified vs. what remains unverified.

## Evidence Summary

| Library | Import Path | Publish Method | Publish Verified | Screenshot File | Notes |
|---------|-------------|----------------|------------------|-----------------|-------|
| `smc_core_types` | `preuss_steffen/smc_core_types/1` | manual | **no** | `automation/tradingview/reports/publish-smc_core_types-manual-2026-04-16.png` | Screenshot shows compile error CE10013 (indentation issue after paste), not a successful publish. User reported fixing and publishing manually — no post-publish screenshot captured. |
| `smc_draw` | `preuss_steffen/smc_draw/1` | manual | **no** | — | No screenshot or evidence file exists in repo. User reported manual publish — unverified. |
| `smc_utils` | `preuss_steffen/smc_utils/1` | manual | **no** | `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_utils-compiled.png` | Screenshot is compile-only (from preflight run), not publish evidence. User reported manual publish — unverified. |
| `smc_profile_engine` | `preuss_steffen/smc_profile_engine/1` | manual | **no** | `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_profile_engine-compiled.png` | Screenshot is compile-only (from preflight run), not publish evidence. User reported manual publish — unverified. |
| `smc_context_resolvers` | `preuss_steffen/smc_context_resolvers/1` | manual | **no** | `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_context_resolvers-compiled.png` | Screenshot is compile-only (from preflight run), not publish evidence. User reported manual publish — unverified. |

## Detailed Evidence Per Library

### 1. smc_core_types

- **File:** `SMC++/smc_core_types.pine`
- **Import path:** `preuss_steffen/smc_core_types/1`
- **Compile evidence:** Screenshot shows the script loaded in Pine Editor with the correct `library("smc_core_types", overlay = true)` declaration, but has compile error CE10013 due to EMA line indentation issue caused by Monaco editor auto-indent during paste.
- **Publish evidence:** None. The screenshot pre-dates the user's manual fix and publish.
- **User report:** User reported they fixed the indentation error manually and published the library. This is plausible but not repo-verified.
- **Screenshot:** `automation/tradingview/reports/publish-smc_core_types-manual-2026-04-16.png`
- **Verdict:** `unverified` — needs post-publish screenshot showing the published import path.

### 2. smc_draw

- **File:** `SMC++/smc_draw.pine`
- **Import path:** `preuss_steffen/smc_draw/1`
- **Compile evidence:** None in repo for this library specifically.
- **Publish evidence:** None.
- **User report:** User reported manual publish. No screenshot was captured.
- **Screenshot:** —
- **Verdict:** `unverified` — needs both compile and publish screenshot.

### 3. smc_utils

- **File:** `SMC++/smc_utils.pine`
- **Import path:** `preuss_steffen/smc_utils/1`
- **Compile evidence:** `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` shows `compile_ok: true` and `overall_preflight_ok: true` for this target. Screenshot from that run exists.
- **Publish evidence:** None.
- **User report:** User reported manual publish. No post-publish screenshot was captured.
- **Screenshot:** `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_utils-compiled.png` (compile only)
- **Verdict:** `unverified` — compile is proven, but publish is not.

### 4. smc_profile_engine

- **File:** `SMC++/smc_profile_engine.pine`
- **Import path:** `preuss_steffen/smc_profile_engine/1`
- **Compile evidence:** `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` shows `compile_ok: true` and `overall_preflight_ok: true`. Screenshot from that run exists.
- **Publish evidence:** None.
- **User report:** User reported manual publish. No post-publish screenshot was captured.
- **Screenshot:** `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_profile_engine-compiled.png` (compile only)
- **Verdict:** `unverified` — compile is proven, but publish is not.

### 5. smc_context_resolvers

- **File:** `SMC++/smc_context_resolvers.pine`
- **Import path:** `preuss_steffen/smc_context_resolvers/1`
- **Compile evidence:** `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json` shows `compile_ok: true` and `overall_preflight_ok: true`. Screenshot from that run exists. Additionally, multiple CE10237 compile warnings were fixed during this session (signal_warnings, signal_quality_score, market_valuation_caution, sq_score).
- **Publish evidence:** None.
- **User report:** User reported manual publish after iterative CE10237 fixes. No post-publish screenshot was captured.
- **Screenshot:** `automation/tradingview/reports/screenshots/2026-04-16T07-04-39-528Z-smc_context_resolvers-compiled.png` (compile only)
- **Verdict:** `unverified` — compile is proven (with fixes), but publish is not.

## What Would Close This

For each library, a publish-verified screenshot must show:

1. The Pine Editor header with the correct script name (e.g. `smc_core_types`)
2. The script is in "published" state (no "Publish script" button, or version indicator visible)
3. The import path shown matches the expected path (e.g. `preuss_steffen/smc_core_types/1`)
4. No compile errors visible

Until these screenshots are captured and added to `automation/tradingview/reports/`,
all 5 libraries remain `publish_verified: no`.

## Related Artifacts

- Compile preflight report: `automation/tradingview/reports/preflight-split-library-2026-04-16-live.json`
- Manual batch tracker (JSON): `automation/tradingview/reports/publish-manual-batch-2026-04-16.json`
- Manual publish checklist: `docs/tradingview-manual-publish-checklist.md`
- Compile readiness doc: `docs/split_library_compile_readiness.md`
- Remediation plan: `docs/tradingview-split-remediation-plan.md`
