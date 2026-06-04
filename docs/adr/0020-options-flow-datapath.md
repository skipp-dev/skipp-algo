# ADR-0020: Options-flow data path — signed UOA notional as the next orthogonal shadow-feature axis

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Proposed (draft for discussion) — **no code changed by this ADR**; it scopes a data-path decision and ranks the three candidate "new information" axes before any feature is built |
| Date     | 2026-06-04                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0016 (aggressor-signed order-flow data path), ADR-0019 (multi-feature family score v2), [resolution feature-gap analysis](../governance/resolution_feature_gap_analysis.md), [feature-onramp saturation verdict](../governance/feature_onramp_saturation_verdict.md) |

## Context

The [feature-onramp saturation verdict](../governance/feature_onramp_saturation_verdict.md)
(2026-06-04) closed the directional **OHLCV / microstructure** onramp: every
close/OHLC-pure shadow candidate (`momentum_ribbon`, `williams_vix_fix`,
`variance_ratio`, `relative_volume`, `amihud_illiquidity`, `kyle_lambda`,
`average_trade_size`, `ofi_imbalance`) returned `no_lift` on the only label the
v1 product trades — **direction**. The lone magnitude exception (SWEEP score)
did not replicate out-of-sample, and the single durable signal (regime-relative
compression) is statistically real but economically sub-marginal. The verdict's
explicit recommendation: **real next gains require a different data axis, not
more formulas on the same bars.**

Three candidate axes carry genuinely new (non-OHLCV) information. This ADR ranks
them by **verified repo maturity**, not theoretical attractiveness, because the
expensive part of every one is the **data path**, not the formula — exactly the
lesson ADR-0016 recorded for the aggressor path.

### What actually exists in the repo (verified)

| Axis | Existing building blocks | Maturity |
|------|--------------------------|----------|
| **Options flow** | `newsstack_fmp/opra_uoa.py` — a fully built UOA detector on Databento `OPRA.PILLAR` `trades`: aggressor `side` (`A`/`B`/`N`), $-notional gate (`size·price·100`), 500 ms multi-exchange sweep window, multi-leg flag. Databento `OPRA.PILLAR` activated 2026-05-12; Unusual Whales subscription cancelled (self-hosted). | **High** — data path exists |
| **L2 book / VPIN** | `ml/features/microstructure.py` (`vpin`, `bid_ask_imbalance`); `scripts/probe_databento_entitlement.py` | **Low→Medium** — formula yes; data **confirmed entitled** (probe 2026-06-04: `mbp-10`/`mbo`/`mbp-1` YES on XNAS.ITCH, DBEQ.BASIC, GLBX.MDP3, XNYS.PILLAR), but still dormant (no cron), data-volume-massive, and the repo `vpin` is non-canonical |
| **Cross-asset lead-lag** | "benchmark" in code = KPI stratification, **not** a second market series | **~Zero** — no second-instrument infra |

### Entitlement ground truth (probe run 2026-06-04)

`scripts/probe_databento_entitlement` was run with the live key. Result, now a
recorded fact rather than an assumption:

- **`OPRA.PILLAR` entitled = True** — options-flow path confirmed; `ENABLE_OPRA_UOA`
  can be flipped on. Coverage 2013-04-01 → present; `trades` + `definition` +
  `statistics` + `cmbp-1` + `cbbo-1s` all present.
- **L2 depth is entitled on the equity datasets we already pull:** `mbp-10`,
  `mbp-1` and `mbo` are **YES** on **XNAS.ITCH** (the exact dataset EV-20 uses
  for OHLCV bars), as well as DBEQ.BASIC, GLBX.MDP3 and XNYS.PILLAR. This
  **resolves the L2 blocker named in the first draft** — the question was never
  "is the formula right" but "is the data even in the tier," and it is.
- **Bonus:** the `imbalance` schema (pre-market order-imbalance signal, flagged
  dormant-but-strategic by the 2026-05-12 audit) is **entitled** on XNAS.ITCH
  and XNYS.PILLAR. `OPRA.PILLAR` itself has no `mbp-*`/`imbalance` (options book
  depth is not in tier) — but equity L2 is what the VPIN/queue thesis needs.

