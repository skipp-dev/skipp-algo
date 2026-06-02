# ADR-0019: Multi-feature family score v2 (meta-label) — order-flow-led resolution

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed (draft) — **no gate or score code is changed by this ADR**; implementation is staged as a separate, reviewed PR gated on a passing A/B run |
| Date     | 2026-06-02                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0017 (live-incubation surrogate), ADR-0018 (split-conformal coverage), EV-20 first real run, [resolution feature-gap analysis](../governance/resolution_feature_gap_analysis.md), [why no family promotes](../governance/why_no_family_promotes_resolution_blocker.md) |

## Context

Under ADR-0015 every SMC family clears the tier-1 `edge_supported` evidence
(PSR 0.99-1.00 benchmark-robust) but is blocked at tier-2 `risk_sizeable` by the
`brier_threshold` check (Brier 0.234-0.257 vs a 0.22 bar). The Murphy/Brier
decomposition pins the binding deficit on **resolution (discrimination)**, not
on miscalibration: ECE is low (~0.035), so the probabilities are
well-*calibrated* but weakly *discriminating*. ADR-0018 made `conformal_coverage`
measurable and confirmed the same structural fact from the other side — a
low-resolution score yields wide prediction sets, so coverage is high while
discrimination stays weak.

The single per-event score is **one-dimensional**:
`governance/family_event_score.SCORE_SOURCE = "atr_normalised_geometry_strength_v1"`
— pure ATR-normalised geometry thickness, no volume, no order-flow, no
liquidity/session/premium-discount context. The [feature-gap
analysis](../governance/resolution_feature_gap_analysis.md) establishes (with
verified evidence) that:

- The five existing FVG-quality features are FVG-only, hand-set linear, and add
  essentially one signal orthogonal to geometry (`distance_to_price_atr`,
  displacement). `hurst_50` is a measured dud (fitted weight 0.0); `gap_size_atr`
  is substantially the current score already.
- The largest un-tapped lever is **order-flow / volume**, which exists in the
  data (bars carry volume; trades carry `size` + `side`) and in
  `ml/features/microstructure.py` (`volume_imbalance`, `vpin`) but is **unused**
  by the score.
- We have **trade-level** data but **no** order-book / DOM, so footprint/depth
  features are out of scope; trade-side imbalance and VPIN are in scope.

## Decision

Define a **family score v2** as a **meta-label** layer in the López de Prado
sense: the existing SMC detector remains the **primary model** that sets the
**side** (long/short); a **secondary** model maps a richer, geometry-orthogonal
feature vector to the **act-or-pass + size** probability that feeds calibration.
The primary side logic is **not** changed. This ADR fixes the **feature
hierarchy**, the **measurement/A/B protocol**, and the **promotion bar** for v2;
it does **not** itself change any score or gate code, and it promotes no family.

### Feature hierarchy (priority order, orthogonal-to-geometry first)

The hierarchy is ordered by expected orthogonality to the current geometry score
and by data availability. Tiers are additive candidate sets, not a fixed final
model — the A/B run measures which actually carry resolution.

1. **Order-flow (primary new lever, available).**
   - `volume_imbalance` (signed trade-side imbalance over the event window).
   - `vpin` (volume-synchronised probability of informed trading,
     Easley-López de Prado-O'Hara) over the formation window.
   - Order-block / formation-candle volume relative to local volume baseline
     (needs a small extractor).
2. **Displacement (the one orthogonal signal from the old five, available).**
   - `distance_to_price_atr` (anchor-to-zone-mid displacement, ATR-normalised).
3. **Liquidity & structural context (available, unused).**
   - Liquidity-sweep context flag (did the move sweep a prior liquidity pool?).
   - Premium/discount position in the IPDA dealing range
     (`smc_core/htf_context.py` q25/mid/q75).
4. **Freshness (available as a label, needs lifting to a pre-trade feature).**
   - Zone freshness / touch-count before entry (fresh zones hold better).
5. **Regime conditioners (available, unused — used as conditioners, not raw
   predictors).**
   - Session / killzone marker and cyclical time-of-day
     (`ml/features/temporal.py`).
   - Volatility regime (`realized_volatility`, `garman_klass`, `parkinson`).

**Explicitly dropped:** `hurst_50` (measured zero discrimination) and a
standalone `gap_size_atr` term (redundant with the current geometry score).

**Out of scope (no data):** order-book depth / footprint / DOM features.

### A/B proof protocol (the bar v2 must clear before it can replace v1)

The v2 score is promoted to **producer default only** if it demonstrably
improves out-of-sample resolution without degrading calibration or coverage, on
real event data. The protocol is deliberately conservative and anti-goalpost:

1. **Shadow first.** v2 is computed alongside v1 (`SCORE_SOURCE` v2 tag) and
   emitted into provenance only; v1 stays the calibration input. No gate sees v2
   until the A/B clears.
2. **Purged walk-forward CV.** Evaluate v1 vs v2 on the same pooled OOS pairs
   using purged, embargoed walk-forward splits (López de Prado, to defend
   against leakage and overlapping-label autocorrelation). The feature vector
   must be strictly point-in-time / leak-free, consistent with
   `smc_integration/measurement_evidence.py` (omitted-not-zero-filled on missing
   data).
3. **Primary metric — resolution.** The pre-registered success metric is the
   **out-of-sample resolution component** of the Brier decomposition. v2 must
   raise resolution by a pre-registered minimum margin (to be fixed in the
   implementation PR, e.g. the margin needed to move Brier from ~0.24 below the
   0.22 bar with a CI that excludes 0.22).
4. **No-regression guards.** v2 must **not** worsen ECE (calibration) or
   `conformal_coverage` (it must still clear its floor), and must not reduce the
   per-side OOS sample power below `MIN_OOS_SAMPLES`.
5. **Per-family, not pooled-only.** The A/B is reported per family (BOS, OB,
   FVG, SWEEP). A family promotes on its own evidence; SWEEP stays inconclusive
   while n < 120.
6. **Pre-registration.** The success margin, the CV scheme parameters, and the
   no-regression thresholds are written **before** the run. A run that misses
   the pre-registered bar is recorded as a negative result — v1 stays the
   default. No re-tuning `alpha`/margins to clear the floor after the fact.

## Consequences

- This ADR changes **no** runtime behaviour: no score, gate, or threshold is
  modified, and no family is promoted. It fixes the design contract for a later,
  separately-reviewed implementation PR.
- If the A/B clears, v2 becomes the calibration input and resolution improves on
  real evidence — the tier-2 Brier blocker can then be cleared on merit, not by
  redefinition.
- If the A/B fails, the honest outcome is recorded and v1 stays. Order-flow not
  lifting resolution would itself be a valuable, publishable negative result.
- The meta-label shape (ML decides size, not side) bounds overfitting risk and
  reuses the existing walk-forward calibration and conformal machinery
  (ADR-0017/0018) unchanged.
- Cost: building the order-flow / freshness / OB-volume extractors and the
  purged-CV harness, and one or more real pipeline runs to measure the A/B. This
  is the accepted price of proving resolution rather than asserting it.

## Status / next step

Draft, **ready to implement once the merge queue clears**. Implementation is a
separate reviewed PR: (1) extractors for the in-scope order-flow / freshness /
OB-volume features, (2) the v2 shadow score behind a new `SCORE_SOURCE` tag,
(3) the purged-CV A/B harness with pre-registered thresholds, (4) a real run.
v1 remains the default until step 4 clears the pre-registered bar.
