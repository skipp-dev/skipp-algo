# A0 early detection implementation status — updated 2026-07-21

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

- `a0-fast-shadow` runs `python -m services.a0_fast_detector.worker` from the
  dedicated Dockerfile; the former accidental root-Streamlit deployment is
  replaced. The earlier source-linked `main` deployment
  `81fa3f96-75b3-451f-9c95-bb64f4598861` exposed excessive Databento
  per-symbol INFO logging. PR #3786 merged the bounded logging fix as
  `fdd3051aa`. After PR #3778 was merged before its evidence gate, deployment
  `486770bd-98fe-425c-b82d-24e3e9e6a5ae` restored the verified pre-notify
  runtime. Worker startup, authentication and subscription acknowledgements
  remain visible without the mapping flood.
- The first regular-session audit on 21 July invalidated the earlier
  "deployed, now collecting" interpretation. The pre-#3840 process received
  15,430 OHLCV messages while processing zero records and writing zero
  snapshots. PR #3840 fixed the missing-`ts_recv` normalization and made
  record rejections visible. Its replacement container then processed live
  records, but a mid-session restart exposed a second blocker: Databento
  Historical ended around eight minutes behind Live, so reconstruction up to
  the current bar returned `422 data_end_after_available_end` and still wrote
  no PRE-A0 evidence.
- The runtime recovery contract now uses Databento Live intraday replay from
  the current session open (or connection time before the open). A failed
  Historical gap repair requests a fresh complete Live replay instead of
  repeatedly querying beyond Historical availability.
- `up{job="a0_fast"}=1`, stream connectivity, model readiness and calibration
  readiness prove only control-plane health. They do not prove that PRE-A0
  measurement is active. `/evidencez=200`, increasing processing/inference/
  snapshot counters and persisted Parquet plus manifest files are now the
  mandatory evidence-flow proof.
- Databento Live authenticated and resolved the configured 899-symbol
  universe. `SVAC` was removed after Databento explicitly returned
  `symbol_resolution_failed`; no other symbol was changed. Because 19 July
  2026 is a Sunday, no market records were
  manufactured: record, decision, snapshot and flush counters correctly
  remain 0.
- PRE-A0 loaded artifact `71831770afe43bdd424aa7ab` with
  `pre_a0_model_ready=1` and `pre_a0_calibration_valid=1`.
- `/app/data` is a ready 5-GB persistent Railway volume. At the 21 July audit
  it was still empty apart from filesystem metadata.
- No session before the first verified `/evidencez=200` interval and durable
  snapshot partition counts toward the collection window. The valid-session
  counter therefore remained zero at this audit.

The separate `opra-live-shadow` daemon is deployed privately with its own
`/app/data` volume and the five-parent hotlist `SPY,QQQ,AAPL,NVDA,TSLA`. The
earlier source-linked `main` deployment `37713734-d43e-4a74-8352-3f941c0e61c7`
authenticated both OPRA subscriptions but exposed a weekend bootstrap defect:
Saturday was incorrectly selected as the latest complete UTC day. PR #3786
merged the weekday/provider-availability fallback as `fdd3051aa`; source
deployment `1fb3066c-66d8-4c5e-bc55-f3eec8a9d16e` now runs that commit. On
Sunday it loaded 39.542 Friday definitions without a bootstrap warning,
acknowledged both `definition` and `tcbbo` live subscriptions and persisted an
updated `shadow_only` snapshot under `/app/data`. Trade and candidate counters
correctly remain 0. The service has no public domain, HTTP, notification, alert
or product-publication path and uses its own 7–10 complete-session evidence
window; that evidence cannot satisfy or bypass any A0-Fast or PRE-A0 gate.

Both Railway services remain connected to `skipp-dev/skipp-algo:main`. PR #3778
was merged as `d38091ba` despite its documented evidence hold; this change
reverts that notification layer. The Railway environment remained fail-closed
throughout: both modes were `shadow`, deployment approval and Slack credentials
were absent, and the 20-session/200-episode gate was unmet. No notification was
sent and the notification implementation requires a fresh review after real
evidence exists.

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
