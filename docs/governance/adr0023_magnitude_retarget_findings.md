# ADR-0023 findings — tier-2 move-size re-target (confirmatory proof)

> **Status: RESOLVED (2026-06-05).** This document was filled by the confirmatory
> implementation PR that runs the ADR-0023 §2 move-size acceptance bar on real
> data. The bar itself is frozen in
> [ADR-0023](../adr/0023-tier-2-size-gate-magnitude-retarget.md) §2 and was
> **not** edited after seeing results. Outcome: the v1 score clears the full bar
> for **2 of 4** families (BOS, SWEEP); FVG and OB miss on the discrimination
> floor. Per the goalpost rule the misses are recorded as negatives, not re-tuned.

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
| Total events     | 10 981                                                    |
| Per family (n)   | BOS 2858 · OB 3039 · FVG 4587 · SWEEP 497                  |
| Magnitude label  | `mag_q = 0.5`, train-only `tau` (leak-safe)               |
| Folds / purge    | `n_folds = 5`, GAP-1 purge, `MIN_OOS_SAMPLES = 40`, `MIN_TRAIN_SAMPLES = 20` |
| Estimators       | B = 1000 bootstrap, B = 1000 permutations, `seed = 230022` |
| Cost             | `cost_bps = 5.0` (round trip)                             |

## 4. Per-family results

Score-alone OOS on the purged walk-forward (baseline arm of
`governance.family_calibration.walk_forward_ab` with `label="magnitude"`). All
metrics from `scripts/run_magnitude_resolution_gate.py`.

| Family | n_oos | mag AUC | AUC 95% CI low | baseline_resolution | perm-null p95 | resolution > null? | dir-Brier (guard) | Verdict |
|--------|-------|---------|----------------|---------------------|---------------|--------------------|-------------------|---------|
| BOS    | 2375 | 0.6178 | 0.5953 | 0.01177 | 0.00137 | yes (p = 0.001) | 0.2412 | **PASS** |
| OB     | 1805 | 0.5616 | 0.5367 | 0.00489 | 0.00153 | yes (p = 0.001) | 0.2389 | FAIL — AUC floor + CI |
| FVG    | 1985 | 0.5528 | 0.5281 | 0.00380 | 0.00137 | yes (p = 0.001) | 0.2322 | FAIL — AUC floor + CI |
| SWEEP  | 410  | 0.6632 | 0.6098 | 0.02090 | 0.00629 | yes (p = 0.001) | 0.2473 | **PASS** |

Reading: the score carries **statistically non-null** move-size resolution in
**all four** families (every `baseline_resolution` clears its own label-permutation
p95, p = 0.001). But only BOS and SWEEP also clear the **discrimination** floor
(AUC ≥ 0.60 and CI lower bound ≥ 0.55). FVG and OB resolve move-size only weakly
(AUC 0.55–0.56, CI lower bound 0.53–0.54) — non-null but not operationally
sizeable, which is exactly the separation the data-independent 0.60 floor was set
to enforce. The dir-Brier column is a guard read only: the additive design
retains the existing `brier_threshold` check, so direction cannot regress
(ADR-0023 §2 condition 3 is structural).

## 5. Secondary confirmation — E[PnL] after costs

ADR-0023 §Consequences requires E[PnL]-after-cost as a secondary check before the
check is allowed to bind a live promotion: a resolution pass that does not
convert to positive **sized** E[PnL] is a recordable negative, not grounds to
activate the gate.

| Family | E[PnL] after cost (bps) | converts? | note |
|--------|-------------------------|-----------|------|
| BOS    | deferred | deferred | requires the directional execution model |
| OB     | n/a | n/a | did not clear §2 (not a sizing candidate) |
| FVG    | n/a | n/a | did not clear §2 (not a sizing candidate) |
| SWEEP  | deferred | deferred | requires the directional execution model |

The move-size signal sizes an **existing directional position**; it does not by
itself generate direction, so a faithful after-cost E[PnL] needs the directional
execution path, not the score-alone resolution arm measured here. That
confirmation is the **activation gate**: the additive `magnitude_resolution_floor`
check is wired but **dormant** — `FamilyMetrics.magnitude_resolution_pass`
defaults to `None` (non-blocking), so this PR changes **no** live sizing
decision. Populating that field from the calibration pipeline (which is the step
that turns the check on for BOS and SWEEP) is gated on the E[PnL] confirmation
and is a separate, deliberate edit.

## 6. Reproduction

```bash
# Score-alone magnitude resolution per family (baseline arm = the v1 score),
# with the ADR-0023 §2.1 bootstrap CI and §2.2 label-permutation null.
EV=~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json
PYTHONPATH=. .venv/bin/python scripts/run_magnitude_resolution_gate.py "$EV" \
  --mag-q 0.5 --n-bootstrap 1000 --n-permutation 1000 --seed 230022 \
  --out /tmp/adr0023_gate.json
# exit 0 => at least one family clears the bar (here BOS + SWEEP).
```

The estimators live in `governance/magnitude_resolution_gate.py`
(`bootstrap_auc_ci`, `permutation_resolution_null`,
`evaluate_family_magnitude_resolution`); the additive gate check is
`magnitude_resolution_floor` in `governance/promotion_gate.py`.

## 7. Verdict

The v1 geometry score **clears the full ADR-0023 §2 move-size bar for BOS and
SWEEP** and misses on the discrimination floor for FVG and OB. The additive
`magnitude_resolution_floor` check is now wired into the promotion gate and
`risk_sizeable` verdict, but stays **dormant** (field defaults to `None`,
non-blocking) until the calibration pipeline populates it — a step gated on the
§5 E[PnL]-after-cost confirmation. Until then the v1 direction-Brier tier-2 gate
stays in force and no family is sized on the move-size objective. The FVG/OB
misses are recorded as negatives; per ADR-0023 §3 the bar is not re-tuned.
