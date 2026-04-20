# SMC System — Final Status Review

Date: 2026-04-16
Branch: `main` @ `77ac1652`
Author: Agent (automated)
Scope: Post-split-closure system-wide status assessment

---

## Executive Summary

The SMC Long-Dip Suite has completed its split-library migration, test
remediation, and TradingView publish cycle.  The monolithic Core Engine
has been decomposed into 9 private Pine libraries, all published and
import-verified on TradingView.  The test suite stands at **1999 passed /
7 failed / 4 skipped** across 4727 collected tests (SMC scope).  The 7
failures are a known consequence of two HEAD commits that changed product
surfaces (dashboard row renumbering, governance gate promotion) without a
corresponding test update — they are not regressions in product logic.
Three hard measurement gates are now active in `release_policy.py`.
Trust-tier and degradation status are surfaced in the live Dashboard.

The system is operationally functional and structurally sound.  The
remaining work is corrective test alignment (not product-code changes)
and continued operational evidence accumulation.

---

## 1. Was ist das System heute?

SMC Long-Dip Suite v7 is a TradingView Pine Script v6 indicator system
for institutional-grade long-dip detection, built on Smart Money Concepts
(BOS/CHoCH, Order Blocks, FVGs, liquidity sweeps).

**Production surfaces:**

| Surface | File | Lines | Role |
|---------|------|-------|------|
| Core Engine | `SMC_Core_Engine.pine` | 5474 | Primary operator indicator — zone detection, lifecycle, alerts |
| Dashboard | `SMC_Dashboard.pine` | 1421 | Pro companion — decision brief, audit view, trust/provider surface |

**Library stack (9 split libraries, all private/invite-only):**

