# ADR-0018: Split-conformal coverage from walk-forward OOS pairs

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Accepted                                                                          |
| Date     | 2026-06-02                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0016 (pipeline-provenance classes), ADR-0017 (live-incubation surrogate), EV-24 walk-forward calibration, C10.1 conformal coverage, EV-20 first real run |

## Context

The promotion gate's `conformal_coverage` check compares a family's measured
empirical coverage against its `conformal_target` (`1 - alpha`) with a small
`conformal_coverage_tolerance` (default 0.02) and blocks when the held-out
coverage falls below the floor (C10.1 conformal prediction — distribution-free
marginal coverage). It is a **non-calibration integrity guard**, so under
ADR-0015 it gates **tier-1 `edge_supported`**: while it is unmeasured the
verdict is `inconclusive`.

The producer-side machinery already exists and is complete:
`scripts/build_family_metrics._conformal_slice` consumes a `conformal` block
holding `alpha`, a `calibration` set and a held-out `test` set (each carrying
`probabilities` and `outcomes`), calibrates a
`ml.calibration.conformal.SplitConformalClassifier`
(Vovk split conformal) on the `calibration` set, measures empirical marginal
coverage on the held-out `test` set, and emits `conformal_coverage`,
`conformal_target = 1 - alpha` and `conformal_method = "split_conformal_vovk"`.

The only gap is that the SMC-direct producer
(`governance/family_returns.to_build_spec`) never **emits** a `conformal` block,
so `conformal_coverage` is permanently "not yet measured". The open question is
the **measurement-design** one: which pairs calibrate the conformity quantile,
which are held out to measure coverage, and at what `alpha`?

## Decision

Derive a split-conformal block from the **same pooled walk-forward
out-of-sample pairs** used for calibration, as an **independent view** of that
OOS pool.

1. `walk_forward_calibration` pools its OOS `(probability, outcome)` pairs in
   **chronological order**. A new pure function
   `governance/family_calibration.partition_conformal` splits the pooled block
   at `CONFORMAL_CALIBRATION_FRACTION` (0.5): the **earlier** half calibrates
   the split-conformal conformity quantile, the **later** half is the held-out
   coverage test set. The chronological order is deliberate — the conformity
   quantile is learned on older OOS and validated on newer OOS, never the
   reverse.

2. `alpha` is fixed at `CONFORMAL_ALPHA = 0.1` (a **90% coverage target**),
   matching the `ml.calibration.conformal` and producer defaults. Fixing it in
   this ADR — rather than tuning per family — prevents an `alpha` that is
   silently chosen to clear the floor (no goalpost-move).

3. The block is emitted **only when both sides stay adequately powered**: each
   of the calibration and test halves must hold at least `CONFORMAL_MIN_SIDE`
   (= `MIN_OOS_SAMPLES`, 40) pairs, i.e. the pool must hold at least 80 OOS
   pairs. Below that `partition_conformal` returns `None`, the caller omits the
   block, and `conformal_coverage` stays honestly **unmeasured** — a quantile
   and a coverage estimate computed from a handful of points are not credible.

4. This is an **independent view** of the same OOS pool that ADR-0017 uses for
   the live surrogate: coverage (does the conformal prediction set contain the
   label at the guaranteed rate?) and live Brier-drift (is the recent OOS
   worse-calibrated than the historical?) are **different diagnostics on the
   same evidence**, so reusing the pairs is sound. The conformal split is
   computed from the **full** pooled block before the live-tail reassignment.
   `to_build_spec` records the `ev26_conformal_source` provenance tag when the
   block is emitted.

This ADR changes **only** how the conformal block is produced from existing OOS
pairs. It does **not** change the gate threshold or tolerance, and it does not
by itself promote any family: coverage still has to clear its floor, and tier-2
`risk_sizeable` still hinges on the unchanged Brier problem.

## Consequences

- `conformal_coverage` becomes **measurable** for any family with enough OOS
  pairs (`>= 2 * CONFORMAL_MIN_SIDE`). For such families it is no longer an
  unmeasured guard forcing ADR-0015 tier-1 `inconclusive`; the family reaches
  tier-1 once coverage (and the remaining non-calibration guards) are measured
  and clear.

- **Honest, non-flattering by design.** A low-resolution score yields **wide**
  prediction sets (often the full `{0, 1}`), so empirical coverage tends to be
  **high** and the floor is usually cleared. This is the correct statement:
  conformal coverage certifies that the *prediction set* is calibrated, it does
  **not** certify discrimination. A family can clear `conformal_coverage` and
  still fail the tier-2 Brier bar — exactly the BOS/OB/FVG situation. Coverage
  is not a back door to `risk_sizeable`.

- Families with too few OOS pairs emit no conformal block and keep an
  honestly-unmeasured `conformal_coverage` — the guard still blocks tier-1 for
  them, which is the correct statement ("not enough out-of-sample history to
  certify coverage yet").

- The 50/50 chronological split spends half the OOS pool on the conformity
  quantile and half on the coverage estimate; both shrink the per-side count
  versus the headline walk-forward Brier (which still uses the full pool /
  remainder). This is an accepted cost of measuring coverage without a separate
  data draw.
