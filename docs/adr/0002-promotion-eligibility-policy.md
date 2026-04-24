# ADR-0002: Promotion Eligibility Policy (S-4)

| Field       | Value                                              |
|-------------|----------------------------------------------------|
| Status      | Accepted                                           |
| Date        | 2026-04-24                                         |
| Deciders    | skipp-dev                                          |
| Supersedes  | (none — first formal eligibility policy block)     |
| Related     | ADR-001, `docs/f2_contextual_promotion_decision_2026-04-21.md`, `docs/freeze_exit_stability_criteria.md` |

## Context

Closes the **S-4** backlog item from
[`docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md`](../TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md):

> **S-4**: Eligibility-Policy als Doku-Block.

The audit observed that the floors that gate strategy / weight / family
promotions exist as **hard-coded constants spread across multiple
modules**, with no single document an operator can consult before
arming a promotion. The constants are correct and battle-tested, but
their *combination* (the actual policy) is currently tribal knowledge.

This ADR consolidates the policy. **No code change** — the constants in
`scripts/run_ab_comparison.py` and `scripts/smc_sprt_stop_rule.py`
remain authoritative. This document only references them so a future
edit cannot drift the policy without also touching the ADR.

## Policy

A treatment arm becomes **eligible for promotion** if and only if all
five conditions below hold simultaneously. Failure of any single
condition results in `HOLD` (re-evaluate next window) or `ROLLBACK`
(per condition 5).

### 1 · Sample-size floor (SPRT terminal decision)

The SPRT must reach a terminal decision other than `"max_n_reached"`.
Configured in [`scripts/run_ab_comparison.py`](../../scripts/run_ab_comparison.py#L143):

| Parameter | Value | Source                                           |
|-----------|-------|--------------------------------------------------|
| `p0`      | 0.55  | Lifetime-corpus median hit-rate across families  |
| `p1`      | 0.60  | Minimum-detectable effect: +5 percentage points  |
| `alpha`   | 0.05  | Type-I error                                     |
| `beta`    | 0.20  | Type-II error                                    |

Wald bounds derive from `(α, β)`; see
[`scripts/smc_sprt_stop_rule.py`](../../scripts/smc_sprt_stop_rule.py).

### 2 · Calibration improvement floor

Treatment must improve **both** `calibrated_brier` **and**
`calibrated_ece` by at least `PROMOTE_IMPROVEMENT = 0.005`
([`run_ab_comparison.py`](../../scripts/run_ab_comparison.py#L226)).
Single-metric improvements do not qualify — the floor is intentionally
conjunctive to avoid one-sided overfit.

### 3 · Hit-rate non-regression tolerance

Treatment hit-rate may regress by at most
`HIT_RATE_REGRESSION_TOLERANCE = 1.0` percentage points vs. control
(same constant). A larger regression flips the decision to `HOLD` even
if conditions 1 and 2 pass.

### 4 · Stability window

Treatment must satisfy conditions 1–3 across **two consecutive
evaluation windows** before the promotion fires. Single-window passes
are recorded as `pending` and re-evaluated next cycle. This rule is
enforced operationally in
[`docs/freeze_exit_stability_criteria.md`](../freeze_exit_stability_criteria.md);
it has no in-code constant because the eval-window cadence is governed
by the refresh workflow.

### 5 · Rollback trigger

Independent of promotion eligibility, an arm currently in production
is **automatically rolled back** if either `calibrated_brier` or
`calibrated_ece` regresses by more than
`ROLLBACK_REGRESSION = 0.010`
([`run_ab_comparison.py`](../../scripts/run_ab_comparison.py#L227)).
Rollback bypasses the stability window — one bad window is enough.

## Worked example

Treatment vs. control over one evaluation window:

| Metric              | Control | Treatment | Δ      | Floor          | Pass? |
|---------------------|---------|-----------|--------|----------------|-------|
| SPRT decision       | —       | `accept_h1` | —    | ≠ max_n_reached| ✅    |
| `calibrated_brier`  | 0.187   | 0.179     | −0.008 | ≥ 0.005 (lower-better) | ✅ |
| `calibrated_ece`    | 0.052   | 0.046     | −0.006 | ≥ 0.005 (lower-better) | ✅ |
| `hit_rate` (pp)     | 56.2    | 55.8      | −0.4   | ≥ −1.0 pp       | ✅    |
| Stability window    | —       | window 1/2| —      | 2/2             | ⏳ pending |

Decision this window: **HOLD (pending stability)**. Re-evaluate next
window; promote on second consecutive pass.

## Out-of-policy items (intentionally NOT eligibility floors)

The following exist in the codebase but are **diagnostic / advisory**,
not gates:

- **Walk-forward CV hit-rate** (`smc_zone_priority_calibration.py`,
  PR #93) — observational only, weights/thresholds unchanged.
- **Random-seed pinning** (`smc_zone_priority_calibration.py`, PR #92)
  — defense-in-depth determinism, not a decision rule.
- **Tier-monotonicity guards** (`fvg_quality.py`, see
  `/memories/repo/pine-tier-monotonicity.md`) — schema invariants, not
  promotion gates.

## Consequences

- Operators have a single canonical reference for "what makes a
  promotion safe to arm".
- The constants stay co-located with the SPRT/comparison code; this
  ADR is the index, not the source of truth.
- Future edits to `PROMOTE_IMPROVEMENT`, `ROLLBACK_REGRESSION`,
  `HIT_RATE_REGRESSION_TOLERANCE`, or the SPRT `(p0, p1, α, β)` tuple
  **must** also update this ADR (otherwise tribal knowledge re-forms).
- S-2 (Benjamini-Hochberg in `run_ab_comparison.py`) is the natural
  next iteration once we run multiple comparisons per refresh — the
  current single-arm SPRT does not need FDR correction. When S-2 lands,
  add a "§6 · multiple-comparisons FDR floor" section here.
