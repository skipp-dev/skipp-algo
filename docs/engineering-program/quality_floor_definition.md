# Quality Floor Definition

Stand: 2026-04-18 (F-14 / WP-9)

## Purpose

This document formalizes what "calibrated", "production-grade", and "minimally
acceptable" mean in the SMC measurement system.  It provides concrete,
machine-enforceable quality tiers so that release gates, dashboards, and
operator decisions can reference a single source of truth.

## Quality Tiers

| Tier | Brier ≤ | ECE ≤ | Min Events | Meaning |
|---|---|---|---|---|
| `production_grade` | 0.25 | 0.15 | 20 | Fully calibrated, safe for autonomous gating |
| `acceptable` | 0.40 | 0.25 | 8 | Usable for advisory signals, not yet autonomous |
| `minimal` | 0.60 | 0.30 | 1 | Meets shadow-lane thresholds, barely passable |
| (below minimal) | > 0.60 | > 0.30 | 0 | Fails quality floor — blocks or degrades |

### Interpretation

- **production_grade**: The measurement lane has enough events and low enough
  error to be treated as a reliable gating signal.  Contextual calibration
  may be promoted.  Trust tier can reach `high`.
- **acceptable**: Measurement is informative but sample size or error prevents
  full trust.  Trust tier stays at `guarded` unless other signals elevate it.
- **minimal**: System is bootstrapping or data is sparse.  Shadow thresholds
  pass but no calibration confidence can be stated.

## Bootstrap Confidence Intervals

Measurement evidence now includes 95% bootstrap confidence intervals for
Brier and ECE scores.  These are computed with 1000 resamples and use the
percentile method (`2.5th` / `97.5th`).

A tier assignment is considered **firm** when the upper bound of the CI falls
within the same tier.  When the CI spans two tiers, the more conservative
tier applies.

## Per-Symbol Quality

Quality tiers are evaluated per symbol-timeframe pair.  The release gate
uses the **worst tier across all reference pairs** for the overall release
decision.  Individual pair tiers are visible in the measurement report.

## Alignment with Existing Thresholds

The `MeasurementShadowThresholds` in `release_policy.py` remain the
authoritative gate boundaries.  The quality floor tiers are a higher-level
classification on top of those raw thresholds:

- `max_calibrated_brier_score = 0.60` ↔ boundary of `minimal`
- `max_calibrated_ece = 0.30` ↔ boundary of `minimal`
- `soft_warn_max_brier_score = 0.30` ↔ approximately `acceptable`/`production_grade` boundary

## Governance

Tier boundaries must not be silently loosened.  Any change requires explicit
documentation in this file with rationale and date.
