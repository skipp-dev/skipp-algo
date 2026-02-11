# v6.2 Evaluation Baselines & Population Split

**Date:** 11. Februar 2026
**Status:** DEPLOYED (main branch)
**File Affected:** `SkippALGO_Strategy.pine`
**Commits:** `4ab1266`, `6f2861a`, `1b3c3b3`, `9a32616`
**Verification:** 247 Tests Passed (Pytest), Pine Extension Lint Clean

## Executive Summary

This update adds **baseline comparators** (Uniform + Prior) and a **population split** mechanism to the evaluation harness, enabling direct measurement of forecast value-add versus naive strategies. The table now displays delta (Δ) metrics with verdict glyphs (✓/✗/~) showing at a glance whether the model beats its baselines.

---

## 1. Baseline Comparators (`4ab1266`)

### Problem

The evaluation harness computed Brier Score and LogLoss for the model, but offered no comparison point. Without baselines, "Brier = 0.19" is uninterpretable — is that good or bad?

### Solution

Two baselines are scored on the **same event population** as the model:

#### A) Uniform Baseline

Predicts each class with equal probability: `(1/3, 1/3, 1/3)`.

Expected constants (given `f_brier3` divides by 3.0):
- **Brier = 2/9 ≈ 0.222222** (not 0.667 — the `/3.0` normalizes per-class)
- **LogLoss = −ln(1/3) ≈ 1.098612**

These are invariant across all market conditions and serve as a "no-skill" ceiling.

#### B) Prior Baseline (Laplace-smoothed)

Predicts using empirical class frequencies with Dirichlet(1,1,1) smoothing:

```pine
prU = (nUp + 1.0) / (nTotal + 3.0)
prF = (nFlat + 1.0) / (nTotal + 3.0)
prD = (nDown + 1.0) / (nTotal + 3.0)
```

- Starts identical to Uniform (all counts = 0)
- Drifts toward actual class distribution as outcomes accumulate
- Counts updated **after** scoring each event (no data leakage)
- Represents "just use the base rate" — a stronger baseline than Uniform

#### Implementation Details

- 16 new rolling + sum arrays in `TfState` (Brier + LogLoss × N + 1 heads × Uniform + Prior)
- `float[3] priorCounts3` for outcome frequency tracking
- Scoring hook in the resolve loop after `f_eval_update_one3`, gated by `canEvalBase`
- Table rows 16 (⊘ Uniform) and 17 (⊘ Prior)

---

## 2. Population Split — `qUseForecast` (`6f2861a`)

### Problem

The evaluation harness scores **all** resolved events, but the model only drives trading decisions when `forecastAllowed == true` (Variant B). Questions like "does the forecast add value *when it's active*?" require separating the population.

### Solution

A `bool[]` queue flag (`qUseForecast`) captures the forecast-eligibility state at enqueue time and replays it at resolve time.

#### Semantics (Variant B, exact)

```pine
// At enqueue (both 3-way and 2-way paths):
array.push(st.qUseForecast, enableForecast and f_forecast_allowed())

// At global scope (entry logic):
forecastAllowed = enableForecast and f_forecast_allowed()
useForecast = (forecastAllowed == true)
```

The expressions are identical — no extra booleans co-mingled. "Eligible" means exactly "Variant B was active at that moment."

#### Queue Lifecycle

| Operation | Location | Action |
|-----------|----------|--------|
| Push | Enqueue (both paths) | `array.push(st.qUseForecast, ...)` |
| Read | Resolve loop | `useFc_i = f_safe_get_bool(st.qUseForecast, i, false)` |
| Remove | Pop/cleanup | `f_safe_remove_bool(st.qUseForecast, i)` |
| Clear | `f_reset_tf` | `array.clear(st.qUseForecast)` |

#### Eligible Eval Accumulators

13 new fields in `TfState` for eligible-only scoring:

| Category | Fields |
|----------|--------|
| Model (N head) | `evBrierN_Elig`, `evSumBrierN_Elig`, `evLogN_Elig`, `evSumLogN_Elig` |
| Model (1 head) | `evBrier1_Elig`, `evSumBrier1_Elig`, `evLog1_Elig`, `evSumLog1_Elig` |
| Uniform baseline | `evBrierBaseU_N_Elig`, `evSumBrierBaseU_N_Elig`, `evLogBaseU_N_Elig`, `evSumLogBaseU_N_Elig` |
| Prior baseline | `evBrierBaseP_N_Elig`, `evSumBrierBaseP_N_Elig`, `evLogBaseP_N_Elig`, `evSumLogBaseP_N_Elig` |
| Prior counts | `priorCounts3_Elig` (shared across heads — see note) |

