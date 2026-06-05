# ADR-0023: Pre-register the tier-2 sizing gate move-size re-target (doc-only)

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed — **no gate, score, threshold, or test code is changed by this ADR**; it pre-registers, before any data is re-examined, the acceptance bar that a *separate, later, real-data-proven* PR must clear before the tier-2 sizing gate may be re-targeted from direction to move-size |
| Date     | 2026-06-05                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0022 (joint meta-label A/B — fixes the move-size re-targeting hypothesis this ADR pre-registers), ADR-0015 (edge vs calibration promotion tiers — this ADR pre-registers a re-target of its tier-2 objective), ADR-0008 (gate thresholds), [magnitude re-target findings (PENDING proof)](../governance/adr0023_magnitude_retarget_findings.md), [joint meta-label A/B findings](../governance/adr0022_meta_label_joint_findings.md) |

## Context

ADR-0022 established two facts on 10,981 real events (5 symbols; BOS, OB, FVG,
SWEEP), and deferred the consequence to a pre-registered follow-up — this ADR is
that pre-registration.

- **The v1 geometry score resolves move-size, not direction.** Score-alone
  out-of-sample AUC is ≈ 0.61–0.69 on a magnitude label (SWEEP ≈ 0.69) versus
  ≈ 0.53–0.58 (coin-flip) on direction. The score is a volatility / move-size
  signal, not a win-rate signal.
- **The tier-2 sizing gate grades the wrong axis.** The tier-2 `risk_sizeable`
  verdict is, on `main` today, **100 % a direction-Brier decision**. The
  verified path is:

  1. `governance/family_calibration.walk_forward_calibration` builds the target
     label as `y = 1.0 if returns[i] > 0 else 0.0` — the **sign** of the return.
  2. That pooled `(probs, outcomes)` pair is scored into a single Brier scalar
     on the direction label.
  3. The scalar lands in `FamilyMetrics.brier`.
  4. `governance/promotion_gate` compares it in the `brier_threshold` check
     against `DEFAULT_BRIER_MAX = 0.22`.
  5. A blocker there clears `risk_sizeable` in `governance/family_verdict` (via
     its calibration-checks set).

  The calibration target tag is frozen as `sign_return_secondary_diagnostic`
  (`governance/family_calibration.TARGET_TAG`). No move-size quantity enters the
  gate path anywhere. Move-size resolution exists **only** in the shadow A/B
  harness (`governance/family_meta_label` and `governance/family_calibration`'s
  `walk_forward_ab`, both of which already accept `label="magnitude"` and
  `mag_q`), which does not feed the gate.

The consequence: families sit at tier-1 `edge_supported` but are blocked from
tier-2 `risk_sizeable` by a Brier bar measured on the one axis the score
provably does **not** resolve, while the axis it **does** resolve has no gate at
all. The fix is to grade sizing on move-size. The risk of the fix is the classic
one — re-targeting a gate is exactly where a bar gets quietly lowered to let a
pet result through. This ADR exists to make that impossible by writing the
acceptance bar down **first**.

## Decision

Pre-register the following acceptance bar. This ADR changes **no** runtime
behaviour, **no** threshold, and **no** test. It fixes what the later
implementation PR must prove on real data before it may touch the gate.

### 1. Objective axis

The re-targeted tier-2 check grades **move-size resolution**: the family score's
ability to resolve a leak-safe magnitude label, not the sign of the return. The
magnitude label and its estimator are the ones already shipped in the shadow
harness (ADR-0022), reused verbatim — no new labelling logic is pre-registered:

- Per fold, `tau = _quantile(|return| over the PURGED TRAIN fold only, mag_q)`
  with `mag_q = 0.5`; the train and validation labels are both
  `1.0 if |return| >= tau else 0.0`, thresholded by that **train-only** `tau`
  (leak-safe). This is exactly `governance/family_meta_label.walk_forward_meta_ab`
  with `label="magnitude"`.
- Resolution is the Murphy decomposition's resolution term already computed by
  the harness (`resolution(probs, outcomes)`), reported as `baseline_resolution`
  for the score-alone arm.

### 2. Acceptance bar (per family, all conditions AND-combined)

A family qualifies for the move-size tier-2 gate **only** if **all** of the
following hold out-of-sample, on a purged walk-forward over real events:

1. **Discrimination floor (data-independent).** Score-alone magnitude AUC point
   estimate ≥ **0.60**, AND the lower bound of its bootstrap 95 % CI (B ≥ 1000,
   resampling OOS rows) ≥ **0.55**. The 0.60 floor is a principled
   "non-trivial separation" line chosen **independently of** the 0.61–0.69
   already observed in ADR-0022 — it is deliberately **not** anchored to the
   observed maximum, so passing is not guaranteed by construction. The CI lower
   bound kills thin-sample flukes (SWEEP n ≈ 497).
2. **Resolution floor (self-anchoring, no magic constant).** Score-alone
   `baseline_resolution` must exceed the **95th percentile of a label-permutation
   null** (shuffle the magnitude labels, identical bins, B ≥ 1000). This makes
   the resolution bar self-calibrating to each family's base rate and sample
   size — no absolute resolution number is hard-coded, so it cannot be tuned.
