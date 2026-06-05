# ADR-0019 Magnitude / Regime A/B Findings — recorded feature suite

> **Date:** 2026-06-05
> **Scope:** Re-test of the recorded-only shadow feature suite on the
> **magnitude** label and under **regime stratification**, to falsify or confirm
> the "wrong-label-axis" hypothesis (microstructure features are magnitude/vol
> theorems that were only ever A/B-tested against the *direction* label).
> **Features:** `kyle_lambda`, `ofi_imbalance`, `relative_volume`,
> `average_trade_size`, `vrvp_vpoc_dist`, `vrvp_va_pos`
> **Harness:** `scripts/run_feature_ab.py` (purged walk-forward; `--label`,
> `--stratify-by abs_feature`)
> **Verdict: hypothesis REFUTED for the direct-input path — no promotion. The
> only residual signal is regime-gating, concentrated in `SWEEP` and thin.**

---

## 1. Why this test

Every microstructure feature in the suite measures *activity / impact / size*,
i.e. quantities that are theorems about **return magnitude**, not return
**direction**. The earlier onramp A/Bs (ADR-0019 VPIN, signed UOA, OFI, etc.)
tested them against the **direction** label and all returned `no_lift`. Before
declaring the single-feature onramp saturated, we owed each feature one fair
test on the axis it actually speaks to:

1. **Magnitude label** (`--label magnitude`): feature as a *score input*
   predicting `|forward return|` over a per-fold quantile (leak-safe vol label).
2. **Regime stratification** (`--stratify-by abs_feature`): feature as a
   *regime gate* — does conditioning on `abs(feature)` strata reveal a sub-regime
   where the v1 score's resolution is materially higher?

## 2. Data

| Parameter | Value |
|-----------|-------|
| Source | Databento `XNAS.ITCH`, 15m bars |
| Symbols | AAPL, MSFT, NVDA, AMZN, TSLA |
| Window | 2026-02-02 → 2026-05-02 (3 months) |
| Events | 10,981 (BOS 2,858 · FVG 4,587 · OB 3,039 · SWEEP 497) |
| Events file | `~/.local/share/skipp/vpin_followup/events_v2.json` |
| Coverage | `kyle_lambda` / `ofi_imbalance` / `average_trade_size` ~87%, `relative_volume` 100%, `vrvp_*` 100% |

