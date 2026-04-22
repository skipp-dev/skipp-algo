# Appendix B — 4-Layer HTF-Stack-Validation

> Preprint subsection draft. Scaffolded under Addendum 2.8 Phase 3
> (`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md` §6).
> Final numbers + ADR pointer are filled in after the Q4 W13 A/B verdict.

## B.1 Motivation

The published SMC engine uses an ICT-standard 3-layer HTF trend stack
(4H / 1D / 1W) plus an adaptive IPDA dach-TF. Several community proposals
(Flux-style 7-TF stacks, FX killzone equivalents) raise the question whether
adding an intermediate 2H layer between Chart-TF and the published 4H layer
materially improves directional hit-rate without degrading calibration.

## B.2 Hypothesis

> *"Does the ≥1000-event sample justify a 4th trend layer (2H) in addition
> to the 4H / 1D / 1W stack?"*

We treat this as a one-sided two-arm A/B test:

| Arm        | HTF stack                  |
|------------|----------------------------|
| Baseline   | 4H · 1D · 1W (current)     |
| Candidate  | 2H · 4H · 1D · 1W (4-layer)|

Both arms run on the same event corpus; arm assignment is symbol-deterministic
via `scripts/smc_ab_experiment.py`.

## B.3 Statistical design

Wald SPRT on per-arm Bernoulli outcomes (`scripts/smc_sprt_stop_rule.py`):

* `H0: p = p0` (no improvement → keep 3-layer stack)
* `H1: p = p1` (uplift ≥ Δ → promote 4-layer stack)
* α = 0.05, β = 0.20, Δ = 3pp HR (matches G1 below)

A fixed-N fallback of 30 calendar days is supplied by the daily rolling
benchmark cron (`.github/workflows/smc-measurement-benchmark-rolling.yml`,
`30 7 * * *`).

## B.4 Promotion gates (cumulative; all three required)

Defined in `scripts/plan_2_8_q4_gate_evaluator.py` with the following
defaults (overridable via CLI flags):

| Gate | Requirement                                                       | Reference          |
|------|--------------------------------------------------------------------|--------------------|
| G1   | HR uplift ≥ 3pp in ≥ 2 of 3 context buckets (RTH/ETH × NORMAL/HIGH) | addendum §3.2 G1   |
| G2   | Brier regression ≤ 0.02 (no calibration degradation)               | addendum §3.2 G2   |
| G3   | ≥ 30 events per bucket post-promotion                              | Blasiok & Nakkiran 2023 (smECE floor) |

## B.5 Decision protocol

1. Operator builds the A/B bundle from the rolling-bench rollup
   (`scripts/plan_2_8_q4_gate_bundle_builder.py`).
2. Workflow `plan-2-8-q4-gate-dryrun` runs the evaluator and uploads
   `plan-2-8-q4-gate-verdict` (90-day retention).
3. Verdict is appended to `docs/DECISIONS.md` as ADR using
   `python scripts/plan_2_8_q4_gate_evaluator.py --format adr`.
4. On GO, `enable_trend_tf_0` default in `SMC_Core_Engine.pine` flips
   from `false` to `true` and per-family calibrated weights for the 2H
   layer are published in the next calibration refresh.
5. On NO-GO, the addendum cross-references the original
   *2026-04-21 — 3-layer HTF trend stack over Flux-style 7-TF bias* ADR
   and re-pins the deferral window (typically +26 weeks).

## B.6 Reproducibility notes

* Out-of-Sample corpus: `artifacts/ci/measurement_benchmark_2026-04-22_partial50_v3`
  (20 symbols × 4 TFs = 80 `scoring_<sym>_<tf>.json` artifacts, n=10 064 events).
* Phase E2 baseline (3-layer): 4H BOS HR=0.908 (n=119), 1H BOS HR=0.906
  (n=203), 5m FVG HR=0.549 (n=3 693), 1H FVG HR=0.644 (n=790).
* Source-of-truth runbook: `docs/plan_2_8_rollout_runbook.md`.
* All thresholds are pinned in
  `tests/test_plan_2_8_q4_gate_evaluator.py` to prevent silent drift.

## B.7 Result

*Filled in post-verdict.* Expected fields:

* Bundle hash, SPRT termination state (continue / accept-H1 / reject-H1),
  per-bucket HR/Brier/n table, per-gate pass/fail with margin,
  decision (GO / NO-GO / INSUFFICIENT_DATA), ADR slug.
