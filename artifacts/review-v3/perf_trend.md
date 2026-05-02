# v3-Phase-5 — Larger-Runner Performance Trend

**Generated:** 2026-05-01  
**Cutoff:** Phase-5 merge commit `573863c5` (2026-04-30 21:02 UTC) — workflows flipped from `ubuntu-latest` to `${ vars.SMC_GH_HOSTED_RUNNER || 'ubuntu-latest-m' }`.  
**Sample window:** last 60 successful runs per workflow (gh run list).  
**Metric:** wallclock = `updatedAt − createdAt` (includes queue + job time).  

## Summary table

| Workflow | n before | n after | median before | median after | Δ | % change |
|---|---:|---:|---:|---:|---:|---:|
| `c13-daily-cron.yml` | 3 | 0 | 47s | — | — | — |
| `phase-b-promotion-readiness.yml` | 0 | 0 | — | — | — | — |
| `smc-measurement-benchmark-rolling.yml` | 2 | 0 | 1.3m | — | — | — |
| `smc-measurement-benchmark.yml` | 5 | 0 | 1.1m | — | — | — |
| `run-open-prep-daily.yml` | 5 | 0 | 3.4m | — | — | — |
| `open-prep-outcome-backfill.yml` | 1 | 0 | 1.6m | — | — | — |
| `feature-importance-daily.yml` | 8 | 0 | 34s | — | — | — |
| `fvg-quality-recal-shadow-daily.yml` | 5 | 0 | 1.4m | — | — | — |
| `f2-promotion-gate-daily.yml` | 7 | 0 | 37s | — | — | — |
| `regime-stratification-validation.yml` | 1 | 0 | 1.3m | — | — | — |
| `plan-2-8-q4-gate-dryrun.yml` | 0 | 0 | — | — | — | — |
| `smc-databento-production-export.yml` | 0 | 0 | — | — | — | — |
| `smc-deeper-integration-gates.yml` | 60 | 0 | 16.1m | — | — | — |
| `smc-library-refresh.yml` | 32 | 0 | 27.8m | — | — | — |

## Aggregate (workflows with ≥5 runs both sides)

- _Insufficient post-cutoff samples (≥5) yet; revisit after more cron cycles._

## Notes

- Negative % change = faster on `ubuntu-latest-m`.
- Wallclock includes queue time, so a regression here can also reflect larger-runner pool starvation rather than the job itself.
- Workflows with `n after < 5` should be re-sampled in the next monthly Phase-5 review.
- Pre-cutoff runs that already used the canonical line (the original 3 workflows: `smc-databento-production-export`, `smc-deeper-integration-gates`, `smc-library-refresh`) compare two `ubuntu-latest-m` regimes against each other — expect ≈0% change for those.

## Reproduce

```bash
.venv/bin/python scripts/phase5_perf_trend.py
```

