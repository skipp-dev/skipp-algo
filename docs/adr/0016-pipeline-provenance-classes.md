# ADR-0016: Pipeline-provenance classes (no-ML pipelines)

> **Note — ADR numbering collision:** Two ADRs share number 0016 in this
> repository. This file covers **pipeline-provenance classes**. The other
> is [0016-orderflow-aggressor-datapath.md](./0016-orderflow-aggressor-datapath.md).
> References to "ADR-0016" in `tests/test_promotion_gate.py`,
> `tests/test_family_returns.py`, and related test/governance files
> refer to **this** document. This collision is tracked; do not add new
> ADRs numbered 0016.

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Accepted                                                                          |
| Date     | 2026-06-02                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), Sprint W1.a strict-provenance gate, EV-17 caller-declared provenance, EV-20 first real run |

## Context

The promotion gate (`governance/promotion_gate`) enforces, under
`strict_provenance=True` (the production default), a set of
`REQUIRED_PROVENANCE_KEYS`. Three of them describe an **upstream
ML-modelling layer** and are *caller-declared* (EV-17), i.e. the metrics
producer cannot compute them itself:

- `bootstrap_method` — C3.1 BCa bootstrap of the modelling layer.
- `block_size` — C4.1 block-permutation of the modelling layer.
- `stacked_used` — C10.1 stacking ensemble.

The EV-20 audit established the decisive structural fact about the SMC
families (BOS/OB/FVG/SWEEP): the live edge pipeline is **SMC-direct** —

- returns come **straight from events** via `realized_return`
  (`governance/family_returns`), not from a model's predicted PnL;
- scores are **raw SMC geometry-strength event scores**
  (`governance/family_event_score`), not ensemble outputs;
- there is **no stacking ensemble** and **no BCa/block-permutation
  modelling layer** — the producer's own block-bootstrap significance test
  is already documented by its nine producer-owned provenance tags
  (`wf_scheme`, `psr_method`, `significance_method`, `fdr_method`,
  `calibration_method`, `conformal_method`, ...).

For such a pipeline the three ML-modelling keys describe work that
**does not exist**. Declaring them anyway to clear the gate would be
fabrication — inventing a BCa bootstrap, a block size and a stacking flag
for a layer the architecture explicitly does not run. The producer-side
contract already states this (`scripts/build_family_metrics`: caller
provenance is "never fabricated; absent → stays absent → gate honestly
blocks 'provenance not declared'").

The gate therefore over-blocks: a legitimate no-ML pipeline is held
permanently at `inconclusive` (ADR-0015 tier-1) by three guards that are
**not-applicable**, not merely **not-yet-measured**. "Not-applicable" and
"unmeasured" are different audit states and must not be collapsed.

## Decision

Introduce an explicit **pipeline-provenance class**, declared by the
caller via a `pipeline_class` provenance key, and make the three
ML-modelling provenance keys **conditional** on that class rather than
globally required.

1. The three keys `{bootstrap_method, block_size, stacked_used}` are the
   `ML_MODELLING_PROVENANCE_KEYS`. The remaining required keys
   (`wf_scheme`, `wf_embargo_bars`, `psr_method`) are **pipeline-agnostic**
   and stay required for **every** class — they describe the
   walk-forward/PSR machinery the producer always runs.

2. A family MAY declare `provenance["pipeline_class"]`. When its value is a
   recognised **no-ML class** (`NO_ML_PIPELINE_CLASSES`, initially
   `{"smc_direct_no_ml"}`), the `ML_MODELLING_PROVENANCE_KEYS` are treated
   as **not-applicable**: their absence emits **no** blocker and does not
   fail `ok_provenance`.

3. The waiver is **conditional, not a global relaxation**. A family that
   does **not** declare a recognised no-ML class still has all six keys
   required. An **unknown** `pipeline_class` value grants **no** waiver —
   the keys stay required — so the waiver cannot be obtained by typing an
   arbitrary string. If a no-ML family *does* declare one of the ML keys,
   the value is still surfaced verbatim in `Decision.provenance` (the gate
   never discards declared metadata).

4. This ADR changes **only** the provenance-key requirement. It does **not**
   touch any numeric edge or calibration check. In particular it does **not**
   waive `conformal_coverage`: conformal coverage is computed on the
   out-of-sample calibration pairs directly (split-conformal) and is
   applicable to a no-ML pipeline, so it remains a measured guard.

The SMC-direct producer (`governance/family_returns.to_build_spec`)
declares `pipeline_class = "smc_direct_no_ml"` for the families it builds,
so the classification flows end-to-end into the gate snapshot.

## Consequences

- A no-ML family is no longer blocked by three not-applicable ML-modelling
  guards. The honest audit state becomes "not-applicable for this pipeline
  class" instead of a permanent "not declared" blocker. This removes three
  of the non-calibration guards that currently force ADR-0015 tier-1
  `inconclusive` for BOS/OB/FVG.

- Reaching tier-1 `edge_supported` still requires the **remaining**
  non-calibration guards to be measured-and-clear (e.g. `live_vs_wf_ratio`,
  `conformal_coverage`, `regime_degraded`, `psi_slope`). This ADR removes
  only the not-applicable ones; it does **not** by itself promote any
  family. Tier-2 `risk_sizeable` continues to hinge on the real calibration
  problem (Brier 0.228–0.284 against the 0.22 bar) and is untouched here.

- A future ML pipeline (if one is ever built on the SMC scores) simply
  declares no `pipeline_class` (or an ML class) and is held to all six keys,
  exactly as today.

- Adding a new no-ML pipeline is a one-line change: extend
  `NO_ML_PIPELINE_CLASSES`. The classification lives in the gate (the audit
  authority), not in each producer.
