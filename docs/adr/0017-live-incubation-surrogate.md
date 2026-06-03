# ADR-0017: Live-incubation surrogate for offline backtests (live-vs-WF)

| Field    | Value                                                                            |
|----------|----------------------------------------------------------------------------------|
| Status   | Accepted                                                                          |
| Date     | 2026-06-02                                                                        |
| Deciders | skipp-dev (autonomous mandate; product owner + principal quant)                  |
| Related  | ADR-0015 (edge vs calibration tiers), ADR-0016 (pipeline-provenance classes), EV-24 walk-forward calibration, C8 live-incubation, EV-20 first real run |

## Context

The promotion gate's `live_vs_wf_ratio` check compares a family's **live**
Brier against its **walk-forward** Brier and blocks when recent calibration
has degraded (ratio above `live_vs_wf_ratio_max`, default 1.5 — C8
live-incubation). It is a **non-calibration integrity guard**, so under
ADR-0015 it gates **tier-1 `edge_supported`**: while it is unmeasured the
verdict is `inconclusive`.

The SMC-direct producer (`governance/family_returns.to_build_spec`) emits only
a `walkforward` calibration block — `governance/family_calibration.walk_forward_calibration`
pools the purged-embargo out-of-sample `(probability, outcome)` pairs into a
single block. It never emits a `live` block, so `live_brier` is always `None`
and the guard is permanently "not yet measured". In a pure **offline backtest**
there is no real live trading feed to draw a live Brier from, which is why the
block was left unwired.

The producer-side machinery already exists: `scripts/build_family_metrics._calibration_slice`
consumes a `calibration.live` sub-block and turns it into `live_brier`. The
only gap is **producing** that sub-block, and the only open question is the
**measurement-design** one: what plays the role of "live" in an offline run?

## Decision

Declare the **most recent chronological slice** of the pooled walk-forward
out-of-sample pairs as a **live-incubation surrogate**, and the older
remainder as the walk-forward reference.

1. `walk_forward_calibration` pools its OOS pairs in **chronological order**
   (earliest fold first, latest fold last), so the **last `LIVE_TAIL_MIN_SAMPLES`
   pairs are the most recent OOS window**. A new pure function
   `governance/family_calibration.partition_live_tail` splits the pooled block
   into `{walkforward: older-remainder, live: recent-tail}`.

2. The split is emitted **only when both partitions stay adequately powered**:
   the pool must hold at least `LIVE_TAIL_MIN_SAMPLES` (live tail) **plus**
   `MIN_OOS_SAMPLES` (walk-forward remainder). Below that the function returns
   `None`, the caller keeps the **full** pooled walk-forward block, and
   `live_brier` stays honestly **unmeasured** — small samples cannot be split
   into two adequately-powered halves, and we do not fabricate a live Brier to
   clear the guard.

3. The surrogate is **explicitly declared, not a real live feed**. The
   `live_vs_wf_ratio` it produces is an honest **recent-vs-historical OOS
   calibration-drift** measure: "is the most recent out-of-sample window
   materially worse-calibrated than the historical walk-forward?" When a true
   live paper-trading feed exists it supersedes this surrogate — the surrogate
   is the best available offline proxy, recorded as such in provenance
   (`ev25_live_source`).

4. `to_build_spec` calls `partition_live_tail` after `walk_forward_calibration`;
   when the split succeeds it emits the `{walkforward, live}` calibration block
   and records the `ev25_live_source` provenance tag. The headline gate Brier
   (and its block-bootstrap CI) is then computed on the **walk-forward
   remainder** (the older OOS), consistent with treating the recent tail as the
   separately-reported live window.

This ADR changes **only** how the calibration block is partitioned. It does
**not** change any threshold, and it does not by itself promote any family:
`live_vs_wf_ratio` still has to come out **at or below** its bar, and tier-2
`risk_sizeable` still hinges on the unchanged Brier problem.

## Consequences

- `live_vs_wf_ratio` becomes **measurable** for any family with enough OOS
  pairs (`>= LIVE_TAIL_MIN_SAMPLES + MIN_OOS_SAMPLES`). For such families it is
  no longer an unmeasured guard forcing ADR-0015 tier-1 `inconclusive`; the
  family reaches tier-1 once the ratio (and the remaining non-calibration
  guards) are measured and clear.

- Families with too few OOS pairs keep the full pooled walk-forward block and
  an honestly-unmeasured `live_brier` — the guard still blocks tier-1 for them,
  which is the correct statement ("not enough out-of-sample history to judge
  recent drift yet").

- The live tail is small (`LIVE_TAIL_MIN_SAMPLES`), so the live Brier has wide
  sampling error; this is acceptable because `live_vs_wf_ratio` is a **coarse
  1.5× alarm**, not a precise threshold. The caveat is recorded here and in the
  module docstring so a reader does not over-read a single ratio.

- A future true live feed is wired by supplying a real `calibration.live` block
  from the live tracker instead of the surrogate; no gate change is needed.
