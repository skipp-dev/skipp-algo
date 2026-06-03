# Resolution feature-gap analysis — are the candidate features the right ones?

| Field    | Value                                                          |
|----------|---------------------------------------------------------------|
| Status   | Evidence note (input to ADR-0019)                             |
| Date     | 2026-06-02                                                    |
| Author   | skipp-dev (autonomous mandate; product owner + principal quant) |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0018 (split-conformal coverage), EV-20 first real run, [why no family promotes](why_no_family_promotes_resolution_blocker.md) |

## Question

Every SMC family is blocked at tier-2 `risk_sizeable` by the `brier_threshold`
check, and the Murphy/Brier decomposition pins the binding deficit on
**resolution (discrimination)**, not on miscalibration. The forward path (M1)
is therefore "improve resolution by feeding the score better features." Before
implementing anything, the honest question is: **are the candidate features the
right ones, are any missing, and did we overlook something?** This note records
the verified answer.

## TL;DR — no, the five candidate features are not the answer

The five FVG-quality features (`gap_size_atr`, `htf_aligned`,
`distance_to_price_atr`, `is_full_body`, `hurst_50`) are a partial,
**FVG-only, linear** win and are by themselves **insufficient**. The largest
un-tapped lever is **volume / order-flow**, which a "Smart Money Concepts"
strategy paradoxically does not look at today.

## 1. What the data already says about the five features (verified)

In `scripts/fvg_quality_recalibration.py` these five features were **fitted
against realised outcomes** on 2026-04-22. The promoted `STRICT_WEIGHTS`:

| Feature                 | Weight | Reading                                            |
|-------------------------|-------:|----------------------------------------------------|
| `gap_size_atr`          |  0.45  | strong — but this is essentially today's score already (zone-thickness / ATR) |
| `distance_to_price_atr` |  0.45  | strong — the **only genuinely new** signal (displacement) |
| `htf_aligned`           | 0.0735 | weak                                               |
| `is_full_body`          | 0.0515 | weak                                               |
| `hurst_50`              |  0.0   | **zeroed — no discriminative value, drop it**      |

Three hard conclusions:

- `hurst_50` is a measured dud — empirically weighted to zero.
- `gap_size_atr` is, in substance, the current governance score
  (zone-thickness / ATR). Adding it brings almost nothing new.
- Realistically the five add **exactly one** signal orthogonal to the existing
  geometry: **displacement** (`distance_to_price_atr`).

Important caveats on this fit: it was (a) FVG-only, (b) hand-set **linear**
weights, (c) against a mitigation label — **not** the governance Brier score.
The recalibration status is usually `insufficient_features`: the five never
flowed into governance scoring at all.

## 2. What we actually overlooked — the real gap

The decisive finding: **the score is pure geometry.** No volume, no order-flow,
no liquidity context, no session, no premium/discount. For a strategy literally
named "Smart Money Concepts," institutional **order-flow is the core thesis** —
and we do not measure it. That is the most likely resolution source precisely
because these signals are **orthogonal to geometry**.

Available (data + extractors exist) but unused:

