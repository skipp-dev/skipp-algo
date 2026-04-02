# v5.5b Architecture — Canonical Reference

**Status**: Active  
**Date**: 2026-04-01  
**Schema Version**: 2.0.0  
**Library Field Version**: v5.5b  

This document is the single canonical architecture overview for the SMC
Unified Lean engine at version v5.5b. It consolidates decisions that were
previously distributed across multiple policy and contract documents.

---

## 1. Design Principles

| # | Principle | Detail |
|---|-----------|--------|
| 1 | **One Primary Decision Surface** | Lifecycle + Signal Quality + Event State + Bias + Warnings. No secondary decision layers. |
| 2 | **Signal Quality Primacy** | Signal Quality (Family 6) is the single composite interpretation layer. All other families are inputs. |
| 3 | **Event Risk User Semantics** | Three user-facing states: blocked / caution / clear. Internal fields (cooldown timers, impact classes) stay hidden. |
| 4 | **No Shadow Logic** | Pine must not rebuild competing interpretation layers. Allowed: visualization, lifecycle labels, runtime constraints, aggregation. Forbidden: parallel computation, reconstruction, duplicate scoring. |
| 5 | **Field Semantics Integrity** | Field names must match actual computation precision. Age-derived labels must not imply price-event detection. |
| 6 | **Pine Runtime Budget** | Runtime efficiency is architectural, not incidental. Every `request.security` call requires budget justification. |
| 7 | **UX Modes** | Compact Mode is the reference UX. Advanced Mode is optional. Hero Surface (Dashboard rows 10-17) is the primary user view. |
| 8 | **Support Family Admission Rule** | Non-lean support blocks are admitted only when: scoring data cannot be derived from the 5 lean families, safe-defaults to neutral on absence, and no gating/blocking logic introduced. |
| 9 | **Generator-First Artifacts** | All Pine field assignments are generator-produced. No hand-written field assignments in Pine. |
| 10 | **Prefer Scoring Over Blocking** | Downgrade signals via quality scoring rather than hard blocks where possible (`DISCOURAGED` > `BLOCKED`). |

---

## 2. Lean Surface — 6 Families, 32 Fields

| Family | Fields | Purpose |
|--------|--------|---------|
| Event Risk Light | 7 | Market/symbol event gating, blocked/caution/clear |
| Session Context Light | 4+1 | Session, killzone, bias, score; optional volatility state |
| OB Context Light | 5 | Nearest OB side, distance, freshness, age, mitigation lifecycle |
| FVG Lifecycle Light | 6 | Nearest FVG side, fill %, maturity (fill-derived), freshness, invalidation |
| Structure State Light | 4 | Last structure event, age, freshness, trend strength |
| Signal Quality | 5 | Composite score, tier, warnings, bias alignment, freshness |

**Contract**: [v5_5_lean_contract.md](v5_5_lean_contract.md)

---

## 3. Signal Quality — Support Block Inputs

Signal Quality reads lean families 1-5 as primary inputs. Additionally it
reads two non-lean support blocks under Principle 8 (Admission Rule):

| Support Block | Component | Max Weight | Rationale |
|---------------|-----------|------------|-----------|
| `liquidity_sweeps` | Liquidity/sweep support | 15 pts | Sweep data is not derivable from lean families. |
| `compression_regime` | Compression regime | 15 pts | ATR regime enriches scoring; `SESSION_VOLATILITY_STATE` already derives from it, so SQ's direct read avoids double-derivation. |

Both blocks are read-only, scoring-only, and safe-default to zero on absence.

**Implementation**: [smc_signal_quality.py](../scripts/smc_signal_quality.py)

---

## 4. OB_MITIGATION_STATE — Age-Derived Lifecycle

States are **age-derived lifecycle stages**, not price-event signals:

| State | Condition | Semantics |
|-------|-----------|-----------|
| `fresh` | ≤ 10 bars, not mitigated | Recently created OB |
| `touched` | 11-30 bars, not mitigated | **Aging lifecycle label** — NOT a "price touched the OB" event |
| `mitigated` | Broad block reports actual mitigation | Price filled the OB zone |
| `stale` | > 30 bars | Old OB, losing relevance |

The label `touched` was kept (not renamed to `aging`) because it is established
in the lean contract and Pine decoder. The docstring in
[smc_ob_context_light.py](../scripts/smc_ob_context_light.py) documents this
explicitly.

---

## 5. Hero Surface — Compact Mode Reference

Compact Mode (`compact_mode = true`) is the recommended UX. The Hero Surface
occupies Dashboard rows 10-17:

**Active** (Hero Surface):
- Direction / Bias (HTF trend summary)
- Lifecycle markers (Reclaim, Confirmation, Ready)
- Signal Quality dashboard rows
- Event State (blocked / caution / clear)
- Warnings (volume quality, strict LTF)
- Health Badge, Risk Levels, Main Dashboard

**Suppressed** (debug + secondary overlays):
- OB / FVG / Engine debug labels
- Microstructure debug markers
- LTF dashboard details
- EMA support / VWAP / mean-target plot lines

All suppression uses `_eff` variables. Filter logic is **not** affected.

---

## 6. Artifact Strategy

Two artifact classes; no third class allowed:

| Class | Source | Purpose |
|-------|--------|---------|
| **Seed Reference** | `generate_smc_micro_profiles.py` | Default/generated artifact, must pass contract |
| **Showcase Reference** | `generate_showcase_summary.py` + `reference_enrichment.json` | Enriched example, must pass contract |

Both must conform to lean contract value domains. The showcase is re-derived
through adapters for consistency verification.

**Policy**: [ARTIFACT_STRATEGY.md](ARTIFACT_STRATEGY.md)

---

