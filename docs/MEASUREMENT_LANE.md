# Measurement Lane — v5.5b

**Status**: Active  
**Date**: 2026-04-01

## Purpose

The measurement lane provides **versionable, CI-auditable** benchmark and
scoring artifacts for every SMC event family. It exists alongside the two
artifact classes (seed + showcase) and operates **entirely in Python** —
no new lean surface fields are introduced.

## Modules

### 1. `smc_core/benchmark.py` — Event Family KPIs

| KPI | Unit | Families |
| --- | --- | --- |
| `hit_rate` | 0–1 ratio | BOS, OB, FVG, SWEEP |
| `time_to_mitigation_mean` | bars | BOS, OB, FVG, SWEEP |
| `invalidation_rate` | 0–1 ratio | BOS, OB, FVG, SWEEP |
| `mae` (Mean Adverse Excursion) | price units | BOS, OB, FVG, SWEEP |
| `mfe` (Mean Favorable Excursion) | price units | BOS, OB, FVG, SWEEP |
| `n_events` | count | BOS, OB, FVG, SWEEP |

**Stratification**: Each KPI set can be stratified by `session`,
`htf_bias`, `vol_regime`.

**Output**: `benchmark_{symbol}_{tf}.json` + `manifest.json` per run.

### 2. `smc_core/scoring.py` — Probabilistic Calibration

| Metric | Range | Description |
| --- | --- | --- |
| Brier Score | [0, 1] | MSE of predicted probability vs outcome (lower = better) |
| Log Score | [0, ∞) | Negative log-likelihood per prediction (lower = better) |
| Hit Rate | [0, 1] | Fraction of events that realized |

**MVP Label**: `label_sweep_reversal` — did a sweep produce a directional
reversal within *N* bars? This is the first scored label; more labels
(OB-mitigation, FVG-fill) follow in later phases.

**Output**: `scoring_{symbol}_{tf}.json` per run.

### 3. `smc_core/vol_regime.py` — Volatility Classification

ATR-ratio bucketing into `LOW`, `NORMAL`, `HIGH`, `EXTREME`.
Used as a stratification dimension in benchmarks.

### 4. `smc_core/bias_merge.py` — Bias SSOT

Resolves conflicting HTF bias, session bias, and structure direction into a
single merged bias + confidence level.

## Calibration Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| Phase 1 | Brier/Log Score on sweep-reversal label, static thresholds | ✅ Shipped |
| Phase 2 | Platt scaling or isotonic regression on SQ score vs. observed outcomes | Planned |
| Phase 3 | GARCH/regime-aware score adjustment, session-specific calibration | Future |
| Phase 4 | State-space model for time-varying SQ calibration | Research |

## Integration Points

- **CI**: Benchmark + scoring artifacts are generated and structure-validated
  by the `measurement_lane` gate in `scripts/run_smc_release_gates.py`.
  The gate is **soft** (non-blocking) — it reports `ok` or `warn` but never
  `fail`. This means measurement failures produce warnings in the release
  report without preventing a release.
- **Evidence path**: When a structure artifact and canonical export bars are
  available for the reference symbol/timeframe, the gate evaluates real
  BOS/OB/FVG/SWEEP evidence and real sweep-reversal scoring inputs instead of
  placeholder empty families. Empty persisted families may fall back to the
  explicitly recomputed structure from those same bars.
- **Release Report**: The JSON report includes:
  - `measurement_artifacts_present` — benchmark artifact generated successfully
  - `scoring_artifacts_present` — scoring artifact generated successfully
  - `brier_finite` / `log_finite` — metric validity checks
- **Tests**: `test_smc_benchmark.py` and `test_smc_scoring.py` validate KPI
  structure and range. These tests are included in the release-gate test matrix.
- **Architecture doc**: See [v5_5b_architecture.md §10](v5_5b_architecture.md)
  for the canonical forward-looking reference.

### What is intentionally NOT blocking

- Score quality thresholds (e.g. "Brier must be < 0.3") — not enforced yet.
  The gate only validates artifact *structure* and metric *finiteness*.
- Artifact/data availability — the gate now evaluates real structure artifacts
  against canonical export bars when those inputs are present. Missing
  artifacts, missing bars, or evidence-resolution drift only produce warnings.
- Hard release blocks — the measurement gate sets `"blocking": false` so it
  never contributes to `overall_status: "fail"`.

## Rules

1. **No surface expansion**: Measurement outputs are Python-only artifacts,
   never new Pine lean fields.
2. **Versionable**: Every artifact carries `schema_version` and `generated_at`.
3. **Stratification-first**: KPIs must always be available unstratified *and*
   stratified (by session, htf_bias, vol_regime).
4. **Proper Scoring Rules**: Only Brier and Log Score. No ad-hoc accuracy
   metrics that reward overconfident predictions.