| Library | File | Lines | Alias | Published |
|---------|------|-------|-------|-----------|
| `smc_core_types` | `SMC++/smc_core_types.pine` | 26 | `ct` | [RsrGIOXB](https://www.tradingview.com/script/RsrGIOXB/) |
| `smc_draw` | `SMC++/smc_draw.pine` | 311 | `d` | [QewoNKHh](https://www.tradingview.com/script/QewoNKHh/) |
| `smc_utils` | `SMC++/smc_utils.pine` | 258 | `u` | [REeaX6OF](https://www.tradingview.com/script/REeaX6OF/) |
| `smc_profile_engine` | `SMC++/smc_profile_engine.pine` | 372 | `pe` | [MLVulTa9](https://www.tradingview.com/script/MLVulTa9/) |
| `smc_context_resolvers` | `SMC++/smc_context_resolvers.pine` | 428 | `cr` | [xqizvhmk](https://www.tradingview.com/script/xqizvhmk/) |
| `smc_lifecycle_private` | `SMC++/smc_lifecycle_private.pine` | 407 | `ll` | [4van2T9D](https://www.tradingview.com/script/4van2T9D-smc-lifecycle-private/) |
| `smc_bus_private` | `SMC++/smc_bus_private.pine` | 404 | `bp` | [aaxpWQEV](https://www.tradingview.com/script/aaxpWQEV-smc-bus-private/) |
| `smc_observability_private` | `SMC++/smc_observability_private.pine` | 131 | `obv` | [Pk1mf5ut](https://www.tradingview.com/script/Pk1mf5ut-smc-observability-private/) |
| `smc_micro_profiles_generated` | `pine/generated/...` | — | `mp` | [3q50DUTi](https://www.tradingview.com/script/3q50DUTi-smc-micro-profiles-generated/) |

**Backend / integration stack:**

- `smc_integration/release_policy.py` — release gate definitions, measurement governance, drift policy
- 135 SMC test files, 4727 tests collected
- Databento-based volatility screener, Streamlit terminal UI, open-prep pipeline
- Automated library refresh and publish scripts (`scripts/tv_publish_*.ts`)

---

## 2. Was ist jetzt belastbar bewiesen?

### Proven via repo evidence

| Claim | Evidence | Status |
|-------|----------|--------|
| Split-library migration complete | `SMC_Core_Engine.pine` imports all 9 libraries; `SMC++/` directory has 8 files; no monolithic fallbacks remain | **proven** |
| All 9 libraries published on TradingView | Profile page + individual script page screenshots in `automation/tradingview/reports/screenshots/` | **proven** |
| Import paths are statically consistent | `grep "^import " SMC_Core_Engine.pine` → all 9 resolve to `preuss_steffen/<lib>/1` | **proven** |
| Long-dip regression suite green | `docs/regression_triage_packs.md`: 69/69 passed, 0 failed | **proven** |
| Legacy governance anchor updated | `test_long_dip_regression_anchors_to_active_core_engine` passes (commit `ed347402`) | **proven** |
| 3 hard measurement gates active | `HARD_BLOCKING_DEGRADATION_CODES` contains `BRIER_ABOVE_THRESHOLD`, `BRIER_REGRESSION`, `ECE_ABOVE_THRESHOLD` | **proven** |
| Trust tier + degradation surfaced in Dashboard | `SMC_Dashboard.pine` rows 18–21: Trust Tier, Provider State, Degradation | **proven** |
| Drift-safe artifact policy codified | `VOLATILE_ARTIFACT_POLICY` in `release_policy.py` classifies all known volatile paths | **proven** |
| Contextual calibration recommendation + promotion policy | Dataclass contracts with codified eligibility floors and stability rules | **proven** |
| BUS schema version check active | Dashboard row 97–104: version mismatch warning label | **proven** |

### Proven via live TradingView compile

| Library | Compile evidence | Source |
|---------|------------------|--------|
| `smc_utils` | `compile_ok: true` | `preflight-split-library-2026-04-16-live.json` |
| `smc_profile_engine` | `compile_ok: true` | same |
| `smc_context_resolvers` | `compile_ok: true` | same |
| `smc_core_types` | Pine Editor v4, Today 17:00 | screenshot evidence |
| `smc_draw` | published with full description | screenshot evidence |

### Proven via pytest

- Full SMC test scope: **1999 passed**, 4 skipped, 2717 deselected
- Long-dip regressions: **69/69 green**
- Legacy governance: **5/5 green**
- Export-surface tests for: `smc_profile_engine`, `smc_utils`, `smc_context_resolvers`
- Bus v2 semantics, core engine split, core engine semantic contract coverage

---

## 3. Was ist nur operativ plausibel?

| Claim | Current state | Why not fully proven |
|-------|---------------|---------------------|
| Full Core Engine + Dashboard compile on TradingView today | No fresh preflight for the complete consumer pair after dashboard trust-tier changes (commit `85c42068`) | Last full-surface TradingView preflight predates the dashboard restructuring |
| Dashboard row numbering matches test expectations | 4 bus_v2 tests fail because dashboard rows shifted from trust-tier insertion | Tests check hardcoded row indices that are now stale |
| Measurement gate classification correct after governance promotion | 3 release-gate tests fail because they expect `warn`/non-blocking for codes now promoted to hard-blocking | Tests not updated after `77ac1652` |
| End-to-end binding + runtime verification on TradingView | Historical evidence from 2026-04-05; not re-run after split-surface changes in April 2026 | Would require a full addToChart + binding + runtime cycle |
| Short-parity lifecycle | Explicitly out of scope per product comments in both Pine files | Not implemented, not promised |

---

## 4. Architekturstatus

### Split-library decomposition

The monolithic Core Engine was split into a layered library stack in commit
`7d769bfb` (2026-04-15).  The dependency graph:

```
smc_core_types          (no dependencies)
smc_draw                (no dependencies)
smc_bus_private         (no dependencies)
smc_lifecycle_private   (no dependencies)
    │
    ▼
smc_utils               (imports: smc_core_types)
    │
    ├──▶ smc_observability_private  (imports: smc_utils)
    ├──▶ smc_profile_engine         (imports: smc_utils, smc_draw)
    └──▶ smc_context_resolvers      (imports: smc_utils, smc_bus_private)
```

All consumer surfaces (`SMC_Core_Engine.pine`, `SMC_Dashboard.pine`) import
from published `/1` versions.  No circular dependencies.  No monolithic
fallback paths remain.

### BUS architecture

The inter-indicator BUS uses packed float series (`input.source` bindings)
with schema version `7001`.  Dashboard validates schema version on every bar
and shows a mismatch warning label if outdated.  74 dashboard rows decode
lifecycle, gate, calibration confidence, per-family performance, FVG health,
diagnostic, quality, support, and debug state from packed BUS slots.

### Product cut

Two product modes: "Decision Brief" (5–9 hero rows, compact) and "Audit View"
(full 74-row expert table including Trust & Provider, Calibration Confidence,
Per-Family Performance, and FVG Health sections).  Compact
dashboard option available for mobile.

---

## 5. Test- und Qualitätsstatus

### Current pytest snapshot (2026-04-16, HEAD `77ac1652`)

```
SMC scope (-k smc):  1999 passed, 7 failed, 4 skipped
Full suite:          4727 tests collected
```

### Failure classification

**4 failures in `test_smc_bus_v2_semantics.py`** — dashboard row index drift:

| Test | Root cause |
|------|-----------|
| `test_micro_profile_row_encodes_modifier_presence_inline` | Expected row 51, actual shifted by trust-tier section insertion |
| `test_hard_gate_decoders_reproduce_current_bus_v2_contract` | Expected row 19 for Session, now row 23 |
| `test_quality_score_uses_fixed_local_bounds_text` | Expected row 35, now row 39 |
| `test_lean_transport_row_exposes_ensemble_and_library_volatility` | Expected row 40, now row 44 |

These 4 tests assert hardcoded `dashboard_row(smc_dashboard, N, ...)` strings against
the dashboard source.  The trust-tier insertion at rows 18–21 shifted all subsequent
rows by 4.  This is a **test drift**, not a product regression.

**3 failures in `test_smc_integration_release_gate_scripts.py`** — governance promotion:

| Test | Root cause |
|------|-----------|
| `test_measurement_gate_uses_real_evidence` | Expects `status == "warn"`, but ECE is now hard-blocking → `"fail"` |
| `test_measurement_gate_warns_brier_above_soft_threshold` | Expects `blocking is False`, but Brier is now hard-blocking |
| `test_measurement_gate_warns_coverage_below_soft_threshold` | Expects `blocking is False`, but ECE threshold triggers hard-block |

These 3 tests were not updated when `77ac1652` promoted 2 degradation codes from
advisory to hard-blocking.  The product behavior is correct per the new policy;
the tests need to match.

### Test remediation history

| Phase | Commit | Result |
|-------|--------|--------|
| Batch 1 — signature changes | `fbe44e17` | Fixed |
| Batch 2 — state-resolution tuples | `5f7ec4fe` | Fixed |
| Batch 3 — moved-to-library | `25cb8be4` | Fixed |
| Final sweep — governance anchor | `ed347402` | Fixed |
| Long-dip regressions | `f8da37c1` | 69/69 green |
| Current HEAD | `77ac1652` | 7 failures (test drift, not product regression) |

---

## 6. TradingView- / Publish-Status

### Publish verification

All 9 libraries are **publish-verified** on TradingView under the `preuss_steffen/`
namespace as private/invite-only Pine Script® libraries.

Verification method: Browser automation via Chrome DevTools MCP navigated to
the TradingView profile page and each individual script page.

Evidence artifacts:
- Profile overview: `automation/tradingview/reports/screenshots/publish-profile-all-libraries-2026-04-16.png`
- Per-library screenshots: `publish-<library>-verified-2026-04-16.png`
- JSON batch tracker: `automation/tradingview/reports/publish-manual-batch-2026-04-16.json`
- Structured evidence: `docs/tradingview-manual-publish-evidence-2026-04-16.md`
- Compile readiness: `docs/split_library_compile_readiness.md`

### Operational gaps

- No automated publish script exists for the 5 manual-publish libraries (`smc_core_types`,
  `smc_draw`, `smc_utils`, `smc_profile_engine`, `smc_context_resolvers`).
  Future code changes in these libraries require manual re-publish.
- The 4 other libraries (`smc_bus_private`, `smc_lifecycle_private`, `smc_observability_private`,
  `smc_micro_profiles_generated`) have dedicated publish scripts in `scripts/`.
- Full end-to-end TradingView binding + runtime verification has not been rerun
  since 2026-04-05.  The latest publish evidence confirms compile + publish only.

---

## 7. Governance- / Gate-Status

### Hard-blocking release gates (measurement lane)

| Gate code | Metric | Threshold | Bootstrap-safe |
|-----------|--------|-----------|----------------|
| `MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD` | calibrated Brier | 0.60 | yes (requires `min_scoring_events ≥ 1`) |
| `MEASUREMENT_CALIBRATED_BRIER_REGRESSION` | calibrated Brier regression | 0.08 vs median | yes (requires `min_history_runs ≥ 2`) |
| `MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD` | calibrated ECE | 0.30 | yes (requires `min_scoring_events ≥ 1`) |

### Deliberately excluded from hard gates

| Code | Reason |
|------|--------|
| `MEASUREMENT_EVENT_COVERAGE_LOW` | Bootstrap deadlock: 0 events → can't publish → no history |
| `MEASUREMENT_CALIBRATED_ECE_REGRESSION` | Noise-susceptible with small samples; absolute ECE threshold sufficient |

### Advisory/soft-warn thresholds (WP-A8)

| Metric | Threshold |
|--------|-----------|
| Brier score soft-warn | 0.30 |
| Event coverage soft-warn | 0.50 |

### Contextual calibration governance

- Recommendation policy: min 8 events, 60% coverage, delta_brier ≥ 0.001, delta_ece ≥ 0.002
- Promotion policy: min 3 history runs, 67% recommended-run ratio, metric consensus required

### Drift-safe artifact policy

`VOLATILE_ARTIFACT_POLICY` classifies all known volatile paths into three classes:
- `restore_on_commit` — runtime churn git-restored before commit
- `stage_only` — intentional output, explicitly staged
- `gitignored` — never tracked

### Release reference matrix

- 12 symbols (AAPL, MSFT, AMZN, JPM, JNJ, XOM, CAT, PG, NEE, AMT, META, LIN)
- 4 timeframes (5m, 15m, 1H, 4H)
- 7-day staleness window
- 14-day evidence lookback
- Min 5 symbols, 2 timeframes coverage

---

## 8. Produktoberfläche / Sichtbarkeit

### Dashboard modes

| Mode | Rows | Audience |
|------|------|----------|
| Compact | 5 hero rows (Action, Trend, Trust/Data, Setup, Risk) | Mobile / glance |
| Decision Brief | 9 rows (above + HTF Trend, Setup Age, Visual, Exec Tier) | Daily operator |
| Audit View | 60+ rows including Gates, Quality, Support, Trust & Provider, Debug | Expert / review |

### Trust & Provider surface (v5.5b, commit `85c42068`)

Added in the Audit View between Lean Surface and Gates sections:

| Row | Content |
|-----|---------|
| 18 | `[ Trust & Provider ]` — section header |
| 19 | Trust Tier — derived from signal quality, freshness, provider state |
| 20 | Provider State — volume data + micro freshness composite |
| 21 | Degradation — explicit degradation diagnosis text |

Trust tiers: `high`, `guarded`, `degraded`, `insufficient`.
Degradation texts: `No degradation`, `Degraded — provider issue`, `Degraded — data stale`, `Insufficient — no measurement data`.

This section is read-only visibility — it does not change the signal model.

---

## 9. Offene Restpunkte

### Muss (blocking quality)

| # | Item | Severity | Effort |
|---|------|----------|--------|
| 1 | **7 test failures on HEAD** — 4 dashboard row-index drift, 3 governance gate classification | test alignment needed | ~30 min |
| 2 | **No full TradingView binding+runtime re-verification** post split-surface changes | evidentiary gap | ~20 min (run preflight) |

### Soll (recommended)

| # | Item | Why |
|---|------|-----|
| 3 | Automated publish scripts for the 5 manual-publish libraries | Re-publish after code changes requires manual TradingView workflow |
| 4 | `tradingview-split-remediation-plan.md` still references `publish_verified: no` for the 5 helper libs | Documentation stale after verification update |
| 5 | Full-suite CI pipeline not evidenced running green end-to-end | No CI run artifact in repo for current HEAD |

### Kann (nice-to-have)

| # | Item |
|---|------|
| 6 | Short-parity lifecycle (explicitly out of scope per product comments) |
| 7 | Reduce bus_v2 test brittleness — use relative row indices or pattern matching instead of hardcoded row numbers |

---

## 10. Empfehlung für den nächsten echten Entwicklungsschritt

**Fix the 7 test failures first.** These are not product regressions — they are
test-expectation drift from two recent product commits.  The fix is mechanical:

1. Update 4 bus_v2 tests to match the new dashboard row indices (shift by +4).
2. Update 3 release-gate tests to expect `"fail"` / `blocking: True` for the
   now-hard-blocking ECE and Brier codes.

After that, **rerun the TradingView preflight** for the full consumer pair
(Core Engine + Dashboard) to close the binding+runtime evidence gap.

Only after both items are green should new feature work begin.

---

## Scorecard

| Dimension | Rating | Basis |
|-----------|--------|-------|
| **Architektur** | 🟢 GREEN | 9-library split complete, no circular deps, clean import graph, BUS v2 schema versioned |
| **Tests** | 🟡 AMBER | 1999/2006 pass (99.7%), but 7 failures on HEAD are test-drift — needs mechanical fix |
| **Release-Governance** | 🟢 GREEN | 3 hard measurement gates active, drift policy codified, contextual calibration policy in place |
| **TradingView-Betrieb** | 🟡 AMBER | All 9 libraries published and import-verified, but no full binding+runtime re-verification since dashboard changes |
| **UX / Product Surface** | 🟢 GREEN | Trust tier + degradation visible, 3 dashboard modes, BUS version check, compact mobile view |
| **Dokumentationsklarheit** | 🟡 AMBER | Extensive documentation corpus (130+ docs), but some cross-references are stale post-verification |

---

## Appendix: Commit trail defining the closure state

| Commit | Date | Summary |
|--------|------|---------|
| `7d769bfb` | 2026-04-15 | `refactor(smc): split Core Engine into modular libraries (WP-SPLIT1–4)` |
| `60b016ec` | 2026-04-15 | `test(smc): harden regression tests for post-split module boundaries` |
| `fbe44e17` | 2026-04-16 | `fix(tests): resolve batch-1 regression failures (signature changes)` |
| `5f7ec4fe` | 2026-04-16 | `fix(tests): resolve batch-2 regression failures (state-resolution tuples)` |
| `25cb8be4` | 2026-04-16 | `fix(tests): resolve batch-3 regression failures (moved-to-library)` |
| `ed347402` | 2026-04-16 | `fix(tests): align governance anchor to active core engine after split` |
| `f8da37c1` | 2026-04-16 | `docs: update regression triage packs — final sweep, 0 failures` |
| `45858132` | 2026-04-16 | `fix(pine): resolve CE10237 unused-arg warnings + export lifecycle funcs` |
| `fce324b0` | 2026-04-16 | `docs(tradingview): record manual publish evidence for split libraries` |
| `85c42068` | 2026-04-16 | `feat(product): surface trust tier and degradation status in live SMC views` |
| `c5dfe326` | 2026-04-16 | `evidence: all 5 split libraries publish-verified via TradingView profile` |
| `77ac1652` | 2026-04-16 | `feat(governance): promote calibrated-brier-regression + calibrated-ECE to hard-blocking` |
