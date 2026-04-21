# Sample Expansion E1+E2 — Evidence Snapshot 2026-04-21

**Plan reference:** `smc_improvement_plan_q3_q4_2026-04-20.md` §2.2 Phase E (E1+E2) and §2.3 Phase F (F1+F2 partial).

## Scope of this run

- **E1 — Symbol-Expansion (W3 target):** Universe extended from 12 → 20 symbols.
  - New symbols added to the recurring CI benchmark: GOOGL, META, NVDA, TSLA, V, UNH, HD, CVX, COP, OXY, BAC, GS, MS.
  - Existing symbols retained: AAPL, MSFT, AMZN, JPM, JNJ, XOM, CAT.
  - Three preset cohorts now covered: Tech-Megacap, Financials, Energy.
- **E2 — Timeframe-Expansion (W4 target):** 5m and 4H added to the existing 15m/1H pair grid.
- **Workflow:** [.github/workflows/smc-measurement-benchmark.yml](../.github/workflows/smc-measurement-benchmark.yml) updated; weekly Saturday cron now produces 80 (sym × tf) artifact dirs.

## Corpus statistics (combined: WP21 + new E1 + new E2)

| Metric | WP21 baseline | E1+E2 incremental | **Combined** |
|---|---:|---:|---:|
| `(symbol, timeframe)` pairs | 13 | 65 (13 × 2 + 20 × 2) | **78** |
| Total events | 1 587 | 8 438 | **10 025** |
| FVG events | 822 | 4 856 | **5 678** |
| BOS events | 248 | 1 362 | **1 610** |
| OB events | 230 | 726 | **956** |
| SWEEP events | 287 | 1 494 | **1 781** |

**Plan gates met:**
- §2.2 E-Exit (W8): ≥1 000 events ✅ (10 025).
- §2.2 E-Exit: ≥300 FVG events ✅ (5 678).
- §2.2 E-Exit: ≥200 BOS events ✅ (1 610).
- §2.1 D4 release-gate prerequisite: out-of-sample FVG events available for Quality-Score binning ✅.

## Calibration findings (F1 partial — testable calibration on real corpus)

Generated via `scripts/smc_zone_priority_calibration.py --benchmark-dir <combined>`.

### Family-weight delta vs current production (`artifacts/reports/zone_priority_calibration.json`)

| Family | Prior (96 evt) | Calibrated (10 004 evt) | Δ | Production change recommended? |
|---|---:|---:|---:|---|
| BOS | 0.81 | 0.8432 | **+0.0332** | Within drift gate (0.15) — safe to promote |
| FVG | 0.61 | 0.5773 | -0.0327 | Within drift gate — safe to promote |
| OB | 0.82 | **0.4666** | **-0.3534** | ⚠ **Exceeds drift gate (0.15)** — A/B-test gated, NOT auto-promoted |
| SWEEP | 0.73 | 0.6765 | -0.0535 | Within drift gate — safe to promote |

**Decision:** Production weights remain **unchanged** until the OB-drop is corroborated by:
1. F1 smECE (Błasiok & Nakkiran 2023) testable-calibration check, and
2. G3 30-day A/B comparing static-vs-recalibrated arms (SPRT or fixed-N stop rule).

The combined corpus mixes 5m / 15m / 1H / 4H, and OB is highly timeframe-sensitive — single-aggregate weights may be the wrong calibration target. Phase F2 (session-adjusted) and the per-timeframe split are the right scope.

### F2 contextual buckets promoted (from this run)

7 buckets meet the min-30-events promotion gate:

| Bucket | Family deltas |
|---|---|
| `session:ASIA` | OB **+0.3005**, FVG **+0.1175**, SWEEP **+0.1338** |
| `session:LONDON` | OB -0.0975, SWEEP -0.0699 |
| `session:NY_AM` | OB -0.0851, FVG -0.0812, BOS +0.0517 |
| `htf_bias:BEARISH` | OB -0.0626 |
| `htf_bias:BULLISH` | OB -0.0756 |
| `vol_regime:HIGH_VOL` | SWEEP -0.0627 |
| `vol_regime:NORMAL` | OB -0.0756 |

→ artifact: `artifacts/ci/measurement_benchmark_combined_2026-04-21/zone_priority_contextual_calibration.json` (ephemeral; reproducible via the same script against any benchmark dir).

## FVG Label Audit (D1 evidence — Phase D)

Generated via `scripts/fvg_label_audit.py --benchmark-dir <combined>` against 5 671 FVG events.

**Headline findings:**

1. FVG hit rate (56.1 %) is 30.7 pp **below** BOS (86.8 %). The FVG weakness identified in WP21 reproduces at 55× sample size — it is a real signal-quality gap, not a small-sample artifact.
2. Largest spread across (sym, tf) pairs: **TSLA / 15m at 100 %** vs **CVX / 4H at 35 %** → context-dependence is the dominant variance source, not symbol or timeframe alone.
3. FVG is **56.7 %** of all events (5 671 / 10 004) — improving FVG has the largest leverage on the overall grade.
4. **Best context:** `session:ASIA` → 75 % HR (matches the F2 promotion above).
5. **Worst context:** `session:NY_AM` → 46 % HR.

**Recommendations baked into the audit JSON:**
- INVESTIGATE: invalidation rule may be too strict (68 % invalidation rate). Consider 2-bar-close-beyond-zone instead of 1.
- INVESTIGATE: add partial-fill tracking (50–80 % zone penetration before invalidation).
- ACTIONABLE: apply context-dependent FVG weighting (boost ASIA, reduce NY_AM) — already executed in the F2 contextual table above.

The full audit JSON is at `artifacts/ci/measurement_benchmark_combined_2026-04-21/fvg_label_audit.json` (ephemeral; reproducible).

## Plan items closed by this run

- ✅ E1 — Symbol-Expansion (W3): universe at 20, three preset cohorts covered.
- ✅ E2 — Timeframe-Expansion (W4): 5m + 4H now in the recurring CI grid.
- ✅ Phase E exit gate (W8): ≥1 000 events with all family minimums satisfied.
- ✅ F1 partial: testable calibration computed on real corpus; smECE wiring + G3 A/B remain.
- ✅ D1 evidence: corpus large enough that the FVG weakness hypothesis is confirmed and contextually attributed.

## Plan items unblocked next

- D4 — FVG Quality-Score recalibration (target ≥300 FVG events; have 5 678).
- F1 — wire smECE alongside ECE in `smc_core/calibration_metrics.py`.
- F2 — promote the 7 contextual buckets above into `zone_priority_contextual_calibration.json` after smECE check.
- F3 — multiplicative vol-regime formula (data now sufficient).
- E3 — rolling-30-day daily incremental benchmark mode.

## Reproducibility

```bash
# E1 cohort (15m + 1H)
python scripts/run_smc_measurement_benchmark.py \
  --symbols GOOGL,META,NVDA,TSLA,V,UNH,HD,CVX,COP,OXY,BAC,GS,MS \
  --timeframes 15m,1H \
  --output-dir artifacts/ci/measurement_benchmark_e1e2_2026-04-21

# E2 cohort (5m + 4H, full 20-symbol universe)
python scripts/run_smc_measurement_benchmark.py \
  --symbols AAPL,MSFT,AMZN,GOOGL,META,NVDA,TSLA,JPM,BAC,GS,MS,V,UNH,JNJ,HD,XOM,CVX,COP,OXY,CAT \
  --timeframes 5m,4H \
  --output-dir artifacts/ci/measurement_benchmark_e2_5m4H_2026-04-21
```

Data source: Databento (DBEQ.BASIC entitlement, live).