So the L2 axis is **no longer gated on entitlement**; its remaining headwinds
are purely (a) MBP-10 data volume (storage/latency/backtest cost) and (b) the
non-canonical fixed-`bucket_size` `vpin` approximation. The ranking below is
updated accordingly.

### The maturity illusion to avoid (named so we do not repeat it)

`opra_uoa.py` is wired into the **news / catalyst** stack, **not** the edge
pipeline. It emits **alerts**, not `FamilyEvent` features. The path from "alert"
to "recorded, leak-free, point-in-time shadow feature with a pre-registered A/B"
is real work — not "free." Three honest constraints:

- **No greeks / gamma / open-interest.** The "dealer gamma positioning" thesis
  that makes options flow attractive is **not built** — a `definition` schema
  exists but there is no greeks calculator. That is its own project.
- **Options data is noisy to interpret.** Separating market-maker hedging flow
  from genuine directional bets is non-trivial; the first feature must be a
  *narrow, robust* aggregate, not a positioning model.
- **`opra_uoa` is a detector, not an extractor.** It produces Benzinga-shaped
  alert dicts, not a `feature_at(bars, anchor_idx)`-compatible PIT scalar.

## Decision

**Treat options flow as the highest-conviction next data-path project — its own
ADR + plumbing PR, gated behind the still-open ADR-0019 queue — and NOT as a
"next shadow candidate" pulled into the current onramp.** Concretely:

1. **Rank and sequence the three axes by repo maturity:**

   1. **Options flow — first.** The expensive data path (`OPRA.PILLAR` ingest +
      UOA detection) already stands. Economically it is also the best thesis:
      options flow is leveraged and directional, so it can *lead* the underlying
      rather than mirror it — genuinely new information OHLCV features cannot
      hold. **Next step: a narrow `signed UOA notional per symbol/bar` shadow
      feature** fed into the same A/B machinery WVF/Kyle/Amihud run through —
      **after** the current queue, as its own ADR. **NOT gamma first.**
   2. **L2 / VPIN — entitlement resolved, now cost-gated.** The probe (2026-06-04)
      confirmed `mbp-10`/`mbo` are **entitled on XNAS.ITCH** (and the other
      equity datasets) — the L2 axis is on the table. What remains is not a
      tier question but an engineering one: the repo `vpin` is a
      fixed-`bucket_size` approximation, not canonical volume-bar VPIN, and
      MBP-10 depth is data-volume-massive. A **bounded metadata cost probe**
      (2026-06-04, AAPL 2025-09-15, XNAS.ITCH, metadata only — no bulk download)
      now quantifies that: `mbp-10` is **1.38 M records/symbol-day** (~1,546× the
      895 `ohlcv-1m` bars), `mbo` 4.08 M (~4,556×). **Dollar cost is trivial**
      ($0.19/symbol-day for `mbp-10`, ~$240 for a 5-symbol × ~250-day backtest);
      the real gate is **record volume** (~1.7 B rows to store, parse, and
      leak-safely PIT-aggregate into bar-level features). So the L2 build-vs-defer
      call is an **engineering-cost decision, not a budget or access one** — and
      it ranks below options flow on effort, not on data availability.
   3. **Cross-asset lead-lag — defer.** Conceptually the most elegant "new axis"
      but the most greenfield plumbing and the highest leakage risk
      (time-aligning two asynchronous series through the single-instrument
      `f(bars, anchor_idx)` bottleneck is a classic leak source). Needs a
      synchronized second instrument (SPY/ES), an async lead-lag estimator
      (cross-correlation / Hayashi-Yoshida), and PIT discipline the adapter
      deliberately does not have today. Later, not now.

