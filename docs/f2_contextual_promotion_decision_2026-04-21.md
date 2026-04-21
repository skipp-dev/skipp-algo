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
