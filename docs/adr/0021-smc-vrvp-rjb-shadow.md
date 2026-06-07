# ADR-0021: VRVP volume-profile location + Rejection Blocks as the next orthogonal shadow features

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed (draft) — **no gate or score code is changed by this ADR**; VRVP scalars and Rejection Blocks are wired RECORDED-ONLY and remain gated on a passing, pre-registered A/B before any promotion |
| Date     | 2026-06-06                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0018 (split-conformal coverage), ADR-0019 (multi-feature family score v2 — shadow→A/B→promote lifecycle), ADR-0020 (options-flow data path), [resolution feature-gap analysis](../governance/resolution_feature_gap_analysis.md) |

## Context

ADR-0019 fixed the resolution deficit as the binding tier-2 blocker (Brier
discrimination, not calibration) and defined the **shadow → purged-walk-forward
A/B → promote** lifecycle every new candidate feature must traverse. ADR-0020
ranked the next *data axes* once the OHLCV/microstructure directional onramp
saturated. Two structure-native signals were prepared as code but deliberately
left unwired:

- **VRVP (visible-range volume profile)** — `scripts/smc_volume_profile.py`
  produces a leak-free, point-in-time
  `volume_profile_at(bars, anchor_idx, *, period)` returning the VPOC (volume
  point of control), the value area
  (VAL/VAH), and the profiled price range. This is *volume-by-price* context:
  it answers **where accepted value sits** relative to where price is now — an
  axis the v1 geometry score (`atr_normalised_geometry_strength_v1`) does not
  carry at all.
- **Rejection Blocks (RJB)** — `scripts/explicit_structure_detectors.detect_rejection_blocks_classic`
  detects two-candle rejection structures (a down→up close-through, or an
  up→down close-through, with a wick-coverage variant split). This is a
  *structure event* family, but it is **not** one of the four scored families.

Both are built and tested but, until this ADR, neither rides alongside outcomes,
so neither can be evaluated. The v1 scored families remain the closed set
`("BOS", "OB", "FVG", "SWEEP")` — a contract asserted exactly by
`tests/test_promotion_gate_producer_e2e.py` and consumed by
`smc_integration/measurement_evidence._FAMILIES`. **Adding RJB as a fifth scored
`EventFamily` now would be a gate-contract change with no out-of-sample
evidence — precisely the "Schnellschuss" the lifecycle forbids.**

## Decision

Wire both signals **RECORDED-ONLY**, on the two channels their shapes fit, and
on neither the score nor the gate. This ADR fixes the wiring, the measurement
protocol, and the promotion bar; it changes no score, gate, threshold, or
`EventFamily` enum, and it promotes nothing.

### 1. VRVP location scalars — recorded on each event (`governance/family_vrvp_v2.py`)

Two scale-free, strictly point-in-time scalars are computed over the trailing
`ATR_PERIOD` window ending at the event anchor (via the leak-free
`volume_profile_at`) and attached to every `FamilyEvent`, exactly as the
existing v2 shadow scalars (`vpin`, `kyle_lambda`, `ofi_imbalance`,
`signed_uoa_notional`) are:

- **`vrvp_vpoc_dist`** — signed VPOC displacement,
  `(close - vpoc) / (price_high - price_low)`. Positive when the close sits
  above the busiest price (price has travelled up and away from accepted value),
  negative below it. Range-normalised so it is comparable across symbols and
  volatility regimes.
- **`vrvp_va_pos`** — discrete value-area position: `-1` below VAL, `0` inside
  `[VAL, VAH]`, `+1` above VAH. The discrete form is the least over-fit read of
  value-area acceptance — it records only whether price has broken out of
  accepted value, not a continuous coordinate that would invite curve-fitting.

Both are **honest-None**: absent (never invented) when the profile cannot be
built, the anchor close is missing, or the normalising range/value-area bounds
are degenerate. They are attached in **both** event geometries
(`_zone_event_to_family` and `_level_event_to_family`) in
`governance/family_event_adapter.py`, recorded-only — they are **not** a
calibration input and do **not** feed the gate.

