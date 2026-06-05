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
> **Verdict: NO promotion. `signed_uoa_notional` is unbuildable from the OPRA
> `trades` schema (degenerate, identically 0). `abs_uoa_activity` is a clean,
> measurable NULL — no `candidate_lifts_resolution` in any family on either
> label. ADR-0020 Meta-Label C stays LOCKED. The options-flow axis is now fully
> tested and exhausted.**

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
| Options tape | Databento `OPRA.PILLAR` `trades`, parent symbology per underlier |
| Symbols | AAPL, MSFT, NVDA, AMZN, TSLA |
| Events | 10,981 (BOS 2,858 · FVG 4,587 · OB 3,039 · SWEEP 497) |
| Events file | `~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json` |
| `abs_uoa_activity` coverage | **98.8%** (10,850 / 10,981) |
| `signed_uoa_notional` coverage | 6,352 non-null — but **0** non-zero |

> The OPRA pull, the per-underlier enrichment bridge, and the regenerated event
> files are **throwaway** infrastructure under
> `~/.local/share/skipp/vpin_followup/` — they are intentionally NOT promoted to
> the repo. Only the feature extractor, its adapter wiring, and this findings
> note are durable.

## 3. The signed feature is degenerate, not measurable

`signed_uoa_notional` is a ratio: `sum(uoa_signed_notional) / sum(uoa_abs_notional)`
over the trailing window, where each print's sign comes from the OPRA aggressor
side (`A` ask-lift = +1 bullish, `B` bid-hit = −1 bearish, `N` cross/unknown = 0).

**The OPRA `trades` schema carries no aggressor side.** On the AAPL options tape
(2026-02-02 14:30–15:00, 58,077 prints) `side.value_counts()` is `{'N': 58077}`
— 100% unknown. Every print signs to 0, so the signed numerator is always 0 and
the ratio is **identically 0.0** for all 6,352 "non-null" events.

Confirmed end-to-end: the enriched bars carry a correctly-populated
`uoa_abs_notional` (e.g. AAPL bars up to 5.9e7 premium, 1,641 / 3,996 bars hit)
while `uoa_signed_notional` is min = max = 0.0 on every bar. The A/B harness duly
returns **thin / degenerate** (a constant feature has zero variance, so
`_fit_logistic` hits its `std ≤ 0` guard and no fold pairs). This is *not* a
clean measurable null — it is an unbuildable feature given the data schema.

> Signed options flow requires quote-classified data (`cbbo` / `tbbo` / `mbp-1`
> + Lee-Ready), not `trades`. That is a separate, materially larger build and is
> **out of scope / ruled out** for this axis.

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

- **Signed options flow is unbuildable from `trades`.** The 100%-`N` aggressor
  side makes `signed_uoa_notional` identically 0. The vacuous A/B is resolved:
  the feature cannot produce `candidate_lifts_resolution` because it has no
  variance, not because directional options flow was fairly tested and failed.
- **Unsigned options activity is a clean, fair NULL.** With real variance and
  98.8% coverage, `abs_uoa_activity` was measured on every family and lifts
  nothing on either label; on the magnitude axis it actively regresses BOS/SWEEP
  calibration. The v1 score already absorbs whatever activity information the
  options tape carries — consistent with the equity-side magnitude axis being
  declared saturated in ADR-0019.
- **The stratify "exit 0"s are not unlocks.** They are `regime_conditions_resolution`,
  explicitly excluded from the Meta-Label C trigger, and here they are
  family-inconsistent and sign-flipping → noise.
- **`abs_uoa_activity` is a magnitude feature on an exhausted axis.** Unsigned
  activity is conceptually closer to the already-saturated magnitude axis than a
  genuinely new directional one, so this null is expected — but it was free to
  confirm now that the datapath exists.

## 6. Decision

| Item | Outcome |
|------|---------|
| `signed_uoa_notional` via OPRA `trades` | **Unbuildable** — degenerate (side = `N`, feature ≡ 0). Ruled out. |
| Quote-classified signed flow (`cbbo`/`tbbo`/`mbp-1` + Lee-Ready) | **Out of scope** — not justified by this evidence |
| `abs_uoa_activity` as score input | **Rejected** — no lift on either label, all four families |
| `abs_uoa_activity` regime gate | `regime_conditions_resolution` only → **does not unlock**; family-inconsistent + sign-flipping = noise |
| ADR-0020 Meta-Label C | **STAYS LOCKED** (no `candidate_lifts_resolution`) |
| Options-flow (OPRA UOA) axis | **Fully tested — EXHAUSTED** |
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
- **Verify the source schema supplies the field a feature needs.** A signed
  options-flow feature needs an aggressor side; OPRA `trades` does not carry one.
  Confirm the raw field exists and is populated before building the feature on
  top of it.
- **A `regime_conditions_resolution` that flips sign between labels is noise.**
  The pre-registered rule (only `candidate_lifts_resolution` unlocks) is exactly
  what stops a thin, sign-unstable regime split from being mistaken for an edge.
