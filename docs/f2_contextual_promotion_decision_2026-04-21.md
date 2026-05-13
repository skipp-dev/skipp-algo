# F2 Contextual Calibration — Promotion Decision Memo 2026-04-21

**Plan reference:** `smc_improvement_plan_q3_q4_2026-04-20.md` §2.3 F2 ("Session-adjusted Zone Priority") and §2.4 G3 (30-day A/B stopping rule).

## State

- Corpus: `artifacts/ci/measurement_benchmark_combined_2026-04-21/` — 10 025 events across 78 (symbol, timeframe) pairs (Databento live).
- Calibration script produced `zone_priority_contextual_calibration.json` with **7 buckets** that clear the 30-event promotion floor.

## The 7 promoted buckets (observed hit-rates vs global)

Global weights on this corpus: OB 0.4666, FVG 0.5773, BOS 0.8432, SWEEP 0.6765.

| Bucket | Family | n | Observed HR | Calibrated (0.3 smoothing) | Δ vs global |
|---|---|---:|---:|---:|---:|
| `session:ASIA` | OB | 48 | 0.8958 | 0.7671 | **+0.3005** |
| `session:ASIA` | FVG | 102 | 0.7451 | 0.6948 | +0.1175 |
| `session:ASIA` | SWEEP | 68 | 0.8676 | 0.8103 | +0.1338 |
| `session:LONDON` | OB | 278 | 0.3273 | 0.3691 | -0.0975 |
| `session:LONDON` | SWEEP | 274 | 0.5766 | 0.6066 | -0.0699 |
| `session:NY_AM` | OB | 626 | 0.3450 | 0.3815 | -0.0851 |
| `session:NY_AM` | FVG | 2 662 | 0.4613 | 0.4961 | -0.0812 |
| `session:NY_AM` | BOS | 772 | 0.9171 | 0.8949 | +0.0517 |
| `htf_bias:BEARISH` | OB | 464 | 0.3772 | 0.4040 | -0.0626 |
| `htf_bias:BULLISH` | OB | 488 | 0.3586 | 0.3910 | -0.0756 |
| `vol_regime:HIGH_VOL` | SWEEP | 46 | 0.5870 | 0.6138 | -0.0627 |
| `vol_regime:NORMAL` | OB | 912 | 0.3586 | 0.3910 | -0.0756 |

## Why these are NOT auto-promoted to production

1. **Global OB weight drifts -0.3534 from the pinned prior (0.82 → 0.4666)**, which exceeds the 0.15 drift-gate the script enforces on deliberate promotion (`--check-drift 0.15` in the weekly workflow).
2. The per-bucket calibrated weights are computed against those drifted global weights, so every bucket inherits the same drift signal. Promoting them would compound the drift.
3. Plan §2.4 G3 requires a **30-day A/B with SPRT or fixed-N stopping rule** before any Brier/ECE-based weight change lands in production — that A/B has not yet been run.
4. F1 smECE = 0.1349 is high enough to indicate the classifier is **not yet calibrated on this corpus** (plan §2.3 target is ECE ≤ 0.03 by Q4 end). Promoting bucket weights on top of a miscalibrated base would lock in a bad zero-point.

## Why the findings *are* still actionable

