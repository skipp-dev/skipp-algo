# Measurement Calibration — v5.5b+

**Status**: Active  
**Date**: 2026-04-04

## Purpose

This document describes the Python-only calibration lane that now sits on top
of the existing SMC measurement/scoring artifacts.

The goal is simple:

1. keep the current lean surface and Pine runtime unchanged,
2. turn scored-event probabilities into explicitly calibrated probabilities,
3. persist the before/after evidence in versionable artifacts,
4. expose the same information by `session`, `htf_bias`, and `vol_regime`.

This is an additive measurement feature, not a second decision surface.

## What Is Calibrated Today

The current measurement lane now prefers event-level
`ScoredEvent.raw_score = SIGNAL_QUALITY_SCORE` whenever the measurement-evidence
path provides complete coverage for the scored event set.

That means BOS, OB, FVG, and SWEEP evidence now typically calibrates against:

- `raw_score_0_100` sourced from event-local `SIGNAL_QUALITY_SCORE`

The scoring contract still keeps the previous fallback path active for partial
coverage or non-measurement producers:

- `predicted_prob` — automatic fallback when raw-score coverage is incomplete

In other words: calibration now runs directly on the product's composite score
when measurement evidence can reconstruct the event-local SQ surface, while the
schema remains backward-compatible.

## Contextual / Regime-Adjusted Calibration

The scoring lane now also computes a second additive view: contextual
calibration adjusted per context dimension.

Today that view is emitted for:

- `session`
- `htf_bias`
- `vol_regime`

Mechanically this means:

1. keep the aggregate raw input series as the baseline,
2. fit one calibrator per populated group inside the chosen dimension,
3. apply those group-local calibrators back onto the same event set,
4. compare the adjusted aggregate Brier / Log / ECE against the raw baseline.

This does **not** change the live runtime. It is a measurement-only answer to:

- Does `session`-specific calibration outperform one global mapping?
- Does `HIGH_VOL` require a different mapping than `NORMAL`?
- Is one context dimension consistently the best calibration partition?

The scoring artifact stores the full per-dimension contextual summary; compact
manifests and bundle summaries store a reduced summary with:

- `dimensions_present`
- `improved_dimensions`
- `best_dimension_by_adjusted_brier`
- `best_dimension_by_adjusted_ece`

The evidence collector now also turns that descriptive output into two
operator-facing policy layers:

- `contextual_calibration_recommendation` — current-run preferred dimension
- `contextual_calibration_promotion` — whether that recommendation is stable
  enough across history to matter for governance

## Aggregate Calibration Path

Aggregate calibration is computed inside [smc_core/scoring.py](../smc_core/scoring.py).

### Preferred path

- Method: `platt_scaling`
- Input: scored-event probabilities
- Sample floor: currently 20 events with both classes present
- Fitting: regularized logistic mapping on `logit(predicted_prob)`

The preferred path produces:

- `calibrated_brier_score`
- `calibrated_log_score`
- `raw_ece`
- `calibrated_ece`
- deltas versus the raw probabilities
- reliability bins with raw mean, observed rate, and calibrated mean

### Safe fallback

When sample size or class balance is insufficient, the lane degrades to:

- Method: `beta_bin`
- Behavior: equal-width probability bins with Beta(1,1) shrinkage

This fallback was chosen deliberately because it is:

- deterministic,
- dependency-free,
- robust on small sample sizes,
- explicit about uncertainty instead of silently pretending precision.

## Stratified Calibration

The scoring lane now persists calibration summaries for the following
dimensions when event context is available:

- `session`
- `htf_bias`
- `vol_regime`

The event context is attached during measurement-evidence construction in
[smc_integration/measurement_evidence.py](../smc_integration/measurement_evidence.py).

Each dimension records:

- present groups
- populated groups
- a calibration summary per group

This means the operator can now answer questions like:

- Is the probability mapping weaker in `NY_AM` than in `LONDON`?
- Does `HIGH_VOL` materially degrade calibration quality?
- Does one HTF-bias bucket drift faster than the others?

## Artifact Contract

Calibration is persisted in three places.

### 1. Scoring artifact

File pattern:

- `scoring_{symbol}_{tf}.json`

New sections:

- `calibration`
- `stratified_calibration`

The `calibration` block contains the full aggregate summary including bins and
parameter metadata. The `stratified_calibration` block stores grouped summaries
by dimension.

### 2. Measurement manifest

File:

- `measurement_manifest.json`

The manifest keeps a compact hand-off view under:

- `quality_summary.calibration`
- `quality_summary.stratified_calibration`

This is intentionally smaller than the full scoring artifact and is meant for
evidence aggregation and release-gate reporting.

### 3. Pair summary / bundle summary

The benchmark harness and snapshot bundle summaries now surface the same
information in compact form so downstream tools do not need to read the full
scoring artifact first.

### 4. Evidence summary

`scripts/collect_smc_gate_evidence.py` now derives contextual recommendation
and promotion state from the per-dimension contextual details.

Per pair, the latest entry can now include:

- `contextual_calibration_recommendation`
- `contextual_calibration_promotion`

At the measurement-history level the evidence summary also exposes:

- `contextual_recommendation_policy`
- `contextual_promotion_policy`
- `pairs_with_contextual_recommendation`
- `pairs_ready_for_contextual_promotion`
- `contextual_recommendations_detected`
- `contextual_promotions_ready`

