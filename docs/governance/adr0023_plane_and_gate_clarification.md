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

| Plane / stream | What it measures | Source | State |
|---|---|---|---|
| **15m magnitude proof** | Does SMC structure predict move size? (the arming) | 15m FamilyEvents (frozen local store) | **frozen** — proof complete, pipeline dead |
| **1D magnitude measurement — §2 AUC AND §5 E[PnL]** | Does the score resolve move-size (§2) AND is it profitable after cost (§5)? | the SAME 1D FamilyEvent pool (rolling-bench → `accumulate_family_events`) | bootstrapping (thin; heartbeats until 40 samples/family) |
| **C13 paper trading** | Does the open-prep swing *execution* survive live paper fills? | `smc_orb_vwap_hold` incubation fills | feeds **Phase-B**, NOT this gate |

The **load-bearing fact** (corrected 2026-07-06 after review): **§5 does NOT
measure C13 paper trades.** `scripts/run_epnl_after_cost_gate.py` reads
**FamilyEvent records** and runs `extract_family_calibration_samples` — the
*same* producer the §2 resolution gate uses. So §2 (AUC) and §5 (E[PnL]) are
two checks on the **one** 1D FamilyEvent pool, both blocked by the same
`MIN_TRADES = MIN_OOS_SAMPLES = 40` samples/family floor. The C13
`smc_orb_vwap_hold` paper fills carry no SMC family and no move-size score, so
they cannot feed §5 at all — they feed the separate **C8 Phase-A→B→C execution
promotion ladder** (`evaluate_phase_criteria.py`). Three streams, three roles;
the earlier framing that "§5 measures the daily paper trades / needs C13 paper
fills" was wrong.

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
  convert to positive sized E[PnL] after costs is a recordable negative." But
  §5 reads the **same 1D FamilyEvent pool** as the §2 AUC (not the C13 paper
  fills) and needs 40 triggered samples/family — so §5 and the 1D AUC become
  measurable at the same time, from the same data.
  Since 2026-08-08, `promotion-gate-daily.yml` executes the §5 gate on that
  explicitly filtered 1D pool and persists `epnl_after_cost_<date>.json` even
  for a measured FAIL or an inconclusive sample count. A configuration/load
  failure remains a hard workflow error.
  Until a measurable calibration artifact is available to this workflow, the
  report explicitly records `cost_source=flat_default` and the pre-registered
  5 bps round-trip haircut; it does not present that placeholder as empirical
  thin-cap execution cost.
- **C13 paper trading = Phase-B, orthogonal to this gate.** It promotes the
  open-prep `smc_orb_vwap_hold` *execution* from paper to real capital
  (`evaluate_phase_criteria.py`). Valuable, but it does **not** advance
  ADR-0023 Stage 3; running the C13 paper cron does nothing for §5.

"Stage 2 stable over multiple windows", operationally, therefore means: **the
1D FamilyEvent pool reaches 40 BOS samples and BOS clears both the §2
resolution bar and the §5 E[PnL]-after-cost bar** — a data-accumulation problem
in the rolling-bench/`accumulate_family_events` pipeline (which the reseed +
score-persistence work addresses), NOT a paper-trading problem.

## 3. Consequences (implemented in this change)

1. **Cross-plane non-demotion.** `magnitude_stage_policy` gains an
   `armed_plane` field (`"15m"` for the current arming). The weekly evaluator
   proves the ledger is single-plane (existing mix guard) and then **suppresses
   demotion when the ledger plane differs from `armed_plane`** — a 1D result
   cannot revoke a 15m arming. The weekly judgement still runs as a health
   monitor; only enforcement is gated. (`scripts/eval_magnitude_shadow_weekly.py`)

   **Consequence to accept explicitly:** with the 15m proof frozen in the
   archive (never read by the weekly job) and the live 1D ledger cross-plane-
   suppressed, the weekly **auto-demotion safety net is now dormant** — no
   ledger can currently demote the armed BOS/SWEEP. This is intended (a 1D
   result must not revoke a 15m arming), but it means the real decay control
   for the armed families is §5's economic verdict, not the weekly AUC. When
   the 1D pool eventually clears 40/family, BOS's 1D verdicts should become the
   armed plane for 1D (a future `armed_plane` update), re-activating demotion
   on the plane that actually trades.

2. **§5 threshold corrected: 40, not 20.** The binding count is
   `MIN_TRADES = MIN_OOS_SAMPLES = 40` triggered FamilyEvent **samples per
   family** (`governance/epnl_after_cost.py`; these are score+return samples
   from the 1D pool, NOT paper fills), not the "≥ 20" earlier prose used. This
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
  *2026-10-01:* still open for the MAGNITUDE measurement (§2 AUC on 15m stays
  frozen). Separately, ADR-0031 (Nachtrag 2026-10-01) adds a 15m RETURNS
  observation — track-record and regime verdicts on the 15m events the pool
  already carries. It revives no pipeline, is not a gate, and changes none of
  the roles assigned in §2 above.
- Whether §5's `MIN_TRADES=40`/family is the right floor for a rare family, or
  whether rare families should be judged on a pooled/relaxed basis (a science
  decision, deliberately not taken here).
