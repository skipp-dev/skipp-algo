# Plan 2.8 rollout runbook

Operator-facing runbook for the MTF-scope addendum rollout. Cross-refs
[`docs/smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md`](./smc_improvement_plan_addendum_2_8_mtf_scope_2026-04-21.md)
and [`DECISIONS.md`](./DECISIONS.md).

## Phase timeline (addendum §6)

| Phase | Window | Deliverable | Status |
| --- | --- | --- | --- |
| Phase 0 | W0–W2 | Pine tooltips on `Trend TF 1/2/3`, README grounding note, parent-plan xref | done |
| Phase 1 | W3–W8 | 4-TF benchmark default (5m/15m/1H/4H), per-TF partitioning, per-TF×family rollup, Phase-E2 verdicts streamed to rolling-bench summary | done |
| Phase 2 | W9–W12 | A/B experiment setup (3-TF arm vs 4-TF-2H arm) — bundle builder ([`scripts/plan_2_8_q4_gate_bundle_builder.py`](../scripts/plan_2_8_q4_gate_bundle_builder.py)) projects two per-TF rollups + Brier values into the evaluator schema | scaffolded |
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

3. **Record the decision.** Regardless of outcome, append an ADR.
   The evaluator can render the body skeleton directly:

   ```
   python scripts/plan_2_8_q4_gate_evaluator.py \
     --bundle artifacts/plan_2_8_q4_gate_bundle.json \
     --format adr \
     > /tmp/adr_body.md

   python scripts/append_adr.py \
     --slug "<pass|reject> 2H 4th HTF layer" \
     --decision "<one-liner from /tmp/adr_body.md>" \
     --evidence "artifacts/q4_gate/plan_2_8_q4_gate_verdict.json (overall: <pass|fail>)" \
     --alternatives-file /tmp/adr_body.md \
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

## Phase 2 bundle assembly (W9–W12)

Once both arms of the A/B experiment have written `scoring_*.json`
artifacts and the daily rolling-bench has produced their respective
`plan_2_8_tf_family_rollup.json` manifests, fold them into a
Q4-gate bundle:

```
python scripts/plan_2_8_q4_gate_bundle_builder.py \
  --baseline-rollup  artifacts/ab_baseline/plan_2_8_tf_family_rollup.json \
  --candidate-rollup artifacts/ab_candidate/plan_2_8_tf_family_rollup.json \
  --brier-baseline   0.235 \
  --brier-candidate  0.236 \
  --output           artifacts/plan_2_8_q4_gate_bundle.json
```

Bucket keys default to the intersection of TF×family slices present
in both rollups, sorted deterministically. Use repeated `--bucket
<tf>/<family>` flags (e.g. `--bucket 5m/FVG --bucket 4H/BOS`) to
restrict the set the W13 gate evaluates.

## Status quick-check

At any point during the rollout, run:

```
python scripts/plan_2_8_status.py
```

The helper walks the expected Phase 0–3 anchors (scripts, workflows,
docs, pin-tests) and emits a markdown report. Exit code `0` =
required anchors present, `1` = at least one missing.

The daily heartbeat workflow
[`.github/workflows/plan-2-8-status-daily.yml`](../.github/workflows/plan-2-8-status-daily.yml)
runs the same script every day at 06:15 UTC and uploads the report
as the `plan-2-8-status-report` artifact (30-day retention).

## Trend history

Each daily rollup is folded into a long-running JSONL automatically by
the rolling-bench workflow's "Plan 2.8 history archive" step. The
history file lives at `${out_dir}/plan_2_8_history.jsonl` and is
uploaded as part of the daily benchmark artifact.

Manual append (e.g. backfilling from a re-downloaded artifact):

```
python scripts/plan_2_8_history_archive.py \
  --rollup  artifacts/<run>/plan_2_8_tf_family_rollup.json \
  --history docs/plan_2_8_history.jsonl
