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

**Active Labels**:

- `label_bos_follow_through` — did a BOS continue in its break direction by a minimum threshold within the lookahead window?
- `label_orderblock_mitigation` — did price mitigate the order block before invalidating it?
- `label_fvg_mitigation` — did price tag/fill the gap before invalidating it?
- `label_sweep_reversal` — did a sweep produce a directional reversal within the lookahead window?

**Output**: `scoring_{symbol}_{tf}.json` per run with aggregate metrics,
`family_metrics`, aggregate `calibration`, and `stratified_calibration`
summaries for BOS, OB, FVG, and SWEEP when present.

**Calibration methods**:

- Preferred: Platt scaling on scored-event probabilities when sample size and
  class balance are sufficient.
- Fallback: deterministic beta-bin shrinkage when Platt scaling would be
  unstable.

**Current input**: the measurement lane now prefers scored-event
`raw_score_0_100` sourced from event-local `SIGNAL_QUALITY_SCORE`, with
automatic fallback to `predicted_prob` when raw-score coverage is incomplete.

## Persistent CI Layout

The `measurement_lane` gate now persists its outputs below `artifacts/ci/measurement/{SYMBOL}/{TF}/`.

Per measured symbol/timeframe pair the gate writes:

- `benchmark_{symbol}_{tf}.json` — family KPIs and stratified benchmark buckets
- `manifest.json` — benchmark artifact registry emitted by `export_benchmark_artifacts(...)`
- `scoring_{symbol}_{tf}.json` — Brier / Log / hit-rate metrics for the scored event set
- `measurement_manifest.json` — small measurement manifest with artifact pointers, evidence flags, warnings, a compact quality summary, and compact calibration summaries

`measurement_manifest.json` is the hand-off contract for evidence aggregation. It contains:

- `symbol`, `timeframe`, `generated_at`, `schema_version`
- `artifacts.benchmark.artifact_path` and `artifacts.benchmark.manifest_path`
- `artifacts.scoring.artifact_path`
- `measurement_evidence_present`, `evaluated_event_counts`, `bars_source_mode`
- `quality_summary.benchmark_event_counts`
- `quality_summary.stratification_coverage`
- `quality_summary.n_events`, `quality_summary.brier_score`, `quality_summary.log_score`, `quality_summary.hit_rate`
- `quality_summary.calibration`
- `quality_summary.stratified_calibration`
- `quality_summary.family_metrics`
- `warnings`

### 3. `smc_core/vol_regime.py` — Volatility Classification

Forecast-aware volatility classification into `LOW_VOL`, `NORMAL`, `HIGH_VOL`, `EXTREME`.

Preferred path: one-step `arch`/GARCH forecast versus a rolling baseline volatility.
Fallback path: deterministic ATR-ratio bucketing when `arch` is unavailable,
history is too short, or model fitting fails.

Used as a stratification dimension in benchmarks and surfaced in snapshot
bundles / measurement evidence with `model_source`, `fallback_reason`,
`forecast_volatility`, `baseline_volatility`, and `forecast_ratio`.

### 4. `smc_core/bias_merge.py` — Bias SSOT

Resolves conflicting HTF bias, session bias, and structure direction into a
single merged bias + confidence level.

## Calibration Roadmap

| Phase | Scope | Status |
| --- | --- | --- |
| Phase 1 | Brier/Log Score on BOS/OB/FVG/SWEEP labels, static thresholds | ✅ Shipped |
| Phase 2 | Aggregate probability calibration (Platt preferred, beta-bin fallback) on scored-event probabilities | ✅ Shipped |
| Phase 3 | Stratified calibration summaries by session, HTF bias, vol regime | ✅ Shipped |
| Phase 4 | Direct event-level `SIGNAL_QUALITY_SCORE` wiring + calibrated shadow governance | ✅ Shipped |
| Phase 5 | Contextual / regime-adjusted calibration summaries by session, HTF bias, vol regime | ✅ Shipped |
| Phase 6 | Contextual recommendation output plus promotion policy | ✅ Shipped |
| Phase 7 | State-space model for time-varying calibration | Research |

## Integration Points

- **CI**: Benchmark + scoring artifacts are generated and structure-validated
  by the `measurement_lane` gate in `scripts/run_smc_release_gates.py`.
  The gate is **soft** (non-blocking) — it reports `ok` or `warn` but never
  `fail`. This means measurement failures produce warnings in the release
  report without preventing a release.
- **Persistent export**: When `scripts/run_smc_release_gates.py` writes its JSON
  report to `artifacts/ci/...`, measurement artifacts are written next to it
  under `artifacts/ci/measurement/...` with report-relative paths such as
  `measurement/AAPL/15m/measurement_manifest.json`.
- **Evidence path**: When a structure artifact and canonical export bars are
  available for the reference symbol/timeframe, the gate evaluates real
  BOS/OB/FVG/SWEEP evidence and family-level scoring inputs instead of
  placeholder empty families. Empty persisted families may fall back to the
  explicitly recomputed structure from those same bars.
