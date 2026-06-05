# ADR-0020 Options-Flow (OPRA UOA) A/B Findings — recorded feature suite

> **Date:** 2026-06-05
> **Scope:** Deliberate build-out of the OPRA options-flow datapath to A/B-test
> the recorded-only options Unusual-Options-Activity (UOA) shadow features that
> were previously *built but untestable* (no options sample existed in the
> equity-only pulls). Two candidates: the **signed** premium imbalance and its
> direction-free **unsigned activity** companion.
> **Features:** `signed_uoa_notional` (ADR-0020 directional candidate),
> `abs_uoa_activity` (ADR-0020 Path-B activity candidate)
> **Harness:** `scripts/run_feature_ab.py` (purged walk-forward; `--label`,
> `--stratify-by abs_feature`)
> **Verdict: NO promotion. `signed_uoa_notional` is degenerate on the OPRA
> `trades` schema (aggressor side ≡ `N`), but the production `tcbbo` quote-rule
> path (#2569) makes it genuinely non-degenerate — and when fairly A/B-tested on
> that real quote-classified data it is a clean, measurable NULL (no
> `candidate_lifts_resolution` in any family on either label). `abs_uoa_activity`
> is likewise a clean, measurable NULL. ADR-0020 Meta-Label C stays LOCKED. The
> options-flow axis — signed *and* unsigned — is now fully and fairly tested and
> exhausted.**

---

## 1. Why this test

`signed_uoa_notional` (`governance/family_signed_uoa_notional_v2.py`) was wired
into the adapter under ADR-0020 as a recorded-only directional candidate, but
every prior dataset was an equity-only Databento pull with **0% options
coverage** — the feature was built but had never seen a single real sample, so
its A/B was vacuous. The pre-registered Meta-Label C unlock is gated on a
`candidate_lifts_resolution` verdict on **real** data; we owed the feature one
honest pull of the entitled `OPRA.PILLAR` options tape.

Building the datapath also let us test the literal reading of *unusual options
activity* — the **unsigned** premium-magnitude axis — via a direction-free
companion `abs_uoa_activity`: the recent option-premium notional over its own
trailing baseline (`> 1` = unusually busy tape, `< 1` = quiet). This is the only
genuinely options-native signal we can extract once the directional path is
ruled out, and the data was already paid for ($0.00, flat-rate plan).

## 2. Data

| Parameter | Value |
|-----------|-------|
| Underlier bars | Databento `XNAS.ITCH`, 15m, 2026-02-02 → 2026-05-03 |
| Options tape (unsigned) | Databento `OPRA.PILLAR` `trades`, parent symbology per underlier |
| Options tape (signed) | Databento `OPRA.PILLAR` `tcbbo` (trade + consolidated BBO), parent symbology — production producer #2569 |
| Symbols | AAPL, MSFT, NVDA, AMZN, TSLA |
| Events | 10,981 (BOS 2,858 · FVG 4,587 · OB 3,039 · SWEEP 497) |
| `abs_uoa_activity` events file | `~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json` |
| `abs_uoa_activity` coverage | **98.8%** (10,850 / 10,981) |
| `signed_uoa_notional` (`trades`) coverage | 6,352 non-null — but **0** non-zero (degenerate) |
| `signed_uoa_notional` (`tcbbo`) events file | `~/.local/share/skipp/vpin_followup/events_v4_tcbbo.json` |
| `signed_uoa_notional` (`tcbbo`) coverage | 6,352 non-null — **6,336 non-zero**, uniq 5,257, range [−1, +1] |

> The OPRA pull, the per-underlier enrichment bridge, and the regenerated event
> files are **throwaway** infrastructure under
> `~/.local/share/skipp/vpin_followup/` — they are intentionally NOT promoted to
> the repo. Only the feature extractor, its adapter wiring, and this findings
> note are durable.

## 3. The signed feature: degenerate on `trades`, fairly NULL on `tcbbo`

`signed_uoa_notional` is a ratio: `sum(uoa_signed_notional) / sum(uoa_abs_notional)`
over the trailing window, where each print's sign comes from the OPRA aggressor
side (`A` ask-lift = +1 bullish, `B` bid-hit = −1 bearish, `N` cross/unknown = 0).

### 3a. Why `trades` is degenerate (not measurable)

**The OPRA `trades` schema carries no aggressor side.** On the AAPL options tape
(2026-02-02 14:30–15:00, 58,077 prints) `side.value_counts()` is `{'N': 58077}`
— 100% unknown. Every print signs to 0, so the signed numerator is always 0 and
the ratio is **identically 0.0** for all 6,352 "non-null" events. The harness
duly returns thin/degenerate (a constant feature has zero variance, so
`_fit_logistic` hits its `std ≤ 0` guard and no fold pairs). This is *not* a
measurable null on `trades` — the feature simply has no variance there.

### 3b. Reconstructing the sign with the `tcbbo` quote rule (#2569)

The sign is recoverable from quote-classified data. The production producer
(`scripts/pull_databento_edge_input.py`, PR #2569) pulls the **`tcbbo`** schema
(trade + consolidated BBO: an NBBO attached to every print) and reconstructs the
aggressor with the quote rule — `price ≥ ask` → `A` (+bullish), `price ≤ bid` →
`B` (−bearish), inside / locked / missing-quote → `N`. A bounded cost-probe
(AAPL, same 30-min window) confirmed it works on real data at **$0.00** (flat-rate
plan): 58,077 prints split A 18,823 / B 17,854 / N 21,400 — **63.2% signed-able**,
with real signed-notional variance.

The full window was then enriched through the production producer for all five
underliers (51–70% signed-able per symbol; ≈9.7M–32.1M prints each), regenerated
into `events_v4_tcbbo.json`. The feature is now **genuinely non-degenerate**:
6,336 of 6,352 non-null events are non-zero, **uniq = 5,257**, bidirectional in
[−1, +1]. This is the fair test the `trades` run could not be.

### 3c. The signed feature is a clean measurable NULL on `tcbbo`

With real variance, all four families were measured on both labels. The plain
A/B (the only verdict that can unlock Meta-Label C) lifts **nothing**:

| Family | n_oos | Direction Δ-res | Magnitude Δ-res | Lift |
|--------|------:|----------------:|----------------:|------|
| BOS | 1,390 | −0.00402 | −0.01728 (regresses calibration) | none |
| FVG | 1,020 | −0.00217 | −0.00657 | none |
| OB | 1,150 | −0.00206 | −0.00848 | none |
| SWEEP | 270 | −0.00394 (regresses calibration) | −0.01629 (regresses calibration) | none |

Every delta is negative on both axes; `families_lifted = []` on both labels
(exit 2, *measurable* no-lift). Direction stratify (`--stratify-by abs_feature`)
returns `families_conditioned = []` — **no regime effect** in any family. Only the
magnitude-label stratify produced a single exit-0
(`regime_conditions_resolution` on SWEEP, spread +0.0152, favouring the
high-activity stratum) — but that is a **regime** verdict, which the
pre-registered ADR-0020 rule explicitly excludes from the Meta-Label C trigger,
and it sits on a thin sub-sample (n ≈ 135/stratum), matching the same
thin-SWEEP-regime noise pattern documented for `abs_uoa_activity` below and in
ADR-0019.

> Directional options flow is therefore **fairly tested and ruled out on this
> axis** — not unbuildable, not out of scope. The `tcbbo` producer exists, the
> sign is real, and it does not lift resolution over the v1 score.

## 4. The unsigned activity feature is a clean measurable NULL

`abs_uoa_activity` reads the populated `uoa_abs_notional`, so it is
non-degenerate — per-family variance is real (uniq 221–1,650; range 0–3.9). All
four families were measured on both labels.

### 4a. Direct input (plain A/B) — `families_lifted = []`, both labels

`resolution_delta` per family (positive = lift):

| Family | n_oos | Direction Δ-res | Magnitude Δ-res | Lift |
|--------|------:|----------------:|----------------:|------|
| BOS | 2,355 | −0.00758 | −0.01102 (regresses calibration) | none |
| FVG | 1,965 | −0.00513 | −0.00350 | none |
| OB | 1,790 | −0.00030 | −0.00464 | none |
| SWEEP | 410 | −0.00962 | −0.01203 (regresses calibration) | none |

Every delta is negative (worse) on both axes; on the magnitude label BOS and
SWEEP additionally **regress calibration** (`no_regression = false`). There is no
family in which recent unsigned options activity adds to the v1 score.

### 4b. Regime gate (`--stratify-by abs_feature`) — does NOT unlock, and is noise

Stratifying returns exit 0 in **regime mode** (`regime_conditions_resolution`),
which per the pre-registered ADR-0020 rule **does not unlock Meta-Label C** —
only `candidate_lifts_resolution` (plain A/B, §4a) does. And the regime effect is
not even a stable axis:

| Label | Conditioned | Favourable stratum | Spread |
|-------|-------------|--------------------|-------:|
| direction | FVG | **low**-activity (res 0.0124 vs 0.0013) | 0.0111 |
| direction | SWEEP | **high**-activity (res 0.0300 vs 0.0109) | 0.0191 |
| magnitude | SWEEP | **low**-activity (res 0.0265 vs 0.0146) | 0.0119 |

The favourable stratum is **family-inconsistent** (FVG favours low activity,
SWEEP favours high) and, worse, **flips for SWEEP between labels** (high under
direction → low under magnitude). A real regime axis does not reverse sign when
you change the outcome label on the same events — this is noise on thin
sub-samples (n ≈ 200/stratum), not a conditioning signal.

## 5. Interpretation

- **Signed options flow is degenerate on `trades` but real on `tcbbo`.** The
  100%-`N` aggressor side makes `signed_uoa_notional` identically 0 on `trades`
  — a zero-variance artifact, not a verdict. The production `tcbbo` quote-rule
  producer (#2569) recovers the sign (51–70% signed-able per symbol, uniq 5,257),
  turning the vacuous test into a fair one.
- **Fairly tested, signed flow is a clean NULL.** On real quote-classified data
  the plain A/B lifts nothing in any family on either label, and on the
  magnitude axis BOS/SWEEP regress calibration. Directional options flow does not
  add to the v1 score.
- **Unsigned options activity is a clean, fair NULL too.** With real variance and
  98.8% coverage, `abs_uoa_activity` was measured on every family and lifts
  nothing on either label; on the magnitude axis it actively regresses BOS/SWEEP
  calibration. The v1 score already absorbs whatever activity information the
  options tape carries — consistent with the equity-side magnitude axis being
  declared saturated in ADR-0019.
- **The stratify "exit 0"s are not unlocks.** They are `regime_conditions_resolution`,
  explicitly excluded from the Meta-Label C trigger, and here they are thin and
  (for the unsigned feature) family-inconsistent and sign-flipping → noise.
- **Both options-flow sub-axes are now exhausted.** Signed (directional) and
  unsigned (activity/magnitude) were each measured on real, non-degenerate data
  and neither lifts. The OPRA UOA axis is closed.

## 6. Decision

| Item | Outcome |
|------|---------|
| `signed_uoa_notional` via OPRA `trades` | **Degenerate** — side = `N`, feature ≡ 0 (zero variance, not a verdict) |
| `signed_uoa_notional` via OPRA `tcbbo` quote rule (#2569) | **Built + fairly A/B-tested — clean NULL.** No `candidate_lifts_resolution` in any family on either label; magnitude regresses BOS/SWEEP calibration |
| Signed-flow magnitude regime gate | `regime_conditions_resolution` on SWEEP only (thin, n≈135) → **does not unlock** |
| `abs_uoa_activity` as score input | **Rejected** — no lift on either label, all four families |
| `abs_uoa_activity` regime gate | `regime_conditions_resolution` only → **does not unlock**; family-inconsistent + sign-flipping = noise |
| ADR-0020 Meta-Label C | **STAYS LOCKED** (no `candidate_lifts_resolution` on either feature) |
| Options-flow (OPRA UOA) axis | **Fully + fairly tested — EXHAUSTED** (signed and unsigned) |
| OPRA datapath | **Throwaway** — kept under `~/.local/share/skipp/vpin_followup/`, not promoted |

Both extractors are retained in-repo as **recorded-only** shadow features
(`signed_uoa_notional`, `abs_uoa_activity`) so the result is reproducible and the
adapter remains audit-complete. Neither feeds the score or the gate.

## 7. Lessons

- **"Non-null count" can mask a degenerate feature.** 6,352 events carried a
  "non-null" `signed_uoa_notional` and every one was 0.0. Always check
  **variance / uniqueness**, not just `is not None`, before trusting an A/B —
  the harness's "thin" verdict was the only thing standing between us and a
  silently meaningless test.
- **Verify the source schema supplies the field a feature needs — then find the
  schema that does.** A signed options-flow feature needs an aggressor side;
  OPRA `trades` does not carry one, so the feature was degenerate. The fix was
  not to abandon the axis but to switch to `tcbbo` (NBBO per print) and
  reconstruct the side with the quote rule — only then is the A/B a fair test.
- **Don't declare an axis exhausted until the feature is non-degenerate.** An
  earlier pass nearly closed signed options flow on the strength of the
  degenerate `trades` result; the real verdict required the `tcbbo` producer and
  a genuinely varying feature (uniq 5,257) before the NULL could be trusted.
- **A `regime_conditions_resolution` that flips sign between labels is noise.**
  The pre-registered rule (only `candidate_lifts_resolution` unlocks) is exactly
  what stops a thin, sign-unstable regime split from being mistaken for an edge.