```

The append is idempotent on `(captured_at, scoring_root)` and the
projection drops the per-symbol noise so the file stays small enough
to graph in a notebook or spreadsheet.

After the archive step, the same workflow runs
[`scripts/plan_2_8_history_rotate.py`](../scripts/plan_2_8_history_rotate.py)
to cap the file at 366 snapshots / 400 days — a full year of daily
runs plus a small grace window. Rotation is atomic (`<path>.bak` is
kept) and fail-soft, so a bad day never touches the bench outcome.
Corrupt lines are preserved by default; pass `--drop-corrupt` to
remove them during a one-shot cleanup.

After the rotate step, the bench runs
[`scripts/plan_2_8_history_validate.py`](../scripts/plan_2_8_history_validate.py)
as a non-destructive integrity check (well-formed JSON, parseable
`captured_at`, no `(captured_at, scoring_root)` duplicates). The
report is uploaded as `plan_2_8_history_validate.json` and streamed
into the run summary. Validation hits do not fail the bench — they
are a warning signal that the archiver/rotator path needs a look.

## Weekly trend digest

Every Monday at 12:00 UTC,
[`.github/workflows/plan-2-8-weekly-digest.yml`](../.github/workflows/plan-2-8-weekly-digest.yml)
pulls the most recent rolling-bench artifact, extracts its
`plan_2_8_history.jsonl`, and runs
[`scripts/plan_2_8_trend_digest.py`](../scripts/plan_2_8_trend_digest.py)
over it. The markdown digest is streamed to the run summary and
uploaded as the `plan-2-8-weekly-digest` artifact (90-day retention).

Knobs (overridable via `workflow_dispatch`):

- `lookback_days` (default 7): age of the comparison endpoint.
- `min_events` (default 30): per-slice floor for a comparable verdict.
- `alert_threshold_pp` (default 0.05): flag slices whose absolute HR
  drift exceeds this value (only counted for comparable slices).

Ad-hoc local digest:

```
python scripts/plan_2_8_trend_digest.py \
  --history /path/to/plan_2_8_history.jsonl \
  --lookback-days 7 \
  --output /tmp/digest.md
```

### Drift-alert auto-issues

When the digest finds at least one comparable slice above
`alert_threshold_pp`, the workflow also renders an issue-body
(`--format issue`) and either opens a fresh GitHub issue labelled
`plan-2.8,drift-alert`, or — when an open issue with that label
pair already exists — appends a comment to the existing thread. The
issue body carries a footer with the workflow-run URL so the
artifact can be located even after the 90-day retention expires.
The `permissions: issues: write` block is scoped to this workflow
only. No issue is opened or commented on when the coverage status
is `empty` / `warmup` or when every comparable slice is within
threshold.

When the digest finds **no** comparable slice over threshold, the
workflow automatically closes any still-open `plan-2.8, drift-alert`
issues with a short comment linking back to the run. This keeps the
backlog honest without a human having to sweep the queue every week.

### Ad-hoc snapshot diff

For incident triage, [`scripts/plan_2_8_history_diff.py`](../scripts/plan_2_8_history_diff.py)
diffs any two snapshots in the history JSONL (by `captured_at` or
by index). Default: last two rows. The weekly workflow also runs
this helper for the most recent pair and streams the result into
the run summary.

```
python scripts/plan_2_8_history_diff.py \
  --history /path/to/plan_2_8_history.jsonl \
  --prev-captured-at   2026-04-14T07:00:00Z \
  --latest-captured-at 2026-04-21T07:00:00Z
```

### Top movers & alert snooze

[`scripts/plan_2_8_top_movers.py`](../scripts/plan_2_8_top_movers.py)
ranks TF×family slices by `|delta_pp|` across a lookback window (30d
by default); the weekly workflow streams its output into the run
summary alongside the snapshot diff.

[`scripts/plan_2_8_alert_snooze.py`](../scripts/plan_2_8_alert_snooze.py)
applies a snooze config to an existing digest JSON so operators can
temporarily silence a known-noisy slice. Each snooze entry carries
an optional `expires` ISO timestamp; invalid timestamps are treated
as inactive so a typo never silently hides an alert.

```
python scripts/plan_2_8_alert_snooze.py \
  --digest /tmp/digest.json \
  --snooze configs/plan_2_8_snoozes.json \
  --output /tmp/digest.snoozed.json
```

The weekly digest workflow now reads
[`configs/plan_2_8_snoozes.json`](../configs/plan_2_8_snoozes.json) at
run-time: when the file contains active `snoozes`, the workflow
recomputes `has_alerts` from the snoozed digest, so suppressed
slices never open a GitHub issue. Commit the file with a PR so the
team can review the scope and expiry.

### Monthly digest & slice coverage

[`.github/workflows/plan-2-8-monthly-digest.yml`](../.github/workflows/plan-2-8-monthly-digest.yml)
runs on the 1st of every month at 13:00 UTC and emits a monthly
trend digest + top-movers (10 slices) from the same rolling-bench
history. Artifacts carry a 365-day retention so retros always have
a year of context to reach back to.

[`scripts/plan_2_8_coverage.py`](../scripts/plan_2_8_coverage.py)
reports how many TF×family slices in the latest snapshot sit below
the `min_events` floor. Use `--fail-on-under` in CI to enforce a
hard coverage bar before promoting a bench run.

The weekly digest workflow now also streams this coverage report
into the run summary (step "Plan 2.8 slice coverage").

### Slice stability

[`scripts/plan_2_8_history_stability.py`](../scripts/plan_2_8_history_stability.py)
computes per-slice HR stddev across the last N snapshots. It surfaces
slices whose calibration jitters week over week even when no
individual alert fires. Use `--fail-on-unstable` in CI when
investigating a regression suspect.

### Managing the snooze config

[`scripts/plan_2_8_snooze_admin.py`](../scripts/plan_2_8_snooze_admin.py)
wraps [`configs/plan_2_8_snoozes.json`](../configs/plan_2_8_snoozes.json)
with `add` / `list` / `expire` / `rm` subcommands so operators don’t
hand-edit JSON:

```
python scripts/plan_2_8_snooze_admin.py add --tf 5m --family OB \
    --reason 'warming up after Phase E2 promotion' \
    --expires 2026-05-01T00:00:00Z
