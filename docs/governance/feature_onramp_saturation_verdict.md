# Feature-onramp saturation verdict — the directional axis is spent, the one durable signal is sub-marginal

| Field    | Value                                                          |
|----------|---------------------------------------------------------------|
| Status   | Evidence note / onramp pause verdict (input to ADR-0019)      |
| Date     | 2026-06-04                                                    |
| Author   | skipp-dev (autonomous mandate; product owner + principal quant) |
| Related  | ADR-0019 (multi-feature family score v2), ADR-0016 (order-flow data path), [resolution feature-gap analysis](resolution_feature_gap_analysis.md) §5, EV-20 first real run |

## Why this note exists

A standing question drove this investigation: *every candidate is a sound,
well-known theorem that works in other programs — what are we missing, or doing
wrong? If none of them works for us, the fault must be in our design.*

This note records the empirical answer, reached through escalating probes on
real EV-20 Databento bars, and the verdict it produces: **the directional
single-feature onramp is saturated, the one apparent magnitude exception does not
replicate out-of-sample, and the single durable signal (regime-relative
compression) is statistically real but economically sub-marginal as a standalone
trade.** It also records the reusable methodological guardrails the investigation
surfaced, so the next axis is not mis-measured the same way.

All probe code lives offline in the `wt-ofi` worktree (`_magnitude_ab.py`,
`_sweep_deepdive.py`, `_compression_probe.py`, `_compression_tradeability.py`).
**Nothing here was gated, branched, or added to the ADR-0019 candidate queue.**

## 1. The design flaw was the label axis, not a feature shortage

Every onramp candidate was evaluated on the v1 **direction/resolution** label
(does the trade close up or down?). The sound theorems that null here —
order-flow imbalance, Kyle's λ, average trade size, VPIN-style participant size,
relative volume, Amihud, variance ratio, Williams VIX-fix, momentum ribbon — are
mostly **magnitude / volatility** theorems. They describe *how big* the next move
is, not *which direction*. Testing a magnitude theorem on a direction label is a
category error: the harness correctly returns `no_lift` because the feature
genuinely does not predict direction.

A positive-control probe confirmed the harness itself is sound (an oracle label
reaches AUC 0.84–0.86), so the nulls are real, not a broken measurement.

## 2. On the magnitude axis the v1 score already absorbs the signal — and most of it is just volatility autocorrelation

Re-running the A/B against a **magnitude label** (`1[|return| > median]`) on the
identical event set:

- Features do carry magnitude signal (e.g. `relative_volume` feature-alone AUC
  0.61–0.64 vs ~0.50 on direction).
- **But the v1 `score` is not a pure direction model** — it already scores
  0.55–0.67 on magnitude. Incremental lift (joint score+feature vs score alone)
  is ≈ 0 in 15 of 16 family×feature cells.
- A trivial **recent-vol EWMA baseline** matches or beats the score on magnitude
  for BOS/FVG/OB. That bulk magnitude predictability is plain **volatility
  autocorrelation**, already available to any ATR sizer — no new money.

The only cell where the v1 score beat the trivial vol baseline was **SWEEP**.

## 3. The SWEEP magnitude exception does NOT replicate out-of-sample

The lone exception was hardened and then tested on a third, disjoint window.

- **Cold-start purge + bootstrap (in-window):** score AUC 0.667 vs vol 0.453.
- **Fair-benchmark correction (the key methodological catch):** a benchmark with
  AUC < 0.5 is mis-specified — part of the gap was just "benchmark points down."
  Giving recent-vol its sign-oracle upper bound (`max(auc, 1−auc)`) the honest
  in-window gap is **+0.158** (CI [+0.110, +0.210]), not the inflated +0.215.
- **Third window (EV-20 run 26939799729, 2025-04-01..2025-10-01, disjoint):** the
  fair gap collapses to **+0.029** with bootstrap 90% CI **[−0.032, +0.093]**,
  P(>0)=78.6% — **not established**. The score-driven SWEEP magnitude edge is an
  in-sample fluke; it does not survive honest out-of-sample fair-benchmark testing.

## 4. The one durable signal: regime-relative compression — real but sub-marginal

