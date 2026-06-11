# Feature-Importance sample directory (Amendment A1.D)

This directory holds daily JSONL ledgers `fi_samples_YYYY-MM-DD.jsonl`
written by `open_prep.outcomes.persist_feature_importance_samples()` after
each `open_prep` outcome-backfill run.

> **⚠️ Data-validity note (2026-06-11):** every `fi_samples_*.jsonl` file
> up to and including 2026-06-09 carries **all-zero values for the 14
> weighted `*_component` features** (only `zone_priority_score` is real).
> Root cause: `outcomes_<date>.json` records never persisted the
> `score_breakdown` components, so `backfill_feature_importance()`
> defaulted every component to `0.0` (c10b side-finding, fixed
> 2026-06-11). Additionally, files overlap: the daily backfill re-emits
> its full lookback window, so the same `(symbol, date)` row appears in
> up to ~3 consecutive files (n-inflation; deduped at read time since
> 2026-06-11). **FI reports/recommendations derived from these legacy
> files are not evidence.** A backfill is not possible — the historical
> component values were never persisted anywhere. Valid samples
> accumulate forward from the first post-fix open-prep run; the weight
> auto-tuning gate (`_MIN_TUNING_SAMPLES = 200` unique labeled samples)
> re-arms once enough clean data exists.


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
