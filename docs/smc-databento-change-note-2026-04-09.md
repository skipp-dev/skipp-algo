# SMC / Databento Change Note - 2026-04-09

Stand: 2026-04-09

## Scope

This note summarizes the latest published SMC / Databento / NewsAPI.ai mainline wave:

- `37b3213a` Add Databento reference alias cache
- `30e01e41` Add NewsAPI status and probe tooling
- `a2e0b520` Integrate Databento reference risk into open prep
- `0c1e0d9b` Add SMC deep review verification docs
- `0b6f350c` Wire Databento reference risk into enrichment
- `2ce832c8` Document NewsAPI and Databento enrichment updates

## What Changed

### 1. Databento reference state is now a first-class input

The repo now carries a cached Databento reference layer that resolves symbol aliases and recent identifier-change events instead of treating them as ad-hoc edge cases.

Key effects:

- symbol normalization can reuse cached alias mappings instead of hardcoded one-off replacements
- recent identifier changes can be folded into event-risk and Open Prep corporate-action penalties
- terminal and screening helpers can refresh reference state before symbol lookup instead of discovering alias drift too late

Main files in this slice:

- `databento_reference.py`
- `databento_utils.py`
- `databento_volatility_screener.py`
- `databento_client.py`
- `terminal_databento.py`

### 2. NewsAPI.ai fallback moved from stateless pull to resumable feed usage

The NewsAPI.ai / Event Registry fallback path now persists cursor state and exposes explicit provider diagnostics.

Key effects:

- news fallback can resume from the last seen article epoch and feed URI instead of always starting from a cold timestamp window
- live snapshot and pipeline consumers can distinguish hard provider failure from `ok_no_recent_matches`
- a dedicated probe script exists for debugging search-seeded feed cursor behavior outside the main pipeline

Main files in this slice:

- `newsstack_fmp/config.py`
- `newsstack_fmp/pipeline.py`
- `newsstack_fmp/ingest_fmp.py`
- `open_prep/newsstack_status.py`
- `scripts/probe_newsapi_feed_cursor.py`
- `scripts/generate_smc_micro_base_from_databento.py`

### 3. Open Prep and event-risk now respect identifier-change signals

The SMC event-risk layer no longer only reflects calendar and news inputs. Recent Databento reference changes can now produce symbol-level risk by themselves.

Key effects:

- `build_event_risk(...)` accepts reference-risk input and can emit `NEXT_EVENT_CLASS = "CORPORATE_ACTION"`
- recent identifier changes can set `SYMBOL_EVENT_BLOCKED`, raise `HIGH_RISK_EVENT_TICKERS`, and keep provider status at `ok` even when calendar/news are empty
- Open Prep corporate-action flags now include identifier-change fields and penalties in the merged premarket context

Main files in this slice:

- `scripts/smc_event_risk_builder.py`
- `scripts/smc_enrichment_types.py`
- `scripts/smc_provider_policy.py`
- `open_prep/run_open_prep.py`

### 4. Review and runbook docs were split into raw review vs verified plan

The deep-review follow-up is now documented as a verified companion instead of leaving the raw review as the only narrative source.

Key effects:

- raw review assertions that were too absolute are now paired with a verified correction layer
- the first productive local SMC run has a dedicated runbook instead of being scattered across older documents
- the root README and architecture docs now describe the current NewsAPI.ai / Databento behavior instead of the older simplified model

Main files in this slice:

- `smc_deep_review_v5.md`
- `docs/smc_deep_review_v5_verified_action_plan.md`
- `docs/smc_local_first_productive_run.md`
- `README.md`
- `docs/tradingview-micro-library-publish.md`
- `docs/v5-enrichment-architecture.md`

## Validation Snapshot

Published work in this wave was covered by focused regression slices:

- `tests/test_smc_live_news_bus.py` -> `15 passed`
- `tests/test_newsstack_fmp.py tests/test_newsstack_status.py tests/test_newsstack_pipeline_newsapi.py` -> `161 passed`
- `tests/test_open_prep.py` -> `259 passed, 2 subtests passed`
- `tests/test_databento_decomposition.py tests/test_enrichment_provider_policy.py tests/test_smc_event_risk_builder.py` -> `210 passed`

## Operator Impact

The practical result of this wave is narrower than a full new feature set but materially important:

- symbol alias drift and identifier changes are now visible to the SMC risk pipeline instead of silently bypassing it
- NewsAPI.ai fallback is now stateful, inspectable, and easier to debug when live feeds return no fresh symbol matches
- the repo now has a cleaner separation between raw architecture review, verified findings, and the shortest productive operator path