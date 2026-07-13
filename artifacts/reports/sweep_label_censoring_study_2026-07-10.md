# SWEEP label censoring study

Source workflow run: `29130315241`
Corpus era: Historical pre-fix corpus: run completed 2026-07-10 before the full-horizon edge-censoring guard in #3591 landed on 2026-07-13; current v2 emissions skip truncated windows.
Joined SWEEP events: **52 / 52**
Forward-window timeframe alignment: **46 match, 6 mismatch, 0 unknown**.

## Result

| Scope | Censored | Unresolved negatives | Observed hit rate | Identified hit-rate interval |
|---|---:|---:|---:|---:|
| As emitted, canonical bars 1–8 | 33/52 (63.5%) | 7 (13.5%) | 80.8% | [80.8%, 94.2%] |
| As emitted, late bars 4–8 | 33/52 (63.5%) | 21 (40.4%) | 50.0% | [50.0%, 90.4%] |
| Aligned-only, canonical bars 1–8 | 27/46 (58.7%) | 7 (15.2%) | 78.3% | [78.3%, 93.5%] |
| Aligned-only, late bars 4–8 | 27/46 (58.7%) | 21 (45.7%) | 43.5% | [43.5%, 89.1%] |

A negative label from a partial horizon is counted as unresolved, not silently corrected. The upper bound asks what the hit rate would be if every unresolved negative later hit.
Aligned-only excludes rows whose forward timestamps imply a different timeframe.

## Dependence

- `censored`: symbol as-emitted ICC=-0.062, k=19; symbol aligned-only ICC=-0.188, k=19; timeframe forward-window timeframe provenance is incomplete or mismatched.
- `canonical_hit`: symbol as-emitted ICC=0.113, k=19; symbol aligned-only ICC=0.006, k=19; timeframe forward-window timeframe provenance is incomplete or mismatched.
- `canonical_unresolved_negative`: symbol as-emitted ICC=-0.067, k=19; symbol aligned-only ICC=-0.179, k=19; timeframe forward-window timeframe provenance is incomplete or mismatched.

## Confidence intervals

Deterministic 95% percentile intervals for the canonical censoring rate:

- `iid`: [50.0%, 75.0%] (2000 replicates).
- `symbol_cluster`: [50.0%, 75.0%] (2000 replicates).
- `timeframe_cluster`: unavailable — forward-window timeframe provenance is incomplete or mismatched.
- `symbol_timeframe_two_way`: unavailable — forward-window timeframe provenance is incomplete or mismatched.
- `symbol_cluster` (aligned-only): [46.8%, 69.8%] (2000 replicates).

Shadow-feature availability in this corpus: `{'sweep_trap_quality_score': 0, 'sweep_trap_outcome_late_boolean': 0, 'reaction_schema_version': 0, 'reaction_outcome_late_boolean': 0}`. Therefore Brier/lift confidence intervals for the new shadow scores remain unmeasured rather than inferred from legacy rows.

## Limitations

- Single workflow-run corpus; no stationarity claim.
- Identified hit-rate bounds are not an imputation model.
- Cluster bootstrap covers symbol/timeframe dependence, not serial dependence across runs.
- Shadow-feature Brier/lift intervals require ledgers emitted with the shadow flags enabled.
- Timeframe ICC and timeframe/two-way bootstrap intervals are withheld because forward-window timestamps do not consistently match the ledger timeframe.
- The aligned-only sensitivity subset cannot recover cross-timeframe evidence; it only removes rows with invalid timeframe provenance.
