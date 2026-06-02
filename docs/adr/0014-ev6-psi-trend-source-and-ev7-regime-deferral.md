# ADR-0014: EV#6 PSI-trend data source, and EV#7 regime-degradation source

| Field      | Value                                                                       |
|------------|-----------------------------------------------------------------------------|
| Status     | Accepted — EV#6 implemented; EV#7 IMPLEMENTED (bar-derived regime label, no fabrication) |
| Date       | 2026-06-02 (EV#7 superseding update 2026-06-02)                            |
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

EV#7 was initially **deferred**: the family-event path carried no per-event
regime label, and reusing the heavy `open_prep` regime classifier
(`MarketRegimeContext`, ADX + Bollinger width) would drag the macro/VIX/
sentiment import chain into the trivially-testable governance module. The
resolution (below) is to derive the regime label **from the same bars the
event already reads**, point-in-time at the anchor — no external data, no
fabrication.

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

### EV#7 — regime-conditional degradation (IMPLEMENTED)

- **Source — bar-derived, point-in-time regime label**
  (`governance/family_event_score.point_in_time_regime`): the Kaufman
  **Efficiency Ratio** (ER) over the trailing `REGIME_WINDOW = ATR_PERIOD`
  closes ending **at** the anchor bar — `net_travel / path_length`, exactly
  the same leak-free trailing read as `atr_at`. ER ≈ 1 (net ≈ path) is
  directional/`TRENDING` (`ER ≥ 0.5`); ER ≈ 0 (much back-and-forth, little
  net) is `RANGING` (`ER ≤ 0.3`); in between is `NEUTRAL`. Source tag
  `kaufman_efficiency_ratio_trailing_closes_v1`.
- **Why ER and not the `open_prep` classifier**: ER reproduces the
  trend/range distinction from **closes alone**, so it needs no ADX/BBwidth
  re-derivation and pulls **no** `open_prep` macro/VIX/sentiment import chain
  into the governance module. This is a deliberate deviation, identical in
  spirit to the geometry-strength `raw_score` deviation already documented in
  `family_event_score`. No VIX/macro = no fabricated external data.
- **Attachment** (`governance/family_event_adapter`): each zone/level family
  event gets `mapped["regime"]` from `point_in_time_regime(bars, anchor_idx)`
  when the trailing window exists; events without enough history carry no
  label and are dropped downstream (honest abstention).
- **Verdict** (`governance/family_returns.regime_degradation`): over the
  family's realized returns + regime labels, compute the **pooled** mean. If
  pooled ≤ 0 there is no pooled edge to protect → `False` (PSR/MinTRL own
  that case). Otherwise look only at the **current** regime = the regime of
  the chronologically **last** event (the honest proxy for what we would
  trade next); if it holds ≥ `REGIME_MIN_SAMPLES = 20` events, return
  `current_mean ≤ 0` (degraded), else `None` (not yet measurable).
- **Lookahead-free & monotonic**: the verdict reads only in-path data, the
  current regime is the last *observed* one (no peeking forward), and it can
  only **add** a blocking `True` — never flip a fail to a pass.
- **Wiring**: `to_build_spec` attaches `entry["regime_degraded"]` and records
  provenance `ev24_regime_source = "kaufman_efficiency_ratio_trailing_closes_v1"`;
  `scripts/build_family_metrics` passes the verdict through verbatim to the
  gate (`governance/promotion_gate` already consumes `regime_degraded`).

## Consequences

- EV#6 `psi_slope` is now a **measured** gate input for families with enough
  chronological history; sparse families abstain (still blocked).
- EV#7 `regime_degraded` is now a **measured** gate input. A family with no
  pooled edge (pooled mean ≤ 0) returns a *measured* `False` — the
  regime-conditional check defers to PSR/MinTRL, which already own the
  no-edge case. Only a family whose **current** regime is under-sampled
  (< 20 events), or that carries no labelled events at all, abstains to
  `None` (not yet measurable, still blocked under strict provenance). No
  regime label is ever fabricated.
- The change is additive and monotonic — no existing pass can flip to a fail
  for the wrong reason, and no fail can flip to a pass.
- The regime label is derived from bars only (Kaufman ER); no external
  macro/VIX data is introduced, preserving the no-fabrication posture.

## Tests

- `tests/test_family_calibration.py`: producer abstains below sample
  threshold and on single-class reference; emits a valid reference + ≥2
  windows on real separable data; raises on length mismatch; and a drifting
  score population yields a markedly larger positive PSI slope than a
  stationary one (the metric is real, not cosmetic).
- `tests/test_family_returns.py`: `to_build_spec` emits the `psi_trend`
  block and `ev24_psi_trend_source` provenance, and `build_bundle` turns it
  into a measured `psi_slope` with `psi_trend_method` provenance.
- `tests/test_family_event_score.py`: `point_in_time_regime` labels monotone
  closes `TRENDING` (ER ≈ 1), saw-tooth closes `RANGING` (ER ≈ 0), abstains
  (`None`) below the window or on a perfectly flat path, and is invariant to
  post-anchor bars (point-in-time / leak-free).
- `tests/test_family_returns.py`: `regime_degradation` returns `None` on no
  data / under-sampled current regime, `False` when pooled ≤ 0 or the current
  regime is itself positive, `True` when pooled > 0 but the current regime
  mean ≤ 0, and raises on length mismatch; `extract_family_regime_samples`
  drops unlabelled events; `to_build_spec` emits `regime_degraded` +
  `ev24_regime_source`, and `build_bundle` carries the verdict through.