- **Order-flow / volume-imbalance / VPIN** — `ml/features/microstructure.py`
  already implements `volume_imbalance` and `vpin`
  (Easley-López de Prado-O'Hara). Bars carry volume; the trades schema carries
  `size` and `side`. This is the #1 gap.
- **Zone freshness / touch-count** — `label_fvg_mitigation` exists but not as a
  *pre-trade* feature. SMC thesis: fresh zones hold better.
- **Liquidity-sweep context** — sweep detectors exist, unused as a feature.
- **Premium / discount (position in the dealing range)** — IPDA q25/mid/q75 in
  `smc_core/htf_context.py`, unused. An ICT core concept.
- **Session / killzone / time-of-day** — `session_marker` and
  `cyclical_encoding` exist in `ml/features/temporal.py`, unused.
- **Volatility regime** — `realized_volatility`, `garman_klass_volatility`, `parkinson_volatility`
  exist in `ml/features/volatility.py`, unused.

Genuinely **absent** (would need building): VWAP distance (only a stub),
order-block candle volume, graded HTF confidence (currently a binary toggle).

**Honest data limit:** we have **trade-level** data (size + side) but **no**
order-book / DOM (MBO/MBP). True footprint/depth features are therefore **not**
possible — but trade-side imbalance and VPIN are (with tick-rule side inference
if needed).

## 3. What the literature says

- **Meta-labeling (López de Prado, AFML ch. 3)** is the architecturally correct
  shape for this exact problem: the SMC detector (primary model) sets the
  **side** (long/short); a secondary ML model decides **act-or-pass + size**
  from the probability. That is the `family_score` problem one-to-one. Bonus: it
  **limits overfitting** because the ML learns only size, not direction, and it
  fits the existing walk-forward calibration directly.
- **Order-flow analysis**: volume, VPOC and buy/sell imbalance determine the
  **strength** of support/resistance — exactly the question of whether an OB/FVG
  zone holds. This supports order-flow features as predictive.

## 4. Revised recommendation

Not "wire the five." Instead a **multi-feature meta-label score** from features
that are **orthogonal to geometry**: order-flow imbalance / VPIN + zone
freshness + liquidity-sweep + premium/discount + session — plus displacement
from the old five. Drop `hurst_50` and the redundant `gap_size_atr`.

With full rigour: **purged walk-forward CV**, and the **out-of-sample
resolution delta must be proven** before anything replaces the current score —
no silent swap. This is ADR-0019 territory.

The most honest line: the five features were a partial win from 2026-04, but
two-thirds of them are geometry redundancy plus one measured dud. The real,
un-tapped lever is **order-flow**, which a "Smart Money" strategy currently does
not look at. Whether it actually lifts resolution must be proven by an A/B run —
not assumed.

## 5. ADR-0019 shadow-candidate A/B results (2026-06-03) — the non-volume axes are empirically exhausted

The ADR-0019 purged walk-forward A/B on-ramp (`scripts/run_feature_ab.py`) has
now run **three** close/OHLC-pure shadow candidates against the v1 `score` on
**real EV-20 Databento bars across two independent regimes** (a calm window
2025-01-02..2025-04-01 and the volatile Aug-2024 window 2024-07-15..2024-10-15,
~22k recorded events). Every one returned `no_lift` across **all four** families
(BOS, FVG, OB, SWEEP) — out-of-sample resolution did not improve and the
candidate discriminated no better than (usually worse than) the baseline:

| Candidate | Axis | Source | Verdict | Notes |
|-----------|------|--------|---------|-------|
| `momentum_ribbon` | smoothed-RSI trend stack | retired (#2545) | `no_lift` ×4, both regimes | candidate AUC ≤ baseline everywhere |
| `williams_vix_fix` | downside volatility | retired (#2551) | `no_lift` ×4 | BOS 0.524<0.567, FVG 0.510<0.558, SWEEP 0.473<0.527 (sub-chance) |
| `variance_ratio` (Lo-MacKinlay VR(2)) | serial dependence / persistence | evaluated, **not adopted** | `no_lift` ×4 | BOS 0.525<0.567, FVG 0.479<0.558, OB 0.492<0.515, SWEEP 0.513<0.527 |

The Variance Ratio was the strongest available proxy for the *persistence* axis
and was empirically confirmed orthogonal to the existing signals before testing
(VR vs v1 `score` Spearman −0.173; VR vs WVF Spearman +0.095; 99.6% coverage on
real bars). Its `no_lift` verdict — together with the already-measured
`hurst_50 = 0` weight (§1, the same persistence axis) — closes the persistence
dimension: Kaufman Efficiency Ratio, Permutation Entropy and Hurst R/S all live
on this same axis and are not expected to behave differently. Because VR is
close-only it needs no live plumbing, so its A/B was run pre-merge on the same
harness and the candidate was **not merged** (no dead shadow code is carried).

This is the empirical confirmation of §2/§4: the geometry, volatility and
persistence axes that need **no volume** are now spent. The remaining un-tapped
lever is exactly the **order-flow / volume** dimension this note named as the #1
gap.

### Blocker before order-flow can be A/B-tested: the producer drops volume

`scripts/pull_databento_edge_input.py::_resampled_bars_payload` currently
serialises only `timestamp/high/low/close` **per bar** — it **drops volume**
(and `open`), even though volume is present in the upstream OHLCV frame. On real
EV-20 data this makes `relative_volume_at` 0%-coverage (always honest-`None`)
and would make Amihud illiquidity (`|r|/dollar_volume`) dead-on-arrival. So the
rational next workstream is a **producer plumbing PR** — add
`"volume": float(row.volume)` (and `"open"`) to `_resampled_bars_payload` and
re-dispatch EV-20 — which unblocks **both** a genuine `relative_volume` A/B and
the Amihud candidate, i.e. the order-flow lever itself.
