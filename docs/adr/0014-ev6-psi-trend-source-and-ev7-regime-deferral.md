# ADR-0014: EV#6 PSI-trend data source, and EV#7 regime-degradation deferral

| Field      | Value                                                                       |
|------------|-----------------------------------------------------------------------------|
| Status     | Accepted — EV#6 implemented; EV#7 DEFERRED (no fabrication)                  |
| Date       | 2026-06-02                                                                  |
| Deciders   | skipp-dev (autonomous mandate; principal quant)                             |
| Related    | ADR-0008 (promotion-gate thresholds, taxonomy E/R/O), EV-15/EV-24 calibration |

## Context

The promotion gate exposes two evidence slots that, until now, every
family reported as "not yet measured" (a deliberate `None` that keeps the
gate **blocking**):

- **EV#6 / C9 `psi_slope`** — population-stability-index *trend* over time.
  The consumer (`scripts/build_family_metrics._psi_trend_slice`) was fully
  wired: given a `psi_trend` block (`reference_probabilities` + ≥2 ordered
  monitoring `windows`) it computes per-window PSI against the reference and
  fits an OLS slope. What was missing was a **producer** emitting that block
  from real data.
- **EV#7 / regime-conditional degradation** — a rule that blocks promotion
  when edge decays under a named market regime.

A prior repo note claimed EV#6 had "no upstream producer emitting real
psi_trend reference distributions." Investigation proved that note
incomplete: `governance/family_calibration.walk_forward_calibration`
**already** produces a real out-of-sample probability series from the EV-24
raw per-family geometry-strength scores (`governance/family_event_score`),
on the same edge-pipeline path that feeds the gate. The probability series
exists; it simply was not being sliced into chronological windows. EV#6 is
therefore buildable from **real, non-fabricated** data.

EV#7 is different. `family_events_from_structure` builds family events from
SMC structure + bars only — **no regime label per event**. The
edge-pipeline family-event path carries no regime signal. A regime
classifier (`open_prep.regime` / `MarketRegimeContext`) exists but is not
wired to family events. Producing a `regime_degraded` verdict now would
require inventing a regime label per event = fabrication.

## Decision

### EV#6 — data source and construction (IMPLEMENTED)

- **Source**: the EV-24 walk-forward score series — the same raw
  per-family scores already calibrated for EV-15. Target is `sign(return)`
  (GAP 2: a win-rate diagnostic, **not** an edge proof), consistent with
  the EV-24 calibration target.
- **Construction** (`governance/family_calibration.walk_forward_psi_trend`):
  a **fixed reference Platt calibrator** is fit on the earliest
  chronological block and applied **both** to that block (the reference
  probability distribution) **and** to each later chronological monitoring
  window. Because every window is scored through the *same* fixed lens, the
  resulting PSI series isolates drift in the **score population** from
  per-fold calibrator-refit drift — the honest decomposition for a drift
  watchdog (standard PSI monitoring: fixed reference, moving window).
- **Partitioning**: the series is split into `k + 1` equal chronological
  segments (1 reference + `k` monitoring windows), `k` the largest value in
  `[PSI_TREND_MIN_WINDOWS=2, PSI_TREND_MAX_WINDOWS=4]` for which every
  segment holds ≥ `max(MIN_TRAIN_SAMPLES, PSI_TREND_MIN_WINDOW_SAMPLES)`
  events. The last window absorbs the integer-division remainder.
- **Honest abstention**: returns `None` (family stays "not yet measured")
  when there are too few events to fit the reference lens or to form two
  non-trivial windows, or when the reference block has a single outcome
  class / degenerate score (the calibrator refuses to fabricate a mapping).
- **Wiring**: `governance/family_returns.to_build_spec` attaches the block
  as `entry["psi_trend"]` and records audit-only provenance
  `ev24_psi_trend_source = "ev24_fixed_reference_calibrator_chronological_windows_v1"`.
  The producer's OLS slope-fit tag (`psi_trend_method = "ols_psi_window_slope"`)
  is owned and added by the consumer.
- **Monotonic safety**: this can only make the gate **stricter** — a measured
  `psi_slope` adds a blocking condition; it can never tune-to-pass.

### EV#7 — regime-conditional degradation (DEFERRED)

- **Status: DEFERRED**, explicitly, with no fabrication. The edge-pipeline
  family-event path carries no per-event regime label, so the rule cannot be
  measured today.
- **Unblock path**: introduce a regime-classifier producer over bars that
  labels each family event (wiring `open_prep.regime` /
  `MarketRegimeContext` into `family_events_from_structure`), then add the
  `regime_degraded` slice as a *new* blocking condition. Until that producer
  exists and is validated, the slot remains "not yet measured" and the gate
  keeps blocking honestly.

## Consequences

- EV#6 `psi_slope` is now a **measured** gate input for families with enough
  chronological history; sparse families abstain (still blocked).
- The change is additive and monotonic — no existing pass can flip to a fail
  for the wrong reason, and no fail can flip to a pass.
- EV#7 remains an open, documented gap rather than a fabricated green. The
  honest "measured fail / not-yet-measured" posture is preserved.

## Tests

- `tests/test_family_calibration.py`: producer abstains below sample
  threshold and on single-class reference; emits a valid reference + ≥2
  windows on real separable data; raises on length mismatch; and a drifting
  score population yields a markedly larger positive PSI slope than a
  stationary one (the metric is real, not cosmetic).
- `tests/test_family_returns.py`: `to_build_spec` emits the `psi_trend`
  block and `ev24_psi_trend_source` provenance, and `build_bundle` turns it
  into a measured `psi_slope` with `psi_trend_method` provenance.
