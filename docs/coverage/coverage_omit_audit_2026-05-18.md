# Coverage Omit Audit — 2026-05-18

**Status:** active audit contract
**Owner:** skipp-dev
**Source of truth:** `pyproject.toml::tool.coverage.run.omit`

## Scope

The open finding cited 13 coverage-gate omits, including 6 added in the
previous two weeks. Current `main` has grown further: this audit records every
current omit entry so future changes cannot hide behind the older count.

Current count:

- 42 total omit patterns in `pyproject.toml`
- 40 production/non-test patterns after excluding `tests/*` and `*.pine`
- 6 Issue #2200 entries from 2026-05-14
- 3 PR #2258 workflow-lint CLI entries
- 23 main-coverage repair entries from 2026-05-20

## Policy

Coverage omits are allowed only when the target is one of:

- `test-or-non-python`: test code or non-Python source outside the coverage run
- `manual-ui`: UI/manual operator surface whose validation is a smoke checklist
- `standalone-cli`: one-shot or workflow-only CLI, not imported by production modules
- `generated-or-probe`: generated, probe, entitlement, or external-system artifact

Every entry must have a reason and a target state. New entries must update this
audit in the same PR.

## Audit table

| Omit pattern | Class | Added / source | Owner | Current rationale | Target state |
|---|---|---|---|---|---|
| `tests/*` | test-or-non-python | baseline | skipp-dev | Test modules are not part of runtime coverage. | Keep permanent. |
| `*.pine` | test-or-non-python | baseline | skipp-dev | Pine files are not Python coverage targets. | Keep permanent. |
| `open_prep/streamlit_monitor.py` | manual-ui | pre-2026-05 | skipp-dev | Large Streamlit monitor UI; covered by manual dashboard smoke flow, not imported into live SMC gate. | Keep until dashboard harness exists. |
| `scripts/fvg_asia_real_sample.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | One-off FVG sample CLI, manual operator action. | Revisit when FVG sample generation becomes scheduled. |
| `scripts/fvg_label_audit_q3.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | One-off label audit CLI, manual operator action. | Revisit if promoted to recurring gate. |
| `scripts/pine_slim.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | Pine slimming utility, invoked manually. | Keep unless moved into release gate. |
| `scripts/probe_newsapi_feed_cursor.py` | generated-or-probe | 2026-04-23 expansion | skipp-dev | External NewsAPI cursor probe; needs live provider access. | Replace with mock-backed smoke if provider path becomes critical. |
| `scripts/run_smc_e2e_smoke_test.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | Smoke runner wrapper; behavior covered by downstream checks. | Keep; do not add business logic here. |
| `scripts/tv_publish_evidence_summary.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | Evidence summarizer CLI; release evidence is validated by TradingView automation tests. | Add unit tests if summary format becomes API. |
| `scripts/run_smc_release_gates.py` | standalone-cli | 2026-04-23 expansion | skipp-dev | Release-gate orchestrator with external TradingView/auth dependencies. | Keep; validate via smoke/contract tests. |
| `scripts/c10b_compute_cofiring.py` | standalone-cli | Issue #2200, 2026-05-14 | skipp-dev | One-shot C10b research computation, not a production import. | Remove omit if C10b analysis is productized. |
| `scripts/c10b_compute_variance_decomp.py` | standalone-cli | Issue #2200, 2026-05-14 | skipp-dev | One-shot C10b research computation, not a production import. | Remove omit if C10b analysis is productized. |
| `scripts/probe_databento_entitlement.py` | generated-or-probe | Issue #2200, 2026-05-14 | skipp-dev | Databento entitlement probe requires external account state. | Replace with mock-backed test only if entitlement probe gates CI. |
| `scripts/generate_showcase_summary.py` | standalone-cli | Issue #2200, 2026-05-14 | skipp-dev | Showcase summary generator, manual/output artifact helper. | Add tests if summary schema becomes consumed by product code. |
| `scripts/measure_databento_ops_run.py` | standalone-cli | Issue #2200, 2026-05-14 | skipp-dev | Operator measurement helper; no production import path. | Keep unless moved into scheduled ops workflow. |
| `newsstack_fmp/ingest_opra_options_flow.py` | generated-or-probe | Issue #2200, 2026-05-14 | skipp-dev | Requires Databento OPRA entitlement; module-test pin tracks deferred mock coverage. | Add mock-stub test when OPRA path enters active scope. |
| `scripts/lint_workflow_permissions.py` | standalone-cli | PR #2258 | skipp-dev | Workflow-only lint CLI; YAML semantics covered by workflow tests. | Keep while CLI remains workflow-only. |
| `scripts/lint_workflow_pythonunbuffered.py` | standalone-cli | PR #2258 | skipp-dev | Workflow-only lint CLI; YAML semantics covered by workflow tests. | Keep while CLI remains workflow-only. |
| `scripts/lint_workflow_defaults.py` | standalone-cli | PR #2258 | skipp-dev | Workflow-only lint CLI; YAML semantics covered by workflow tests. | Keep while CLI remains workflow-only. |
| `scripts/check_environment.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Local environment/self-check CLI for operators; no production import path. | Keep unless it becomes part of enforced setup automation. |
| `scripts/c10c_aggregate_per_bar.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | One-shot C10c analysis/export helper, manually invoked. | Remove omit if C10c analytics are productized. |
| `scripts/c10c_cofiring_vs_single.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | One-shot C10c analysis comparison CLI, not in runtime path. | Remove omit if promoted into regular analytics flow. |
| `scripts/c10c_joint_vs_product.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | One-shot C10c research computation, manually run. | Remove omit if turned into tested library code. |
| `scripts/count_main_locals.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Repo audit helper for local-variable counting, manual maintenance only. | Keep unless folded into a tested lint rule. |
| `scripts/databento_smoke_test.py` | generated-or-probe | main repair, 2026-05-20 | skipp-dev | Smoke/probe CLI against external Databento state. | Replace with mock-backed smoke if it becomes CI-critical. |
| `scripts/export_extended_structure_discovery_report.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Manual export/report generator, not imported by production modules. | Add tests if report schema becomes API-like. |
| `scripts/export_open_prep_lists.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Manual open-prep export CLI; policy tests guard write semantics, not business branches. | Keep unless moved into scheduled/reporting pipeline. |
| `scripts/export_open_prep_reports.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Manual open-prep reporting export, operator-triggered only. | Add tests if promoted to recurring pipeline step. |
| `scripts/export_parquet_csv_streaming.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Format-conversion/export utility, manually invoked. | Keep unless conversion logic is imported by product code. |
| `scripts/export_smc_live_news_snapshot.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Operator snapshot export for live-news state, not runtime-linked. | Add tests if snapshot schema becomes consumed downstream. |
| `scripts/export_smc_structure_artifacts_from_workbook.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Workbook-driven export helper, manual artifact generation only. | Keep unless moved under automated artifact pipeline. |
| `scripts/export_smc_structure_audit.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Small audit/export helper for structure review, manual invocation. | Keep unless promoted into gate logic. |
| `scripts/fvg_session_artifact_diagnosis.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Diagnosis CLI for session artifacts, operator troubleshooting tool. | Remove omit if diagnosis paths are productized. |
| `scripts/ib_client_id.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Interactive/manual IB client-id helper rather than runtime module. | Keep unless converted into importable client-id library logic. |
| `scripts/investigate_universe_delta.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Manual audit/investigation tool for universe deltas. | Keep unless turned into a scheduled validation gate. |
| `scripts/phase5_perf_trend.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Perf-trend analysis CLI used for ad-hoc review, not runtime execution. | Add tests if trend outputs become contract data. |
| `scripts/probe_fmp_13f_endpoints.py` | generated-or-probe | main repair, 2026-05-20 | skipp-dev | External FMP 13F endpoint probe requiring live provider behavior. | Replace with mock-backed contract test if endpoint path becomes core. |
| `scripts/profile_cron_with_pyspy.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Profiling helper for cron runs, manual diagnostics only. | Keep unless profiling moves into a tested support library. |
| `scripts/profile_pytest_durations.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Ad-hoc pytest duration profiler, maintenance-only CLI. | Keep unless profiling logic becomes imported tooling. |
| `scripts/regenerate_requirements_lock.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Manual requirements lock regeneration helper; not part of product runtime. | Keep unless lock generation becomes a tested release gate. |
| `scripts/scan_manifests_for_pytest_provenance.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Workflow/maintenance scan CLI; current assurance is policy-level rather than branch coverage. | Keep unless the scanner grows business logic worth direct tests. |
| `scripts/start_open_prep_suite.py` | standalone-cli | main repair, 2026-05-20 | skipp-dev | Suite/bootstrap runner wrapper, manually invoked orchestration surface. | Keep while downstream behavior remains covered elsewhere. |

## Follow-up rule

A PR that changes `tool.coverage.run.omit` must also update this audit. The
contract test `tests/test_coverage_omit_audit.py` enforces that every omit
pattern in `pyproject.toml` appears here verbatim.
