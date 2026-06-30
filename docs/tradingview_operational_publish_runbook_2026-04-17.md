# TradingView Operational Publish & Verification Runbook

Date: 2026-04-17
Branch: `main`
Owner: Operator (preuss_steffen TradingView account)

---

## 1. Purpose

This document is the **single canonical reference** for publishing,
verifying, and maintaining TradingView Pine libraries in the SMC Long-Dip
Suite. It replaces the need to cross-reference multiple scattered docs
by consolidating the complete operational lifecycle in one place.

## 2. Scope

| In Scope | Out of Scope |
|----------|--------------|
| All 9 Pine libraries | Pine product logic changes |
| Publish sequence and dependency order | Indicator/Strategy feature development |
| Compile, binding, runtime verification | Manual chart-level trading decisions |
| Evidence capture and storage | TradingView platform bugs |
| Failure modes and escalation | Companion overlay scripts |
| CI automation boundaries | User-facing documentation |

## 3. Library Inventory

| # | Library | Import Path | Source File | Dependencies | Publish Method |
|---|---------|-------------|-------------|--------------|----------------|
| 1 | `smc_core_types` | `preuss_steffen/smc_core_types/1` | `SMC++/smc_core_types.pine` | none | manual or `tv:publish-core-types-library:profile` |
| 2 | `smc_draw` | `preuss_steffen/smc_draw/1` | `SMC++/smc_draw.pine` | none | manual or `tv:publish-draw-library:profile` |
| 3 | `smc_bus_private` | `preuss_steffen/smc_bus_private/1` | `SMC++/smc_bus_private.pine` | none | manual (no dedicated script) |
| 4 | `smc_lifecycle_private` | `preuss_steffen/smc_lifecycle_private/1` | `SMC++/smc_lifecycle_private.pine` | none | `tv:publish-lifecycle-library:profile` |
| 5 | `smc_utils` | `preuss_steffen/smc_utils/1` | `SMC++/smc_utils.pine` | `smc_core_types` | manual or `tv:publish-utils-library:profile` |
| 6 | `smc_observability_private` | `preuss_steffen/smc_observability_private/1` | `SMC++/smc_observability_private.pine` | `smc_utils` | `tv:publish-observability-library:profile` |
| 7 | `smc_profile_engine` | `preuss_steffen/smc_profile_engine/1` | `SMC++/smc_profile_engine.pine` | `smc_utils`, `smc_draw` | manual or `tv:publish-profile-engine-library:profile` |
| 8 | `smc_context_resolvers` | `preuss_steffen/smc_context_resolvers/1` | `SMC++/smc_context_resolvers.pine` | `smc_utils`, `smc_bus_private` | manual or `tv:publish-context-resolvers-library:profile` |
| 9 | `smc_micro_profiles_generated` | `preuss_steffen/smc_micro_profiles_generated/1` | `pine/generated/smc_micro_profiles_generated.pine` | none | CI-automated (`smc-library-refresh.yml`) |

## 4. Dependency Graph & Mandatory Publish Order

```
Layer 0 (no deps):  smc_core_types, smc_draw, smc_bus_private, smc_lifecycle_private
                          │              │           │
Layer 1:                  └──►  smc_utils ◄──────────┘ (core_types)
                                    │
Layer 2:        smc_observability   │   smc_profile_engine   smc_context_resolvers
                (utils)             │   (utils, draw)        (utils, bus_private)
                                    │
Layer 3:        SMC_Core_Engine.pine (imports ALL 9 libraries)
                    │
Layer 4:        SMC_Dashboard.pine (59 bindings to Core Engine)
                SMC_Long_Strategy.pine (8 bindings to Core Engine)
```

**Rule:** A library MUST be published before any library that imports it.
Publish in layer order: 0 → 1 → 2 → 3 → 4.

## 5. Canonical Publish Sequence

### 5.1 Preconditions

- [ ] Repo on `main`, fully pulled: `git fetch origin && git checkout main && git pull`
- [ ] No uncommitted Pine source changes
- [ ] TradingView account `preuss_steffen` logged in
- [ ] Auth available: persistent Chromium profile at `automation/tradingview/auth/chromium-profile/`
      OR valid storage state at `automation/tradingview/auth/storage-state.json`