python scripts/plan_2_8_snooze_admin.py list --active
python scripts/plan_2_8_snooze_admin.py expire
```

[`scripts/plan_2_8_snooze_lint.py`](../scripts/plan_2_8_snooze_lint.py)
validates the config shape, flags stale or malformed entries, and
catches duplicate `(tf, family)` pairs. The weekly workflow runs it
in `--warn-only` mode before the snooze is applied so operators see
issues in the run summary without blocking the digest.

### Alert history log

[`scripts/plan_2_8_alert_history.py`](../scripts/plan_2_8_alert_history.py)
appends every fired drift alert to a long-running JSONL log, keyed by
`(captured_at, tf, family)` so replays don’t duplicate rows. Useful
for multi-quarter retrospectives on "which slices kept us noisy?".
The weekly digest workflow runs this append step after the digest
upload and publishes the rolling log as the `plan-2-8-alert-history`
artifact with 365-day retention.

[`scripts/plan_2_8_alert_history_summary.py`](../scripts/plan_2_8_alert_history_summary.py)
reads that log and ranks TF×family slices by how many times they
fired inside a configurable lookback window — helpful when
triaging chronic offenders for snooze or calibration review.

### N-week rolling HR trend

[`scripts/plan_2_8_digest_rollup.py`](../scripts/plan_2_8_digest_rollup.py)
buckets snapshots into ISO weeks (latest wins within a week) and
emits a sparkline per TF×family over the last N weeks, with the
first→last `trend_pp` delta. The monthly digest workflow streams
this rollup into the run summary as a quick "is this slice sloping?"
read.

## Pin-test inventory

- `tests/test_plan_2_8_s0_pine_trend_tf_tooltips.py`
- `tests/test_plan_2_8_s3_1_chart_tf_expansion.py`
- `tests/test_plan_2_8_s3_1_per_tf_partitioning.py`
- `tests/test_plan_2_8_tf_family_rollup.py`
- `tests/test_plan_2_8_rolling_workflow_rollup_wiring.py`
- `tests/test_plan_2_8_rolling_workflow_history_wiring.py`
- `tests/test_plan_2_8_q4_gate_bundle_builder.py`
- `tests/test_plan_2_8_q4_gate_evaluator.py`
- `tests/test_plan_2_8_q4_gate_evaluator_adr_body.py`
- `tests/test_plan_2_8_q4_gate_workflow.py`
- `tests/test_plan_2_8_status.py`
- `tests/test_plan_2_8_status_daily_workflow.py`
- `tests/test_plan_2_8_history_archive.py`
- `tests/test_plan_2_8_history_rotate.py`
- `tests/test_plan_2_8_history_validate.py`
- `tests/test_plan_2_8_history_diff.py`
- `tests/test_plan_2_8_top_movers.py`
- `tests/test_plan_2_8_alert_snooze.py`
- `tests/test_plan_2_8_coverage.py`
- `tests/test_plan_2_8_history_stability.py`
- `tests/test_plan_2_8_snooze_admin.py`
- `tests/test_plan_2_8_snooze_lint.py`
- `tests/test_plan_2_8_history_backfill.py`
- `tests/test_plan_2_8_adr_queue.py`
- `tests/test_plan_2_8_weekly_runcard.py`
- `tests/test_plan_2_8_health.py`
- `tests/test_plan_2_8_changelog_digest.py`
- `tests/test_plan_2_8_runcard_index.py`
- `tests/test_plan_2_8_digest_compare.py`
- `tests/test_plan_2_8_alert_history_heatmap.py`
- `tests/test_plan_2_8_runbook_toc.py`
- `tests/test_plan_2_8_status_snapshot.py`
- `tests/test_plan_2_8_digest_archive.py`
- `tests/test_plan_2_8_runcard_from_status.py`
- `tests/test_plan_2_8_history_prune.py`
- `tests/test_plan_2_8_history_export.py`
- `tests/test_plan_2_8_runbook_link_check.py`
- `tests/test_plan_2_8_snooze_expiry_report.py`
- `tests/test_plan_2_8_manifest.py`
- `tests/test_plan_2_8_manifest_diff.py`
- `tests/test_plan_2_8_digest_schema.py`
- `tests/test_plan_2_8_runcard_badge.py`
- `tests/test_plan_2_8_badge_markdown.py`
- `tests/test_plan_2_8_alert_trend.py`
- `tests/test_plan_2_8_alert_trend_gate.py`
- `tests/test_plan_2_8_digest_to_coverage.py`
- `tests/test_plan_2_8_runbook_sections.py`
- `tests/test_plan_2_8_status_ledger.py`
- `tests/test_plan_2_8_status_ledger_summarize.py`
- `tests/test_plan_2_8_status_ledger_prune.py`
- `tests/test_plan_2_8_weekly_index.py`
- `tests/test_plan_2_8_run_stamp.py`
- `tests/test_plan_2_8_status_flip_alert.py`
- `tests/test_plan_2_8_ledger_csv_export.py`
- `tests/test_plan_2_8_ledger_validate.py`
- `tests/test_plan_2_8_ledger_stats_json.py`
- `tests/test_plan_2_8_artifact_checksum.py`
- `tests/test_plan_2_8_digest_archive_index.py`
- `tests/test_plan_2_8_checksum_verify.py`
- `tests/test_plan_2_8_ledger_status_matrix.py`
- `tests/test_plan_2_8_digest_size_budget.py`
- `tests/test_plan_2_8_ledger_downtime.py`
- `tests/test_plan_2_8_ledger_weekly_rollup.py`
- `tests/test_plan_2_8_digest_index_compare.py`
- `tests/test_plan_2_8_ledger_uptime_pct.py`
- `tests/test_plan_2_8_digest_file_manifest.py`
- `tests/test_plan_2_8_weekly_summary_index.py`
- `tests/test_plan_2_8_ledger_latest_status.py`
- `tests/test_plan_2_8_ledger_longest_streak.py`
- `tests/test_plan_2_8_digest_metadata.py`
- `tests/test_plan_2_8_metadata_diff.py`
- `tests/test_plan_2_8_ledger_trend.py`
- `tests/test_plan_2_8_weekly_summary_linkcheck.py`
- `tests/test_plan_2_8_ledger_flap_rate.py`
- `tests/test_plan_2_8_trend_threshold_alert.py`
- `tests/test_plan_2_8_digest_artifact_catalog.py`
- `tests/test_plan_2_8_ledger_status_today.py`
- `tests/test_plan_2_8_digest_recent_changes.py`
- `tests/test_plan_2_8_weekly_summary_toc_only.py`
- `tests/test_plan_2_8_ledger_streak_now.py`
- `tests/test_plan_2_8_digest_artifact_age.py`
- `tests/test_plan_2_8_ledger_month_summary.py`
- `tests/test_plan_2_8_ledger_worst_day.py`
- `tests/test_plan_2_8_digest_catalog_diff.py`
- `tests/test_plan_2_8_weekly_summary_section_stats.py`
- `tests/test_plan_2_8_ledger_best_day.py`
- `tests/test_plan_2_8_digest_size_trend.py`
- `tests/test_plan_2_8_weekly_summary_heading_order.py`
- `tests/test_plan_2_8_ledger_status_share.py`
- `tests/test_plan_2_8_digest_missing_artifacts.py`
- `tests/test_plan_2_8_weekly_summary_toc_checksum.py`
- `tests/test_plan_2_8_ledger_hour_histogram.py`
- `tests/test_plan_2_8_digest_stale_report.py`
- `tests/test_plan_2_8_weekly_summary_required_sections.py`
- `tests/test_plan_2_8_ledger_weekday_histogram.py`
- `tests/test_plan_2_8_digest_summary_index.py`
- `tests/test_plan_2_8_ledger_gap_detector.py`
- `tests/test_plan_2_8_ledger_transition_matrix.py`
- `tests/test_plan_2_8_digest_hash_inventory.py`
- `tests/test_plan_2_8_weekly_summary_preview.py`
- `tests/test_plan_2_8_alert_history.py`
- `tests/test_plan_2_8_alert_history_summary.py`
- `tests/test_plan_2_8_digest_rollup.py`
- `tests/test_plan_2_8_monthly_digest_workflow.py`
- `tests/test_plan_2_8_rolling_workflow_rotate_wiring.py`
- `tests/test_plan_2_8_rolling_workflow_validate_wiring.py`
- `tests/test_plan_2_8_trend_digest.py`
- `tests/test_plan_2_8_trend_digest_issue_body.py`
- `tests/test_plan_2_8_weekly_digest_workflow.py`
- `tests/test_plan_2_8_weekly_digest_issue_wiring.py`
- `tests/test_docs_decisions_adr.py`
- `tests/test_append_adr.py`

## Escalation

If Phase 2 bundle producer is not ready by W12, open an ADR with
`Status. deferred.` on the "2H promotion" slug and slip the W13 gate
to the next 13-week window. Do not short-circuit the gate.
