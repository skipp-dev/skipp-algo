# Library Field Audit — WP-A5

Commit-Basis: `1003cccd` on `origin/main`  
Date: 2026-04-15

## Summary

| Category | Count | Description |
|---|---|---|
| **HERO_CRITICAL** | 15 | Feed into hero card, trust tier, product state |
| **SURFACE_ACTIVE** | 144 | Used by at least one Pine `mp.*` consumer |
| **BACKEND_ONLY** | 66 | Generated for enrichment; no Pine consumer |
| **DEPRECATED** | 63 | In `DEPRECATED_FIELD_POLICY`; zero Pine consumers |
| **Total** | **288** | |

Active fields (HERO + SURFACE): **159** (target: 120–150).

## HERO_CRITICAL (15)

| Field | Hero Role |
|---|---|
| `MARKET_REGIME` | `compose_core_hero_text`, `lib_regime_blocked/dimmed` |
| `TRADE_STATE` | `lib_regime_blocked` ("BLOCKED"), `lib_regime_dimmed` ("DISCOURAGED") |
| `SIGNAL_QUALITY_SCORE` | `lib_sq_score` → confidence threshold, BUS QualityScore |
| `SIGNAL_QUALITY_TIER` | `lib_sq_tier` → `resolve_trust_tier`, health badge |
| `SIGNAL_WARNINGS` | `lib_sq_warnings` → `compose_why_now_text`, `compose_main_risk_text` |
| `SIGNAL_BIAS_ALIGNMENT` | `lib_sq_bias_alignment` → `resolve_core_bias_text`, health badge |
| `SIGNAL_FRESHNESS` | `lib_sq_freshness` → `resolve_trust_tier` |
| `EVENT_PROVIDER_STATUS` | `lib_erl_provider_status` → `resolve_trust_tier`, provider state |
| `EVENT_WINDOW_STATE` | `lib_erl_window_state` → event risk state, BUS LeanPackA |
| `EVENT_RISK_LEVEL` | `lib_erl_level` → event risk state, BUS LeanPackA |
| `MARKET_EVENT_BLOCKED` | `lib_erl_market_blocked` → event risk state, BUS LeanPackA |
| `SYMBOL_EVENT_BLOCKED` | `lib_erl_symbol_blocked` → event risk state, BUS LeanPackA |
| `STRUCTURE_TREND_STRENGTH` | `lib_strl_trend_strength` → BUS LeanPackA |
| `STRUCTURE_FRESH` | `lib_strl_fresh` → BUS LeanPackA |
| `STRUCTURE_LAST_EVENT` | `lib_strl_last_event` → BUS LeanPackA |

## DEPRECATED (63) — Zero Pine Consumers

| Group | Fields | Count |
|---|---|---|
| event_risk_v5 | `NEXT_EVENT_CLASS`, `HIGH_RISK_EVENT_TICKERS` | 2 |
| session_context_v5_2 | `SESSION_STRUCTURE_STATE`, `SESSION_FVG_BULL_ACTIVE`, `SESSION_FVG_BEAR_ACTIVE`, `SESSION_BPR_ACTIVE`, `SESSION_RANGE_TOP`, `SESSION_RANGE_BOTTOM`, `SESSION_MEAN`, `SESSION_VWAP`, `SESSION_TARGET_BULL`, `SESSION_TARGET_BEAR` | 10 |
| liquidity_pools_v5_2 | `BUY_SIDE_POOL_LEVEL`, `SELL_SIDE_POOL_LEVEL`, `BUY_SIDE_POOL_STRENGTH`, `SELL_SIDE_POOL_STRENGTH`, `POOL_PROXIMITY_PCT`, `POOL_CLUSTER_DENSITY`, `UNTESTED_BUY_POOLS`, `UNTESTED_SELL_POOLS` | 8 |
| order_blocks_v5_2 | `NEAREST_BULL_OB_LEVEL`, `NEAREST_BEAR_OB_LEVEL`, `BULL_OB_FRESHNESS`, `BEAR_OB_FRESHNESS`, `BULL_OB_MITIGATED`, `BEAR_OB_MITIGATED`, `BULL_OB_FVG_CONFLUENCE`, `BEAR_OB_FVG_CONFLUENCE`, `OB_DENSITY`, `OB_BIAS`, `OB_NEAREST_DISTANCE_PCT`, `OB_STRENGTH_SCORE`, `OB_CONTEXT_SCORE` | 13 |
| zone_projection_v5_2 | `ZONE_PROJ_TARGET_BULL`, `ZONE_PROJ_TARGET_BEAR`, `ZONE_PROJ_RETEST_EXPECTED`, `ZONE_PROJ_TRAP_RISK`, `ZONE_PROJ_SPREAD_QUALITY`, `ZONE_PROJ_HTF_ALIGNED`, `ZONE_PROJ_BIAS`, `ZONE_PROJ_CONFIDENCE`, `ZONE_PROJ_DECAY_BARS`, `ZONE_PROJ_SCORE` | 10 |
| profile_context_v5_2 | `PROFILE_VOLUME_NODE`, `PROFILE_DECAY_HALFLIFE`, `PROFILE_CONSISTENCY`, `PROFILE_RECLAIM_RATE`, `PROFILE_STOP_HUNT_RATE` | 5 |
| imbalance_lifecycle_v5_3 | `BPR_DIRECTION` | 1 |
| session_structure_v5_3 | `SESS_HIGH`, `SESS_LOW`, `SESS_OPEN_RANGE_HIGH`, `SESS_OPEN_RANGE_LOW`, `SESS_OPEN_RANGE_BREAK`, `SESS_IMPULSE_DIR`, `SESS_IMPULSE_STRENGTH`, `SESS_INTRA_BOS_COUNT`, `SESS_INTRA_CHOCH`, `SESS_PDH`, `SESS_PDL`, `SESS_PDH_SWEPT`, `SESS_PDL_SWEPT`, `SESS_STRUCT_SCORE` | 14 |

