# Feature-Importance sample directory (Amendment A1.D)

This directory holds daily JSONL ledgers `fi_samples_YYYY-MM-DD.jsonl`
written by `open_prep.outcomes.persist_feature_importance_samples()` after
each `open_prep` outcome-backfill run.

Until the daily job has produced ≥ 5 sequential days of files,
`open_prep.feature_importance_report` will return `status=no_data`.

Acceptance gate (G1 baseline → green):

* ≥ 5 sequential daily files present.
* `feature_importance_report --lookback 7` returns `status=ok`.
* Top-10 ranking stable between days 5 and 10
  (`max_position_delta ≤ 3`).

Once green, write `docs/g1_baseline_<DATE>.md` with the Top-10 + drift
status and update `/memories/repo/q3q4-plan-progress-*` with the
acceptance date so G2/G3 (Amendment A1.E) can start.
