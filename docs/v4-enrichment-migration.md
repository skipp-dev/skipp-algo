# v4 Enrichment Migration

## What Changed

The generated Pine library expanded from **11 fields** (base-scan-only) to **37 `export const` fields** across 7 sections:

| Section | Fields | Count |
|---------|--------|-------|
| Core + Meta | `SMC_UNIVERSE`, `SMC_BULLISH`, `SMC_WATCH`, `SMC_VERSION`, `SMC_ASOF`, `SMC_FIELD_VERSION` | 6 |
| Lists | `SMC_BULLISH_LIST`, `SMC_WATCH_LIST`, `SMC_ADDED_LIST`, `SMC_REMOVED_LIST`, `SMC_PROMOTED_LIST`, `SMC_DEMOTED_LIST`, `SMC_FULL_UNIVERSE_LIST` | 7 |
| Regime | `SMC_MARKET_REGIME`, `SMC_VIX_LEVEL`, `SMC_MACRO_BIAS`, `SMC_SECTOR_BREADTH` | 4 |
| News | `SMC_NEWS_BULLISH`, `SMC_NEWS_BEARISH`, `SMC_NEWS_NEUTRAL`, `SMC_NEWS_HEAT`, `SMC_TICKER_HEAT` | 5 |
| Calendar | `SMC_EARNINGS_TODAY`, `SMC_EARNINGS_TOMORROW`, `SMC_EARNINGS_BMO`, `SMC_EARNINGS_AMC`, `SMC_MACRO_EVENT`, `SMC_MACRO_EVENT_NAME`, `SMC_MACRO_EVENT_TIME` | 7 |
| Layering | `SMC_GLOBAL_HEAT`, `SMC_GLOBAL_STRENGTH`, `SMC_TONE`, `SMC_TRADE_STATE` | 4 |
| Providers + Volume | `SMC_PROVIDER_COUNT`, `SMC_STALE_PROVIDERS`, `SMC_TOTAL_VOLUME`, `SMC_AVG_VOLUME` | 4 |

The library manifest now carries `library_field_version: "v4"` and an `enrichment_blocks` list enumerating the 24 enrichment keys present.

## What Is Guaranteed

1. **All 37 fields are always present** in every generated library, regardless of provider health.
2. **Safe neutral defaults** are applied when a provider fails:
   - Regime: `UNKNOWN`, `vix_level = 0.0`, `macro_bias = 0.0`, `sector_breadth = 0.0`
   - News: empty ticker lists, `news_heat = 0.0`, empty heat map
   - Calendar: empty ticker strings, `high_impact_macro_today = false`, empty event name/time
   - Layering: `global_heat = 0.0`, `global_strength = 0.0`, `tone = "NEUTRAL"`, `trade_state = "ALLOWED"`
   - Providers: `provider_count = 0`, `stale_providers = ""`
3. **Backward compatibility**: SMC_Core_Engine.pine reads 15 of the 37 fields via `mp.FIELD`. The remaining 22 are reserved for Dashboard and Strategy consumption via BUS channels. Existing consumers are unaffected.

## Provider Policy

Each enrichment domain has an explicit provider chain:

| Domain | Primary | Fallbacks |
|--------|---------|-----------|
| base_scan | Databento | — |
| regime | FMP | — (defaults on failure) |
| news | FMP | Benzinga |
| calendar | FMP | Benzinga |
| technical | FMP | TradingView |

Provider provenance is recorded in the enrichment dict (`regime_provider`, `news_provider`, `calendar_provider`) and surfaced via `SMC_PROVIDER_COUNT` and `SMC_STALE_PROVIDERS` in the library.

## Defaults on Provider Failure

The `write_pine_library()` function in the generator applies defaults per `EnrichmentDict` (defined in `scripts/smc_enrichment_types.py`). All sub-dicts use `total=False` so any block can be omitted — the writer falls back to safe neutral values for every missing key. No field is ever absent from the generated output.

## CI Workflow

The GitHub Actions workflow (`.github/workflows/smc-library-refresh.yml`) runs enrichment automatically 4× daily on weekdays (12:30, 14:30, 16:30, 18:30 UTC). It:

1. Generates the full v4 library with enrichment
2. Gates on the enrichment contract (37 fields)
3. Detects changes against the previous commit
4. Publishes to TradingView if changed
5. Commits updated artifacts
6. Fires Telegram/email alerts on enrichment state changes

## Test Coverage

- `tests/test_enrichment_contract_integration.py` — 36 tests validating all 37 fields
- `tests/test_pine_consumer_contract.py` — 16 tests validating BUS channel contracts
- `tests/test_smc_bridge_regression.py` — golden fixture regression (updated with `enrichment` block)
