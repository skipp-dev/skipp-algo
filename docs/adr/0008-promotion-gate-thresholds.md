# ADR-0008: PromotionGate threshold origins and recalibration policy

| Field       | Value                                                                |
|-------------|----------------------------------------------------------------------|
| Status      | Accepted                                                             |
| Date        | 2026-05-17                                                           |
| Deciders    | skipp-dev                                                            |
| Supersedes  | (none — first formal threshold-provenance record for the gate)       |
| Related     | ADR-0002, `governance/promotion_gate.py`, `docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md`, `docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md`, `docs/SPRINT_PLAN_C9_DRIFT_2026-04-26.md`, `docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md` |

## Context

[`governance/promotion_gate.py`](../../governance/promotion_gate.py)
aggregates seven per-check thresholds into a single
`Decision.promoted` flag per event family. The constants are mirrored
in `DEFAULT_*` module-level names and re-exposed via the
`GateThresholds` dataclass. The current values are:

```python
DEFAULT_BRIER_MAX              = 0.22
DEFAULT_ECE_MAX                = 0.05
DEFAULT_FDR_Q                  = 0.05
DEFAULT_PSR_MIN                = 0.95
DEFAULT_MINTRL_MAX_YEARS       = 2.0
DEFAULT_PSI_MAX                = 0.25
DEFAULT_LIVE_VS_WF_RATIO_MAX   = 1.5
```

