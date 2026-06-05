# ADR-0023 findings — tier-2 move-size re-target (PENDING confirmatory proof)

> **Status: PENDING.** This document is the pre-registered results skeleton for
> ADR-0023. It is intentionally **empty of verdicts**. It is filled **only** by
> the separate, later implementation PR that runs the move-size acceptance bar
> on real data. The acceptance bar itself is frozen in
> [ADR-0023](../adr/0023-tier-2-size-gate-magnitude-retarget.md) §2 and must
> **not** be edited here after seeing results.

## 1. Pre-registered question

Does the v1 geometry family score resolve **move-size** out-of-sample strongly
enough — by the ADR-0023 §2 bar, fixed before this run — to justify re-targeting
the tier-2 `risk_sizeable` sizing gate from a direction-Brier objective to an
additive move-size objective (`magnitude_resolution_floor`)?

## 2. Pre-registered acceptance bar (copied read-only from ADR-0023 §2)

A family passes **only** if **all** hold OOS on a purged walk-forward:

1. Magnitude AUC point estimate ≥ 0.60 **and** bootstrap 95 % CI lower bound
   ≥ 0.55 (B ≥ 1000).
2. Score-alone `baseline_resolution` > 95th percentile of the label-permutation
   null (B ≥ 1000, identical bins).
3. No direction-Brier regression beyond the harness `no_regression` tolerance.
4. `MIN_OOS_SAMPLES = 40` (else inconclusive, not a pass).

Goalpost rule: a miss is a negative result; the bar is not re-tuned here.

## 3. Dataset

| Field            | Value                                                     |
|------------------|-----------------------------------------------------------|
| Events file      | `~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json` |
| Total events     | _PENDING_                                                 |
| Per family (n)   | BOS _PENDING_ · OB _PENDING_ · FVG _PENDING_ · SWEEP _PENDING_ |
| Magnitude label  | `mag_q = 0.5`, train-only `tau` (leak-safe)               |
| Folds / purge    | `n_folds = 5`, GAP-1 purge, `MIN_OOS_SAMPLES = 40`, `MIN_TRAIN_SAMPLES = 20` |

## 4. Per-family results

| Family | n_oos | mag AUC | AUC 95% CI low | baseline_resolution | perm-null p95 | resolution > null? | dir-Brier regression? | Verdict |
|--------|-------|---------|----------------|---------------------|---------------|--------------------|-----------------------|---------|
| BOS    | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ |
| OB     | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ |
| FVG    | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ |
| SWEEP  | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ | _PENDING_ |

## 5. Secondary confirmation — E[PnL] after costs

ADR-0023 §Consequences requires E[PnL]-after-cost as a secondary check: a
resolution pass that does not convert to positive sized E[PnL] is a recordable
negative, not grounds to ship the gate.

| Family | E[PnL] after cost (bps) | converts? | note |
|--------|-------------------------|-----------|------|
| BOS    | _PENDING_ | _PENDING_ | _PENDING_ |
| OB     | _PENDING_ | _PENDING_ | _PENDING_ |
| FVG    | _PENDING_ | _PENDING_ | _PENDING_ |
| SWEEP  | _PENDING_ | _PENDING_ | _PENDING_ |

## 6. Reproduction

```bash
# Score-alone magnitude resolution per family (baseline arm = the v1 score).
EV=~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json
PYTHONPATH=. .venv/bin/python scripts/run_meta_label_ab.py "$EV" \
  --feature-key vpin --label magnitude --mag-q 0.5
# The confirmatory PR adds the bootstrap-CI and label-permutation-null
# estimators (ADR-0023 §2.1, §2.2) and the gate wiring; both are new code that
# does NOT exist on main at the time ADR-0023 was written.
```

## 7. Verdict

_PENDING — to be filled by the confirmatory real-data PR. Until then, the v1
direction-Brier tier-2 gate stays in force and no family is sized on the
move-size objective._
