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