3. **No direction regression (guard).** Re-targeting must not silently degrade
   the axis the gate grades today: the existing direction-Brier must not worsen
   beyond the established tolerance (the harness `no_regression` clause). Sizing
   on move-size may not come at a hidden cost to the win-rate axis.
4. **Minimum sample.** `MIN_OOS_SAMPLES = 40` per family. Below that the family
   is **inconclusive**, which is **not** a pass.

### 3. Accept / reject and goalpost discipline

- A family **passes** only on (1) AND (2) AND (3); (4) is a precondition.
- A run that misses the pre-registered bar is a **negative result**. The v1
  direction-Brier tier-2 gate **stays in force** for that family. The bar above
  is **not** re-tuned, re-anchored, or relaxed after seeing the data. Any future
  change to the numbers in §2 requires a **new** ADR that supersedes this one and
  states why — never an in-place edit on a losing run.

### 4. Additive, not replacing

The move-size objective is pre-registered as a **new, additional** tier-2 check
(working name `magnitude_resolution_floor`) alongside the existing
`brier_threshold` check — **not** as a replacement for it. An additive gate can
never lower an existing bar. Whether the direction-Brier check is ultimately
kept, demoted to a diagnostic, or replaced is **out of scope** for this ADR and
is itself a decision for the later real-data PR, justified by the §2 evidence.

## Scope boundary

This ADR is **doc-only**. It does **not**:

- modify `governance/promotion_gate.py` (the `DEFAULT_BRIER_MAX = 0.22` bar or
  any check), `governance/family_verdict.py` (the `risk_sizeable` calc),
  `governance/family_returns.py` (the calibration target), or
  `governance/types.py` (the blocker check-name inventory);
- add, remove, or rename any promotion-gate check name;
- flip any threshold or change any runtime behaviour.

The later implementation PR that acts on a **passing** §2 result will, by
contrast, have to **deliberately and visibly** touch these frozen pins, each of
which exists to prevent an accidental gate change:

- `tests/test_promotion_gate.py` — pins the 0.22 Brier bar.
- `tests/test_family_returns.py` — pins the calibration target tag
  `sign_return_secondary_diagnostic`.
- `tests/test_promotion_gate_check_name_inventory.py` and
  `governance/types.py`'s blocker check-name list — pin the set of gate checks;
  a new `magnitude_resolution_floor` check must be registered there.

Naming these here is the audit trail: a reviewer of the later PR can confirm the
pin edits were intended and bar-raising, not a silent relaxation.

## Consequences

- **Positive.** The acceptance bar for the highest-leverage open question
  (should sizing grade move-size?) is now falsifiable and fixed before the data
  is re-examined. The later PR is reduced to a mechanical "did the pre-registered
  bar pass on real data, yes/no" — there is no room to move the goalposts.
- **Positive.** All required machinery already exists
  (`walk_forward_meta_ab --label magnitude`, the Murphy `resolution`
  decomposition, the real dataset),
  so the confirmatory PR adds only the permutation-null and bootstrap-CI
  estimators plus the gate wiring — no new labelling or scoring logic.
- **Negative / accepted.** Until that PR lands and passes, every family remains
  blocked from tier-2 sizing by the direction-Brier bar it cannot clear. This is
  the correct conservative default: no family is sized on an unproven objective.
- **Risk.** Move-size resolution may not convert to sizeable out-of-sample
  E[PnL] after costs. The §2 bar tests resolution, not realised PnL; the later
  PR's findings doc must record E[PnL]-after-cost as a secondary confirmation,
  and a resolution pass that does not convert to PnL is itself a recordable
  negative — not grounds to ship the gate.

## Alternatives considered

- **Anchor the bar to a reference run.** Run the harness on
  `events_v3_abs_opra.json` first, read the magnitude resolution, then set the
  bar at those values. **Rejected** — circular. ADR-0022 has already seen the
  0.61–0.69 AUC; anchoring the bar to observed values guarantees a pass and is
  precisely the goalpost-move the pre-registration exists to forbid.
- **AUC floor only (no resolution floor).** **Rejected** — AUC is rank-only and
  ignores calibration; a well-ranked but mis-calibrated score is not safe to
  size on. Resolution is the quantity the gate ultimately needs.
- **Resolution floor only (no AUC floor).** **Rejected** — an absolute
  resolution constant would be an un-anchored magic number and thin-sample
  fragile; pairing the permutation-null resolution test with the AUC floor is
  both self-calibrating and discrimination-grounded.
- **Replace the direction-Brier check outright.** **Rejected for this ADR** — a
  replacement could lower the effective bar in one step. The additive framing
  keeps every existing bar in force; the keep-vs-replace decision is deferred to
  the evidence-backed later PR.

## Evidence

The pre-registration rests on ADR-0022's executed, recorded result (joint
direction A/B null on real data; score-alone magnitude AUC 0.61–0.69). The
confirmatory move-size run is **not** part of this ADR — it is the subject of the
separate PR, whose results will be recorded in
[adr0023_magnitude_retarget_findings.md](../governance/adr0023_magnitude_retarget_findings.md),
currently a PENDING skeleton.
