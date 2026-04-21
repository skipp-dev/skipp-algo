# A1.D — G1 Feature-Importance Baseline Seed (started)

* **Started:** 2026-04-21
* **Workflow:** `.github/workflows/feature-importance-daily.yml` (added in
  same batch as this marker).
* **Sink directory:** `artifacts/open_prep/outcomes/feature_importance/`
  created with README; `.gitkeep` not needed because README counts.
* **Acceptance gate:**
  * ≥ 5 sequential `fi_samples_YYYY-MM-DD.jsonl` files.
  * `python -m open_prep.feature_importance_report --lookback 7` returns
    `status=ok`.
  * Top-10 ranking stable between day 5 and day 10
    (`max_position_delta ≤ 3`).
* **Earliest acceptance date:** 2026-04-26 (5 weekday runs).
* **Drift comparator:** the E4 work (commit `c23b64aa`,
  `_extract_ranking()` + `compute_ranking_drift()` + `_load_previous_latest()`)
  is already wired and emits `ranking_drift` blocks once two
  `latest.json` snapshots exist.

Status:
* [ ] day 5 reached
* [ ] day 10 reached
* [ ] approval memo `docs/g1_baseline_<DATE>.md` written
* [ ] G2 (Amendment A1.E) can start
