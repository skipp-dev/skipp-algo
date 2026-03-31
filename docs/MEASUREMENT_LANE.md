# Measurement Lane — v5.5b

**Status**: Active  
**Date**: 2025-07-21

## Purpose

The measurement lane provides **versionable, CI-auditable** benchmark and
scoring artifacts for every SMC event family. It exists alongside the two
artifact classes (seed + showcase) and operates **entirely in Python** —
no new lean surface fields are introduced.

## Modules

### 1. `smc_core/benchmark.py` — Event Family KPIs

| KPI | Unit | Families |
|-----|------|----------|
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
|--------|-------|-------------|
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
|-------|-------|--------|
| Phase 1 | Brier/Log Score on sweep-reversal label, static thresholds | ✅ Shipped |
| Phase 2 | Platt scaling or isotonic regression on SQ score vs. observed outcomes | Planned |
| Phase 3 | GARCH/regime-aware score adjustment, session-specific calibration | Future |
| Phase 4 | State-space model for time-varying SQ calibration | Research |

## Integration Points

- **CI**: Benchmark + scoring scripts can be invoked by
  `scripts/run_smc_release_gates.py` (or the GitHub Actions workflow).
- **Tests**: `test_lean_value_domains.py` validates KPI structure and range.
- **Architecture doc**: See [v5_5b_architecture.md §10](v5_5b_architecture.md)
  for the canonical forward-looking reference.

## Rules

1. **No surface expansion**: Measurement outputs are Python-only artifacts,
   never new Pine lean fields.
2. **Versionable**: Every artifact carries `schema_version` and `generated_at`.
3. **Stratification-first**: KPIs must always be available unstratified *and*
   stratified (by session, htf_bias, vol_regime).
4. **Proper Scoring Rules**: Only Brier and Log Score. No ad-hoc accuracy
   metrics that reward overconfident predictions.
