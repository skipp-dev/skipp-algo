# Architectural Decisions

> Canonical ADR-style log of deliberate architecture choices for
> `skippALGO/skipp-algo`. Each entry records a decision, the rationale,
> alternatives considered, and the rejection reasons for the paths
> not taken. Entries are append-only; superseded decisions stay visible
> with a `Status: superseded` header and a pointer to the replacement.

## Format

Each ADR is a `### YYYY-MM-DD - <slug>` H3 section with the following
labelled subsections (all required):

- **Context** — the situation that triggered the decision.
- **Decision** — the chosen path, in imperative voice ("we do X").
- **Alternatives considered** — enumerated list; each item names the
  alternative and the single-sentence reject reason.
- **Consequences** — what the decision costs us and what it buys.
- **Evidence** — links to tests, benchmarks, or upstream references
  that ground the decision.
- **Status** — one of `accepted`, `superseded by <slug>`, `deferred`.

---

## Entries

### 2026-04-21 - 3-layer HTF trend stack over Flux-style 7-TF bias

**Context.** Competitor scripts (notably
[Flux Market Structure Dashboard](https://www.tradingview.com/script/vXui7vrm-Market-Structure-Dashboard-Flux-Charts/))
advertise 7-TF configurable bias stacks. Marketing pressure suggested
matching feature count. The measurement lane's per-bucket calibration
story is incompatible with user-chosen TF weights.

**Decision.** Keep the ICT-standard 3-layer trend hierarchy
(`4H / 1D / 1W`) plus the adaptive IPDA dach-TF above layer 3.
Expand only the *benchmark* chart-TF coverage
(`5m / 15m / 1H / 4H`) — see Plan 2.8 S3.1. Reject Flux-style
user-configurable 7-TF bias stacks.

**Alternatives considered.**

- *Flux-style 7-TF user-configurable bias stack.* Rejected: breaks
  per-family × per-context calibration because the scorer becomes
  user-specific and thus non-reproducible.
- *4th intraday trend layer immediately (30m or 2H).* Deferred to
  Q4-gate review (W13): can only land if the three §3.2 gates pass
  (HR uplift >= 3pp in >= 2 buckets, Brier regression <= 0.02, every
  bucket >= 30 events). 30m also rejected vs 2H because it sits too
  close to the 15m chart-TF and adds noise rather than signal.
- *Sub-minute LTF (5s / 15s) for microstructure.* Deferred to 2027
  Q1+: requires Databento tick integration in the benchmark side
  and breaks the Free-Tier reproducibility guarantee.

**Consequences.**

- Calibration story stays compact and reproducible. The
  "measured not claimed" positioning remains defensible.
- Feature-count comparison tables put us at apparent disadvantage
  (3 TFs vs. 7). Mitigated via the tooltips on `Trend TF 1/2/3`
  inputs (they document the intent explicitly) and via the README
  Academic Grounding section.
- Preprint appendix (Q4) can report a single calibrated scorer
  rather than a per-user family of scorers.

**Evidence.**

- [`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`](./smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md)
  (the full decision memo).
- [`tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`](../tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py)
  pins the tooltip accuracy.
- [`tests/test_plan_2_8_s3_1_chart_tf_expansion.py`](../tests/test_plan_2_8_s3_1_chart_tf_expansion.py)
  pins the 4-TF benchmark default.
- [`tests/test_plan_2_8_s3_1_per_tf_partitioning.py`](../tests/test_plan_2_8_s3_1_per_tf_partitioning.py)
  pins per-TF artifact partitioning.
- [`scripts/plan_2_8_q4_gate_evaluator.py`](../scripts/plan_2_8_q4_gate_evaluator.py)
  is the W13 gate evaluator; passing it is a precondition for
  reconsidering the "4th trend layer deferred" branch.

**Status.** accepted.
