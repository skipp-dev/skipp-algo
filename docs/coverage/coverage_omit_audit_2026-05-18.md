# Coverage Omit Audit — 2026-05-18

**Status:** active audit contract
**Owner:** skipp-dev
**Source of truth:** `pyproject.toml::tool.coverage.run.omit`

## Scope

The open finding cited 13 coverage-gate omits, including 6 added in the
previous two weeks. Current `main` has grown further: this audit records every
current omit entry so future changes cannot hide behind the older count.

Current count:

- 19 total omit patterns in `pyproject.toml`
- 17 production/non-test patterns after excluding `tests/*` and `*.pine`
- 6 Issue #2200 entries from 2026-05-14
- 3 PR #2258 workflow-lint CLI entries

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

## Follow-up rule

A PR that changes `tool.coverage.run.omit` must also update this audit. The
contract test `tests/test_coverage_omit_audit.py` enforces that every omit
pattern in `pyproject.toml` appears here verbatim.