- `session:ASIA` shows a coherent, strong, and directionally **agreeing** signal across all four families (every family's HR is above its global HR, OB dramatically so). This is the single strongest evidence in the corpus for a genuine regime-shift effect, not noise.
- `session:NY_AM` FVG underperformance (-0.0812 at n = 2 662) corroborates the D1 FVG Label Audit's headline finding and is the single largest actionable lever for overall system HR.
- Direction of every promoted bucket is **consistent** with trading intuition (ASIA thin books → clean sweeps; NY_AM chop → FVG partial-fills).

## Next actions (order matters)

1. **D4 FVG Quality-Score recalibration** first — lifts FVG base HR with no global-weight change, reducing the magnitude of every F2 bucket delta that follows.
2. **G3 A/B plumbing** — reuse `scripts/smc_ab_experiment.py` + `scripts/run_ab_comparison.py` (already in the tree from OV7) to register an experiment spec `{ arm_A: static_global_weights, arm_B: contextual_weights + quality_score }` with SPRT stop rule.
3. **Run arm_B on the rolling-30-day benchmark** (new `smc-measurement-benchmark-rolling.yml`, landed this session) for 30 calendar days.
4. **Only after SPRT declares significance**: update `artifacts/reports/zone_priority_calibration.json` + write the first real `artifacts/reports/zone_priority_contextual_calibration.json` and let `scripts/generate_smc_micro_profiles.py` emit the updated Pine exports.

## Reproducibility

```bash
python scripts/smc_zone_priority_calibration.py \
  --benchmark-dir artifacts/ci/measurement_benchmark_combined_2026-04-21 \
  --output-path artifacts/ci/measurement_benchmark_combined_2026-04-21/zone_priority_calibration.json
```

Outputs: `zone_priority_calibration.json` (+ testable_calibration block), `zone_priority_contextual_calibration.json`, `zone_priority_calibration.md`.

## 2026-04-23 — G3 Dual-Arm Wiring Operationalized

The promotion-gate workflow (`f2-promotion-gate-daily.yml`) had been
exiting `status=skipped` every day because the rolling-bench workflow
emits a single-arm artifact tree but the gate expects two parallel
arms (`artifacts/ci/f2/{static_global_weights,contextual_weights}/<DATE>/`).
This PR closes that gap **without** running the harness twice.

### What landed

- New post-processor `scripts/f2_apply_contextual_calibration.py`
  reads each pair's per-event JSONL ledger
  (`events_<SYMBOL>_<TF>.jsonl`, schema `EVENT_LEDGER_SCHEMA_VERSION = 1.0`)
  and re-scores every event twice in-place:
  - **control arm** — `predicted_prob` blended with the family's
    *global* calibrated weight from `zone_priority_calibration.json`.
  - **treatment arm** — `predicted_prob` blended with the family's
    *contextual* weight resolved through
    `resolve_contextual_weight()` (session → vol_regime → global →
    default).
  Both arms run through the *same* blending transform so the SPRT
  delta isolates the context dimension, not the blending function.
- Blending formula (default, `--blend-mode anchor`):

      p_blended = clip(0.5 + (base - 0.5) + alpha*(w - 0.5), 0.05, 0.95)

  with `alpha = 1.0`. Additive Bayesian-prior shift (Dawid 1982 /
  Platt 1999) — preserves the directional signal coming out of
  `_directional_probability` while folding in the family hit-rate.
- Workflow `smc-measurement-benchmark-rolling.yml` gains a new
  fail-soft step that invokes the post-processor and a new
  `f2-dual-arm-<DATE>` upload-artifact.
- Workflow `f2-promotion-gate-daily.yml` gains a fail-soft
  `gh run download` step that pulls the dual-arm artifact from the
  most-recent rolling-bench run on `main`. The locate step is
  unchanged — `status=skipped` now only fires on a real download
  failure.

### Causal-correctness invariants

- The `outcome` label is **never** rewritten — only `predicted_prob`
  is mutated, so this path cannot leak look-ahead.
- The post-processor can never mark the rolling-bench run failed
  (`exit 0` even on rc=2 / rc=1).
- An empty `promoted_buckets` set causes the treatment arm to fall
  back to global weights → arms become byte-identical → gate
  correctly converges to `insufficient_data`. Pinned by
  `tests/test_f2_apply_contextual_calibration.py::test_empty_promoted_buckets_make_treatment_equal_to_control`.

### Determinism

The post-processor is byte-stable across reruns:
- `generated_at = 0.0` in all emitted JSON,
- `artifact_dir` is relative to the arm root (no absolute paths),
- `json.dumps(..., sort_keys=True, indent=2)` everywhere.
Pinned by
`tests/test_f2_apply_contextual_calibration.py::test_post_processor_is_byte_deterministic`.

### Expected 30-day countdown

The first rolling-bench run on `main` after this PR merges will
publish `f2-dual-arm-<DATE>`. The next 10:00 UTC promotion-gate run
will then exit with `decision ∈ {insufficient_data, hold, promote, rollback}` instead of `status=skipped`.

> ### 2026-04-23 follow-up — countdown does NOT start with this PR
>
> A pre-merge audit of the dual-arm chain found three statistical
> defects that make the *first* set of dual-arm Brier/ECE deltas
> meaningless as a basis for a `promote` decision:
>
> 1. **In-sample leakage (C1, A1).** The treatment arm reads
>    `zone_priority_contextual_calibration.json` that is fit from
>    the same per-event ledger the post-processor then re-scores.
>    Brier-delta is therefore a structural overfit, not a forecast
>    of out-of-sample lift. Resolved by PR #43 (Frozen Treatment
>    Artifact: a one-time fit from `combined_2026-04-21` plus an
>    explicit timestamp filter, `status="shadow"` until promote).
> 2. **Single-arm SPRT vs fixed `p0=0.55` (C2, A2).** The current
>    `_sprt_decision()` tests `treat.hit_rate` against a fixed
>    `p0=0.55`; it never compares treatment to control. Combined
>    with `hit_rate ≡ outcome_mean` from `_summarize_scored_events`,
>    the SPRT decision is mathematically independent of the
>    contextual weights. Resolved by PR #44 (paired Brier-delta
>    Gaussian-SPRT: `d_i = (p_treat_i − y_i)² − (p_ctrl_i − y_i)²`,
>    one-sided, with `event_id` + `outcome` paired-equivalence pin).
> 3. **SPRT terminates in a single day (C3, A3).** With ~1.6k
>    events/day vs `max_n=600`, SPRT converges to accept/reject in
>    one run, so a hit-rate sitting in `[0.56, 0.59]` would loop on
>    `insufficient_data` indefinitely without any 30-day window
>    actually elapsing. Resolved by PR #44 (cross-day SPRT state at
>    `artifacts/ci/f2/sprt_state.json` so the trial state persists
>    between daily runs).
>
> Operational guard while #43/#44 are open: the spec ships at
> `status="plumbing_only"`. Both `scripts/f2_run_promotion_gate.py`
> and `scripts/f2_promote_contextual_weights.py` refuse to surface
> `decision="promote"` (the gate coerces to `hold`; the promoter
> raises `ValueError` and the CLI exits 1) until the spec is
> flipped to `status="live"` as part of PR #44. The
> rolling-bench plumbing keeps running daily so we accumulate
> operator telemetry, but the **real 30-day SPRT countdown only
> starts after PR #44 lands**.


