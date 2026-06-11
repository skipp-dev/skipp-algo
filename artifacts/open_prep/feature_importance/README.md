# Feature-importance reports

Daily reports `report_<ts>.json` + `latest.json` written by
`open_prep.feature_importance_report` from the fi_samples ledgers in
`artifacts/open_prep/outcomes/feature_importance/`.

> **⚠️ Reports ≤ 2026-06-09 are vacuous — do not treat as evidence.**
> Their input samples carried all-zero values for the 14 weighted
> `*_component` features (c10b producer bug: `score_breakdown` was never
> persisted into `outcomes_<date>.json`; fixed 2026-06-11) and the
> labeled-sample counts are ~3× inflated by overlapping backfill windows
> (deduped at read time since 2026-06-11). The 🔴 "weak predictor"
> recommendations in those reports are artifacts of zero-variance input,
> and `ranking_drift: ok` reflects a constant ranking on constant data.
> No production weight adjustment was ever derived from them (verified
> 2026-06-11: no candidate-weight artifacts exist, `DEFAULT_WEIGHTS`
> unchanged). Recomputation is impossible — the historical component
> values were never persisted. Trustworthy reports restart with the
> first post-fix samples.