2. **Keep one-at-a-time, shadow-first discipline (ADR-0019).** None of these
   three axes is a "next shadow candidate." All are **data-path projects** (own
   ADR + reviewed PR), exactly as ADR-0016 framed the aggressor path. The
   ADR-0019 queue is still open (WVF #2546, Kyle #2554, Amihud); no options-flow
   shadow code lands while that queue runs.

3. **Scope the options-flow first feature narrowly — `signed_uoa_notional`,
   NOT gamma.** The minimal plumbing sketch (deferred until the queue clears and
   this ADR is accepted):
   - **Producer side:** alongside the EV-20 OHLCV pull, pull `OPRA.PILLAR`
     `trades` for the same symbols/window and reuse `opra_uoa`'s aggressor
     classification to aggregate, **per underlying per bar**, signed premium
     notional = `Σ side∈{A:+1,B:−1,N:0} · size · price · 100`, plus a UOA-only
     subset above the existing `$`-notional gate. Carry it as a sibling series
     keyed by bar timestamp (same shape the ADR-0016 signed-volume sketch uses).
   - **Adapter side:** extend `family_events_from_structure` to accept the
     options series and pass it to a new
     `signed_uoa_notional_at(bars, opts, anchor_idx)` extractor, preserving
     **honest-None** (no options prints in window → `None`, never 0) and
     **point-in-time** guarantees (only prints strictly before the anchor).
   - The feature stays **shadow-only** under the same pre-registered purged
     walk-forward A/B gate (`scripts/run_feature_ab`). Greeks / dealer-gamma are
     explicitly **out of scope** for this first feature — a separate future ADR.

4. **Reuse the saturation-verdict guardrails** on this new axis: match the label
   to the theorem (options flow is a *directional-lead* thesis → test on the
   direction label, where it should finally have a chance), demand multi-window
   sign stability, pre-register the pass criterion on an out-of-sample window,
   distinguish FAIL from UNDERPOWERED, and run the money-worth test with
   realistic costs before any promotion.

## Consequences

### Positive
- Converts a vague "options flow is the next axis" pointer into a ranked,
  repo-grounded sequence with an explicit cheapest-first step per axis.
- Protects the one-at-a-time discipline: the open ADR-0019 queue is not
  disturbed; options flow is *planned and vetted*, not *opened now*.
- Reuses the existing `OPRA.PILLAR` ingest + `opra_uoa` aggressor logic, so the
  first feature is a thin aggregation layer, not a new data integration.
- Picks the narrowest honest first feature (`signed_uoa_notional`), avoiding the
  gamma/greeks rabbit hole that would otherwise stall the axis.

### Negative
- Defers the highest-conviction axis behind the open queue rather than starting
  it immediately. Mitigation: the queue is short and the data path already
  exists, so the lead time is plumbing, not integration.
- Adds producer→adapter surface area (a second data series through the boundary)
  when built — more invariants to test, same cost ADR-0016 already accepted for
  the aggressor path.
- The L2 axis, now confirmed entitled, carries a real MBP-10 data-volume cost
  that is not yet measured; its build-vs-defer call waits on a bounded cost
  probe, so its ranking below options flow is on cost/effort, not access.

## Status notes

- Doc-only. No code, no shadow feature, no candidate added to the ADR-0019
  queue. The first plumbing PR is gated behind (a) the open queue clearing and
  (b) acceptance of this ADR.
- **Entitlement probe RUN 2026-06-04** (see "Entitlement ground truth" above):
  `OPRA.PILLAR` entitled; equity `mbp-10`/`mbo`/`imbalance` entitled on
  XNAS.ITCH. The L2 axis is **no longer entitlement-blocked** — only cost-gated.
  The next cheap step for L2 shifted from an entitlement probe to a **bounded
  MBP-10 data-volume + canonical-VPIN cost probe** before any feature build.
- **Bounded cost probe RUN 2026-06-04** (AAPL, 2025-09-15, XNAS.ITCH, metadata
  only): `mbp-10` = 1.38 M records/symbol-day (~1,546× `ohlcv-1m`), `$0.19`;
  `mbo` = 4.08 M (~4,556×), `$0.26`; `trades` = 144 k (~161×), `mbp-1` = 801 k
  (~895×). **Verdict: L2 dollar cost is trivial (~$240 for a 5-symbol × ~250-day
  backtest); the binding constraint is record volume (~1.7 B rows) and the
  engineering to PIT-aggregate it leak-safely.** This keeps L2 ranked #2 below
  options flow on engineering effort, not on access or budget.