- **Vol regime metadata**: Snapshot bundles and measurement evidence include
  `model_source`, `fallback_reason`, `forecast_volatility`,
  `baseline_volatility`, and `forecast_ratio` so CI can distinguish
  forecast-driven classifications from ATR fallback.
- **Release Report**: The JSON report includes:
  - `measurement_artifacts_present` — benchmark artifact generated successfully
  - `scoring_artifacts_present` — scoring artifact generated successfully
  - `measurement_manifest_present` — measurement manifest written successfully
  - `measurement_manifest_path` / `benchmark_artifact_path` / `scoring_artifact_path` — report-relative artifact locations
  - `brier_score` / `log_score` / `scoring_hit_rate` — compact quality metrics copied into gate details
  - `calibration` / `stratified_calibration` — compact aggregate and stratified calibration summaries copied into gate details
  - `contextual_calibration` — compact contextual/regime-adjusted calibration summary copied into gate details
  - `scoring_family_metrics` / `scoring_families_present` — family-level proper scoring summaries
  - `benchmark_event_counts` / `stratification_coverage` — compact benchmark coverage summary
  - `brier_finite` / `log_finite` — metric validity checks
- **Evidence Summary**: `scripts/collect_smc_gate_evidence.py` now loads
  `measurement_manifest.json`, `benchmark_*.json`, and `scoring_*.json` to
  build `measurement_history.latest_by_pair` and `measurement_history.history_by_pair`
  entries with Brier, Log Score, family metrics, event counts, benchmark coverage, and
  stratification coverage.
- **Contextual recommendation surface**: the same evidence summary now computes
  operator-facing `contextual_calibration_recommendation` and
  `contextual_calibration_promotion` payloads per pair, plus top-level
  `pairs_with_contextual_recommendation`,
  `pairs_ready_for_contextual_promotion`,
  `contextual_recommendations_detected`, and
  `contextual_promotions_ready` summaries.
- **Shadow Governance**: `smc_integration/release_policy.py` now centralizes
  warn-only measurement thresholds for Brier, Log Score, calibrated Brier,
  calibrated ECE, event coverage, and stratification coverage. Release reports expose machine-readable
  `measurement_degradations_detected` / `degradations_detected` rows per
  measurement gate, while evidence summaries compute historical comparisons for
  `measurement_history.shadow_degradations_detected` and
  `measurement_degradations_detected`.
- **History-tightened calibrated ceilings**: once enough history exists, the
  calibrated absolute warn ceilings are tightened automatically from the
  historical median plus regression slack and surfaced as
  `measurement_shadow_effective_thresholds` in the release report.
- **Optional promotion path**: `scripts/run_smc_release_gates.py` accepts
  `--measurement-baseline-summary <path>` to compare the current run against a
  prior evidence summary and `--strict-measurement-shadow` to promote those
  shadow degradations from warn-only to blocking failures.
- **Benchmark harness**: `scripts/run_smc_measurement_benchmark.py` provides a
  reproducible one-command operator path for R5. It writes pair-scoped JSON and
  CSV summaries, `benchmark_run_summary.csv`, `benchmark_run_manifest.json`,
  `ensemble_quality_{symbol}_{tf}.json`,
  `reliability_{symbol}_{tf}.html`, and
  `stratification_{symbol}_{tf}.html` below an output root such as
  `artifacts/ci/measurement_benchmark/`.
- **Reliability plot**: the harness now overlays raw and calibrated reliability
  traces and includes the calibration method plus ECE delta in the plot title.
- **Ensemble quality**: snapshot bundles now expose a bounded
  `ensemble_quality` payload derived from heuristic layering strength, merged
  bias, and vol-regime confidence, while measurement evidence adds the scored
  event calibration component and the benchmark harness persists the versioned
  JSON artifact for each pair.
- **Manual CI path**: `.github/workflows/smc-measurement-benchmark.yml` runs
  the harness on demand and uploads the full artifact tree for offline review.
- **Tests**: `test_smc_benchmark.py` and `test_smc_scoring.py` validate KPI
  structure and range. These tests are included in the release-gate test matrix.
- **Architecture doc**: See [v5_5b_architecture.md §10](v5_5b_architecture.md)

## Local Reproduction

Single-command benchmark harness:

```bash
python scripts/run_smc_measurement_benchmark.py \
  --symbols AAPL,MSFT \
  --timeframes 15m,1H \
  --output-dir artifacts/ci/measurement_benchmark
```

Each pair writes its own `harness_manifest.json`; the output root also writes
`benchmark_run_manifest.json` so downstream tooling can discover the complete
artifact set without guessing filenames.
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
5. **Calibration stays Python-only**: Calibrated probabilities are artifacts and
  summaries, not new lean exports.

## Detailed Calibration Doc

For the full calibration contract, methods, fallback logic, artifact shape,
and calibrated shadow-governance behavior, see
[MEASUREMENT_CALIBRATION.md](MEASUREMENT_CALIBRATION.md).