> **Regeneration note.** The original `events.json` predated the VRVP wiring
> (#2575) and carried `vrvp_*` at 0%. The file was regenerated through the
> current `main` adapter into `events_v2.json` — **identical** 10,981-event set
> and family mix, now with `vrvp_vpoc_dist` / `vrvp_va_pos` at 100%.
> `signed_uoa_notional` remains 0% (no OPRA options sample in this equity pull)
> and is therefore **not testable here**.

## 3. Results

### 3a. Direct input (plain A/B) — `families_lifted = []` everywhere, both axes

`resolution_delta` per family (positive = lift). Min/max across the four
families:

| Feature | Direction Δ-resolution | Magnitude Δ-resolution | Lift |
|---------|-----------------------|------------------------|------|
| `kyle_lambda` | −0.0101 … −0.0009 | −0.0217 … −0.0050 | none |
| `ofi_imbalance` | −0.0068 … −0.0007 | −0.0192 … −0.0061 | none |
| `relative_volume` | −0.0072 … −0.0009 | −0.0079 … **+0.0021** | none |
| `average_trade_size` | −0.0083 … −0.0009 | −0.0236 … −0.0016 | none |
| `vrvp_vpoc_dist` | −0.0075 … −0.0012 | −0.0176 … −0.0029 | none |
| `vrvp_va_pos` | −0.0075 … −0.0010 | −0.0200 … −0.0037 | none |

Switching to the magnitude axis did **not** resurrect a single feature as a
score-additive signal. Deltas are uniformly negative (worse) on both axes; the
only positive number anywhere is a `relative_volume` / FVG blip of **+0.0021**
in one family — far below any promotion margin and not a verdict-lift. The v1
score already absorbs whatever magnitude information these features carry.

### 3b. Regime gate (`--stratify-by abs_feature`) — real but `SWEEP`-concentrated and thin

Here the features *do* carry information, but as a **regime filter on the v1
score's resolution**, not as a score input. The signal lives almost entirely in
`SWEEP` (n ≈ 360–410):

| Feature | Axis | Conditioned families | Strongest split (resolution by stratum) |
|---------|------|----------------------|------------------------------------------|
| `ofi_imbalance` | magnitude | `SWEEP` | **0.0621 vs 0.0061** (spread 0.056, ~10×, favours low-OFI) |
| `average_trade_size` | magnitude | `BOS`, `OB`, `SWEEP` | SWEEP 0.060 vs 0.012 (spread 0.048); broadest reach |
| `kyle_lambda` | dir + mag | `SWEEP` | 0.036 vs 0.025 (spread ≤ 0.011) |
| `relative_volume` | dir + mag | `SWEEP` | 0.024 vs 0.010 (spread ≤ 0.014) |
| `vrvp_va_pos` | magnitude | `SWEEP` | 0.035 vs 0.005 (spread 0.030) |
| `vrvp_vpoc_dist` | — | **none** (dead on all four passes) | — |

`average_trade_size` on the magnitude axis is the only feature reaching beyond
`SWEEP` (also conditions `BOS` n=2,065 and `OB` n=1,625). `ofi_imbalance`
produces the single largest resolution split (~10×) but on `SWEEP`'s thin
n≈360.

## 4. Interpretation

- **The "wrong-label-axis" hypothesis is refuted for the direct-input path.**
  The magnitude axis does not unlock any of these features as a score input. The
  single-feature onramp is saturated on the magnitude axis exactly as it was on
  the direction axis. **Closed.**
- **The residual signal is regime-gating, not scoring.** Microstructure
  `abs(feature)` strata condition the v1 score's resolution on `SWEEP` (and,
  for `average_trade_size`, also `BOS`/`OB` on the magnitude axis). This
  sharpens — but does not change — the standing "regime-relative compression"
  thread: the durable edge is *when* the score is trustworthy, not *what* the
  feature adds to it.
- **Thin = sub-marginal.** The strongest splits sit on `SWEEP`'s n≈360–410 OOS
  events. Per the onramp-saturation verdict this is economically sub-marginal
  and not promotion-grade on its own.
- **`vrvp_vpoc_dist` is dead; `vrvp_va_pos` barely conditions `SWEEP`-magnitude.**
  This pre-answers the planned VRVP+RJB A/B: neither VRVP scalar is
  promotion-worthy. Keep recorded-only or retire; no separate A/B needed.

## 5. Decision

| Item | Outcome |
|------|---------|
| Magnitude axis as score-input rescue | **Rejected** — no lift, both axes, all features |
| Regime-gate signal | Real, `SWEEP`-concentrated, thin → **not promotion-grade alone** |
| VRVP scalars (`vrvp_*`) | **Not promotion-worthy** — `vpoc_dist` dead, `va_pos` marginal |
| Single-feature onramp | **Saturated on both axes — CLOSED** |
| Tick-level (Hayashi-Yoshida) infrastructure | **Not justified by this evidence** — remains gated behind a cross-asset@15m null |
| Next live test | **Cross-asset lead-lag @15m** (ADR-0021, first cross-instrument signal) |

## 6. Lessons

- **Verify feature coverage in the recorded dataset before launching an A/B.**
  The original `events.json` predated the VRVP wiring and carried `vrvp_*` at
  0%; testing it would have silently measured nothing. Always regenerate through
  the current adapter and confirm per-key coverage first.
- **Fair-test a feature on the axis it speaks to before declaring it dead.** A
  magnitude theorem tested only against a direction label is a category error;
  the negative result is only durable once both axes are checked.
- **A negative result that is *thin* is still negative.** A ~10× resolution
  split on n≈360 is not a green light — pre-registered minimum-sample and
  economic-margin gates exist precisely to stop thin regime splits from being
  promoted.