The only thread with cross-window life is the **inverse** recent-vol → sweep-size
relation (low realized vol *before* a sweep → larger sweep; "compression →
breakout"), cleanly separated from the v1 score.

- **Sign stability (gate 1):** raw recent-vol magnitude AUC is inverse in **all
  three** windows (0.405 / 0.396 / 0.415) — the sign never flips. But pooled it
  washes to 0.500 because the absolute vol *level* differs between regimes
  (Simpson-style masking — the same wash-out that made earlier probes call vol a
  "coin flip").
- **Regime-relative fix (gate 1b):** using the vol **percentile rank** within a
  trailing lookback recovers the signal through pooling (W1 0.396 / W2 0.463 /
  W3 0.431 / all-3 pooled **0.453**, still inverse).
- **Out-of-sample (gate 2):** as a feature it beats the coin flip on W3 —
  sign-oracle AUC 0.569, bootstrap (AUC−0.5) 90% CI **[+0.021, +0.116]**,
  P(>0.5)=99%.

**Tradeability — the money-worth test (pre-registered pass criterion):** on W3
OOS, a long-vol (straddle-like) selection of compressed sweeps, net payoff
= `|return| − vrp_mult × TRAIN-mean|return|`:

| Cost (vrp_mult) | Net/trade | 90% CI | Per-trade Sharpe | Verdict |
|---|---|---|---|---|
| 0.0 (gross, context) | +0.373% | [+0.318, +0.432] | 1.01 | PASS (ignores premium) |
| **1.0 (fair, headline)** | **+0.063%** | **[+0.011, +0.119]** | 0.171 | **PASS (net>0, CI>0)** |
| 1.1 (realistic VRP) | +0.032% | [−0.019, +0.090] | 0.087 | UNDECIDABLE (CI crosses 0) |

The literal pre-registered bar passes at fair cost, **but the edge is razor-thin
and economically fragile**: a mere 10% variance-risk-premium — conservative for
buying short-dated vol — flips it to undecidable. The signal survives only if vol
can be bought at ≈ zero premium, which the market does not offer. **Not worth
productizing as a standalone straddle.**

### Why "compression as a position-size multiplier" is NOT a valid rescue

A sizing multiplier scales the expectation that already exists; it does not
create one:

$$\mathbb{E}[\text{PnL}] = \text{size} \times \mathbb{E}[\text{directional return}]$$

The SWEEP **direction** has no OOS-proven positive expectation (§3, the v1 score
collapsed). With $\mathbb{E}[\text{directional return}] \approx 0$, scaling up on
compressed sweeps multiplies **variance, not return**. A backtest that appeared
to "pass" this way would imply directional edge leaked in from somewhere — i.e. a
new false positive, not progress. The compression payoff is magnitude, monetised
only via a vol bet (§4), which is sub-marginal after premium. So this rescue is
**not cleanly testable today** and is explicitly rejected.

## 5. Verdict and recommendation

1. The directional OHLCV / microstructure axis is **saturated** — all candidates
   null on the only label (direction) the v1 product trades.
2. The apparent magnitude exception (SWEEP score) **does not replicate** OOS.
3. The one durable signal (regime-relative compression) is **statistically real
   and window-stable but economically sub-marginal** as a standalone trade, and
   **not monetisable as a sizing layer** for lack of a directional edge to scale.
4. Real next gains need a **different data axis**, not more formulas on the same
   bars. **Options flow (`opra` / unusual-options-activity) is the top pick** —
   it is the closest forward-looking, non-OHLCV axis and the data path is the
   most reachable next step. L2 book/queue depth and cross-asset lead-lag are the
   secondary candidates. The three axes are ranked by verified repo maturity and
   scoped as data-path projects in [ADR-0020](../adr/0020-options-flow-datapath.md).

This is not a failure: it is a cleanly evidenced "this seam is mined out, here is
the map to the next one" — the result that stops further quarters being sunk into
OHLCV feature tuning.

## 6. Reusable methodological guardrails (the real durable output)

These were the difference between an honest verdict and a shipped false positive,
and apply to every future axis:

- **Match the label to the theorem.** Magnitude/volatility theorems must be
  judged on a magnitude label (`_magnitude_ab.py` track), never on the direction
  label — a magnitude theorem will always look like `no_lift` on direction.
- **Never quote a gap against a sub-0.5 benchmark.** AUC < 0.5 means the
  benchmark is mis-specified (wrong sign, overfit). Give it the sign-oracle upper
  bound `max(auc, 1−auc)` before claiming any edge over it. This alone turned an
  overstated +0.215 into the honest +0.158.
- **Demand multi-window sign stability.** A real signal points the same way in
  every window; a sign that flips across windows is noise. Beware Simpson-style
  wash-out when pooling across regimes with different levels — normalise
  (percentile rank) before pooling.
- **Pre-register the pass criterion** (metric, cost level, OOS window) *before*
  seeing the result, and test on a window **not** used to discover the feature.
- **Distinguish FAIL from UNDERPOWERED.** A CI that crosses zero on a thin sample
  is "not decidable", not "no edge" — and conversely a thin-sample PASS is not a
  green light. State trade counts and per-trade Sharpe, not just significance.
- **A statistically real signal (AUC>0.5, CI>0) is not a tradeable edge.** Always
  run the money-worth test with realistic (not cosmetic) costs before promoting.
