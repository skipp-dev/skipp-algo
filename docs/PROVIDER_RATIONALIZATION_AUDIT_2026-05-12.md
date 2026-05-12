# Provider rationalization — final-state audit (2026-05-12)

This document closes the provider-utilization audit started in PR #2154
and rolls together every code change made in the post-OPRA PR series
(#2155 through #2160). It is the **single source of truth** for which
external data providers the platform consumes, which endpoints are live
vs. dormant, and the remaining recommendations.

## TL;DR

- Six external providers are still in scope: **FMP, Databento, Benzinga,
  Finnhub, Unusual Whales, NewsAPI.ai**.
- **Databento OPRA.PILLAR** replaces UW flow-alerts as the canonical
  UOA/options-flow source (PR #2155). `ENABLE_OPRA_UOA` stays at 0
  until the entitlement probe (#2157) confirms PILLAR is in-plan.
- **UW flow-alerts** code path is gone (#2158); other UW endpoints
  remain in module but dormant.
- **FMP mover-seed + eod-bulk** path is verified consumed by
  `run_open_prep` and now has live HTTP probes (#2159).
- **FinnhubClient** stubs are wired to real HTTP (#2156, Option A) for
  the four signals with no FMP equivalent.
- **Finnhub `/company-news`** dropped as duplicative with FMP
  `/stable/news/stock-latest` (#2160).

## Final-state provider matrix

| Provider | Status | Critical endpoints | Probed in `scripts/probe_providers.py` |
|---|---|---|---|
| **FMP** | Production primary | `/stable/quote`, `/stable/news/stock-latest`, `/stable/news/press-releases-latest`, `/stable/company-screener`, `/stable/technical-indicators/rsi`, `/stable/treasury-rates`, `/stable/biggest-gainers`, `/stable/biggest-losers`, `/stable/most-actives`, `/stable/eod-bulk` | **all critical=True** |
| **Databento** | Production primary | `metadata.list_datasets`, `ohlcv-1d`, OPRA.PILLAR (UOA gated by `ENABLE_OPRA_UOA`) | critical=True |
| **Benzinga** | Mixed | News + earnings calendar live; options_activity retired; ratings/analyst live in UI | non-critical |
| **Finnhub** | Free-tier four-signal | social-sentiment, news-sentiment, recommendation, insider-sentiment | critical=True (`/quote`) + the four signals |
| **Unusual Whales** | Dormant | flow-alerts removed; darkpool / spot-GEX / market-tide / insider remain non-critical, gated by DISABLED-on-401/403 | non-critical |
| **NewsAPI.ai** | Dormancy delta documented separately | — | — |

## Per-finding final state (cross-ref to PRs)

### G1 / D2 — smc-library-refresh `workflow_run` trigger
**Status:** Already implemented. Recommendation withdrawn in
`docs/audit-followup-2026-05-12-G1-G2-correction.md`. No new PR.

### G2 / D3 — FMP eod-bulk + most-actives + biggest-gainers/losers
**Status:** Already consumed by `_build_mover_seed` (lines 829-854) +
`_incremental_atr_from_eod_bulk` (line 3023) in `open_prep/run_open_prep.py`.
**Closed by:** PR #2159 — added four live HTTP probes
(`probe_fmp_biggest_gainers`, `probe_fmp_biggest_losers`,
`probe_fmp_most_actives`, `probe_fmp_eod_bulk`) registered as
`critical=True` so a plan-tier downgrade surfaces in CI.

### G3 — 13F-HR refresh
**Status:** Closed by PR #2154 + commit `40e47997`.

### G4 — FMP plan-tier documentation
**Status:** Closed by PR #2154 + commit `5257a99c`.

### G5 — FinnhubClient empty stubs
**Status:** Closed by **PR #2156 (Option A)**. The user rejected the
audit's "remove dead methods" recommendation because the FMP-replacement
mapping is NOT 1:1 for `/stock/recommendation`, `/news-sentiment`,
`/stock/social-sentiment`, `/stock/insider-sentiment`. Stubs now
delegate to `terminal_finnhub._get` so:
- DISABLED-on-403/404 muting is inherited
- 429 backoff is inherited
- API-key handling is consistent across open-prep + terminal UI
Return shapes: `get_insider_sentiment` and `get_pattern_recognition`
now return raw `dict` (was `[]`); existing callers already destructure
via `.get("data", [])` / `.get("points", [])`.

### G6 — FMP endpoint usage instrumentation
**Status:** Closed by PR #2154 + commit `f1792e73`.

### Databento entitlement
**Status:** Closed by **PR #2157**. Added
`scripts/probe_databento_entitlement.py` (read-only via
`client.metadata.list_datasets()` + `get_dataset_range()`) cross-tabbed
against the audit-focus datasets (OPRA.PILLAR, DBEQ.BASIC, XNAS.ITCH,
XNYS.PILLAR, GLBX.MDP3, OPRA.AUCTION, DBEQ.MAX) and schemas (mbo, mbp-1,
mbp-10, definition, statistics, imbalance, cmbp-1, cbbo-1s, trades).
`docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` updated with a Databento
entitlement subsection. **`ENABLE_OPRA_UOA` stays at 0** until the
entitlement probe confirms PILLAR access.

### Unusual Whales — flow-alerts surgical removal
**Status:** Closed by **PR #2158** (stacked on #2155). Removed:
- `UW_FLOW_ALERTS_PATH` constant
- `UnusualWhalesAdapter.fetch_flow_alerts()` method
- `fetch_uw_options_flow()` module-level wrapper
- `_to_benzinga_shape()` renamed `_DEPRECATED` (kept as historical
  reference for the shape `ingest_opra_options_flow.py` reproduces)
- `_fetch_uw_options` import + UW branch in
  `_cached_bz_options_op` (open_prep/streamlit_monitor.py)
- `probe_uw_options_flow()` function + its `critical=True` Probe entry
**Preserved:** darkpool, spot-GEX, market-tide, insider, news-headlines
endpoints — they remain in module and route through the existing
DISABLED-on-401/403 pattern (silent `[]` when no key configured).
`is_uw_configured` kept in `streamlit_monitor.py` so the other UW tabs
still light up if a key is ever restored.

### Finnhub Option B — drop duplicates
**Status:** Closed by **PR #2160**. Only `fetch_company_news` /
`CompanyNewsItem` / `_NEWS_TTL` removed — FMP `/stable/news/stock-latest`
is the canonical newsstack source and Finnhub `/company-news` had zero
production callers. The other four free-tier signals are no-op-removable
because they have no FMP equivalent (kept under Option A).

## Open recommendations (not yet executed)

1. **Flip `ENABLE_OPRA_UOA` default to `1`** — blocked on the
   entitlement-probe results from #2157. When the probe confirms
   OPRA.PILLAR is in-plan (mbo + trades + definition schemas
   reachable), this becomes a 1-line config change. Until then, the
   monitor falls back to the "Benzinga (retired)" caption and returns
   `[]` rows, which is the documented graceful-degrade behaviour.

2. **NewsAPI.ai dormancy delta** — documented separately. The current
   wiring is not on the production hot-path; no removal recommended at
   this time, but a "dormant" marker should be added to the ops doc to
   prevent accidental future re-activation without a use-case review.

3. **UW dormancy retention period** — re-evaluate in Q3 2026 whether
   the remaining UW endpoints (darkpool, spot-GEX, market-tide,
   insider, news-headlines) should be removed entirely or kept dormant.
   Decision deferred to a separate audit cycle so this PR series stays
   surgical.

4. **Probe parity** — `scripts/probe_providers.py` now covers all 10
   FMP critical endpoints, both Databento entitlement paths, the four
   live Finnhub signals, and the dormant UW endpoints. Suggest adding
   a `--json` output format in a follow-up so the probe can drive a
   CI alert with structured payload (out of scope here).

## PR series at a glance

| PR | Subject | Branch | Base |
|---|---|---|---|
| #2154 | provider-utilization audit follow-up (G3/G4/G6 + G1/G2 corrections) | — | main |
| #2155 | feat: replace UW options-flow with Databento OPRA.PILLAR UOA detector | `feat/opra-uoa-detector-replace-uw` | main |
| #2156 | feat: G5/Option-A wire FinnhubClient to terminal_finnhub HTTP | `chore/g5-remove-dead-macro-stubs` | main |
| #2157 | audit: Databento entitlement probe + ops doc audit-focus schemas | `feat/databento-entitlement-probe` | main |
| #2158 | refactor: surgical removal of UW flow-alerts options-flow path | `chore/remove-unusual-whales` | `feat/opra-uoa-detector-replace-uw` |
| #2159 | audit(probes): G2/D3 re-check — FMP mover-seed + eod-bulk probes | `chore/g2-d3-fmp-mover-probes` | main |
| #2160 | refactor(finnhub): Option B — drop /company-news (duplicative with FMP) | `chore/finnhub-option-b-drop-duplicates` | main |

## Discipline pins still green

All seven PRs were verified against the discipline pin bundle:

- `tests/test_silent_security_and_boundary_bundle.py` — frozen
  ledgers for `sys.path` / `logging.basicConfig`
- `tests/test_requirements_discipline_pin.py` — `_DEP_LINE_BUDGET = 24`
- `tests/test_workflow_databento_cron_respacing.py` — ≥60-min handoff

Commit identity used throughout: `skipp-dev <preuss.steffen@yahoo.com>`.
No `--no-verify`, no force-push, no `workflow_dispatch` triggered.

## References

- Audit follow-up correction: `docs/audit-followup-2026-05-12-G1-G2-correction.md`
- Ops quick reference: `docs/OPEN_PREP_OPS_QUICK_REFERENCE.md` (Databento entitlement section)
- Provider failure semantics: `docs/engineering-program/provider_failure_semantics.md`
- Code: `scripts/probe_providers.py`, `scripts/probe_databento_entitlement.py`, `open_prep/macro.py::FinnhubClient`, `newsstack_fmp/ingest_unusual_whales.py`, `newsstack_fmp/ingest_opra_options_flow.py`, `open_prep/opra_uoa.py`
