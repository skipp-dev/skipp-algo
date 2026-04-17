# Gate Governance Promotion — Initial Formalization

**Date:** 2026-04-17
**Reviewer:** owner
**Scope:** All known measurement degradation codes

## Summary

Formalized the governance status of all measurement degradation codes
into the `GATE_GOVERNANCE_REGISTRY` in `smc_integration/release_policy.py`.

## Promotion Decisions

| Code | Status | Reason |
|------|--------|--------|
| MEASUREMENT_CALIBRATED_BRIER_ABOVE_THRESHOLD | HARD_BLOCKING | Core signal quality ceiling |
| MEASUREMENT_CALIBRATED_BRIER_REGRESSION | HARD_BLOCKING | Prevents silent calibration degradation |
| MEASUREMENT_CALIBRATED_ECE_ABOVE_THRESHOLD | HARD_BLOCKING | Calibration quality ceiling |
| MEASUREMENT_BRIER_ABOVE_THRESHOLD | ADVISORY | Early warning, raw metric |
| MEASUREMENT_LOG_SCORE_ABOVE_THRESHOLD | ADVISORY | Supplementary metric |
| MEASUREMENT_BRIER_REGRESSION | ADVISORY | Noisy with small samples |
| MEASUREMENT_LOG_SCORE_REGRESSION | ADVISORY | Noisy with small samples |
| MEASUREMENT_CALIBRATED_ECE_REGRESSION | SHADOW | Noise-susceptible; absolute ECE threshold is safety net |
| MEASUREMENT_EVENT_COVERAGE_LOW | EXCLUDED | Bootstrap deadlock avoidance |
| MEASUREMENT_STRATIFICATION_COVERAGE_LOW | ADVISORY | Quality signal, not blocking |
| MEASUREMENT_EVENT_COVERAGE_REGRESSION | ADVISORY | Baseline comparison, advisory |
| MEASUREMENT_STRATIFICATION_COVERAGE_REGRESSION | ADVISORY | Baseline comparison, advisory |

## What Was Not Changed

- No threshold values were modified.
- No new measurement methodology was introduced.
- The existing `HARD_BLOCKING_DEGRADATION_CODES` frozenset was preserved.
- The `classify_measurement_degradation_severity` function remains the runtime classifier.

## Audit Trail Format

Future promotions should follow this format:
1. Date and reviewer
2. Which code(s) changed status
3. Old status → new status
4. Evidence reference (benchmark reports, stability data)
5. Explicit confirmation that no thresholds were changed