- [ ] Node.js + tsx installed (`npx tsx --version`)

### 5.2 Layer 0: Leaf Libraries (no dependencies)

For each of `smc_core_types`, `smc_draw`, `smc_bus_private`, `smc_lifecycle_private`:

| Step | Action | Automated? | Abort If |
|------|--------|------------|----------|
| 1 | Run `npm run tv:publish-<name>-library:profile` | **yes** (Playwright) | Script exits non-zero |
| 2 | Verify JSON report: `publish_ok: true`, `compile_ok: true` | **yes** (in report) | Missing or `false` |
| 3 | Screenshot saved to `automation/tradingview/reports/` | **yes** | Missing file |

**Manual fallback** (if automation fails):
1. Open TradingView Pine Editor → paste source from `SMC++/<name>.pine`
2. Save → wait for green compile
3. Publish → Private Library → verify import path = `preuss_steffen/<name>/1`
4. Screenshot → save to `automation/tradingview/reports/publish-<name>-manual-YYYY-MM-DD.png`

**Note:** `smc_bus_private` has no dedicated publish script — use manual fallback.

### 5.3 Layer 1: `smc_utils`

| Step | Action | Automated? | Abort If |
|------|--------|------------|----------|
| 1 | Confirm Layer 0 complete (esp. `smc_core_types`) | manual check | Layer 0 incomplete |
| 2 | Run `npm run tv:publish-utils-library:profile` | **yes** | Script exits non-zero |
| 3 | Verify JSON report | **yes** | `compile_ok: false` → Layer 0 not resolved |

### 5.4 Layer 2: `smc_observability_private`, `smc_profile_engine`, `smc_context_resolvers`

These can be published in parallel (independent of each other). Each depends only on Layer 0+1.

| Step | Action | Automated? | Abort If |
|------|--------|------------|----------|
| 1 | Confirm Layer 1 complete | manual check | Layer 1 incomplete |
| 2 | Run `npm run tv:publish-<name>-library:profile` | **yes** | Non-zero exit |
| 3 | Verify JSON report | **yes** | `compile_ok: false` |

### 5.5 Layer 3: Core Engine Compile Verification

| Step | Action | Automated? | Abort If |
|------|--------|------------|----------|
| 1 | Run `npm run tv:preflight:smc-mainline` | **yes** (Playwright) | Non-zero exit |
| 2 | Check report: `compile_green: true` | **yes** | `false` → import resolution failure |
| 3 | Check report: `binding_green: true` (59 dashboard + 8 strategy) | **yes** | `false` → binding drift |
| 4 | Check report: `runtime_green: true` | **yes** | `false` → runtime regression |

### 5.6 Layer 4: Dashboard & Strategy Binding Verification

| Step | Action | Automated? | Abort If |
|------|--------|------------|----------|
| 1 | Dashboard bindings (59 channels) verified by preflight | **yes** (step 5.5) | Binding count mismatch |
| 2 | Strategy bindings (8 channels) verified by preflight | **yes** (step 5.5) | Binding count mismatch |
| 3 | **Manual** scenario validation (5 lifecycle states) | **manual** | Visual mismatch |

### 5.7 Post-Publish: `smc_micro_profiles_generated`

This library is **fully CI-automated** via `smc-library-refresh.yml` (4×/trading day).

| Step | Action | Automated? |
|------|--------|------------|
| 1 | Generator runs, detects field changes | **yes** (CI) |
| 2 | Publish via `tv_publish_micro_library.ts` | **yes** (CI) |
| 3 | Post-release validation via `verify_tradingview_post_release.py` | **yes** (CI) |
| 4 | Release manifest written to `artifacts/tradingview/library_release_manifest.json` | **yes** (CI) |

## 6. Evidence Requirements

### 6.1 Per-Library Evidence

Each publish event MUST produce:

| Artifact | Format | Location | Required |
|----------|--------|----------|----------|
| Publish report | JSON | `automation/tradingview/reports/publish-<name>-*.json` | **yes** |
| Compile screenshot | PNG | `automation/tradingview/reports/screenshots/` | **yes** |
| Profile page screenshot | PNG | `automation/tradingview/reports/screenshots/` | recommended |