**Note:** `zone_intelligence_v5_1` (13), `reversal_context_v5_1` (12), and `structure_state_v5_3` (14) are in `DEPRECATED_FIELD_POLICY` but **all** their fields still have active Pine consumers — they remain SURFACE_ACTIVE.

## BACKEND_ONLY (66) — No Pine Consumer

| Group | Fields | Count |
|---|---|---|
| Meta | `ASOF_TIME`, `LOOKBACK_DAYS`, `REFRESH_COUNT`, `UNIVERSE_ID`, `UNIVERSE_SIZE` | 5 |
| Regime | `MACRO_BIAS`, `MACRO_BIAS_RAW`, `SECTOR_BREADTH`, `VIX_LEVEL` | 4 |
| News | `NEWS_HEAT_GLOBAL`, `NEWS_NEUTRAL_TICKERS`, `TICKER_HEAT_MAP` | 3 |
| Calendar | `EARNINGS_AMC_TICKERS`, `EARNINGS_BMO_TICKERS`, `EARNINGS_TOMORROW_TICKERS`, `MACRO_EVENT_NAME`, `MACRO_EVENT_TIME` | 5 |
| Layering | `GLOBAL_HEAT`, `GLOBAL_STRENGTH`, `TONE` | 3 |
| Provider | `PROVIDER_COUNT`, `STALE_PROVIDERS` | 2 |
| Volume | `HOLIDAY_SUSPECT_TICKERS` | 1 |
| Volatility | `VOLATILITY_ATR_RATIO`, `VOLATILITY_FALLBACK_REASON`, `VOLATILITY_PROXY_SOURCE`, `VOLATILITY_PROXY_SYMBOL`, `VOLATILITY_REGIME_CONFIDENCE` | 5 |
| Ensemble | `ENSEMBLE_AVAILABLE_COMPONENTS` | 1 |
| Liquidity Sweeps | `SWEEP_DIRECTION`, `SWEEP_ZONE_TOP`, `SWEEP_ZONE_BOTTOM`, `LIQUIDITY_TAKEN_DIRECTION` | 4 |
| Range Regime | `RANGE_REGIME`, `RANGE_WIDTH_PCT`, `RANGE_POSITION`, `RANGE_HIGH`, `RANGE_LOW`, `RANGE_DURATION_BARS`, `RANGE_VPOC_LEVEL`, `RANGE_VAH_LEVEL`, `RANGE_VAL_LEVEL`, `RANGE_BALANCE_STATE`, `RANGE_REGIME_SCORE` | 11 |
| Range Profile | `RANGE_ACTIVE`, `RANGE_TOP`, `RANGE_BOTTOM`, `RANGE_MID`, `RANGE_WIDTH_ATR`, `RANGE_BREAK_DIRECTION`, `PROFILE_POC`, `PROFILE_VALUE_AREA_TOP`, `PROFILE_VALUE_AREA_BOTTOM`, `PROFILE_VALUE_AREA_ACTIVE`, `PROFILE_BULLISH_SENTIMENT`, `PROFILE_BEARISH_SENTIMENT`, `PROFILE_SENTIMENT_BIAS`, `LIQUIDITY_ABOVE_PCT`, `LIQUIDITY_BELOW_PCT`, `LIQUIDITY_IMBALANCE`, `PRED_RANGE_MID`, `PRED_RANGE_UPPER_1`, `PRED_RANGE_UPPER_2`, `PRED_RANGE_LOWER_1`, `PRED_RANGE_LOWER_2`, `IN_PREDICTIVE_RANGE_EXTREME` | 22 |

## Anomaly

`SMC_Imbalance_Context.pine` references `mp.FVG_NET_IMBALANCE` — field **not generated** by `write_pine_library()`. Orphan/stale reference.

## Reduction Candidates

To reach the 120–150 active target, the 63 DEPRECATED fields should be sunset (WP-A6).
The 66 BACKEND_ONLY fields are enrichment data kept for dashboard/API consumers and
should be reviewed for actual backend usage in a follow-up.
