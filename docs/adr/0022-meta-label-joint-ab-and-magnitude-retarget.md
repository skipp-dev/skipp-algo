# ADR-0022: Joint meta-label A/B executed — direction axis is saturated; re-target tier-2 sizing to move-size

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed — **no gate or score code is changed by this ADR**; it records the executed ADR-0019 A/B result and fixes the tier-2 re-targeting hypothesis to be tested by a separate, reviewed PR |
| Date     | 2026-06-05                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0019 (multi-feature family score v2 / meta-label design — this ADR executes its A/B protocol), ADR-0015 (edge vs calibration promotion tiers — this ADR proposes re-targeting its tier-2 objective), ADR-0008 (gate thresholds), [magnitude/regime A/B findings](../governance/adr0019_magnitude_regime_ab_findings.md), [joint meta-label A/B findings](../governance/adr0022_meta_label_joint_findings.md) |

## Context

ADR-0019 specified a **meta-label** layer (López de Prado): the SMC detector
keeps setting the side; a secondary model maps a geometry-orthogonal feature
vector to the act-or-pass + size probability that feeds calibration. Its A/B
protocol (§"A/B proof protocol") pre-registered **out-of-sample resolution** as
the primary metric and required the protocol to *measure which features actually
carry resolution* before declaring the single-feature onramp saturated.

Two facts framed the open question:

- The repo's prior A/B harness (`governance/family_feature_ab`) compares a
  feature **alone** against the score **alone**. Its own module docstring flags
  that the *incremental / joint* question — does the feature add resolution **on
  top of** the score, i.e. a multivariate meta-label model — was deliberately
  **out of scope** and "the next slice". That next slice had never been built,
  so every prior `no_lift` / "axis saturated" verdict only established that *one*
  feature, calibrated *alone*, does not out-discriminate the geometry score. It
  did **not** establish that a feature adds nothing **in combination**.
- ADR-0015 put every family at tier-1 `edge_supported` (PSR 0.99–1.00) but
  blocked tier-2 `risk_sizeable` on `brier_threshold` against the
  `sign_return_secondary_diagnostic` target (`governance/family_calibration.
  TARGET_TAG`) — i.e. on the **direction** (win-rate) axis. ADR-0015's "Option A
  roadmap" to graduate a family to tier-2 was to *lift resolution above ~6 % via
  discriminating features*, implicitly on that same direction axis.

This ADR records the result of finally executing ADR-0019's joint A/B on real
event data, and the structural finding it produced.

## Decision

Adopt two conclusions and one re-targeting hypothesis. This ADR changes **no**
runtime behaviour; it records executed evidence and fixes what the next
implementation PR must test.

### 1. The joint meta-label adds no direction resolution — the direction axis is saturated