## 7. Runtime Budget

| Metric | Value |
|--------|-------|
| Total lines | ~6155 |
| `var` declarations | ~371 |
| `input.*` declarations | ~260 |
| `plot()` calls | 32 / 64 |
| `request.security` | 5 (limit: 40) |
| `request.security_lower_tf` | 2 |

**Dead inputs**: no longer treated as auto-removal work. The current
Phase C candidate queue is maintained separately and must be re-audited
before deletion.

**Removal Roadmap**:
- Phase A: Legacy field cleanup — ✅ done (~173 lines)
- Phase B: BUS compat fields — ✅ done (~265 lines, 33 fields, 12 resolvers, 3 plots)
- Phase C: Rebased to non-behavioural cleanup only; current candidate inventory and guard live in [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md) and `tests/test_smc_core_engine_phase_c_audit.py`
- Phase D: Old broad event risk fields — pending (requires BUS EventRiskRow lean-only)

**Details**: [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md), [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md), [PHASE_C_ANALYSIS.md](PHASE_C_ANALYSIS.md)

---

## 8. No Shadow Logic Policy

Pine must not rebuild competing interpretation layers outside the generator chain.

| Allowed | Forbidden |
|---------|-----------|
| Visualization (colors, labels) | Parallel computation of scores |
| Lifecycle labels (bar-level aging) | Reconstruction of composite metrics |
| Runtime constraints (clamping) | Duplicate scoring logic |
| Aggregation (combining received fields) | Alternative decision surfaces |

**Policy**: [NO_SHADOW_LOGIC_POLICY.md](NO_SHADOW_LOGIC_POLICY.md)

---

## 9. Version History

| Version | Change | Commit |
|---------|--------|--------|
| v5.5 | Lean Contract Freeze — 32 fields, 6 families | — |
| v5.5a | Semantic sharpening — hierarchy, optionality, naming precision | — |
| v5.5b | Migration packages — schema-drift fix, bias merge, vol regime, scoring, benchmarks, Phase B cleanup | 1a99c757 |

**Why v5.5b (not v5.6)**:
- No new lean fields added to the surface
- No fields removed from the surface
- Changes are infrastructure/scoring/cleanup, not surface-breaking
- `b` suffix signals "second sharpening patch"

---

## 10. Forward-Looking Extensions

v5.5b ships four infrastructure modules that lay the ground for
measurement, calibration, and probabilistic scoring **without** breaking the
lean surface contract.

### 10.1 Benchmark Artifacts (`smc_core/benchmark.py`)

| Concept | Detail |
|---------|--------|
| KPI set | `EventFamilyKPI` — hit_rate, time_to_mitigation, invalidation_rate, MAE, MFE per family |
| Families | BOS, OB, FVG, SWEEP |
| Stratification | session, htf_bias, vol_regime |
| Output | `benchmark_{symbol}_{tf}.json` + `manifest.json` in a per-run directory |

Benchmark results are **versionable** — each JSON artifact carries
`schema_version` and `generated_at`.

### 10.2 Probabilistic Scoring (`smc_core/scoring.py`)

| Concept | Detail |
|---------|--------|
| Scores | Brier Score (MSE of probabilities), Log Score (negative log-likelihood) |
| MVP label | `label_sweep_reversal` — did a sweep produce a directional reversal within *N* bars? |
| Output | `scoring_{symbol}_{tf}.json` per run |

Scoring results feed into the SQ calibration loop once live data is
available — they are **not** used in the Pine indicator today but are ready
for future CI-gated quality gates.

### 10.3 Vol-Regime Classification (`smc_core/vol_regime.py`)

ATR-ratio bucketing into `LOW`, `NORMAL`, `HIGH`, `EXTREME`.
Consumed by benchmark stratification and available for future
bias-merge weighting.

### 10.4 HTF/Session Bias Merge (`smc_core/bias_merge.py`)

Single-source-of-truth resolution of conflicting HTF bias, session bias, and
structure direction.  Returns the merged bias plus a confidence level.

### 10.5 Calibration Roadmap

| Phase | Scope | Status |
|-------|-------|--------|
| Phase 1 (current) | Brier/Log Score on sweep-reversal label, static thresholds | ✅ Shipped |
| Phase 2 (next) | Platt scaling or isotonic regression on SQ score vs. observed outcomes | Planned |
| Phase 3 | GARCH/regime-aware score adjustment, session-specific calibration | Future |
| Phase 4 | State-space model for time-varying SQ calibration | Research |

**Rule**: No calibration change may introduce new lean surface fields.
Calibration outputs remain internal Python artifacts or Dashboard-only
annotations.

---

## Supporting Documents

| Document | Scope | Status |
|----------|-------|--------|
| [v5_5_lean_contract.md](v5_5_lean_contract.md) | Field definitions, value domains, mapping | Active |
| [ARTIFACT_STRATEGY.md](ARTIFACT_STRATEGY.md) | Artifact classes, rules | Active (v5.5b) |
| [NO_SHADOW_LOGIC_POLICY.md](NO_SHADOW_LOGIC_POLICY.md) | Shadow logic rules | Active |
| [RUNTIME_BUDGET.md](RUNTIME_BUDGET.md) | Pine runtime metrics | Active |
| [LEGACY_REMOVAL_PLAN.md](LEGACY_REMOVAL_PLAN.md) | Removal phases | Active |
| [MEASUREMENT_LANE.md](MEASUREMENT_LANE.md) | Benchmark & scoring documentation | Active (v5.5b) |
| [SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md](SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md) | Historical architecture (DE/EN) | Supporting |
| [v5_5a_lean_contract_refinement_en.md](v5_5a_lean_contract_refinement_en.md) | Contract refinement notes | Supporting |
