# ADR-0016: Aggressor-signed order-flow data path for microstructure shadow features

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed (draft for discussion) — **no code changed by this ADR**; it scopes a data-path decision before any microstructure feature is built |
| Date     | 2026-06-03                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0014 (EV#6/EV#7 feature sources), the ADR-0019 order-flow shadow-feature workstream (`governance/family_score_features_v2.py`, `governance/family_vix_fix_v1.py`) |

## Context

The EV-20 Murphy/Brier decomposition (ADR-0015) pins the binding promotion
deficit on **resolution (discrimination)**, not calibration. The ADR-0019
workstream answers this by adding **shadow features** — pure, leak-free
extractors recorded alongside `FamilyEvent` outcomes and evaluated with a
pre-registered purged walk-forward A/B (`scripts/run_feature_ab`) before any
feature is wired into the v1 `score` / promotion gate. Two candidates have run
this gate so far:

- `relative_volume` (`orderflow_relative_volume_v2`) — recorded, in main.
- `momentum_ribbon` — **retired** (PR #2545) after two-window `no_lift`.
- `williams_vix_fix` (`downside_volatility_williams_vix_fix_v1`) — recorded,
  awaiting its real-data A/B verdict (PR #2546).

### The data-path constraint (the decision this ADR exists to settle)

Every shadow extractor is invoked by the adapter as a **pure function of the
symbol's own OHLCV bars**:

```python
# governance/family_event_adapter.py
feat = feature_at(bars, anchor_idx)   # bars = this symbol's OHLCV only
if feat is not None:
    mapped["feature_name"] = feat
```

`family_events_from_structure(structure, bars)` receives only:

1. the detected SMC `structure` for one symbol, and
2. that symbol's own `bars` (timestamp / open / high / low / close / volume).

It has **no trade-level side data** (no `ask_aggressor_flag`, no MBP/MBO book)
and **no second instrument** (no benchmark / index series). This is why the
two highest-conviction microstructure candidates from the order-flow research
do **not** fit the current path:

| Candidate | Needs | In OHLC path? |
|-----------|-------|---------------|
| **Kyle's λ** (price impact per *signed* volume, Kyle 1985) | per-bar **aggressor-signed** volume (true buy/sell initiation) | ❌ no trade side |
| Real-CVD VZO | tick aggressor flag | ❌ no trade side |
| RS-Line percentile | benchmark (SPX/SPY) series | ❌ no second instrument |
| Amihud ILLIQ (`|r|/$vol`, Amihud 2002) | OHLCV only | ✅ fits today |
| Yang-Zhang / Parkinson vol | OHLC only | ✅ fits today |
| Williams VIX Fix | OHLC only | ✅ fits today (PR #2546) |

The trap to avoid (named explicitly so we do not repeat it): Kyle's λ can be
*approximated* inside the OHLC path with the **tick rule on bar closes** — but
that is the exact estimator the source author flags as 30–50 % misclassified
(Ellis/Michaely/O'Hara 2000). Building λ that way reproduces the *biased* part
and throws away our only edge: we already ingest **real Databento aggressor
flags**. An OHLC-path λ would be self-deceiving shadow code.

## Decision

**Treat aggressor-signed order-flow as a deliberate data-path project, not a
shadow extractor.** Concretely:

1. **Do not** implement Kyle's λ (or any aggressor-signed feature) against the
   current OHLC-only adapter path. A bar-close tick-rule approximation is
   explicitly rejected as it discards the Databento edge and re-introduces a
   known 30–50 % sign-classification bias.

2. **Sequence shadow candidates by data-path fit, one at a time** (ADR-0019
   discipline). While the aggressor data path is unbuilt, the eligible
   microstructure candidates are the **OHLC-pure** ones. Recommended next
   shadow candidate after the WVF A/B clears: **Amihud ILLIQ** — orthogonal to
   v1 geometry, `relative_volume`, and `williams_vix_fix`; public domain
   (Amihud 2002); three lines of OHLCV. (Yang-Zhang and the σ-normalised trend
   angle are deferred as they overlap existing dimensions — vol with WVF,
   trend with v1 geometry — pending an orthogonality check.)

3. **Scope the aggressor data path as its own work item** (a future ADR +
   reviewed PR), gated behind the WVF A/B verdict so we never accumulate
   untested shadow code ahead of an open A/B. The minimal plumbing sketch:
   - Producer side (EV-13 `pull_databento_edge_input`): already has access to
     Databento; carry per-bar **signed-volume aggregates** (sum of
     ask-initiated minus bid-initiated size, and trade count) into the bar
     records or a sibling series keyed by bar timestamp.
   - Adapter side: extend `family_events_from_structure` to accept the signed
     aggregates and pass them to a new `kyle_lambda_at(bars, signed, anchor_idx)`
     extractor (OLS of Δprice on signed volume over the trailing window),
     keeping the **honest-None** and **point-in-time** guarantees.
   - The feature stays **shadow-only** under the same pre-registered A/B gate.

## Consequences

### Positive
- Prevents a third repeat of the "Tier-1 candidate doesn't fit the path"
  mistake by making the OHLC-only constraint an explicit, recorded contract.
- Protects the Databento aggressor edge: λ is only built where the real
  sign data is available, never as a biased OHLC approximation.
- Keeps ADR-0019's one-candidate-at-a-time, shadow-first discipline intact —
  no new shadow code lands while the WVF A/B is open.
- The aggressor data path, once built, unlocks a whole orthogonal family
  (Kyle λ, real-CVD, VPIN) behind one plumbing investment.

### Negative
- Defers the highest-conviction research finding (Kyle λ) behind a data-path
  project rather than shipping it immediately. Mitigation: the OHLC-pure
  Amihud candidate captures part of the same liquidity/price-impact dimension
  in the interim, at near-zero cost.
- Adds producer→adapter surface area when the aggressor path is built (more
  data carried through the boundary, more invariants to test).

## Status notes

This ADR is **Proposed**: it records the decision to *not* build aggressor
features in the OHLC path and to sequence Amihud next, but changes no code.
Acceptance follows the WVF A/B verdict (PR #2546) and, separately, a scoped
plumbing PR for the aggressor data path.