### 6.2 Per-Release Evidence (after all libraries published)

| Artifact | Format | Location | Required |
|----------|--------|----------|----------|
| Mainline preflight report | JSON | `automation/tradingview/reports/preflight-*.json` | **yes** |
| Dashboard binding match | in preflight JSON | `.binding_green: true` | **yes** |
| Strategy binding match | in preflight JSON | `.binding_green: true` | **yes** |
| Runtime smoke pass | in preflight JSON | `.runtime_green: true` | **yes** |
| Manual scenario validation | Markdown report | `docs/tradingview-manual-validation-report-*.md` | recommended |

### 6.3 Evidence Staleness Policy

- Publish evidence older than **7 days** after a code change to the same library
  is considered **stale** and must be refreshed before a release.
- CI post-release validation enforces a 2-hour staleness window for the
  micro profiles library (`_POST_RELEASE_MANIFEST_STALE_AFTER_SECONDS`).
- Mainline preflight evidence older than **14 days** triggers an advisory
  in the release gate.

## 7. Failure Modes

### 7.1 Compile Failures

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `Could not find library` | Dependency not published or wrong version | Publish the dependency first (check layer order) |
| `Undeclared identifier` | Source code drift vs. published library | Re-publish the library with current source |
| `Type mismatch` | Breaking type change in dependency | Align consumer to new type signature |
| Pine Editor shows red | Syntax error in source | Fix in repo, re-run preflight |

### 7.2 Binding Failures

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `binding_green: false` | Input label renamed or removed | Check `SMC_Core_Engine.pine` plot labels match `docs/tradingview-validation-checklist.md` |
| Binding count mismatch | New inputs added without dashboard/strategy update | Update binding contract in checklist |
| `NaN` in dashboard | Core Engine not computing (wrong symbol/timeframe) | Verify chart settings match expectations |

### 7.3 Auth Failures

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `auth_ok: false` | Storage state expired or cookies invalidated | Re-capture: `npm run tv:profile-login` (interactive) |
| CI auth failure | `TV_STORAGE_STATE` GitHub secret expired | Update secret: follow [tradingview-storage-state-capture-runbook.md](tradingview-storage-state-capture-runbook.md) (`tv:storage-state` + `gh secret set`) |
| Profile dir missing | Chromium profile not created | Run `npm run tv:profile-login` once |

### 7.4 Publish Failures

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `Publish Script` button missing | Script already published (use `Update`) | Use `Update Existing Publication` instead |
| `publish_ok: false` in report | Playwright selector mismatch (TV UI changed) | Use manual fallback, file selector issue |
| Version mismatch (`/2` instead of `/1`) | TradingView assigned new version | All consumers must update import path |

### 7.5 Runtime Failures

| Symptom | Likely Cause | Resolution |
|---------|-------------|------------|
| `runtime_green: false` | Script not on chart or chart error state | Re-add script to chart via preflight |
| Indicator shows "Error" | Runtime exception in Pine | Check Pine Editor console for error message |
| Strategy shows no trades | Execution trigger conditions not met | Change symbol/timeframe or verify logic |

## 8. Recovery State Model

### 8.1 Preflight Outcome States

After a preflight run, the system is in one of these states:

| State | Compile | Binding | Action |
|---|---|---|---|
| **FULL GREEN** | ✅ | ✅ | None — ready for release |
| **COMPILE GREEN, BINDING FLAKY** | ✅ | ❌ (timeout/selector) | Retry once. If persistent, verify manually that bindings look correct on chart. Record in evidence doc as "binding verified manually" |
| **COMPILE GREEN, BINDING DRIFT** | ✅ | ❌ (count mismatch) | Pine contract changed — update `smc_product_cut_manifest.json` expected labels, then re-run |
| **COMPILE RED** | ❌ | — | Dependency not published or source broken. Check layer order, re-publish dependencies |
| **AUTH FAILED** | — | — | Refresh auth: `npm run tv:profile-login` (persistent profile) or re-capture storage state |
| **TIMEOUT / CRASH** | — | — | Retry. If persistent, check TradingView service status. Last resort: manual verification |