A multivariate, purged walk-forward A/B (`governance/family_meta_label`,
`scripts/run_meta_label_ab.py`) was run on 10,981 real events (5 symbols; BOS,
OB, FVG, SWEEP). The candidate arm is a joint logistic over **[score] + the
selected features** (score prepended as column 0, so the joint model strictly
contains the baseline's information); the baseline arm is the score alone. Across
**every** configuration — order-flow-5, VRVP, abs-UOA, the kitchen-sink-8, and
relative-volume-only — **no family lifts direction resolution**; the
kitchen-sink even *regresses* (BOS Δresolution −0.0024, an overfit). The
orthogonal-combination ("meta-label") hypothesis is therefore **rejected on the
direction axis on real data**. ADR-0019's narrative escape hatch — "single-
feature nulls do not prove a joint null" — is now closed by the joint test
itself: the joint result is also null.

### 2. The v1 geometry score already resolves move-size — the axis was wrong, not the score

On the **magnitude** label (`|forward return|` over a leak-safe per-fold
quantile), the **score-alone baseline** resolves outcomes at **AUC ≈ 0.61–0.69**
(BOS ≈ 0.62, SWEEP ≈ 0.66–0.69), versus **AUC ≈ 0.53–0.58** (near coin-flip) on
the direction label. The v1 `atr_normalised_geometry_strength_v1` score —
zone-thickness/ATR and displacement — is structurally a **volatility / move-size**
signal, not a directional one. Adding any microstructure feature on top of it
*regresses* the magnitude arm (candidate AUC drops; several land
`regresses_calibration`), consistent with the existing
[magnitude/regime findings](../governance/adr0019_magnitude_regime_ab_findings.md)
that features do not lift the magnitude axis either. The lever is therefore **not
a new feature** — it is the **objective axis**.

### 3. Hypothesis to test next: re-target tier-2 sizing from direction-Brier to move-size / E[PnL]

ADR-0015 already separated *edge proof* (tier-1, PSR) from *calibrated sizing*
(tier-2, Brier/ECE). The finding above says tier-2's **target** is mis-specified:
it grades calibration of a **direction** (win-rate) label on a strategy whose
edge is in **asymmetric payoff** (PSR ≈ 1.0 *with* direction-Brier ≈ 0.24, i.e.
near coin-flip win-rate) and whose only resolved axis is **move-size**. The
hypothesis this ADR fixes for a later, separately-reviewed PR:

> Re-target the tier-2 `risk_sizeable` objective from the
> `sign_return_secondary_diagnostic` (direction) Brier/resolution check to a
> **move-size / E[PnL]** resolution check that grades the axis the score
> actually discriminates, and size positions on the magnitude/payoff
> distribution (E[PnL]/Kelly) rather than win-probability calibration.

This is **not** a threshold change and **not** a goalpost move: no bar is
lowered, no family is promoted. It proposes grading the *correct* axis, to be
pre-registered and proven on real data exactly as ADR-0019 required — or recorded
as a negative result if move-size resolution does not translate into sizeable
E[PnL] out of sample.

### Scope boundary of this ADR

Records executed evidence and fixes the next hypothesis only. It changes **no**
gate, score, target, or threshold code. The implementation — a move-size / E[PnL]
tier-2 objective in `governance/family_verdict` / `governance/promotion_gate`,
with pre-registered thresholds and tests pinning the new target — lands as a
separate, reviewed PR so the re-targeting is auditable in isolation.

## Consequences

- **Positive.** The "feature axis saturated" narrative is now backed by the
  *joint* test it always lacked, not only single-feature-alone nulls — a
  stronger, honest negative result. It also surfaces a concrete, un-mined lever
  (move-size sizing) that needs **no** new data or feature, only a correctly-
  targeted objective, and reuses the existing purged-WF / conformal machinery.
- **Positive.** The joint harness (`family_meta_label`) and its CLI are now
  permanent, tested tooling; any future "does X add resolution on top of the
  score" question is answerable in one command rather than re-litigated in prose.
- **Negative / cost.** Re-targeting tier-2 requires defining and pre-registering
  a move-size / E[PnL] resolution metric and one or more real runs to prove it;
  until then no family advances past tier-1. If move-size resolution does **not**
  convert into out-of-sample sizeable E[PnL], the tier-2 blocker stands and the
  result is recorded as a second negative — the price of proving sizing rather
  than asserting it.
- **Neutral.** No runtime behaviour changes. v1 remains the calibration input;
  the direction-target tier-2 gate stays in force until a re-targeting PR clears
  its own pre-registered bar.

## Alternatives considered

- **Declare the axis exhausted and stop.** Rejected. The joint null closes the
  *direction* axis, but the same runs show the score resolves *move-size* at
  AUC 0.61–0.69 — declaring "exhausted" would ignore the one axis the evidence
  says is live.
- **Search for yet more direction features.** Rejected. The joint test shows
  even the kitchen-sink-8 combination does not lift direction resolution and
  overfits; more features on the wrong axis is the sunk-cost antipattern.
- **Lower `brier_max` so families pass on the direction axis.** Rejected
  outright — the tune-to-pass / admin-bypass antipattern already rejected by
  ADR-0015. The decision here is to grade the *correct* axis, not to weaken the
  bar on the wrong one.
