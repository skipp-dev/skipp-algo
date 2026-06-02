# ADR-0015: Edge proof and calibration are separate promotion tiers

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Accepted (decision) — implementation staged as a separate, reviewed PR; **no gate code changed by this ADR** |
| Date     | 2026-06-02                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0002 (promotion eligibility), ADR-0008 (gate thresholds), EV-15/EV-24 calibration, EV-20 first real run |

## Context

The EV-20 first real Databento run (5 decisions, run 26791442554) and the
follow-up resolution + PSR cost-parity audit
(`scripts/ev20_resolution_cost_audit.py`) produced the first product-grade
evidence about where the SMC families actually stand:

- **The return edge is real and benchmark-robust.** Recomputing PSR
  (Bailey/López de Prado) against a regime-neutral SPY buy-and-hold proxy
  (annual Sharpe 0.55), not just against zero, leaves PSR at **0.99–1.00**
  for BOS/OB/FVG. The earlier suspicion that "PSR only saturates because the
  benchmark is zero" was **falsified**.
- **On the true time-basis the edge is, if anything, stronger.** After the
  EV-20 `periods_per_year` fix (ADR-adjacent, PR #2513) the per-event Sharpe
  re-annualised on the *realised* event cadence (431–571 events/yr for
  BOS/OB/FVG) is **2.9–5.1**, higher than the legacy `sqrt(252)` headline —
  the daily-bar basis had *understated* the frequent-event families. (SWEEP,
  at 62 events/yr, corrects the other way: 4.07 → 2.02, and is anyway
  inconclusive at n=100 < 120.)
- **Every family is blocked by the `brier_threshold` check, not by the edge
  proof.** Brier clusters at 0.234–0.257 against a 0.22 bar. The Murphy/Brier
  decomposition shows the binding deficit is **resolution (discrimination)**,
  3–6 % near the lower bound — *not* miscalibration: ECE is low (~0.035) for
  BOS/OB/FVG, so the probabilities are well-*calibrated* but weakly
  *discriminating*.

The decisive structural fact: the calibration target is declared in the
producer itself as `sign_return_secondary_diagnostic`
(`governance/family_calibration.TARGET_TAG`, GAP 2) — a **win-rate
diagnostic, explicitly NOT an edge proof**. Yet `governance/promotion_gate`
emits `brier_threshold` as a hard `blocker`, so `promoted` is `False` and the
verdict layer can never reach `edge_supported` while brier sits above the bar
— even though the verdict layer's own `primary_metric` is PSR, not brier.

The gate therefore **conflates two distinct questions** and lets the
secondary one veto the primary one:

1. *Does this family have a real, benchmark-robust edge?* (PSR / MinTRL / FDR
   / significance — the primary edge proof.)
2. *Can we precisely size and risk-manage that edge from its probability
   estimates?* (Brier / ECE / resolution — calibrated sizing.)

The product owner has already ruled that gating the **sellable** result
behind question 2 is wrong ("Mit Kalibrierung verkaufen wir noch gar nichts"):
an investor buys a *proven edge*, and *calibrated sizing* is a hardening
milestone on top of it — not a precondition for recognising the edge exists.

## Decision

Adopt a **two-tier promotion taxonomy** that separates the two questions
instead of fusing them. This is the synthesis of the A/B fork — structurally
option **B** (the brier veto is removed from edge-recognition), with option
**A** retained as the roadmap to the higher tier.

- **Tier 1 — `edge_supported` (edge proof).** Gated by the *primary* edge
  evidence only: PSR, MinTRL, FDR-adjusted significance, sample adequacy,
  and the lookahead/regime/PSI-drift integrity guards (ADR-0014). Brier/ECE
  **do not gate this tier.** A family that clears tier 1 has a recognised,
  benchmark-robust edge and is the first object with sales value.
- **Tier 2 — `risk_sizeable` (calibrated sizing).** A strictly **higher**
  bar: tier 1 **plus** the brier/ECE/resolution thresholds, unchanged
  (`brier_max = 0.22`, `ece_max` per ADR-0008). A family here has an edge
  whose probability estimates are sharp enough to size and risk-manage
  automatically.

This is **not** a threshold change and **not** a goalpost move:

- No threshold is lowered. `brier_max` stays at 0.22; `ece_max` is unchanged.
- No family is promoted to a tier it has not earned. Under this taxonomy
  BOS/OB/FVG become `edge_supported` (tier 1) but **not** `risk_sizeable`
  (tier 2) — an honestly *lower* status than today's "fully promoted", never
  a pass.
- The full set of checks is preserved; only their **mapping to tiers**
  changes. Nothing that blocked before is deleted — the brier/ECE checks are
  **relocated** to the tier they actually evidence (sizing), not removed.
- The conflation that let a documented *secondary* diagnostic veto the
  *primary* edge proof is removed — a stricter, more honest separation, not a
  weaker one.

Option A (sharpen the signal — lift resolution above ~6 % via discriminating
features such as confluence strength, HTF alignment, and liquidity context so
brier falls below 0.22) is **retained as the tier-2 roadmap**, not abandoned.
Tier 2 is where the real sizing/risk product value lives; A is how a family
graduates from tier 1 to tier 2.

### Scope boundary of this ADR

This ADR **records the decision only**. It changes **no gate code**. The
implementation — a `risk_sizeable` tier in `governance/family_verdict` /
`governance/promotion_gate` with the brier/ECE checks re-tagged from
edge-blocking to tier-2-blocking, plus tests pinning that a tier-1 family with
failing brier lands `edge_supported` **and** `risk_sizeable=False` — lands as
a separate, reviewed PR so the taxonomy change is auditable in isolation.

## Alternatives considered

- **Pure A — keep brier as a single hard blocker; ship nothing until
  brier < 0.22.** Rejected. It conflates "has an edge" with "is calibrated",
  indefinitely withholds a *proven, benchmark-robust* edge behind a
  diagnostic the code itself labels secondary, and contradicts the product
  owner's ruling that the sellable result must not be gated on calibration.
- **Pure B — delete the brier/ECE blocker outright.** Rejected. Calibrated
  probabilities have genuine product value (position sizing, risk
  management); discarding the check would lose the tier-2 signal entirely and
  *is* a goalpost move. The tiered decision keeps every check, only at the
  tier it evidences.
- **Lower `brier_max` to ~0.25 so the families pass.** Rejected outright —
  this is the admin-bypass / tune-to-pass antipattern; it manufactures a pass
  rather than recognising the real, separable state of the evidence.

## Consequences

- Once implemented, BOS/OB/FVG (subject to confirmation on a clean
  `observed_periods_per_year` run) become **`edge_supported`** — the first
  recognised, sellable edge — while honestly carrying `risk_sizeable=False`
  pending resolution improvement.
- The next live EV-20 run gains a concrete, pre-registered milestone:
  **M1 = the first family reaching tier 2 (`risk_sizeable`, brier < 0.22)**,
  *and* confirmation that BOS/OB/FVG hold tier 1 under the new taxonomy on
  the corrected time-basis.
- Investor-facing narrative becomes truthful and concrete: "a proven,
  benchmark-robust edge today (tier 1); calibrated automated sizing is the
  next hardening milestone (tier 2)" — no reliance on "calibration" as the
  headline.
- Risk: a tier-1 edge that is never sized well still ships as tier 1. This is
  accepted and bounded — tier 1 is an *edge-existence* claim, sized manually
  / conservatively until tier 2; the taxonomy makes that limitation explicit
  rather than hiding it behind a single pass/fail.

## Evidence

- [`scripts/ev20_resolution_cost_audit.py`](../../scripts/ev20_resolution_cost_audit.py)
  — resolution band + PSR-vs-SPY reconstruction + true-cadence SR
  (`SRtrue`), reading `extra.observed_periods_per_year` when present.
- [`governance/family_calibration.py`](../../governance/family_calibration.py)
  — `TARGET_TAG = "sign_return_secondary_diagnostic"` (brier is a win-rate
  diagnostic, not an edge proof).
- [`governance/promotion_gate.py`](../../governance/promotion_gate.py)
  — `brier_threshold` emitted as a hard `blocker` (the conflation this ADR
  resolves).
- [`governance/family_verdict.py`](../../governance/family_verdict.py)
  — verdict `primary_metric` is the hypothesis-registered metric (PSR), yet
  `edge_supported` requires `promoted=True` (which brier currently vetoes).
- EV-20 run 26791442554 (5 archived promotion decisions) — PSR 0.99–1.00 vs
  SPY; brier 0.234–0.257; resolution 3–6 % near the lower bound.

## Status

Accepted (decision). Implementation staged as a separate, reviewed PR; no
gate code is changed by this ADR.
