# SMC Measurement Baseline — 2026-04-17

## 1. Purpose

This document records the **first successful local measurement and gate
baseline** for the SMC Long-Dip Suite. It establishes observed metric ranges
from a real run, defines what this baseline proves and what it does NOT prove,
and sets the monitoring cadence for future runs.

## 2. Active Gates

| Gate | Status | Blocking? | Result |
|------|--------|-----------|--------|
| `provider_health` | **ok** | yes (hard) | All 12 pairs passed provider/artifact/smoke checks |
| `reference_bundle` | **ok** | yes (hard) | All 12 bundles built successfully |
| `publish_contract` | skipped | — | Skipped (`--skip-publish-contract`) — not relevant for local baseline |
| `measurement_lane` | **ok** | no (soft) | All 12 pairs scored, zero hard-blocking degradations |

## 3. Run Context

| Property | Value |
|----------|-------|
| Date | 2026-04-17T01:06 UTC |
| Branch | `main` @ `96e9972f` |
| Python | 3.13 (venv), pandas 2.3.3, pyarrow 23.0.1 |
| Runner | Local macOS (not CI) |
| Symbols | AAPL, MSFT, AMZN, JPM, JNJ, XOM |
| Timeframes | 15m, 1H |
| Pairs evaluated | 12 (6 × 2) |
| Bar source | `canonical_export_bundle` (production workbook 2026-04-05) |
| Structure artifact refresh | Pre-release refresh ran immediately before gate run |
| Gate runner | `scripts/run_smc_release_gates.py --skip-publish-contract` |
| Benchmark harness | `scripts/run_smc_measurement_benchmark.py` |

### Important: Conda vs. Venv Python

The initial runs failed with `bars_source_mode: none` because the terminal
used conda Python (`/opt/anaconda3/bin/python`) with pyarrow 19.0.0, which
could not read the production parquet files (error: `Repetition level histogram size mismatch`). The fix was to use venv Python (`~/.venv/bin/python`) with pyarrow 23.0.1. **CI uses the venv Python and is not affected.**

### Manifest Contamination Fix

The 15m/1H/4H/5m structure manifests were contaminated by a test run that
overwrote the `producer.upstream` path with a pytest temp directory. The
`run_smc_pre_release_artifact_refresh.py` script regenerated all 4 manifests
from the production workbook before the gate run.

## 4. Artifacts Produced

