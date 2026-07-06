# ADR-0023 clarification — measurement planes, the binding gate, and family classification

> **Status: ACCEPTED (2026-07-06).** A follow-up clarification to
> [`adr0023_live_rollout_handover.md`](adr0023_live_rollout_handover.md). It
> does not change the §2 acceptance bar or the staged-rollout mechanics; it
> resolves an ambiguity that had three measurement planes running silently
> against each other, and records three governance consequences (now
> implemented). Prompted by the daily magnitude ledger freezing unnoticed for
> weeks and by the discovery that the §5 economic gate measures a different
> timeframe than the arming rests on.

## 1. The problem: three planes, silently conflated

ADR-0023 arms **BOS** and **SWEEP** (Stage 2) on a **15m** SMC magnitude
proof (AUC 0.62 / 0.69, large out-of-sample n). But three different things
were being treated as one:

| Plane / stream | What it measures | Timeframe | State |
|---|---|---|---|
| **15m magnitude proof** | Does SMC structure predict move size? (the arming) | 15m intraday | **frozen** — proof complete, pipeline dead (no fresh 15m events) |
| **1D magnitude measurement** | Same question, on daily bars (CI rolling-bench) | 1D | bootstrapping (thin; heartbeats until `MIN_OOS`) |
| **§5 E[PnL]-after-cost** | Do the trades make money after costs? (the Stage-3 gate) | **daily** (open-prep swing, `smc_orb_vwap_hold`) | not started — needs C13 paper fills |

The **load-bearing fact**: the operational system that actually risks capital —
open-prep daily swing setups sized by magnitude, and the §5 gate that measures
them — runs on the **daily** timeframe. The 15m result was the *discovery*, not
the plane the money trades. Yet the arming, the daily measurement, and the §5
gate were being read as if they were one coherent "BOS/SWEEP magnitude edge",
when they are three experiments on two timeframes.

## 2. The decision

**Assign each plane one explicit role, and let the economic gate be binding.**

- **15m = frozen proof of concept.** It established that the edge exists. It is
  **not** re-confirmed on 15m (reviving a 15m pipeline for a plane no capital
  trades is high cost, low value). It stays as documented discovery.
- **1D magnitude measurement = health monitor, not a gate.** The daily
  rolling-bench + weekly k-of-n evaluator run on 1D to detect *gross* edge
  decay on the operational timeframe. A 1D result does **not** gate Stage 3
  and does **not** demote a 15m arming.
- **§5 E[PnL]-after-cost = the binding Stage-2→3 gate.** The handover's own
  logic already subordinates the AUC to §5: "a resolution pass that does not
  convert to positive sized E[PnL] after costs is a recordable negative." The
  economically-relevant confirmation is inherently daily (it measures the daily
  paper trades) and needs `MIN_TRADES = 40` triggered fills per family.

"Stage 2 stable over multiple windows", operationally, therefore means: **BOS
delivers durably positive magnitude-sized E[PnL] after costs on the daily
paper track (§5)** — monitored, as an early-warning, by the 1D AUC.

## 3. Consequences (implemented in this change)

1. **Cross-plane non-demotion.** `magnitude_stage_policy` gains an
   `armed_plane` field (`"15m"` for the current arming). The weekly evaluator
   proves the ledger is single-plane (existing mix guard) and then **suppresses
   demotion when the ledger plane differs from `armed_plane`** — a 1D result
   cannot revoke a 15m arming. The weekly judgement still runs as a health
   monitor; only enforcement is gated. (`scripts/eval_magnitude_shadow_weekly.py`)

2. **§5 threshold corrected: 40, not 20.** The binding count is
   `MIN_TRADES = MIN_OOS_SAMPLES = 40` triggered fills **per family**
   (`governance/epnl_after_cost.py`), not the "≥ 20" earlier prose used. This
   roughly doubles the time to a first BOS §5 verdict and makes SWEEP
   effectively unmeasurable on §5. The handover and progress-summary docs are
   corrected.

3. **SWEEP reclassified `proof_of_concept_15m`.** SWEEP's 15m proof is valid,
   but SWEEP is too rare on the daily plane to reach `MIN_OOS=40` (AUC) **or**
   `MIN_TRADES=40` (§5) — it cannot be operationally confirmed. It **stays
   armed** (the fail-closed protection is preserved) but is flagged, via the
   git-versioned `FAMILY_CLASSIFICATION` constant and a policy history entry,
   as not expected to reach operational confirmation. **BOS is the only
   operationally viable candidate.** (`governance/magnitude_stage_policy.py`)

## 4. What this does NOT change

- The §2 acceptance bar (frozen).
- The arming itself: BOS and SWEEP stay armed; nothing is de-armed.
- The fail-closed enforcement (an armed family with unmeasured magnitude is
  info-blocked; a measured FAIL on the *armed* plane hard-blocks).
- Stage 3 is still gated on §5 and still not started.

## 5. Open items this surfaces (not decided here)

- Whether to ever revive a 15m measurement pipeline (only worth it if a 15m
  operational system is planned).
- Whether §5's `MIN_TRADES=40`/family is the right floor for a rare family, or
  whether rare families should be judged on a pooled/relaxed basis (a science
  decision, deliberately not taken here).