### 8.2 Distinguishing Flaky vs. Real Failures

**Flaky indicators** (retry or accept):
- `openSettingsForScript` timeout but `compile_ok: true`
- Wrong `observed_input_labels` (generic chart inputs instead of BUS inputs)
- `binding_green: not_run` with no `error` field

**Real failure indicators** (investigate):
- `compile_ok: false` — always a real issue
- `missing_input_labels` lists BUS fields that were present before
- Binding count drops between runs without Pine changes

### 8.3 Known Automation Blockers (as of 2026-04-17)

| Blocker | Target | Since | Classification | Workaround |
|---|---|---|---|---|
| Settings dialog timeout | SMC Dashboard | 2026-04-05 (intermittent) | TradingView UI flakiness | Retry with `mutating` mode; manual fallback |
| Wrong legend entry selection | SMC Strategy | 2026-04-16 | Legend candidate bug | Manual binding verification |

These are tracked in `docs/tradingview_e2e_revalidation_2026-04-17.md`.

### 8.4 Recovery Escalation Path

```
Preflight fails
  ├── Auth issue → refresh session → retry
  ├── Compile issue → check layer order → re-publish deps → retry
  ├── Binding timeout → retry (up to 2x) → manual verification → accept
  ├── Binding drift → update manifest → retry
  └── Unknown → capture screenshot + report → file GitHub issue
```

## 9. Automation vs. Manual Boundary

### What Is Automated

| Capability | Tool | Confidence |
|------------|------|------------|
| Auth resolution (storage state / persistent profile) | `tv_shared.ts` | high |
| Pine source injection into editor | `tv_shared.ts` | high |
| Compile verification (green/red) | `tv_preflight.ts` | high |
| Script save & publish | `tv_publish_*.ts` | high |
| Input binding enumeration & matching | `tv_preflight.ts` | high |
| Screenshot capture | `tv_shared.ts` | high |
| JSON report generation | all scripts | high |
| Micro library CI publish pipeline | `smc-library-refresh.yml` | high |
| Post-release manifest validation | `verify_tradingview_post_release.py` | high |

### CI Timeout Budget Contract

The TradingView automation has one shared step budget and two editor-specific
substep budgets:

| Env var | Default behavior | Intended use |
|---------|------------------|--------------|
| `TV_STEP_TIMEOUT_MS` | Shared default for tracked Playwright steps; CI sets it to `90000` in the readonly preflight and mutating publish steps. | Raise the whole TradingView step budget for slow CI chart/editor hydration. |
| `TV_SET_EDITOR_CONTENT_TIMEOUT_MS` | When unset, defaults to `Math.max(TV_STEP_TIMEOUT_MS, 90000)`. | Override only for a targeted editor-content investigation. CI should normally leave it unset. |
| `TV_EDITOR_PREPARE_TIMEOUT_MS` | When unset, defaults to `Math.max(TV_STEP_TIMEOUT_MS, 45000)`. | Override only for a targeted Pine-editor preparation investigation. CI should normally leave it unset. |

In other words, raising `TV_STEP_TIMEOUT_MS` above 90s also raises the default
editor-content budget. Lowering `TV_STEP_TIMEOUT_MS` does not reduce editor
content below 90s or editor prepare below 45s. Explicit editor-specific env vars
are operator overrides and intentionally win over those defaults, so do not set
them below the CI floor in workflows unless you are debugging a local timeout
path.

### What Remains Manual

| Capability | Reason | Risk |
|------------|--------|------|
| Initial one-time binding setup (59+8 inputs) | TradingView UI requires drag-and-drop | low (one-time) |
| Scenario validation (5 lifecycle states) | Requires human judgment on visual correctness | medium |
| Product-surface screenshots (chart renders) | Automation cannot verify visual rendering quality | medium |
| `smc_bus_private` publish | No dedicated publish script | low (rarely changes) |
| Auth session refresh | Requires interactive browser login | low (every ~30 days) |
| Selector maintenance when TV UI changes | Requires DOM inspection | medium |

### Explicit Non-Automation Decisions

These items are **intentionally** kept manual:

