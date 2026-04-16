# RFC: Composite Consolidation Score — Shadow Discovery

**Date:** 2026-04-16
**Status:** Discovery / Shadow-only
**Author:** AI-assisted analysis
**Scope:** Assessment only — no production code, no gate changes, no BUS mutation

---

## 1. Purpose

This RFC answers one question:

> Is a graduated Composite Consolidation Score for the SMC system
> factually sound, governance-compatible, and measurably useful — or
> is the perceived gap already covered by existing mechanisms?

This is explicitly **not** a feature proposal. It is a structured assessment
that either yields a clear shadow-evaluation plan or a documented No-Go.

---

## 2. Current SMC Baseline

### 2.1 What SMC already has for squeeze / consolidation / regime

The SMC Core Engine contains **six independent squeeze-adjacent subsystems**,
each producing its own binary or graduated signal:

| # | Subsystem | Group | Type | Gate Class |
|---|-----------|-------|------|------------|
| 1 | **Vola Compression Gate** | g_vola (17) | Binary | HARD (env) |
| 2 | **Vol Regime** (4-MA stack + ROC + spread) | g_volreg (21) | Binary (tiered) | SCORING |
| 3 | **Vol Squeeze** (BB inside KC) | g_volreg (21) | Binary | SCORING (opt-in) |
| 4 | **Stretch Context** (z-score to SMA100) | g_stretch (22) | Graduated → Binary per tier | SCORING |
| 5 | **DDVI Context** (DI± with BB extremes) | g_ddvi_ctx (23) | Graduated → Binary per tier | SCORING |
| 6 | **Pullback Acceleration** (4-LR slope blend) | g_accel (19) | Graduated → Binary per tier | SCORING |

Additionally:
- **ADX** feeds `resolve_long_clean_tier` and quality score (weight 2).
- **SD Confluence** (second derivative + divergence) feeds tiered gates.
- **Library snapshot** provides `SQUEEZE_ON`, `SQUEEZE_RELEASED`,
  `ATR_REGIME`, `ATR_RATIO`, `SPREAD_REGIME` — but these are
  **display-only** in HTF Confluence and Profile Context; none feed Core
  Engine gates.

### 2.2 How these are consumed

Each subsystem feeds its **own independent gate** at each lifecycle tier
(Armed → Confirmed → Ready → Best → Strict). Gates are evaluated in
parallel, not composed. The operator sees individual pass/fail rows on
the Dashboard.

### 2.3 What is genuinely missing

| Gap | Description |
|-----|-------------|
| **No cross-domain composition** | When vola compression + BB/KC squeeze + stretch lower-extreme + acceleration exhaustion all fire simultaneously, there is no amplification or composite readiness signal. Each gate passes independently. |
| **No graduated consolidation intensity** | All squeeze-related signals are flattened to binary at each gate tier. The system knows "squeeze on: yes/no" but not "how compressed are we on a 0–1 scale across all dimensions." |
| **Library squeeze data is disconnected** | `mp.SQUEEZE_ON`, `mp.ATR_REGIME`, `mp.ATR_RATIO` from the generated library never feed Core Engine decisions — only the companion display scripts consume them. |
| **No squeeze-to-expansion quality** | The vola gate checks `compression_recent AND expansion_now` as a binary. Duration, magnitude, and transition speed of the compression→expansion sequence are not measured. |

### 2.4 What seems like a gap but is covered

| Apparent gap | Actually covered by |
|---|---|
| No BB/KC squeeze detector | `compute_vol_regime()` — full BB(20,2.0) inside KC(20,1.5) |
| ADX not used for decisions | `adx_strong` feeds quality tier + context quality score |
| No mean-reversion detection | Stretch context — z-score with anti-chase thresholds per tier |
| No compression→expansion detector | Vola compression gate — `compression_recent + expansion_now` |
| No momentum exhaustion detection | Acceleration module's `accel_below_zero_rising` |
| No directional divergence | SD confluence + DDVI hidden/strong bull divergence |

---

## 3. Why This Topic Exists

The standalone script `USI-CHOCH.pine` implements a 4-component composite
consolidation score:

```
consolidation_score = (ADX_low ? 1 : 0) + (ATR_contracting ? 1 : 0)
                    + (USI_spread_tight ? 1 : 0) + (BB_squeeze_on ? 1 : 0)
is_consolidation    = consolidation_score >= 2
```

