# Plan 2.8 rollout runbook

Operator-facing runbook for the MTF-scope addendum rollout. Cross-refs
[`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`](./smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md)
and [`DECISIONS.md`](./DECISIONS.md).

## Phase timeline (addendum §6)

| Phase | Window | Deliverable | Status |
| --- | --- | --- | --- |
| Phase 0 | W0–W2 | Pine tooltips on `Trend TF 1/2/3`, README grounding note, parent-plan xref | done |
| Phase 1 | W3–W8 | 4-TF benchmark default (5m/15m/1H/4H), per-TF partitioning, per-TF×family rollup, Phase-E2 verdicts streamed to rolling-bench summary | done |
| Phase 2 | W9–W12 | A/B experiment setup (3-TF arm vs 4-TF-2H arm) — bundle producer feeds `scripts/plan_2_8_q4_gate_evaluator.py` | in-flight |
| Phase 3 | W13 | Q4-gate review + ADR entry (accept or reject 2H promotion) | scheduled |

## Daily automation

- [`.github/workflows/smc-measurement-benchmark-rolling.yml`](../.github/workflows/smc-measurement-benchmark-rolling.yml)
  cron `30 7 * * *`. Runs all four TFs, emits
  `plan_2_8_tf_family_rollup.json` per out_dir, streams Phase-E2
  verdict markdown (`fvg_ttf_5m_vs_baseline`,
  `bos_stability_4h_vs_baseline`) into the step summary.
- Pin-tests guarding the wiring:
  [`tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`](../tests/test_plan_2_8_rolling_workflow_rollup_wiring.py).

## Q4-gate W13 review checklist

1. **Prepare the A/B bundle.** Phase-2 experiment output must be
   normalised into a JSON bundle:
   ```json
   {
     "buckets": [
       {"key": "RTH/NORMAL/LONG",  "hr_baseline": 0.46, "hr_candidate": 0.49, "n_events": 120},
       {"key": "RTH/NORMAL/SHORT", "hr_baseline": 0.44, "hr_candidate": 0.47, "n_events": 110},
       {"key": "ETH/HIGH/LONG",    "hr_baseline": 0.38, "hr_candidate": 0.40, "n_events":  35}
     ],
     "brier_baseline":  0.235,
     "brier_candidate": 0.238
   }
   ```
   Push the file under `artifacts/plan_2_8_q4_gate_bundle.json`
   (or any repo-relative path you pass as workflow input).

2. **Fire the dry-run workflow.** Actions → "plan-2.8 q4-gate dryrun"
   → Run workflow, accept defaults (0.03 / 2 / 0.02 / 30). The step
   summary shows the verdict; the JSON is uploaded as the
   `plan-2-8-q4-gate-verdict` artifact (90-day retention).

3. **Record the decision.** Regardless of outcome, append an ADR:
   ```
   python scripts/append_adr.py \
     --slug "<pass|reject> 2H 4th HTF layer" \
     --decision "<one-liner>" \
     --evidence "artifacts/q4_gate/plan_2_8_q4_gate_verdict.json (overall: <pass|fail>)" \
     --alternatives-file /tmp/alts.md \
     --consequences "<operator impact>" \
     --status accepted
   ```
   On reject, cross-reference the original 3-layer ADR
   (`2026-04-21 - 3-layer HTF trend stack over Flux-style 7-TF bias`)
   and re-pin the deferral window (typically +26 weeks).

## Three gates (cumulative, all must pass)

| Gate | Requirement | Tunable flag |
| --- | --- | --- |
| G1 uplift | ≥3pp HR uplift in ≥2 of 3 context buckets | `--uplift-min-pp` / `--uplift-min-buckets` |
| G2 Brier | `brier_candidate - brier_baseline ≤ 0.02` | `--brier-max-regression` |
| G3 events | every bucket ≥30 events | `--min-events-per-bucket` |

Defaults pinned in
[`scripts/plan_2_8_q4_gate_evaluator.py`](../scripts/plan_2_8_q4_gate_evaluator.py)
(`DEFAULT_UPLIFT_MIN_PP = 0.03`,
`DEFAULT_UPLIFT_MIN_BUCKETS = 2`,
`DEFAULT_BRIER_MAX_REGRESSION = 0.02`,
`DEFAULT_MIN_EVENTS_PER_BUCKET = 30`).

## Pin-test inventory

- `tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`
- `tests/test_plan_2_8_s3_1_chart_tf_expansion.py`
- `tests/test_plan_2_8_s3_1_per_tf_partitioning.py`
- `tests/test_plan_2_8_tf_family_rollup.py`
- `tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`
- `tests/test_plan_2_8_q4_gate_evaluator.py`
- `tests/test_plan_2_8_q4_gate_workflow.py`
- `tests/test_docs_decisions_adr.py`
- `tests/test_append_adr.py`

## Escalation

If Phase 2 bundle producer is not ready by W12, open an ADR with
`Status. deferred.` on the "2H promotion" slug and slip the W13 gate
to the next 13-week window. Do not short-circuit the gate.
