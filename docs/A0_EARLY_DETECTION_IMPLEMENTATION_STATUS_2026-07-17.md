# A0 early detection implementation status — updated 2026-07-18

## Implemented and merged

- Versioned A0 volume semantics, provider-neutral decision contract, golden
  replay cases, latency telemetry, Databento-style stream state, recovery,
  parity storage and bounded load behavior.
- Deterministic PRE-A0 trailing features, robust multi-window ETA,
  `NONE/WATCH/BUILDING/IMMINENT` hysteresis and a payload that cannot represent
  confirmed A0 or calibrated probability.
- Horizon outcomes, atomic partitioned snapshot dataset, censor-aware labels,
  machine-readable leakage audit and deterministic sealed day splits.
- Base rate, deterministic logistic baseline, Platt calibration, Brier/ECE,
  versioned model artifact and fail-closed shadow inference.
- Timestamp-bounded volume-profile, microstructure, news and opening-auction
  contracts, bounded warm set and common ablation gate.
- Independent flags, deployment approval gates, alert budget, telemetry, alert
  rules and separate A0-Fast/PRE-A0 rollback runbooks.
- PRE-A0 shadow/observe runtime wiring in the isolated A0-Fast worker, including
  per-symbol trailing state, reset on recovery/disconnect, calibrated scoring,
  weighted 5s/1s sampling, atomic Parquet flushes and combined metrics. There
  is still no notification import or publication path.

## Operational status on Railway

- `a0-fast-shadow` deployment `0040410c-92b0-4d79-b51a-6de96dece18d`
  runs `python -m services.a0_fast_detector.worker` from the dedicated
  Dockerfile; the former accidental root-Streamlit deployment is replaced.
- `/healthz` passed and Grafana reports
  `up{job="a0_fast"}=1` for the private `/metrics` endpoint.
- Databento Live authenticated and resolved the configured 900-symbol
  universe. Because 18 July 2026 is a Saturday, no market records were
  manufactured: record, decision and snapshot counters correctly remain 0.
- PRE-A0 loaded artifact `71831770afe43bdd424aa7ab` with
  `pre_a0_model_ready=1` and `pre_a0_calibration_valid=1`.
- `/app/data` is a ready 5-GB persistent Railway volume. It is empty apart
  from filesystem metadata until the first real market record is persisted.
- The collection clock starts with the next complete US regular session.

The separate `opra-live-shadow` daemon is deployed privately as Railway
deployment `ec65c6ff-1503-444a-b7ef-ce076f23e8f6`, with its own `/app/data`
volume and the five-parent hotlist
`SPY,QQQ,AAPL,NVDA,TSLA`. It authenticated both the `definition` and `tcbbo`
OPRA subscriptions and loaded 39.542 definitions after one correctly retried
gateway timeout. A live-discovered parent-symbology defect in the historical
definition bootstrap was corrected and regression-tested before the final
rollout. Because the rollout happened on Saturday, the trade and candidate
counters correctly remain 0. The service has no public domain, HTTP,
notification, alert or product-publication path and uses its own 7–10
complete-session evidence window; that evidence cannot satisfy or bypass any
A0-Fast or PRE-A0 gate.

## Deliberately not claimed

The code foundation does not manufacture empirical evidence. The following
gates remain open until representative real sessions and approved provider
inputs exist:

- 20+ session A0-Fast parity and stability evidence;
- representative positive, negative and censored PRE-A0 corpus;
- untouched walk-forward comparison proving a model beats base rate and ETA;
- valid calibration and slice stability on final/shadow windows;
- provider-specific microstructure, Benzinga and auction ablation reports;
- any `active` or `notify` deployment.

The production-effect default remains `off`; the isolated Railway worker is
intentionally `shadow`. Active notification or production promotion requires
a separate explicit deployment decision after the evidence gates pass.
