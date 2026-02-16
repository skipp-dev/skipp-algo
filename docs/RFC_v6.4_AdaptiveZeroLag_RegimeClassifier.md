# RFC v6.4 — Adaptive Zero-Lag Trend Core + Regime Classifier 2.0

Status: **Draft (proposed)**  
Owner: `SkippALGO` core  
Date: 2026-02-15

## 1) Motivation

The strongest recent gain came from **USI Zero-Lag**. Next logical step is to apply the same philosophy to:

1. **Trend core lag reduction** (earlier but stable trend-state detection)
2. **Regime-adaptive behavior** (different entry strictness for Trend/Range/Chop/Vol-shock)

Goal: improve **timeliness** without reintroducing noise and improve **robustness** across market phases.

---

## 2) Scope

### Feature A: Adaptive Zero-Lag Trend Core

Add an optional trend source module that can replace or blend with current EMA/trend smooth logic.

Proposed modes (`trendCoreMode`):

- `ClassicEMA` (current behavior)
- `ZeroLagEMA` (DEMA/TEMA-style)
- `AdaptiveHybrid` (recommended default for rollout experiments)

### Feature B: Regime Classifier 2.0

Add explicit regime state machine used to auto-adjust effective gating/preset strictness.

Regimes:

- `TREND`
- `RANGE`
- `CHOP`
- `VOL_SHOCK`

---

## 3) Pine Inputs (proposed)

### A) Zero-Lag trend core

- `useZeroLagTrendCore = input.bool(false, "Use Zero-Lag Trend Core")`
- `trendCoreMode = input.string("AdaptiveHybrid", "Trend Core Mode", options=["ClassicEMA","ZeroLagEMA","AdaptiveHybrid"])`
- `zlTrendLenFast = input.int(13, "ZL Fast Length", minval=2)`
- `zlTrendLenSlow = input.int(34, "ZL Slow Length", minval=3)`
- `zlTrendAggressiveness = input.float(0.35, "ZL Aggressiveness", minval=0.0, maxval=1.0, step=0.05)`
- `zlTrendNoiseGuard = input.float(0.15, "ZL Noise Guard", minval=0.0, maxval=1.0, step=0.05)`

### B) Regime Classifier 2.0

- `useRegimeClassifier2 = input.bool(false, "Use Regime Classifier 2.0")`
- `regimeLookback = input.int(50, "Regime Lookback", minval=10)`
- `regimeAtrShockPct = input.float(85.0, "Vol Shock Percentile", minval=50, maxval=99, step=1)`
- `regimeAdxTrendMin = input.float(18.0, "Trend ADX Min", minval=5, maxval=40, step=1)`
- `regimeHurstRangeMax = input.float(0.48, "Range Hurst Max", minval=0.30, maxval=0.60, step=0.01)`
- `regimeChopBandMax = input.float(0.0035, "Chop ATR/Close Max", minval=0.0005, maxval=0.02, step=0.0005)`
- `regimeAutoPreset = input.bool(true, "Regime Auto-Preset")`

---

## 4) Integration points in current architecture

### A) Trend core wiring

Use Zero-Lag output where these are currently decided:

- `trendReg`
- `trendUp`, `trendDn`
- `trendUpSmooth`, `trendDnSmooth`
- optional context in `scoreCtxLongOk/scoreCtxShortOk`

Fail-safe rule:

- if Zero-Lag source is `na`/unstable => fallback to classic EMA path immediately.

### B) Regime-driven effective controls

Map regimes to effective settings (`*_Eff`) only when `regimeAutoPreset` is ON:

- `TREND`: lower score threshold, looser ChoCH floor, normal cooldown
- `RANGE`: neutral defaults, require stronger confirmation
- `CHOP`: higher thresholds, stronger vetoes, longer cooldown
- `VOL_SHOCK`: temporarily strict risk + entry gating, optional abstain boost

Suggested first mapped variables:

- `scoreThresholdLongEff`, `scoreThresholdShortEff`
- `scoreMinProbLongEff`, `scoreMinProbShortEff`
- `cooldownBarsEff`
- `chochMinProb`
- `abstainGate` sensitivity via confidence floor

---

## 5) Implementation blueprint (incremental)

### Phase 1 (safe scaffolding)

- add inputs and helper functions only
- add internal debug outputs for derived trend core/regime
- no behavior change unless toggles enabled

### Phase 2 (opt-in behavior)

- wire trend core into `trendUp/trendDn` path under flag
- wire regime-based `*_Eff` adjustments under flag
- preserve default behavior when both flags OFF

### Phase 3 (quality tuning)

- calibrate thresholds per preset (`Manual/Intraday/Swing`)
- add minimal hysteresis to regime transitions to avoid flapping

---

## 6) Test plan (must-have)

1. **Parity tests**
   - indicator/strategy both contain new inputs and core mappings
   - same regime→effective parameter mapping strings

2. **Behavior tests (simulator)**
   - zero-lag ON produces earlier trend state transition in controlled synthetic trend
   - noisy sideways sequence does not increase false entry rate above baseline guardrail
   - each regime changes expected `*_Eff` variables deterministically

3. **Regression invariants**
   - no change when both new features OFF
   - no NaN leaks in gate chain
   - conflict resolution unchanged

4. **Golden snapshots**
   - fixed synthetic sequences for TREND/CHOP/VOL_SHOCK event traces

Success gates (initial):

- maintain pass: `pytest -q` full suite
- no parity regressions
- in synthetic TREND scenario: median entry latency reduced vs baseline
- in synthetic CHOP scenario: false entries not increased beyond baseline + tolerance

---

## 7) Risk & rollback

Risks:

- over-sensitive trend core in chop
- regime flapping around thresholds
- excessive coupling into score path

Mitigations:

- hard OFF by default (`useZeroLagTrendCore=false`, `useRegimeClassifier2=false`)
- regime hysteresis and minimum-hold bars
- strict fallback to legacy path on invalid state

Rollback:

- single-toggle disable returns baseline behavior
- no data migration needed

---

## 8) Suggested GitHub research checklist

Keywords to evaluate before implementation:

- `Ehlers zero lag super smoother`
- `Kalman trend filter trading`
- `Hurst exponent regime detection`
- `Page-Hinkley drift detector`
- `CUSUM online change detection`

Selection criteria:

- low compute footprint in Pine v6
- stable behavior without repainting
- simple explainability for end users

---

## 9) Recommended next action

Implement **Phase 1** first in a small PR:

- add inputs + helper functions + debug visibility only
- no trading behavior change by default
- ship with parity + behavioral tests

Then move to **Phase 2** once baseline snapshots are stable.