Plus a graduated pressure score (0..1):
```
pressure = 0.30 × ADX_pressure + 0.25 × ATR_pressure
         + 0.20 × USI_pressure + 0.25 × squeeze_pressure
```

This raises the question: would SMC benefit from a similar composite that
unifies its existing 6+ independent squeeze signals into a single graduated
readiness indicator?

---

## 4. Candidate Score Components

### Preferred schema: Weighted normalized composite (0.0–1.0)

Each component is independently normalized to 0.0–1.0 before weighting.
The composite is **not** a new signal — it is a read-only aggregation
of existing signals.

| # | Component | Data source in SMC | Normalization | Proposed Weight | Status |
|---|-----------|-------------------|---------------|-----------------|--------|
| C1 | **Volatility compression intensity** | `atr_now / atr_baseline` from g_vola (group 17) | `1.0 − clamp(ratio, 0.5, 1.2)` scaled to 0–1 | 0.30 | Available in Core Engine |
| C2 | **BB/KC squeeze state** | `vol_squeeze_on` from g_volreg (group 21) | Binary: 0.0 or 1.0 | 0.20 | Available in Core Engine |
| C3 | **Stretch z-score proximity to lower extreme** | `distance_to_mean_z` from g_stretch (group 22) | `clamp(−z, 0, 2) / 2` (lower z = higher consolidation readiness) | 0.20 | Available in Core Engine |
| C4 | **Acceleration exhaustion** | `accel_value` from g_accel (group 19) | `clamp(−accel, 0, threshold) / threshold` | 0.15 | Available in Core Engine |
| C5 | **ADX trend weakness** | `adx_value` from Core Engine | `1.0 − clamp(adx / 50, 0, 1)` (lower ADX = more consolidation) | 0.15 | Available in Core Engine |

**All five components use data already computed in the Core Engine.**
No new indicators, no new library imports, no new LTF requests.

### Components explicitly excluded

| Excluded | Reason |
|----------|--------|
| USI (Zero-Lag RSI spread) | Not available in SMC; would require new library dependency and violate No-Shadow-Logic principle |
| CMF / OBV | Not in SMC; new indicator with its own validation burden |
| DDVI | Already has its own dedicated gate; folding it in would create circular dependency |
| SD Confluence | Already has its own dedicated gate |
| Library `mp.SQUEEZE_ON` | Comes from a different computation path (daily snapshot vs. intrabar); mixing would create temporal inconsistency |

---

## 5. SMC Fit / Misfit Analysis

### 5.1 Where the score could theoretically dock

| Docking point | Feasibility | Notes |
|---|---|---|
| **Shadow/advisory BUS field** | ✅ Feasible | New float field on LeanPackB or diagnostic row. Display-only initially. No gate influence. |
| **Dashboard diagnostic row** | ✅ Feasible | Render as 0–100% bar or colored badge. Pure visualization. |
| **Quality score weight** | ⚠️ Conditional | Could contribute to `resolve_long_clean_tier` as one additional factor. Requires shadow evidence first. |
| **Ready-gate context** | ⚠️ Conditional | Could sharpen "is the environment ready for an entry" without changing structure/reclaim logic. Only after shadow validation proves Brier-neutral. |
| **Entry-gate modifier** | ❌ Not recommended | Too close to primary signal territory. Risk of score becoming a de facto entry filter. |
| **Zone quality enrichment** | ❌ Not recommended | Would blur the line between structure quality (OB/FVG intrinsic) and context quality (extrinsic). |

### 5.2 Compatibility assessment

| Criterion | Assessment |
|---|---|
| No new primary signal | ✅ Score aggregates existing signals only |
| Context enhancer only | ✅ Advisory/shadow by design |
| Measurement gates unaffected | ✅ No gate threshold changes; shadow-only |
| Long-dip/reclaim focus preserved | ✅ Score is context, not structure |
| No BUS-v2 schema change | ✅ Uses existing diagnostic/advisory row slot |
| No Shadow Logic violation | ✅ No competing interpretation — pure aggregation of existing computations |
| No new indicator computation | ✅ All 5 components already computed |
| Additive to bundle delivery | ✅ Goes in `structure_context` enrichment, not `SmcStructure` canonical keys |

---