This keeps the contextual-calibration lane in the evidence/governance surface
without making it a live Pine runtime dependency.

## Reliability Plot Behavior

The benchmark harness still writes:

- `reliability_{symbol}_{tf}.html`

The plot now overlays:

- ideal calibration diagonal
- raw reliability trace
- calibrated reliability trace when calibration changes the mapping

The plot title also includes the active calibration method and the aggregate
ECE improvement when available.

## Why This Does Not Violate v5.5b Architecture

This implementation stays inside the existing architectural guardrails:

- no new lean fields
- no Pine runtime expansion
- no parallel interpretation layer in the indicator
- measurement-only evidence, artifacts, and operator summaries

The live decision surface remains:

- Lifecycle + Signal Quality + Event State + Bias + Warnings

Calibration only improves the measurement lane around that surface.

## Shadow Governance

Warn-only measurement governance now also tracks calibrated metrics in
[smc_integration/release_policy.py](../smc_integration/release_policy.py):

- `calibrated_brier_score`
- `calibrated_ece`

Both are checked against conservative absolute thresholds and, when enough
history exists, against historical medians. This keeps calibration observable
in CI without introducing a second live decision surface.

When sufficient history exists, the calibrated absolute thresholds are also
tightened automatically from that history:

- `max_calibrated_brier_score`
  becomes `min(configured_ceiling, historical_median + calibrated_brier_regression_slack)`
- `max_calibrated_ece`
  becomes `min(configured_ceiling, historical_median + calibrated_ece_regression_slack)`

This means the absolute warn threshold becomes stricter over time instead of
staying permanently anchored to the original conservative ceiling.

## Contextual Recommendation And Promotion

Contextual calibration is now no longer just descriptive. The release-policy
layer evaluates whether one dimension is strong enough to recommend and whether
that recommendation is stable enough to promote.

### Recommendation policy

The current run receives a preferred dimension only when a candidate dimension
has enough support and enough actual improvement.

Current recommendation gates include:

- minimum scored-event count
- minimum coverage ratio
- minimum populated groups
- minimum delta improvement in Brier or ECE
- maximum fallback-event ratio

When multiple dimensions remain eligible, the policy prefers:

- the dimension that wins both adjusted-Brier and adjusted-ECE best-dimension votes
- otherwise the strongest combined improvement / coverage ranking

### Promotion policy

Promotion is intentionally stricter than recommendation.

The current default policy requires:

- enough total history runs
- enough runs with an actual recommendation
- metric consensus on the current run
- a minimum fraction of recommendation-eligible runs selecting the same dimension

This keeps contextual calibration in a shadow-governance posture until the
preferred dimension is not just locally better, but historically stable.

## Operational Reading Guide

When inspecting a new run, read the values in this order:

1. `brier_score` / `log_score`
2. `calibration.calibrated_brier_score` / `calibration.calibrated_log_score`
3. `calibration.raw_ece` / `calibration.calibrated_ece`
4. `stratified_calibration.dimension_group_counts`
5. group-level summaries for the dimensions that matter in the current market

If calibrated metrics are meaningfully better than raw metrics, the current
probability mapping benefits from post-hoc calibration.

If one stratum is consistently worse than the aggregate, that stratum is the
right place for the next calibration or regime-adjustment experiment.

## Local Reproduction

Aggregate and stratified calibration are emitted automatically by the existing
benchmark harness:

```bash
python scripts/run_smc_measurement_benchmark.py \
  --symbols AAPL,MSFT \
  --timeframes 15m,1H \
  --output-dir artifacts/ci/measurement_benchmark
```

Then inspect:

- `scoring_{symbol}_{tf}.json`
- `measurement_summary_{symbol}_{tf}.json`
- `reliability_{symbol}_{tf}.html`

To inspect how the contextual recommendation behaves across the collected
history window, first build an evidence summary and then analyze it:

```bash
python scripts/collect_smc_gate_evidence.py \
  --input-glob "artifacts/ci/smc_*_report.json" \
  --output artifacts/ci/smc_evidence_summary.json

python scripts/analyze_smc_contextual_calibration_history.py \
  --input artifacts/ci/smc_evidence_summary.json \
  --output artifacts/ci/smc_contextual_history_analysis.json \
  --markdown-output artifacts/ci/smc_contextual_history_analysis.md \
  --pair-summary-csv artifacts/ci/smc_contextual_history_pairs.csv
```

The resulting analysis summarizes, across all measurement-history rows:

- how often each dimension was recommended
- how often each dimension was promotion-ready
- which pairs switch recommendation over time
- which latest pair recommendations are still not promotion-ready

Optional secondary outputs make the result easier to consume operationally:

- `--markdown-output` writes a compact review document with headline counts,
  dimension distribution, and flagged pairs
- `--pair-summary-csv` writes one flat row per pair for filtering and sorting in
  spreadsheets

## Recommended Next Step

The next high-value follow-up is narrower now that recommendation and
promotion are implemented:

- review the default recommendation thresholds on real history windows
- decide whether promotion-ready dimensions should influence dashboard emphasis
- evaluate whether specific `session` or `vol_regime` buckets warrant separate
  live dashboard diagnostics