### 2. Rejection Blocks — recorded in the auxiliary channel (not a scored family)

RJB records are surfaced in the structure artifact's **`auxiliary`** block —
alongside `liquidity_lines`, `broken_fractal_signals`, and the session/IPDA
context — and explicitly **not** in the scored `structure` block. Concretely:

- `scripts/explicit_structure_profiles._compose_common` calls
  `detect_rejection_blocks_classic` and places the deduped records under
  `auxiliary["rejection_blocks"]`.
- `smc_integration/structure_contract.AUXILIARY_KEYS` and
  `smc_integration/structure_batch` carry `rejection_blocks` through to the
  artifact; `spec/smc_structure_artifact.schema.json` admits it as an additive,
  optional auxiliary array.
- The scored `EventFamily` set, `raw_score`, the walk-forward outcome horizons,
  and the promotion-gate producer are **untouched**. `measurement_evidence._FAMILIES`
  stays `("BOS", "OB", "FVG", "SWEEP")` and the gate-producer e2e contract
  stays green.

This keeps RJB measurable (it is now persisted next to outcomes) while leaving
the decision to score it to a future, evidence-backed PR.

### A/B proof protocol (the bar these candidates must clear before promotion)

Identical in spirit to ADR-0019 §"A/B proof protocol", pre-registered here:

1. **Shadow first.** VRVP scalars and RJB records are emitted into
   provenance/auxiliary only. No gate or calibration input sees them until the
   A/B clears.
2. **Purged walk-forward CV.** Evaluate on pooled OOS pairs with purged,
   embargoed walk-forward splits (López de Prado), features strictly
   point-in-time / leak-free (omitted-not-zero-filled on missing data).
3. **Primary metric — resolution.** Pre-registered success = a minimum lift in
   the out-of-sample **resolution** component of the Brier decomposition, with a
   CI that excludes the no-lift null. For VRVP, the test is whether the location
   scalars lift resolution of the existing scored families. For RJB, the future
   test is whether an RJB-conditioned score discriminates outcomes well enough to
   justify promoting it to a scored family.
4. **No-regression guards.** No worsening of ECE (calibration) or
   `conformal_coverage`; no reduction of per-side OOS power below
   `MIN_OOS_SAMPLES`.
5. **Per-family, not pooled-only.** Reported per family; each promotes on its own
   evidence.
6. **Pre-registration.** Margins, CV parameters, and no-regression thresholds are
   fixed **before** the run. A miss is recorded as a negative result; no
   post-hoc re-tuning.

### Promotion path (explicitly deferred)

- Promoting **RJB to a scored `EventFamily`** (extending the closed set,
  `measurement_evidence._FAMILIES`, `raw_score`, outcome horizons, and the
  gate-producer contract) is a **separate, deliberate future PR**, gated on a
  passing RJB A/B. It is out of scope here.
- Feeding **VRVP scalars into the v2 calibration input** is likewise gated on a
  passing VRVP A/B and is out of scope here.

## Consequences

- This ADR changes **no** runtime scoring or gating behaviour: no score, gate,
  threshold, or `EventFamily` enum is modified, and no family is promoted. Two
  signals merely begin to ride alongside outcomes so they *can* be evaluated.
- The structure artifact's `auxiliary` block gains an additive `rejection_blocks`
  array; the artifact `structure` (scored) block and the promotion-gate family
  contract are unchanged and their tests stay green.
- If a candidate's A/B clears, it advances to its next lifecycle stage (VRVP →
  calibration input; RJB → scored family) on real evidence, via a separate
  reviewed PR — not by redefinition.
- If the A/B fails, the honest negative result is recorded and nothing promotes.

## Status

Shadow — wired RECORDED-ONLY, awaiting a pre-registered purged walk-forward A/B.
No promotion until that A/B clears its pre-registered resolution bar with no
calibration/coverage regression.
