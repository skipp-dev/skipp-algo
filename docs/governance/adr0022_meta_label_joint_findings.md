# ADR-0022 Joint Meta-Label A/B Findings — direction saturated, score resolves move-size

> **Date:** 2026-06-05
> **Scope:** Execute ADR-0019's pre-registered **joint (multivariate)**
> meta-label A/B — does a logistic over **[score] + features** out-resolve the
> **score alone** — closing the "single-feature nulls do not prove a joint null"
> escape hatch. Then read off the **score-alone baseline** on each label axis.
> **Harness:** `scripts/run_meta_label_ab.py` (joint, purged walk-forward,
> score prepended as column 0) and `scripts/run_feature_ab.py --label magnitude`
> (score-alone baseline arm).
> **Events:** `~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json` —
> 10,981 events, 5 symbols (BOS 2,858 · OB 3,039 · FVG 4,587 · SWEEP 497).
> **Verdict: joint meta-label adds NO direction resolution in any config (the
> direction axis is saturated); but the score-alone baseline resolves
> MOVE-SIZE at AUC ≈ 0.61–0.69 vs ≈ 0.53–0.58 on direction — the tier-2
> objective is on the wrong axis.** See [ADR-0022](../adr/0022-meta-label-joint-ab-and-magnitude-retarget.md).

---

## 1. Why this test

`governance/family_feature_ab` only ever compared a feature **alone** against the
score **alone**; its docstring flags the *incremental / joint* question — does a
feature add resolution **on top of** the score — as deliberately out of scope.
ADR-0019 specified that joint meta-label but it had never been built, so every
prior "axis saturated" verdict rested only on single-feature-alone nulls. This
run builds and executes the joint test (`governance/family_meta_label`): the
candidate arm is a multivariate logistic over **[score] + selected features**
with the score prepended as column 0, so the candidate strictly contains the
baseline's information and any `no_lift` is a genuine joint null, not a framing
artefact. Same purged walk-forward pairing and GAP-1 purge as the existing
harness.

## 2. Joint meta-label A/B — DIRECTION label

`families_lifted = []` and exit code `2` (`no_lift`) in **every** configuration.
`Δres` = candidate resolution − baseline (score-alone) resolution; positive =
joint lift.

| Config (features added to score) | BOS Δres | FVG Δres | OB Δres | SWEEP Δres | Verdict |
|----------------------------------|---------:|---------:|--------:|-----------:|---------|
| order-flow-5 `relative_volume,vpin,kyle_lambda,average_trade_size,ofi_imbalance` | +0.0004 | −0.0007 | −0.0001 | −0.0072 | all `no_lift` |
| VRVP-2 `vrvp_vpoc_dist,vrvp_va_pos` | −0.0006 | +0.0002 | −0.0006 | +0.0007 | all `no_lift` |
| abs-UOA-2 `abs_uoa_activity,relative_volume` | +0.0002 | +0.0006 | −0.0001 | +0.0013 | all `no_lift` |
| kitchen-sink-8 (order-flow-5 + VRVP-2 + abs_uoa) | **−0.0024** | −0.0012 | −0.0004 | −0.0014 | all `no_lift` |
| `relative_volume`-only | −0.0006 | −0.0002 | −0.0007 | −0.0056 | all `no_lift` |

The deltas hover at the ±1e-3 noise floor; the only consistently *signed* result
is the kitchen-sink-8, which **regresses** BOS by −0.0024 (candidate AUC drops
0.569 → 0.558) — the classic over-fit signature of throwing every feature at a
saturated axis. **The orthogonal-combination ("meta-label") hypothesis is
rejected on the direction axis, jointly, on real data.** The ADR-0019 escape
hatch is closed.

## 3. Score-alone baseline — DIRECTION vs MAGNITUDE axis

The decisive number is in the **baseline arm itself** (score alone, no feature),
read off both label axes. Magnitude label = `|forward return|` over a leak-safe
per-fold quantile (`run_feature_ab.py --label magnitude --mag-q 0.5`); the
baseline AUC is identical regardless of which feature the candidate arm carries,
so the per-feature rows below report the **same score-alone baseline** measured on
each run's complete-case slice.

| Family | Direction baseline AUC | **Magnitude baseline AUC (score alone)** |
|--------|-----------------------:|-----------------------------------------:|
| BOS    | ≈ 0.53–0.57            | **0.614 – 0.630** |
| FVG    | ≈ 0.55                 | **0.553 – 0.583** |
| OB     | ≈ 0.53                 | **0.562 – 0.585** |
| SWEEP  | ≈ 0.54                 | **0.663 – 0.689** |

> Magnitude baseline AUC by feature-run (score alone, complete-case n varies):
> `relative_volume` BOS .618 / FVG .553 / OB .562 / SWEEP .663 ·
> `vpin` BOS .630 / FVG .583 / OB .584 / SWEEP .689 ·
> `ofi_imbalance` BOS .630 / FVG .583 / OB .584 / SWEEP .689 ·
> `abs_uoa_activity` BOS .614 / FVG .553 / OB .566 / SWEEP .663 ·
> `kyle_lambda` BOS .630 / FVG .583 / OB .584 / SWEEP .689.

On direction the score is near a coin flip (AUC ≈ 0.53–0.58, consistent with the
tier-2 direction-Brier ≈ 0.24 blocker). On **magnitude** the *same score* sits at
AUC ≈ 0.61–0.69 — SWEEP up to 0.69. The v1
`atr_normalised_geometry_strength_v1` score (zone-thickness/ATR + displacement)
is structurally a **volatility / move-size** discriminator. Adding any
microstructure feature on the magnitude axis *regresses* it (candidate AUC drops,
several land `regresses_calibration`), corroborating
[adr0019_magnitude_regime_ab_findings.md](adr0019_magnitude_regime_ab_findings.md):
features do not lift magnitude either. The lever is the **objective axis**, not a
new feature.

## 4. Synthesis

1. **Direction is saturated, jointly.** Neither single features (prior A/Bs) nor
   the joint meta-label (this run) lift direction resolution; the kitchen-sink
   over-fits. Stop searching for direction features.
2. **The score already resolves the axis that matters for sizing.** Move-size
   AUC 0.61–0.69 with PSR ≈ 1.0 and an asymmetric payoff means E[PnL] is driven
   by *how far*, not *which way* — exactly what the score discriminates.
3. **Tier-2 grades the wrong axis.** ADR-0015 tier-2 `risk_sizeable` gates on
   `sign_return_secondary_diagnostic` (direction) Brier/resolution. ADR-0022
   proposes re-targeting it to a move-size / E[PnL] objective, to be
   pre-registered and proven on real data in a separate PR — or recorded as a
   second negative if move-size resolution does not convert to sizeable
   out-of-sample E[PnL].

## 5. Reproduction

```bash
EV=~/.local/share/skipp/vpin_followup/events_v3_abs_opra.json

# Joint meta-label A/B (direction) — every config returns exit 2 / no_lift
PYTHONPATH=. .venv/bin/python scripts/run_meta_label_ab.py "$EV" \
  --feature-key relative_volume,vpin,kyle_lambda,average_trade_size,ofi_imbalance

# Score-alone magnitude baseline (read baseline_auc from any feature run)
PYTHONPATH=. .venv/bin/python scripts/run_feature_ab.py "$EV" \
  --feature-key vpin --label magnitude --mag-q 0.5
```