<a id="regeneration-recipe"></a>

## Regeneration recipe (PR #43 frozen artifact, Option C)

This recipe is referenced by `frozen_provenance.regeneration_instructions` in
both `artifacts/reports/zone_priority_calibration.json` and
`artifacts/reports/zone_priority_contextual_calibration.json`. The recipe
is the **authoritative** way to re-derive a frozen artifact for audit;
running these steps on the same `source_commit` against a corpus whose
`benchmark_run_manifest.json` matches `benchmark_manifest_sha256` MUST
produce byte-identical JSON outputs (modulo the `generated_at` and
`frozen_at` timestamps).

### Prerequisites

- Databento Python client installed and authenticated
  (`DATABENTO_API_KEY` env var or `~/.databento/credentials`)
- Working tree at `source_commit` recorded in the existing artifact's
  `frozen_provenance.source_commit`
- Disk space for the corpus (~200 MB for 90 days, ~10 k events)

### Step 1 — Pull the corpus

```bash
# Replace <START> / <END> with the dates from frozen_provenance
# (or pick a fresh 90-day window for a re-calibration).
python scripts/run_smc_measurement_benchmark.py \
  --output-dir artifacts/ci/measurement_benchmark_combined_<END> \
  --start-date <START> --window-days 90 \
  --symbols <SYMBOL_LIST> --timeframes 5m,15m
```

Inputs to record after the run completes:

| Field | How to get it |
|---|---|
| `benchmark_manifest_sha256` | `shasum -a 256 artifacts/ci/measurement_benchmark_combined_<END>/benchmark_run_manifest.json` |
| `n_events` | `jq '.n_events // .total_events' artifacts/ci/measurement_benchmark_combined_<END>/benchmark_run_manifest.json` |
| `max_event_timestamp_utc` | `jq -r '.max_event_timestamp_utc // .end_date' …/benchmark_run_manifest.json` |

### Step 2 — Run frozen calibration

```bash
python scripts/smc_zone_priority_calibration.py \
  --benchmark-dir artifacts/ci/measurement_benchmark_combined_<END> \
  --output-path artifacts/reports/zone_priority_calibration.json \
  --smoothing 0.3 \
  --frozen \
  --status shadow \
  --frozen-at <ISO_UTC_NOW> \
  --corpus-manifest-hash <SHA_FROM_STEP_1>
```

Defaults:
- `--status shadow` — required initial state. Promotion to
  `production` is a separate, governed event (see "Promotion to
  production" below).
- `--smoothing 0.3` — must match prior frozen runs; changing this
  invalidates SPRT comparisons.
- `--frozen-at` — defaults to `now()` when omitted; pin it explicitly
  for reproducibility.

### Step 3 — Verify outputs

```bash
ls -1 artifacts/reports/zone_priority_*calibration*.json
jq '.frozen_provenance' artifacts/reports/zone_priority_contextual_calibration.json
jq '.promoted_buckets | length' artifacts/reports/zone_priority_contextual_calibration.json
```

Expected:
- Two `*_calibration.json` files plus their `*.md` siblings
- `frozen_provenance` block populated in both JSONs (status=shadow,
  matching `benchmark_manifest_sha256` and `source_commit`)
- `promoted_buckets` length > 0 (at least the global weights must promote;
  bucket count depends on corpus volume)

### Step 4 — Commit

Commit only the four files under `artifacts/reports/`:

```bash
git add artifacts/reports/zone_priority_calibration.json \
        artifacts/reports/zone_priority_calibration.md \
        artifacts/reports/zone_priority_contextual_calibration.json
git commit -m "data(f2): regenerate frozen contextual calibration artifact (corpus <START>–<END>)"
```

Do **NOT** commit the `artifacts/ci/measurement_benchmark_combined_<END>/`
corpus — it is reproducible from Databento (see
[docs/sample_expansion_e1_e2_evidence_2026-04-21.md](sample_expansion_e1_e2_evidence_2026-04-21.md)
for why corpus dirs are intentionally ephemeral).

### Promotion to production

Flipping `frozen_provenance.status` from `shadow` to `production`
requires a separate calibration run with `--status production` after
the SPRT in `f2_run_promotion_gate.py` has signaled significance over
≥30 calendar days against the new corpus. Do not hand-edit the
JSONs — re-run the script.

### Why Option C is temporary

This recipe is currently the only path to regenerate the artifact and
is documented as a permanent record-of-process. The follow-up
[issue #43](https://github.com/skippALGO/skipp-algo/issues/43) tracks
moving regeneration into a `workflow_dispatch`-only GitHub Actions
workflow (`f2-frozen-artifact-bootstrap.yml`) so future re-calibrations
do not require operator-local Databento setup.
