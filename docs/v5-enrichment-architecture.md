# v5 Enrichment Architecture

## Overview

The v5 generated Pine library emits **51 `export const` fields** across 8 sections:

| Section | Count | New in v5 |
|---------|-------|-----------|
| Core + Meta | 6 | — |
| Microstructure lists | 7 | — |
| Regime | 4 | — |
| News | 5 | — |
| Calendar | 7 | — |
| Layering | 4 | — |
| Providers + Volume | 4 | — |
| **Event Risk** | **14** | **Yes** |

The manifest carries `library_field_version: "v5"`, and the `enrichment_blocks` list includes `event_risk`.

## Event Risk Fields (v5)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `EVENT_WINDOW_STATE` | string | `"CLEAR"` | `CLEAR` / `PRE_EVENT` / `ACTIVE` / `COOLDOWN` |
| `EVENT_RISK_LEVEL` | string | `"NONE"` | `NONE` / `LOW` / `ELEVATED` / `HIGH` |
| `NEXT_EVENT_CLASS` | string | `""` | `MACRO` / `EARNINGS` / `""` |
| `NEXT_EVENT_NAME` | string | `""` | e.g. `"FOMC Rate Decision"` |
| `NEXT_EVENT_TIME` | string | `""` | e.g. `"14:00"` |
| `NEXT_EVENT_IMPACT` | string | `"NONE"` | `NONE` / `LOW` / `MEDIUM` / `HIGH` |
| `EVENT_RESTRICT_BEFORE_MIN` | int | `0` | Minutes to restrict before event |
| `EVENT_RESTRICT_AFTER_MIN` | int | `0` | Minutes to restrict after event |
| `EVENT_COOLDOWN_ACTIVE` | bool | `false` | Post-event cooldown period active |
| `MARKET_EVENT_BLOCKED` | bool | `false` | Market-wide block active |
| `SYMBOL_EVENT_BLOCKED` | bool | `false` | Symbol-level block active (earnings) |
| `EARNINGS_SOON_TICKERS` | string | `""` | CSV ticker list |
| `HIGH_RISK_EVENT_TICKERS` | string | `""` | CSV ticker list |
| `EVENT_PROVIDER_STATUS` | string | `"ok"` | `ok` / `no_data` / `calendar_missing` / `news_missing` |

## What Is Guaranteed

1. **All 51 fields are always present** in every generated library, regardless of provider health.
2. **Safe neutral defaults** are applied when a provider fails — every section has its own default set.
3. **Backward compatibility**: all 37 v4 fields remain at their original positions. The 14 event-risk fields are additive. Existing Pine consumers (SMC_Core_Engine, Dashboard, Strategy) are unaffected.

## Provider Policy

| Domain | Primary | Fallbacks | Provenance key |
|--------|---------|-----------|----------------|
| base_scan | Databento | — | `base_scan_provider` |
| regime | FMP | — (defaults on failure) | `regime_provider` |
| news | FMP | Benzinga | `news_provider` |
| calendar | FMP | Benzinga | `calendar_provider` |
| technical | FMP | TradingView | `technical_provider` |
| event_risk | smc_event_risk_builder (derived) | — | `event_risk_provider` |

Event risk is a **derived stage** — it reads the calendar + news results already obtained by their respective provider chains. It does not call any external API directly. `EVENT_PROVIDER_STATUS` reflects whether the upstream calendar and/or news domains delivered data.

Provider provenance is surfaced via `SMC_PROVIDER_COUNT` and `SMC_STALE_PROVIDERS` in the library.

## Runtime Boundary

The v5 generation path has **zero dependency on `open_prep`**. The FMP client is `scripts/smc_fmp_client.SMCFMPClient` — a thin stdlib-only adapter. All 12 canonical runtime modules are verified `open_prep`-free via `tests/test_smc_fmp_client_isolation.py`.

## CI Workflow

The GitHub Actions workflow (`.github/workflows/smc-library-refresh.yml`) runs 4× daily on weekdays (12:30, 14:30, 16:30, 18:30 UTC):

1. **Base data scan** (Databento)
2. **Enrichment** (regime, news, calendar, layering, event-risk)
3. **Evidence gates** (integration / structure / core tests)
4. **Change detection** (diff against previous library)
5. **Version governance** (breaking-change detection)
6. **Publish** to TradingView (blocked on breaking changes)
7. **Commit** artifacts (blocked on breaking changes)
8. **Signal + event-risk alerts** (Telegram / email)

## Secret Naming

| Secret | Required | Purpose |
|--------|----------|---------|
| `FMP_API_KEY` | Yes | FMP enrichment data |
| `BENZINGA_API_KEY` | Yes | News/calendar fallback |
| `DATABENTO_API_KEY` | Yes | Base data generation |
| `TV_STORAGE_STATE` | Yes | TradingView publish |
| `GH_PAT` | Yes | Auto-commit |
| `TELEGRAM_BOT_TOKEN` | No | Alert delivery |
| `TELEGRAM_CHAT_ID` | No | Alert delivery |
| `SMTP_HOST` / `SMTP_USER` / `SMTP_PASS` | No | Email alerts |
| `ALERT_EMAIL_FROM` / `ALERT_EMAIL_TO` | No | Email alerts |

**Compatibility note**: Secret names are unchanged from v4 — no reconfiguration needed when upgrading.

## Alerting (v5)

The v5 alert notifier (`scripts/smc_alert_notifier.py`) evaluates both legacy and event-risk rules:

- **Legacy**: `RISK_OFF`, `TRADE_BLOCKED`, `MACRO_EVENT`, `PROVIDER_DEGRADED`
- **Event-risk**: `EVENT_INCOMING`, `EVENT_RELEASE`, `EVENT_COOLDOWN_START`, `EVENT_COOLDOWN_END`, `EVENT_MARKET_BLOCKED`, `EVENT_SYMBOL_BLOCKED`

Duplicate suppression via a JSON state file ensures alerts fire only on state transitions.

## Test Coverage

- `tests/test_enrichment_contract_integration.py` — field inventory (51 fields), deterministic output
- `tests/test_enrichment_provider_policy.py` — provider policy, event-risk wiring (58 tests)
- `tests/test_smc_event_risk_builder.py` — event-risk builder (40 tests)
- `tests/test_smc_fmp_client_isolation.py` — open_prep boundary (37 tests)
- `tests/test_smc_alert_notifier.py` — v5 alert rules (55 tests)
- `tests/test_pine_consumer_contract.py` — BUS channel contracts
- `tests/test_v4_pipeline_e2e.py` — end-to-end pipeline
- `tests/test_cli_pipeline_e2e.py` — CLI integration