| Artifact | Path | Size |
|----------|------|------|
| Pre-release refresh report | `artifacts/ci/smc_pre_release_refresh.json` | 35 KB |
| Release gates baseline report | `artifacts/ci/smc_release_gates_baseline_report.json` | 77 KB |
| Benchmark run manifest | `artifacts/ci/measurement_benchmark/benchmark_run_manifest.json` | — |
| Benchmark summary CSV | `artifacts/ci/measurement_benchmark/benchmark_run_summary.csv` | — |
| Per-pair measurement summaries | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/measurement_summary_*.json` | 12 files |
| Per-pair benchmark JSONs | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/benchmark_*.json` | 12 files |
| Per-pair scoring JSONs | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/scoring_*.json` | 12 files |
| Per-pair reliability plots | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/reliability_*.html` | 12 files |
| Per-pair stratification plots | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/stratification_*.html` | 12 files |
| Refreshed structure manifests | `reports/smc_structure_artifacts/manifest_{5m,15m,1H,4H}.json` | 4 files |

## 5. Observed Metrics

### 5.1 Event Coverage

| Pair | Total Events | BOS | FVG | OB | SWEEP |
|------|-------------|-----|-----|----|-------|
| AAPL/15m | 21 | 4 | 7 | 4 | 6 |
| AAPL/1H | 21 | 4 | 7 | 4 | 6 |
| MSFT/15m | 17 | 3 | 7 | 4 | 3 |
| MSFT/1H | 17 | 3 | 7 | 4 | 3 |
| AMZN/15m | 25 | 3 | 10 | 7 | 5 |
| AMZN/1H | 25 | 3 | 10 | 7 | 5 |
| JPM/15m | 23 | 2 | 10 | 3 | 8 |
| JPM/1H | 23 | 2 | 10 | 3 | 8 |
| JNJ/15m | 21 | 5 | 7 | 2 | 7 |
| JNJ/1H | 21 | 5 | 7 | 2 | 7 |
| XOM/15m | 22 | 6 | 7 | 2 | 7 |
| XOM/1H | 22 | 6 | 7 | 2 | 7 |
| **Total** | **258** | **46** | **96** | **46** | **70** |

### 5.2 Scoring Metrics

| Pair | Brier | Cal. Brier | Cal. ECE | Hit Rate | Log Score |
|------|-------|-----------|----------|----------|-----------|
| AAPL/15m | 0.2473 | 0.2091 | 0.1407 | 0.6667 | 0.6878 |
| AAPL/1H | 0.2587 | 0.1833 | 0.1835 | 0.7619 | 0.7112 |
| MSFT/15m | 0.2573 | 0.1480 | 0.1154 | 0.6471 | 0.7084 |
| MSFT/1H | 0.2573 | 0.1745 | 0.1242 | 0.7059 | 0.7084 |
| AMZN/15m | 0.2884 | 0.1609 | 0.1390 | 0.8000 | 0.7718 |
| AMZN/1H | 0.2308 | 0.1355 | 0.0355 | 0.8400 | 0.6543 |
| JPM/15m | 0.2905 | 0.1324 | 0.1566 | 0.8261 | 0.7760 |
| JPM/1H | 0.2279 | 0.1584 | 0.0929 | 0.7826 | 0.6483 |
| JNJ/15m | 0.2701 | 0.1567 | 0.1402 | 0.8095 | 0.7345 |
| JNJ/1H | 0.2815 | 0.1841 | 0.1515 | 0.7619 | 0.7578 |
| XOM/15m | 0.2971 | 0.1763 | 0.1597 | 0.7727 | 0.7896 |
| XOM/1H | 0.2862 | 0.1995 | 0.1434 | 0.7273 | 0.7673 |

### 5.3 Summary Statistics

| Metric | Mean | Min | Max | Threshold |
|--------|------|-----|-----|-----------|
| Brier score | 0.2661 | 0.2279 | 0.2971 | ≤ 0.60 |
| Calibrated Brier | 0.1682 | 0.1324 | 0.2091 | ≤ 0.60 |
| Calibrated ECE | 0.1319 | 0.0355 | 0.1835 | ≤ 0.30 |
| Hit rate | 0.7585 | 0.6471 | 0.8400 | — |
| Log score | 0.7263 | 0.6483 | 0.7896 | ≤ 1.20 |
| Events/pair | 21.5 | 17 | 25 | ≥ 1 |

### 5.4 Gate Degradation Summary

| Degradation Type | Count |
|-----------------|-------|
| Hard-blocking degradations | **0** |
| Advisory degradations | **0** |
| Quality recommendation | `observable` (all 12 pairs) |
| Quality guardrail | `observable only` (all 12 pairs) |

## 6. What This Baseline Proves

1. The measurement and gate infrastructure **runs end-to-end** and produces
   structured, parseable, machine-readable artifacts.
2. All 3 active gates (`provider_health`, `reference_bundle`, `measurement_lane`)
   execute without errors across 6 representative symbols and 2 timeframes.
3. The scoring pipeline produces **real event-level metrics** from production
   structure artifacts and the canonical export bundle.
4. All calibrated metrics are **well within thresholds**: calibrated Brier
   scores are 2.2–3.4× below the 0.60 hard-block ceiling; calibrated ECE is
   1.6–8.5× below the 0.30 hard-block ceiling.
5. 258 total events across 4 event families (BOS, FVG, OB, SWEEP) were
   evaluated — enough for a meaningful initial signal.

## 7. What This Baseline Does NOT Prove

1. **Stability over time.** This is a single run. No regression detection is
   possible without ≥2 historical runs (`min_history_runs = 2`).
2. **CI reproducibility.** This run was executed locally (macOS). CI runners
   may differ in parquet library versions, available data, or timing.
3. **Full reference coverage.** Only 6 of 12 reference symbols and 2 of 4
   reference timeframes were evaluated. 5m and 4H are not included.
4. **Contextual calibration promotion.** The promotion policy requires
   `min_history_runs: 3` and `min_recommended_run_ratio: 0.67`. With 1 run,
   contextual calibration cannot be promoted.
5. **Event volume robustness.** 17–25 events per pair is above the `min_scoring_events: 1`
   floor but well below the soft-warn threshold of `min_event_coverage_ratio: 0.50`
   relative to a future larger baseline.
6. **Post-release validation.** The `post_release_validation` gate was not
   exercised (requires a post-release validation report artifact).
7. **Publish contract.** The `publish_contract` gate was skipped.

## 8. Follow-Up Cadence

### Required Next Steps

| Step | When | Purpose |
|------|------|---------|
| Run #2 (same symbols/TFs) | Within 7 days | Establish regression baseline (`min_history_runs: 2`) |
| Run #3 | Within 14 days | Enable contextual calibration promotion |
| Expand to 12 symbols × 4 TFs | After run #3 | Full reference coverage |
| CI run | Next `smc-deeper-integration-gates` or `smc-measurement-benchmark` workflow | Verify CI reproducibility |

### Steady-State Monitoring

| Cadence | Run Type | Trigger |
|---------|----------|---------|
| Every push to main | Fast PR gates | `smc-fast-pr-gates` workflow |
| Nightly (03:15 UTC) | Deeper integration + release gates | `smc-deeper-integration-gates` workflow |
| Weekly (Saturday 08:00 UTC) | Standalone measurement benchmark | `smc-measurement-benchmark` workflow |
| Every release | Full strict release gates | `smc-release-gates` workflow |

## 9. Monitoring Plan

### 9.1 Artifacts Per Run

Each gate/benchmark run produces:

| Artifact | Location | Retention |
|----------|----------|-----------|
| Gate report JSON | `artifacts/ci/smc_release_gates_report.json` | GitHub Actions artifact (90 days default) |
| Measurement summaries | `artifacts/ci/measurement/{SYM}/{TF}/*.json` | GitHub Actions artifact |
| Benchmark KPI CSV | `artifacts/ci/measurement_benchmark/benchmark_run_summary.csv` | GitHub Actions artifact |
| Reliability plots | `artifacts/ci/measurement_benchmark/{SYM}/{TF}/reliability_*.html` | GitHub Actions artifact |
| Evidence summary | `artifacts/ci/smc_evidence_summary.json` | GitHub Actions artifact |

### 9.2 Who Reads Them

| Consumer | What They Check | When |
|----------|-----------------|------|
| CI workflow | `overall_status != "fail"` → pass/fail | Automated |
| Release gate | Hard-blocking degradations → release blocked | Automated |
| Operator (pre-release) | Evidence summary readiness (GELB→GRÜN) | Manual before release |
| Operator (post-incident) | Metric regression detail for diagnosis | As needed |

### 9.3 Failure/Escalation Criteria

| Condition | Classification | Action |
|-----------|---------------|--------|
| `overall_status: fail` | **Blocking** | Release blocked. Investigate `failure_reasons`. |
| Hard-blocking degradation code fired | **Blocking** | Identify pair+metric. Do not weaken threshold. |
| `overall_status: warn` with advisory degradations | **Advisory** | Review, document, proceed with awareness. |
| `overall_status: ok` | **Nominal** | No action required. |
| No gate run in 7+ days | **Stale** | Trigger manual or nightly run. |

### 9.4 Threshold Reference

These thresholds are **not to be changed** without explicit governance review:

| Metric | Absolute Ceiling | Regression Ceiling | Baseline Observed |
|--------|------------------|--------------------|-------------------|
| Calibrated Brier | ≤ 0.60 | ≤ 0.08 from median | 0.132–0.209 |
| Calibrated ECE | ≤ 0.30 | ≤ 0.10 from median | 0.035–0.184 |
| Raw Brier | ≤ 0.60 | ≤ 0.08 from median | 0.228–0.297 |
| Raw Log Score | ≤ 1.20 | ≤ 0.20 from median | 0.648–0.790 |

---

_This is a single-run baseline. It must not be cited as proof of stability._
_The next run is required within 7 days to enable regression detection._