The audit ("welche dieser Schwellen sind empirisch verankert, welche
sind Operator-Intuition?") surfaced that **provenance varies per
threshold**, but the gate header documents only the *location* of each
constant — not whether the number itself was derived from a backtest
distribution, a textbook reference, or operator judgment. Without that
distinction, an operator cannot tell which thresholds carry empirical
weight versus which are unanchored defaults that may need
recalibration.

ADR-0002 documents the *eligibility-policy structure* (5 conditions
plus SPRT). This ADR is its complement: it documents **per-threshold
provenance and the conditions under which each threshold must be
re-evaluated**.

This is **doc-only**. No constant changes here; the constants in
`governance/promotion_gate.py` remain authoritative. A future edit to
any of them must also touch this ADR (Consequences section).

## Provenance taxonomy

Each threshold is classified by **anchor type**:

- **Empirical (E)**: derived from an in-repo backtest distribution,
  walk-forward analysis, or recalibration run. Recalibration trigger
  is anchored in the underlying distribution drifting.
- **Reference (R)**: taken from an external paper / textbook
  convention. Recalibration trigger is the literature converging on a
  different default for the same problem class.
- **Operator judgment (O)**: a conservative bound chosen without an
  empirical or referential anchor. Carries the highest recalibration
  obligation: every operator-judgment threshold must be re-evaluated
  on a fixed cadence to prevent it from silently calcifying into
  policy.

## Per-threshold record

### 1 · `brier_max = 0.22` — anchor: **E (partial)**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_BRIER_MAX`                     |
| Sprint of origin    | C10 ML layer (see `docs/SPRINT_PLAN_C10_ML_LAYER_2026-04-26.md`)      |
| Empirical anchor    | Reference distribution of per-family calibrated Brier on the lifetime corpus; cap chosen ≈ Q90 (gate is intentionally generous: this is the absolute backstop, not the per-window improvement floor). The per-window improvement floor (`PROMOTE_IMPROVEMENT = 0.005`) lives in [`run_ab_comparison.py`](../../scripts/run_ab_comparison.py) and is governed by ADR-0002 §2. |
| Operator margin     | Yes — Q90 ≈ 0.20 was rounded up to 0.22 for headroom against benign regime variance |
| Recalibration trigger | (a) Q90 of the lifetime-corpus per-family Brier drifts above 0.20 OR below 0.16 for ≥ 100 live windows OR ≥ 6 months. (b) Live recalibrator (`brier_regret_threshold ≈ 0.02` in the C10 ML layer) starts firing on > 25 % of windows. |

### 2 · `ece_max = 0.05` — anchor: **R**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_ECE_MAX`                       |
| Sprint of origin    | C10 ML layer                                                          |
| Empirical anchor    | Reference convention: 5 % ECE is the widely-cited "well-calibrated probabilistic classifier" threshold (Guo et al. 2017, *On Calibration of Modern Neural Networks*, Niculescu-Mizil & Caruana 2005). No in-repo backtest distribution was used to derive 0.05. |
| Operator margin     | None (literal literature default)                                     |
| Recalibration trigger | (a) Empirical distribution of per-family `ece` on the lifetime corpus has a Q75 above 0.05 (i.e. the convention is uncomfortably tight for this domain). (b) The calibration method changes (e.g. switch from isotonic to spline) — re-derive from new method's residual distribution. |

### 3 · `fdr_q = 0.05` — anchor: **R**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_FDR_Q`; mirrored in [`scripts/run_ab_comparison.py::FDR_Q`](../../scripts/run_ab_comparison.py) |
| Sprint of origin    | C8 incubation A/B comparison                                          |
| Empirical anchor    | Reference convention: Benjamini-Hochberg q-value 0.05 (Benjamini & Hochberg 1995). Matches the SPRT α = 0.05 (see ADR-0002 §1) — keeping multiple-comparison correction at the same nominal rate as the SPRT type-I error avoids a hidden tightening when many families are compared in one window. |
| Operator margin     | None (literature default + alignment with SPRT α)                     |
| Recalibration trigger | Only if the SPRT α changes — the two must move together. Otherwise no recalibration; q = 0.05 is the contract. |

### 4 · `psr_min = 0.95` — anchor: **R**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_PSR_MIN`                       |
| Sprint of origin    | C6 PSR/MinTRL (see `docs/SPRINT_PLAN_C6_PSR_MINTRL_2026-04-26.md` and [`open_prep/stats_helpers.py::probabilistic_sharpe`](../../open_prep/stats_helpers.py)) |
| Empirical anchor    | Reference: Bailey & López de Prado (2012, 2014) recommend PSR ≥ 0.95 as the operating point at which the observed Sharpe is "significantly greater than a chosen benchmark with 95 % confidence". Matches the FDR q and SPRT α nominal rates. |
| Operator margin     | None (literature default; alignment with §3 + ADR-0002 §1)            |
| Recalibration trigger | Only if SPRT α or FDR q change. The three confidence levels are intentionally aligned. |

### 5 · `mintrl_max_years = 2.0` — anchor: **O**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_MINTRL_MAX_YEARS`              |
| Sprint of origin    | C6 PSR/MinTRL (`open_prep/stats_helpers.py::min_trl`)                 |
| Empirical anchor    | **None — operator judgment, no empirical anchor.** 2 years is the operator-chosen ceiling for "this strategy's expected time-to-significance is acceptable to put into the incubation queue". Lopez de Prado does not publish a numeric ceiling; MinTRL is left as a planning metric for the operator to threshold. |
| Operator margin     | n/a (entire value is operator judgment)                               |
| Recalibration trigger | **Fixed cadence: every 100 live promotions OR every 6 months, whichever comes first.** Re-evaluate by inspecting the empirical distribution of MinTRL across the families that *did* promote in the prior window; if Q75(MinTRL) < 1.0 year, the 2-year ceiling is provably loose and should tighten; if Q50 ≥ 1.5 years, the ceiling is binding too often and should either widen or be re-derived from a longer corpus. |

### 6 · `psi_max = 0.25` — anchor: **R**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_PSI_MAX`                       |
| Sprint of origin    | C9 drift layer (see `docs/SPRINT_PLAN_C9_DRIFT_2026-04-26.md`; the `ml/drift/` package does not yet expose a module-level constant) |
| Empirical anchor    | Reference convention: the industry-standard PSI banding is `< 0.10` "no shift", `0.10–0.25` "moderate shift", `> 0.25` "major shift" (Siddiqi 2006, *Credit Risk Scorecards*). Gate uses 0.25 as the hard "major" cap. |
| Operator margin     | None at the gate level; per-feature alarm thresholds inside the drift layer are tighter. |
| Recalibration trigger | (a) Per-feature alarms in `ml/drift/` start firing at < 0.25 systematically (suggesting the global cap is too generous for *this* feature set). (b) The feature set materially changes (new HERO fields, dropped legacy features) — re-derive per-feature PSI distributions on the new schema before re-anchoring the gate. |

### 7 · `live_vs_wf_ratio_max = 1.5` — anchor: **O**

| Item                | Value                                                                 |
|---------------------|-----------------------------------------------------------------------|
| Source of truth     | `governance/promotion_gate.py::DEFAULT_LIVE_VS_WF_RATIO_MAX`          |
| Sprint of origin    | C8 incubation (see `docs/SPRINT_PLAN_C8_LIVE_INCUBATION_2026-04-26.md`) |
| Empirical anchor    | **None — operator judgment, no empirical anchor.** 1.5 was chosen as "50 % degradation of live Brier vs. the walk-forward expectation is the maximum tolerable before we suspect the model is overfitting the WF window or the live regime has shifted materially." No paper grounds this; no in-repo distribution was used. |
| Operator margin     | n/a (entire value is operator judgment)                               |
| Recalibration trigger | **Fixed cadence: every 100 live promotions OR every 6 months.** Re-derive by computing the empirical distribution of `live_brier / walkforward_brier` across all promoted families over the prior window. Re-anchor at Q90; round up to one decimal. A *lower bound* ("too good to be true") should be added in a separate ADR + code change if the empirical distribution shows Q05 < 0.5 — i.e. live materially out-performing WF should also be flagged, because it almost always indicates a data-leakage or single-regime overfit. |

## Decision

1. Every threshold in `GateThresholds` has an entry in this ADR with
   anchor type (E / R / O) and a recalibration trigger.
2. Operator-judgment thresholds (**O**) carry a **mandatory fixed
   recalibration cadence**: 100 live promotions OR 6 months,
   whichever comes first. This prevents unanchored defaults from
   silently calcifying.
3. Empirical thresholds (**E**) and reference thresholds (**R**)
   recalibrate only on the **specific triggers** named in their row
   (not on a cadence).
4. The constants in `governance/promotion_gate.py` remain the source
   of truth. This ADR is the index, not the value.

## Out-of-scope (intentionally not gated thresholds)

- `brier_regret_threshold ≈ 0.02` (live recalibrator, C10 ML layer) —
  not a gate constant; lives in the model layer.
- Per-feature PSI alarm thresholds inside `ml/drift/` — not a gate
  constant; they fire before the global cap and are diagnostic.
- SPRT `(p0, p1, α, β)`, `PROMOTE_IMPROVEMENT`,
  `HIT_RATE_REGRESSION_TOLERANCE`, `ROLLBACK_REGRESSION` —
  governed by ADR-0002, not by `PromotionGate`.

## Consequences

- Operators can answer "is this threshold empirically anchored or
  operator judgment?" without reading sprint plans.
- Recalibration of operator-judgment thresholds (`mintrl_max_years`,
  `live_vs_wf_ratio_max`) is now a **scheduled obligation**, not a
  vague "we should look at this someday".
- A future edit to any constant in
  [`governance/promotion_gate.py`](../../governance/promotion_gate.py)
  must:
  1. Update the row in the table above (value, anchor, recalibration
     trigger if it changed).
  2. If the anchor type changes (e.g. an **O** becomes **E** because
     a backtest distribution now grounds it), update both the row and
     this ADR's "Decision" section.
- A future addition of a `live_vs_wf_ratio_min` lower bound — or any
  new threshold to `GateThresholds` — must add a new row to the
  per-threshold record table in the **same commit** that adds the
  constant. Reviewers should reject PRs that grow `GateThresholds`
  without growing this ADR.

## Recalibration log

Append entries when an operator-judgment threshold is recalibrated.
Format: `YYYY-MM-DD · <threshold> · old → new · evidence (commit SHA / report path)`.

- (none yet — first recalibration due by 2026-11-17 OR after 100 live
  promotions, whichever comes first)
