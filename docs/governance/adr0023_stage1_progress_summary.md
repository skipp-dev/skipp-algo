# ADR-0023 Stage-1 — stakeholder progress summary (move-size axis)

> **Audience: non-specialist.** This is a plain-language companion to the
> technical findings. The numbers come from the pre-registered runs recorded in
> [adr0023_magnitude_retarget_findings.md](adr0023_magnitude_retarget_findings.md),
> [adr0022_meta_label_joint_findings.md](adr0022_meta_label_joint_findings.md)
> and [adr0023_live_rollout_handover.md](adr0023_live_rollout_handover.md). It
> does **not** introduce new claims — it explains the existing ones.
>
> **Status: 2026-06-06.** Stage-1 wiring complete; rollout stays in shadow
> (measure-only). No live capital is sized differently yet.

## The core result in one sentence

We proved on real market data that our signal can predict **how large** the next
price move will be — for two of four setup families with statistical
confidence — which opens a new, viable direction for position sizing.

## 1. The two "axes"

Think of each trading setup like a weather forecast. There are two different
questions you can ask:

| Axis | Question | Analogy |
|------|----------|---------|
| **Direction** | Does the price go **up or down**? | "Will it rain tomorrow — yes or no?" |
| **Magnitude (move-size)** | **How large** is the move, regardless of direction? | "A drizzle or a downpour?" |

The strategy historically tried to make money on the **direction** axis. The key
shift of the last days: we measured that our signal works markedly better on the
**magnitude** axis.

**The metric (AUC) in plain terms** — AUC is the probability that the signal
ranks a genuinely large move above a small one:

- `0.50` = coin-flip (worthless)
- `0.60` = the bar we fixed **in advance**
- higher = better

## 2. What was tested, and what came out

### Positive finding A — the direction axis is exhausted (cleanly proven)

We long suspected no combination of our features predicts **direction**. Until
now that was only tested per feature, leaving a back door: "maybe the
*combination* works." We closed that door. A joint (multivariate) model over
**signal + up to 8 features at once** (order-flow, VPIN, volume-profile, options
flow, and more) added **no value** in **every** configuration (all deltas inside
the noise band of ±0.001). The "everything-in" variant even slightly **degraded**
the best setup (BOS) — the classic signature of overfitting an exhausted axis.

**Why this is a positive result:** we now know with confidence that further
searching on the direction axis would be wasted effort. That redirects energy to
the axis that actually works.

### Positive finding B — the magnitude axis works (the breakthrough)

In the **same** test the decisive number was the magnitude axis. Results on real
OPRA data (~11,000 events, 5 symbols, a clean purged walk-forward so nothing
leaks from the future):

| Family | Magnitude AUC | Bar 0.60 cleared? | Permutation null | Verdict |
|--------|---------------|-------------------|------------------|---------|
| **BOS** | **0.618** | yes | not explained by chance (p ≈ 0.001) | **PASS** |
| **SWEEP** | **0.663** | yes | not explained by chance (p ≈ 0.001) | **PASS** |
| FVG | 0.553 | no | effect real but too weak | honest negative |
| OB | 0.562 | no | effect real but too weak | honest negative |

What was done well for trustworthiness:

- The bar (AUC ≥ 0.60, lower confidence bound ≥ 0.55) was locked **before** the
  run — no moving the goalposts afterwards.
- A **permutation test** answers "could a result like this appear by chance?" —
  for BOS/SWEEP the answer is a clear no.
- FVG/OB are logged as **honest negatives**, not re-tuned into passes.

### Positive finding C — the signal is not just resolving, it is profitable

One open worry remained: a statistically clean signal is useless if it makes no
money **after trading costs**. That secondary check (ADR-0023 §5) was just built
and run on real data (5 bps cost):

| Family | Equal-weight | With magnitude sizing | Lower 95% bound | Sizing uplift | Verdict |
|--------|--------------|-----------------------|-----------------|---------------|---------|
| **BOS** | +13.2 bps | **+21.6 bps** | **+16.7 bps** | +8.4 bps | **PASS** |
| **SWEEP** | +16.6 bps | **+23.9 bps** | **+9.8 bps** | +7.4 bps | **PASS** |

**Translated:** weighting positions by the predicted move *size* raises expected
profit per trade noticeably — and stays clearly positive **even in the
pessimistic case** (the lower confidence bound). This is the first hard evidence
that the magnitude axis carries not only statistically but **economically**.

## 3. Infrastructure built to support this

So these findings do not become a flash in the pan, we built a staged,
safety-first governance scaffold. Everything currently runs in **shadow mode**
(measure only, nothing armed). No capital is sized differently until every stage
is green.

Merged in the last days:

| PR | Building block | Function |
|----|----------------|----------|
| #2583 | Daily shadow runner | measures magnitude resolution |
| #2584 | Weekly k-of-n evaluator | "does a setup pass robustly across weeks?" |
| #2585 | Snapshot wiring | connects the measurement to the promotion gate |
| #2586 | §5 E[PnL]-after-cost check | the profitability blocker for Stage 3 |
| #2587 | Daily scheduler | automates the daily measurement |

Design principle: the gate can only ever **block**, never silently **unlock**
sizing. Where there is no measurement, it does nothing.

## 4. Planned next steps

The rollout has **three stages**. We are at the end of **Stage 1**.

1. **Stage 1 — shadow / measure only** (essentially complete)
   - All four families are measured passively each day (BOS/SWEEP as candidates,
     FVG/OB as a negative control group).
   - Dispatch the scheduler once manually from the Actions UI to confirm the
     no-data green path.
   - **Accumulate evidence**: several weeks of shadow data so the weekly k-of-n
     evaluator shows BOS/SWEEP pass **stably over time**, not just on one date.

2. **Stage 2 — parallel trial** (not started)
   - Run magnitude sizing **in parallel** and compare against the active
     direction gate — still with no real effect on orders.

3. **Stage 3 — arming** (not started, guarded by §5)
   - Only once the E[PnL]-after-cost check stays **durably** positive may the
     tier-2 sizing gate switch from the direction axis to the magnitude axis.

**In short:** the scientific question is answered (magnitude beats direction, and
it is profitable). What remains is **patient confirmation over time** and a
clean, staged arming — with no shortcuts.
