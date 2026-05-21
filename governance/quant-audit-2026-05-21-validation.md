# Quant Audit 2026-05-21 — Validation Response

**Status:** Validated. 8 of 10 audit claims are already mitigated with code +
dedicated regression tests + governance controls. 2 claims are PARTIAL and are
addressed by the dedicated pin tests landed alongside this document.

**Audit input:** External "SkippALGO Repository Quant Audit Report" dated
2026-05-21. The report follows a generic AI-templated structure and cites
several invented file paths (`backtest_engine.py`, `candidate_ranking.py`,
`incident_response/`) that do not match the actual repository state. It also
makes a factually incorrect claim that `ml/walkforward.py` "lacks embargo" —
the file does exist (see Claim #1 below) and López-de-Prado embargo + purging
is implemented and regression-tested.

## Per-claim verdicts

| # | Audit risk | Verdict | Evidence in repo |
|---|---|---|---|
| 1 | Lookahead bias in ML walkforward | **MITIGATED** | `ml/walkforward.py` implements López-de-Prado embargo + purging; pinned by `tests/test_walk_forward_embargo_c2_1.py`. |
| 2 | Databento cache data leakage | **PARTIAL → PINNED** | `databento_client._clamp_request_end` + `_daily_request_end_exclusive` clamp every request end to the published `available_end`. Per-API-key cache scoping landed 2026-05-10 (`terminal_databento.py`). New pin: `tests/test_databento_ingestion_asof_invariant.py`. |
| 3 | Open-prep macro context timing | **MITIGATED** | `open_prep/macro.py` enforces strict US/Eastern timing and recency classification on macro events. |
| 4 | Pine script repainting | **MITIGATED** | `tests/test_pine_alert_bar_close_gate.py` enforces `barstate.isconfirmed` on alerts; `test_usi_lint.py` flags conditional `ta.*` calls. |
| 5 | ML calibration (Brier / ECE) | **MITIGATED** | `ml/metrics.py` exposes `brier_score` + `expected_calibration_error`; promotion-gate pinned by `tests/test_metric_brier_ece_pin.py`. |
| 6 | Backtest realism (slippage / latency / impact) | **MITIGATED** | `scripts/build_backtest_slippage_samples.py` derives slippage from real live-incubation fills (stronger than synthetic models). Bridge latency monitored in `smc_tv_bridge/provider_status.py`. |
| 7 | Multiple-testing / alpha-budget governance | **MITIGATED** | `governance/alpha_ledger.py` enforces a 0.05 alpha budget; `governance/promotion_gate.py` enforces FDR significance. |
| 8 | Survivorship bias in candidate ranking | **PARTIAL → PINNED** | `databento_reference.py` (line 45) tracks `LSTAT` (listing-status) corporate-action events; `open_prep/run_open_prep.py::_fetch_corporate_action_flags` converts them into `corporate_action_penalty`; `open_prep/screen.py` surfaces the `corporate_action_risk` warn flag at penalty >= 1.0. New pin: `tests/test_open_prep_screen_delisting_filter.py`. |
| 9 | CI gate quality / artifact reproducibility | **MITIGATED** | 30+ workflows in `.github/workflows/`, ~425 test files including dedicated workflow-policy tests (`test_workflow_upload_artifact_unguarded_inventory.py`, `test_workflow_continue_on_error_inventory.py`, `test_workflow_dependency_hygiene.py`, etc.). |
| 10 | Operational incident response | **MITIGATED** | `docs/runbook-degraded-mode.md`, `docs/OPEN_PREP_INCIDENT_RUNBOOK_MATRIX.md`, plus per-component ADRs and runbooks in `docs/`. |

## Audit recommendations explicitly NOT adopted

The audit suggested opening 8 GitHub issues with test commands like
`pytest tests/test_walkforward.py`, `tests/test_no_lookahead.py`,
`tests/test_no_data_leakage.py`, `tests/test_model_calibration.py`,
`tests/test_survivorship_bias.py`, `tests/test_backtest_realism.py`,
`tests/test_alpha_budget.py`, `tests/test_ci_gates.py`. None of those file
names exist; equivalents already exist under descriptive names listed in the
table above. Opening those issues would create reviewer noise and duplicate
existing work, so they are **deliberately not filed**.

## Action items landed with this PR

- `tests/test_databento_ingestion_asof_invariant.py` — pins
  `_clamp_request_end` / `_daily_request_end_exclusive` /
  `_exclusive_ohlcv_1s_end` against silent regression to future-data requests.
- `tests/test_open_prep_screen_delisting_filter.py` — pins the LSTAT →
  `corporate_action_penalty` → screen `corporate_action_risk` warn-flag flow,
  complementing the existing `LCC` test
  (`test_corporate_action_flags_include_reference_identifier_change`).

## Re-running this audit response

Future audits arriving with similar generic claims can be triaged in minutes
by consulting the table above. If a new claim does not match the repo state,
extend this document rather than re-running an end-to-end audit.