1. **Visual scenario validation** — no reliable automated way to verify
   that the dashboard shows correct values for neutral/armed/confirmed/ready/
   invalidated states. A human must visually confirm.
2. **Binding creation** — the initial `input.source()` binding in TradingView
   requires mouse interaction. Once bound, the preflight can verify it persists.
3. **Product-surface evidence** — a rendered chart screenshot showing the
   actual trading view is not equivalent to an editor compile screenshot.
   Human review is required to confirm visual correctness.

## 9. Operational Checklist — Quick Reference

### Before Any Publish

```
□ git fetch origin && git checkout main && git pull
□ No uncommitted changes to SMC++/ or pine/generated/
□ npm run tv:test    (selector + validation model unit tests)
□ Auth verified: npm run tv:smoke-readonly (or just check storage state exists)
```

### After All Libraries Published

```
□ npm run tv:preflight:smc-mainline
□ Preflight JSON shows: auth_ok=true, compile_green=true, binding_green=true, runtime_green=true
□ Screenshots saved in automation/tradingview/reports/screenshots/
□ Update docs/split_library_compile_readiness.md if publish dates changed
□ Commit evidence: git add automation/tradingview/reports/ && git commit -m "chore(tv): update publish evidence"
```

### Release Gate Verification

```
□ Micro library manifest not stale (< 2 hours)
□ Mainline preflight green (< 14 days)
□ All 9 libraries publish-verified
□ No blocking compile errors
□ Manual scenario validation passed (if release includes Pine changes)
```

## 10. Report File Conventions

### Naming

| Report Type | Pattern | Example |
|-------------|---------|---------|
| Preflight | `preflight-{ISO-timestamp}.json` | `preflight-2026-04-07T19-12-02-524Z.json` |
| Library publish | `publish-{name}-library-{timestamp}.json` | `publish-lifecycle-library-20260405.json` |
| Manual batch | `publish-manual-batch-YYYY-MM-DD.json` | `publish-manual-batch-2026-04-16.json` |
| Release manifest | `library_release_manifest.json` | (fixed name, overwritten) |
| Screenshots | `screenshots/{descriptive-name}.png` | `screenshots/publish-smc_draw-verified-2026-04-16.png` |

### Report Retention

- **Canonical evidence** (latest publish + latest preflight): keep indefinitely
- **Iteration/debug reports**: may be cleaned up after 30 days
- **Screenshots**: keep at least the latest per library + latest mainline

## 11. Related Documents

| Document | Purpose | Canonical? |
|----------|---------|------------|
| This runbook | **Master operational reference** | **yes** |
| `docs/tradingview_e2e_revalidation_2026-04-17.md` | Compile + binding evidence (WP-12) | historical |
| `docs/tradingview-manual-publish-checklist.md` | Step-by-step manual publish guide | supplementary |
| `docs/tradingview-manual-publish-evidence-2026-04-16.md` | Evidence record for 2026-04-16 batch | historical |
| `docs/split_library_compile_readiness.md` | Compile/publish status matrix | supplementary |
| `docs/tradingview-split-remediation-plan.md` | Split migration plan | historical |
| `docs/tradingview-validation-checklist.md` | Binding contract (59+8 labels) | supplementary |
| `docs/tradingview-manual-validation-runbook.md` | Manual scenario validation steps | supplementary |
| `docs/tradingview-status-model.md` | Preflight report field reference | supplementary |
| `docs/tradingview-auth-modes.md` | Auth resolution modes | supplementary |
| `docs/tradingview-runtime-validation.md` | Runtime validation tracking | supplementary |
| `docs/tradingview-micro-library-publish.md` | Micro library pipeline guide | supplementary |

## 12. Ownership

| Area | Owner | Escalation |
|------|-------|------------|
| TradingView account | `preuss_steffen` | — |
| Publish automation scripts | Repo maintainer | GitHub issue |
| CI workflows | Repo maintainer | GitHub issue |
| Selector maintenance | Repo maintainer | Urgent: TV UI changed |
| Auth session renewal | Account owner | Every ~30 days |
| Evidence review | Repo maintainer | Before each release |

---

_Last updated: 2026-04-17_