## 6. Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **False precision** — a 0.73 composite score implies knowledge that 6 binary gates cannot individually support | Medium | Always display with uncertainty band. Never use as sole decision criterion. |
| **Brier/ECE regression** — if score influences gate decisions, it adds a dimension that calibration must cover | High | Shadow-only until ≥ 3 measurement cycles prove Brier stability ≤ 0.60, regression ≤ 0.08. |
| **Dashboard complexity** — one more row for operators to process | Low | Implement as collapsible diagnostic row, not primary decision surface. |
| **Product identity drift** — accumulating "nice to have" context layers dilutes the SMC focus on structure + reclaim | Medium | Hard rule: score never influences zone detection, never modifies lifecycle state machine, never appears in alert conditions. |
| **Weight tuning temptation** — 5 weights invite perpetual optimization that never converges | Medium | Fix weights at design time. No per-symbol or per-TF tuning. Weights change only with RFC amendment. |
| **Circular dependency** — if ADX feeds both the quality tier AND the composite, changes in ADX affect two paths | Low | Acceptable: the composite is read-only and does not feed back into ADX computation. No circular dataflow. |
| **Temporal inconsistency** — components from different lookback windows may disagree | Low | All 5 components use bar-level data with comparable lookback horizons (14–100 bars). No cross-timeframe mixing. |

---

## 7. Non-Goals

These are explicitly out of scope for this RFC and any subsequent shadow work:

1. **No new entry generator.** The score must never trigger entries on its own.
2. **No replacement for structure/reclaim logic.** BOS, CHoCH, OB lifecycle, FVG
   mitigation remain the sole primary signals.
3. **No USI / Pre-CHoCH / CMF bundle.** Each of those is a separate feature with
   its own validation burden. This RFC covers only the consolidation composite.
4. **No gate threshold changes.** Existing Brier/ECE/coverage thresholds are
   immutable for this work.
5. **No library snapshot dependency.** The score uses only Core Engine intrabar
   computations, not `mp.*` library fields.
6. **No short-side extension.** SMC is long-dip focused. The composite is defined
   for long-side readiness only.
7. **No weight optimization loop.** Weights are fixed at design time and changed
   only via RFC amendment.

---

## 8. Shadow Evaluation Design

### 8.1 Shadow fields required

If approved for shadow evaluation, the following fields would be added to the
**diagnostic surface only** (not to any gate, not to BUS-v2 contract):

| Field | Type | Description |
|-------|------|-------------|
| `consolidation_composite` | float (0.0–1.0) | Weighted composite score |
| `consolidation_component_mask` | int (bitmask) | Which of 5 components are above their respective activation thresholds |
| `consolidation_active_count` | int (0–5) | Number of active components |
| `consolidation_regime` | string | "NONE" / "MILD" (1–2) / "MODERATE" (3) / "STRONG" (4–5) |

### 8.2 Comparison groups

| Group | Definition | Purpose |
|-------|-----------|---------|
| A (baseline) | Current system without composite | Control group |
| B (shadow) | Current system + composite logged but NOT influencing any gate | Treatment group |

Comparison is purely observational: does the composite score correlate with
setup quality outcomes without requiring gate changes?

### 8.3 Measurable hypotheses

| # | Hypothesis | Metric | Success threshold |
|---|-----------|--------|-------------------|
| H1 | High composite (≥ 0.6) setups have lower Brier scores than low composite (< 0.3) setups | Brier score stratified by composite tercile | ≥ 0.03 Brier improvement in top tercile |
| H2 | Composite does not degrade overall calibration | Brier score (all events) | Regression ≤ 0.02 vs. pre-shadow baseline |
| H3 | Composite does not reduce event coverage | Coverage ratio (all events) | Coverage reduction ≤ 5% |
| H4 | Weak setups (composite < 0.3) have measurably worse outcomes | Win rate / R-multiple in bottom tercile vs. top tercile | ≥ 10% relative difference |
| H5 | Composite adds information beyond individual components | Mutual information: composite vs. each component alone | Composite MI > max single-component MI |

### 8.4 Minimum data requirements