**Head-independent prior:** The prior baseline uses outcome frequencies only, so one track serves both N and 1 heads. Only `_N_Elig` arrays exist for the prior (not a bug — documented in UDT comments).

#### No-Leakage Design

Both eligible and all-population priors update counts **after** scoring:

```pine
// Score using current counts
peB3 = f_brier3(peU, peF, peD, outcome)
// THEN update counts
if outcome == 1
    array.set(st.priorCounts3_Elig, 0, neUp + 1.0)
```

---

## 3. Delta (Δ) Display with Verdict Glyphs (`1b3c3b3`, `9a32616`)

### Δ Computation

```
Δ = model_mean - baseline_mean
```

- **Negative Δ** → model beats baseline (lower is better for both Brier and LogLoss)
- Both values are rolling means: `sum / array.size(buf)`
- Denominators always match (all buffers updated in same `if` block)

### Verdict Glyphs

```pine
f_deltaVerdict(val) =>
    na(val) ? "" : val <= -deltaDeadzone ? " ✓" : val >= deltaDeadzone ? " ✗" : " ~"
```

| Glyph | Condition | Meaning |
|-------|-----------|---------|
| ✓ | Δ ≤ −deadzone | Model materially outperforms baseline |
| ✗ | Δ ≥ +deadzone | Model materially underperforms |
| ~ | within ±deadzone | Dead zone / noise band |

### Configurable Threshold

```pine
deltaDeadzone = input.float(0.01, "Δ dead-zone (verdict threshold)", minval=0.001, maxval=0.10, step=0.005)
```

### Color Coding

| Color | Condition |
|-------|-----------|
| Green (lime, 40) | Δ < 0 (model wins) |
| Red (red, 40) | Δ > 0 (model loses) |
| Gray (gray, 60) | Δ = 0 or na |

### Formatting

`f_fmtDelta` always outputs fixed-width: sign + 3 decimals + glyph (e.g., `-0.015 ✓`, `+0.003 ~`). Table cells don't jitter.

---

## 4. Table Layout (21 rows)

| Row | Label | Content |
|-----|-------|---------|
| 0 | Header | Column titles |
| 1–8 | Eval rows | Model Brier, LogLoss, ECE, Drift per TF |
| 9–15 | TF detail rows | Per-timeframe statistics |
| 16 | ⊘ Uniform | Baseline Brier, LogLoss, ΔBrier, ΔLogLoss |
| 17 | ⊘ Prior | Baseline Brier, LogLoss, ΔBrier, ΔLogLoss |
| 18 | ✦ Elig | Eligible model Brier, LogLoss, n count |
| 19 | ✦ Elig Δ | Eligible model vs eligible prior Δ |
| 20 | Footer | Target description |

---

## 5. Helper Functions Added

| Function | Purpose |
|----------|---------|
| `f_safe_remove_bool(arr, idx)` | Safe bool array element removal |
| `f_safe_get_bool(arr, idx, def)` | Safe bool array access with default |
| `f_deltaVerdict(val)` | Verdict glyph based on configurable deadzone |
| `f_fmtDelta(val)` | Signed delta formatting with verdict |
| `f_colDelta(val)` | Delta cell color (green/red/gray) |

---

## 6. TradingView Smoke Checks

### Invariants (must hold on any symbol)

| Check | Expected |
|-------|----------|
| ⊘ Uniform Brier | ≈ 0.222 (constant, = 2/9) |
| ⊘ Uniform LogLoss | ≈ 1.099 (constant, = −ln(1/3)) |
| ⊘ Prior initial | ≈ Uniform (before outcomes accumulate) |
| ✦ Elig n | ≤ All population n |
| ✦ Elig Δ | Changes only when eligible events resolve |

### Behavioral Checks

1. Toggle `enableForecast` off → Elig `n` should stop growing
2. Δ glyphs respond to `deltaDeadzone` input changes
3. Uniform Δ is stable (model improves/worsens vs constant)
4. Prior Δ becomes informative after ~50+ resolved events

---

## 7. Verification

- **Pytest:** 247 passed, 0 failed
- **Pine Extension (VS Code):** 0 errors
- **Evidence Pack:**
  - `qUseForecast`: pushed at both enqueue paths, read at resolve, removed at pop, cleared at reset
  - `priorCounts3_Elig`: used for eligible prior probs, updated after scoring, cleared at reset
  - `canEvalBase`: gates all baseline scoring
  - `f_fmtDelta`/`f_colDelta`: used in rows 16, 17, 19 with correct sign convention