| Requirement | Value | Rationale |
|-------------|-------|-----------|
| Minimum shadow runs | 5 | Governance requires ≥ 3 deeper-OK + 2 release-OK |
| Minimum symbols | 5 | Release policy breadth requirement |
| Minimum timeframes | 2 | Release policy breadth requirement |
| Minimum scoring events per tercile | 15 | Statistical reliability for Brier stratification |
| Shadow duration | ≥ 21 calendar days | Cover ≥ 3 weekly cycles |
| Artifact classification | `stage_only` | Shadow fields are diagnostic, committed when content changes |

### 8.5 Gate conflict assessment

| Potential conflict | Assessment |
|---|---|
| Brier hard gate (≤ 0.60) | No risk — shadow does not modify any gate. Composite is logged, not acted upon. |
| Brier regression gate (≤ 0.08) | No risk — no gate changes. |
| ECE hard gate (≤ 0.30) | No risk — no calibration change. |
| Coverage floor (advisory) | No risk — no events are filtered or added. |
| Trust tier promotion | No risk — composite is not a measurement family member. |

---

## 9. Decision Criteria

### Go criteria (all must be true)
1. The baseline analysis confirms genuine gaps (not covered differently).
2. All candidate components use only existing Core Engine data.
3. A clean shadow evaluation plan is formulable without gate changes.
4. Governance rules are fully compatible (no Shadow Logic violation, no BUS mutation).
5. Expected benefit is measurable with existing measurement infrastructure.

### No-Go criteria (any one triggers No-Go)
1. The gap is already sufficiently covered by existing independent gates.
2. The score requires new indicator computations not in the Core Engine.
3. No measurable hypothesis can be formulated.
4. The score would require gate threshold changes to be useful.
5. Shadow evaluation would require ≥ 6 months of data for statistical power.

---

## 10. Recommendation: **Not Yet**

### Rationale

**The gap is real but narrow.** SMC already has 6+ squeeze-adjacent subsystems
that individually cover ATR compression, BB/KC squeeze, mean-reversion
proximity, momentum exhaustion, directional divergence, and trend-strength
filtering. Each feeds its own tiered gate. The genuine gap is the
**cross-domain composition** — knowing that 4 of 6 consolidation components
are simultaneously active vs. only 1.

**The score is architecturally clean.** All 5 proposed components use data
already computed in the Core Engine. No new indicators, no new library
dependencies, no Shadow Logic violation, no BUS-v2 mutation. The composite
would be a pure aggregation function over existing signals.

**But the measurable benefit is unproven.** The critical question — does a
graduated composite improve readiness precision compared to the existing
independent binary gates — cannot be answered without shadow data. And
the shadow evaluation requires:
- A diagnostic surface change (new fields in artifacts)
- ≥ 5 measurement runs across ≥ 5 symbols × 2 timeframes
- ≥ 21 calendar days of data
- Stratified Brier analysis by composite tercile

This is feasible but requires infrastructure work (adding shadow fields to
the diagnostic/artifact pipeline) that is non-trivial. It should not be
started as a side-task.

### Verdict breakdown

| Criterion | Status |
|---|---|
| Gap is real | ✅ Yes — cross-domain composition is genuinely missing |
| Components available | ✅ Yes — all 5 use existing Core Engine data |
| Governance compatible | ✅ Yes — shadow-only, no gate/BUS changes |
| Shadow plan formulable | ✅ Yes — 5 testable hypotheses defined |
| Benefit proven | ❌ No — requires shadow data that does not yet exist |
| Infrastructure ready | ⚠️ Partial — diagnostic artifact pipeline needs new fields |

### Recommended next steps (if prioritized)

1. **Prerequisite:** Ensure the diagnostic artifact pipeline supports
   additional float/string fields without schema-breaking changes.
2. **Shadow implementation:** Add the 4 shadow fields (composite, mask,
   count, regime) to the diagnostic surface. No gate influence.
3. **Collect data:** Run ≥ 5 measurement cycles (≥ 21 days).
4. **Evaluate:** Test H1–H5. If H1 shows ≥ 0.03 Brier improvement in
   top tercile AND H2 shows regression ≤ 0.02, promote to RFC amendment
   for gate-advisory integration.
5. **If hypotheses fail:** Close as "Not needed — existing independent
   gates are sufficient."

### What this RFC does NOT recommend

- Immediate implementation of the composite in any form
- Bundling with USI, Pre-CHoCH, CMF, or other standalone features
- Changing any existing gate thresholds
- Adding the composite to alert conditions
- Treating the composite as a validated signal

---

*End of RFC.*
