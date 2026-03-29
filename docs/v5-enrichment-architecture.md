# v5.3 Enrichment Architecture

## Overview

The v5.3 generated Pine library will emit **214 `export const` fields** across 22 sections.
v5.3 adds four new context layers that move the enrichment pipeline from a *snapshot-static* model
toward *structure-aware, lifecycle-tracking* intelligence.

| Section | Count | v5 | v5.1 | v5.2 | v5.3 |
|---------|-------|----|------|------|------|
| Core + Meta | 6 | — | — | — | — |
| Microstructure lists | 7 | — | — | — | — |
| Regime | 4 | — | — | — | — |
| News | 5 | — | — | — | — |
| Calendar | 7 | — | — | — | — |
| Layering | 4 | — | — | — | — |
| Providers + Volume | 4 | — | — | — | — |
| Event Risk | 14 | Yes | — | — | — |
| Flow Qualifier | 14 | — | Yes | — | — |
| Compression / ATR Regime | 5 | — | Yes | — | — |
| Zone Intelligence | 13 | — | Yes | — | — |
| Reversal Context | 12 | — | Yes | — | — |
| Session Context | 10 | — | — | Yes | — |
| Liquidity Sweeps | 9 | — | — | Yes | — |
| Liquidity Pools | 11 | — | — | Yes | — |
| Order Blocks | 13 | — | — | Yes | — |
| Zone Projection | 10 | — | — | Yes | — |
| Profile Context | 18 | — | — | Yes | — |
| **Structure State** | **12** | — | — | — | **Yes** |
| **Imbalance Lifecycle** | **11** | — | — | — | **Yes** |
| **Session-Scoped Structure** | **14** | — | — | — | **Yes** |
| **Range / Profile Regime** | **11** | — | — | — | **Yes** |

The manifest will carry `library_field_version: "v5.3"`.

### Version Progression

| Version | Total fields | Theme |
|---------|-------------|-------|
| v5 | 51 | Event risk, provider policy |
| v5.1 | 95 (+44) | Flow qualifier, compression, zone intelligence, reversal context |
| v5.2 | 166 (+71) | Session context, liquidity structure, order blocks, zone projection, profile context |
| **v5.3** | **214 (+48)** | **Structure state, imbalance lifecycle, session-scoped structure, range regime** |

---

## Contract-First Design Principle

Every v5.3 layer follows the same contract:

1. **DEFAULTS dict** — canonical safe defaults in a `dict[str, Any]`.
2. **TypedDict block** — added to `smc_enrichment_types.py` with `total=False`.
3. **EnrichmentDict key** — one new key per layer.
4. **Builder function** — `build_*(*, snapshot, symbol, overrides) → dict[str, Any]`.
5. **Pine section** — appended to `write_pine_library()`, reads from DEFAULTS on missing keys.
6. **`build_enrichment()` flag** — `enrich_*: bool = False`.
7. **V5_FIELD_INVENTORY** — all new field names added to both test inventories.

The generated library always emits all 228 fields regardless of provider health.
The builder may be disabled (flag `False`), in which case DEFAULTS are used.
No downstream consumer may assume a builder was actually executed — only that the fields exist.

The manifest carries `library_field_version: "v5.2"`, and the `enrichment_blocks` list includes all 6 new v5.2 blocks.

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

1. **All 228 fields are always present** in every generated library, regardless of provider health.
2. **Safe neutral defaults** are applied when a provider fails — every section has its own default set.
3. **Backward compatibility**: all 51 v5 fields remain at their original positions. The 44 v5.1, 71 v5.2, and 48 v5.3 fields are additive. Existing Pine consumers (SMC_Core_Engine, Dashboard, Strategy) are unaffected.

## v5.1 Fields — Flow Qualifier (14 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `REL_VOL` | float | `0.0` | Relative volume vs 20-day average |
| `REL_ACTIVITY` | float | `0.0` | Relative trade count vs average |
| `REL_SIZE` | float | `0.0` | Relative average trade size |
| `DELTA_PROXY_PCT` | float | `0.0` | Proxy for buy-sell delta (%) |
| `FLOW_LONG_OK` | bool | `false` | Flow confirms long direction |
| `FLOW_SHORT_OK` | bool | `false` | Flow confirms short direction |
| `ATS_VALUE` | float | `0.0` | Average trade size value |
| `ATS_CHANGE_PCT` | float | `0.0` | ATS change vs previous (%) |
| `ATS_ZSCORE` | float | `0.0` | ATS z-score (standardized) |
| `ATS_STATE` | string | `"NEUTRAL"` | `ACCUMULATION` / `DISTRIBUTION` / `TRANSITION` / `NEUTRAL` |
| `ATS_SPIKE_UP` | bool | `false` | Unusual spike up in ATS |
| `ATS_SPIKE_DOWN` | bool | `false` | Unusual spike down in ATS |
| `ATS_BULLISH_SEQUENCE` | bool | `false` | 3+ consecutive increasing ATS |
| `ATS_BEARISH_SEQUENCE` | bool | `false` | 3+ consecutive decreasing ATS |

## v5.1 Fields — Compression / ATR Regime (5 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `SQUEEZE_ON` | bool | `false` | BB inside KC — squeeze active |
| `SQUEEZE_RELEASED` | bool | `false` | Squeeze just released |
| `SQUEEZE_MOMENTUM_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `ATR_REGIME` | string | `"NORMAL"` | `COMPRESSION` / `NORMAL` / `EXPANSION` / `EXHAUSTION` |
| `ATR_RATIO` | float | `1.0` | ATR(14) / ATR(50) ratio |

## v5.1 Fields — Zone Intelligence (13 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ACTIVE_SUPPORT_COUNT` | int | `0` | Active support zones |
| `ACTIVE_RESISTANCE_COUNT` | int | `0` | Active resistance zones |
| `ACTIVE_ZONE_COUNT` | int | `0` | Total active zones |
| `PRIMARY_SUPPORT_LEVEL` | float | `0.0` | Nearest / strongest support price |
| `PRIMARY_RESISTANCE_LEVEL` | float | `0.0` | Nearest / strongest resistance price |
| `PRIMARY_SUPPORT_STRENGTH` | int | `0` | Support zone touch count |
| `PRIMARY_RESISTANCE_STRENGTH` | int | `0` | Resistance zone touch count |
| `SUPPORT_SWEEP_COUNT` | int | `0` | Liquidity sweeps into support |
| `RESISTANCE_SWEEP_COUNT` | int | `0` | Liquidity sweeps into resistance |
| `SUPPORT_MITIGATION_PCT` | float | `0.0` | Support zones mitigated (%) |
| `RESISTANCE_MITIGATION_PCT` | float | `0.0` | Resistance zones mitigated (%) |
| `ZONE_CONTEXT_BIAS` | string | `"NEUTRAL"` | `SUPPORT_HEAVY` / `RESISTANCE_HEAVY` / `NEUTRAL` |
| `ZONE_LIQUIDITY_IMBALANCE` | float | `0.0` | Support-minus-resistance imbalance |

## v5.1 Fields — Reversal Context (12 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `REVERSAL_CONTEXT_ACTIVE` | bool | `false` | Reversal context qualifies |
| `SETUP_SCORE` | int | `0` | 0–5 composite setup quality |
| `CONFIRM_SCORE` | int | `0` | 0–5 confirmation strength |
| `FOLLOW_THROUGH_SCORE` | int | `0` | 0–5 post-confirm continuation |
| `HTF_STRUCTURE_OK` | bool | `false` | HTF structure supports trade |
| `HTF_BULLISH_PATTERN` | bool | `false` | Bullish HTF pattern active |
| `HTF_BEARISH_PATTERN` | bool | `false` | Bearish HTF pattern active |
| `HTF_BULLISH_DIVERGENCE` | bool | `false` | Bullish divergence on HTF |
| `HTF_BEARISH_DIVERGENCE` | bool | `false` | Bearish divergence on HTF |
| `FVG_CONFIRM_OK` | bool | `false` | FVG confirms entry direction |
| `VWAP_HOLD_OK` | bool | `false` | VWAP hold sustained |
| `RETRACE_OK` | bool | `false` | Retrace within Fib 61.8% |

## v5.2 Fields — Session Context (10 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `SESSION_CONTEXT` | string | `"NONE"` | `ASIA` / `LONDON` / `NY_AM` / `NY_PM` / `NONE` |
| `IN_KILLZONE` | bool | `false` | Inside a killzone (ASIA_KZ, LONDON_KZ, NY_KZ) |
| `SESSION_MSS_BULL` | bool | `false` | Market structure shift bullish in session |
| `SESSION_MSS_BEAR` | bool | `false` | Market structure shift bearish in session |
| `SESSION_FVG_BULL_ACTIVE` | bool | `false` | Bullish FVG active in session |
| `SESSION_FVG_BEAR_ACTIVE` | bool | `false` | Bearish FVG active in session |
| `SESSION_TARGET_BULL` | float | `0.0` | Bullish session target level |
| `SESSION_TARGET_BEAR` | float | `0.0` | Bearish session target level |
| `SESSION_DIRECTION_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `SESSION_CONTEXT_SCORE` | int | `0` | 0–5 composite session quality |

## v5.2 Fields — Liquidity Sweeps (9 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `RECENT_BULL_SWEEP` | bool | `false` | Recent bullish sweep detected |
| `RECENT_BEAR_SWEEP` | bool | `false` | Recent bearish sweep detected |
| `SWEEP_TYPE` | string | `"NONE"` | `NONE` / `STOP_HUNT` / `LIQUIDITY_GRAB` / `INDUCEMENT` |
| `SWEEP_DIRECTION` | string | `"NONE"` | `NONE` / `BULL` / `BEAR` |
| `SWEEP_ZONE_TOP` | float | `0.0` | Upper boundary of sweep zone |
| `SWEEP_ZONE_BOTTOM` | float | `0.0` | Lower boundary of sweep zone |
| `SWEEP_RECLAIM_ACTIVE` | bool | `false` | Price reclaimed after sweep |
| `LIQUIDITY_TAKEN_DIRECTION` | string | `"NONE"` | `NONE` / `BUY_SIDE` / `SELL_SIDE` |
| `SWEEP_QUALITY_SCORE` | int | `0` | 0–5 sweep quality |

## v5.2 Fields — Liquidity Pools (11 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `BUY_SIDE_POOL_LEVEL` | float | `0.0` | Nearest buy-side liquidity pool price |
| `SELL_SIDE_POOL_LEVEL` | float | `0.0` | Nearest sell-side liquidity pool price |
| `BUY_SIDE_POOL_STRENGTH` | int | `0` | 0–5 strength of buy-side pool |
| `SELL_SIDE_POOL_STRENGTH` | int | `0` | 0–5 strength of sell-side pool |
| `POOL_PROXIMITY_PCT` | float | `0.0` | Distance to nearest pool (%) |
| `POOL_CLUSTER_DENSITY` | int | `0` | 0–5 density of nearby pools |
| `UNTESTED_BUY_POOLS` | int | `0` | Count of untested buy pools |
| `UNTESTED_SELL_POOLS` | int | `0` | Count of untested sell pools |
| `POOL_IMBALANCE` | float | `0.0` | −1..+1 buy/sell imbalance |
| `POOL_MAGNET_DIRECTION` | string | `"NONE"` | `NONE` / `UP` / `DOWN` |
| `POOL_QUALITY_SCORE` | int | `0` | 0–5 overall pool quality |

## v5.2 Fields — Order Blocks (13 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `NEAREST_BULL_OB_LEVEL` | float | `0.0` | Nearest bullish OB price |
| `NEAREST_BEAR_OB_LEVEL` | float | `0.0` | Nearest bearish OB price |
| `BULL_OB_FRESHNESS` | int | `0` | 0–5 freshness (5 = very recent) |
| `BEAR_OB_FRESHNESS` | int | `0` | 0–5 freshness |
| `BULL_OB_MITIGATED` | bool | `false` | Bullish OB has been mitigated |
| `BEAR_OB_MITIGATED` | bool | `false` | Bearish OB has been mitigated |
| `BULL_OB_FVG_CONFLUENCE` | bool | `false` | Bullish OB overlaps with FVG |
| `BEAR_OB_FVG_CONFLUENCE` | bool | `false` | Bearish OB overlaps with FVG |
| `OB_DENSITY` | int | `0` | 0–5 count of nearby OBs |
| `OB_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `OB_NEAREST_DISTANCE_PCT` | float | `0.0` | Distance to nearest OB (%) |
| `OB_STRENGTH_SCORE` | int | `0` | 0–5 strongest OB quality |
| `OB_CONTEXT_SCORE` | int | `0` | 0–5 overall OB context |

## v5.2 Fields — Zone Projection (10 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `ZONE_PROJ_TARGET_BULL` | float | `0.0` | Projected bullish target price |
| `ZONE_PROJ_TARGET_BEAR` | float | `0.0` | Projected bearish target price |
| `ZONE_PROJ_RETEST_EXPECTED` | bool | `false` | Zone retest expected |
| `ZONE_PROJ_TRAP_RISK` | string | `"NONE"` | `NONE` / `LOW` / `MEDIUM` / `HIGH` |
| `ZONE_PROJ_SPREAD_QUALITY` | string | `"NORMAL"` | `TIGHT` / `NORMAL` / `WIDE` |
| `ZONE_PROJ_HTF_ALIGNED` | bool | `false` | Higher timeframe aligned |
| `ZONE_PROJ_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `ZONE_PROJ_CONFIDENCE` | int | `0` | 0–5 projection confidence |
| `ZONE_PROJ_DECAY_BARS` | int | `0` | Bars since zone formation |
| `ZONE_PROJ_SCORE` | int | `0` | 0–5 composite projection quality |

## v5.2 Fields — Profile Context (18 fields)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `PROFILE_VOLUME_NODE` | string | `"NONE"` | `HVN` / `LVN` / `POC` / `NONE` |
| `PROFILE_VWAP_POSITION` | string | `"AT"` | `ABOVE` / `BELOW` / `AT` |
| `PROFILE_VWAP_DISTANCE_PCT` | float | `0.0` | Distance from VWAP (%) |
| `PROFILE_SPREAD_REGIME` | string | `"NORMAL"` | `TIGHT` / `NORMAL` / `WIDE` |
| `PROFILE_AVG_SPREAD_BPS` | float | `0.0` | Average spread in basis points |
| `PROFILE_SESSION_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `PROFILE_RTH_DOMINANCE_PCT` | float | `0.0` | RTH share of total volume (%) |
| `PROFILE_PM_QUALITY` | string | `"NORMAL"` | `STRONG` / `NORMAL` / `WEAK` |
| `PROFILE_AH_QUALITY` | string | `"NORMAL"` | `STRONG` / `NORMAL` / `WEAK` |
| `PROFILE_MIDDAY_EFFICIENCY` | float | `0.0` | Midday session efficiency |
| `PROFILE_DECAY_HALFLIFE` | float | `0.0` | Setup decay half-life (bars) |
| `PROFILE_CONSISTENCY` | float | `0.0` | 0–1 consistency score |
| `PROFILE_WICKINESS` | float | `0.0` | Wick-to-body ratio |
| `PROFILE_CLEAN_SCORE` | float | `0.0` | 0–1 clean intraday score |
| `PROFILE_RECLAIM_RATE` | float | `0.0` | 0–1 reclaim success rate |
| `PROFILE_STOP_HUNT_RATE` | float | `0.0` | Stop hunt frequency |
| `PROFILE_TICKER_GRADE` | string | `"C"` | `A` / `B` / `C` / `D` |
| `PROFILE_CONTEXT_SCORE` | int | `0` | 0–5 overall profile quality |

---

## v5.3 Layer 1 — Structure State (12 fields) — REQUIRED

Tracks real-time market structure: BOS/CHoCH events, swing sequences, and structure integrity.
This layer turns the enrichment pipeline from *point-in-time snapshot* into *stateful structure awareness*.

### Ownership

| Component | Responsibility |
|-----------|---------------|
| `scripts/smc_structure_state.py` | Python builder — derives from snapshot + optional CHoCH/BOS history |
| `smc_enrichment_types.py` | `StructureStateBlock` TypedDict |
| `generate_smc_micro_profiles.py` | Pine `export const` emission (12 fields) |
| `SMC_Core_Engine.pine` | Field reads + `struct_state_ok` context gate + BUS resolver |
| `SMC_Structure_State.pine` | **Optional** overlay — swing visualization, BOS/CHoCH markers |

### Field Contract

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `STRUCT_TREND` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` — dominant structure direction |
| `STRUCT_LAST_BOS_DIR` | string | `"NONE"` | `BULL` / `BEAR` / `NONE` — direction of last BOS |
| `STRUCT_LAST_CHOCH_DIR` | string | `"NONE"` | `BULL` / `BEAR` / `NONE` — direction of last CHoCH |
| `STRUCT_HH_COUNT` | int | `0` | Consecutive higher-high count |
| `STRUCT_LL_COUNT` | int | `0` | Consecutive lower-low count |
| `STRUCT_SWING_HIGH` | float | `0.0` | Current swing high level |
| `STRUCT_SWING_LOW` | float | `0.0` | Current swing low level |
| `STRUCT_BREAK_LEVEL` | float | `0.0` | Level that would invalidate current structure |
| `STRUCT_PROTECTED_HIGH` | bool | `false` | Protected (strong) high is intact |
| `STRUCT_PROTECTED_LOW` | bool | `false` | Protected (strong) low is intact |
| `STRUCT_FRESHNESS` | int | `0` | 0–5 recency of last structural event |
| `STRUCT_STATE_SCORE` | int | `0` | 0–5 composite structure quality |

### Engine Gate (required)

```
struct_state_ok = lib_struct_trend != "NEUTRAL" and lib_struct_freshness >= 2
```

### Rationale

Without structure state, the engine has no concept of *where* price is in its structural cycle.
v5.2 has BOS/CHoCH in the Session Context but only as session-level MSS flags — not as
a persistent, rolling structure tracker. This layer fills that gap.

---

## v5.3 Layer 2 — Imbalance Lifecycle (11 fields) — REQUIRED

Tracks the lifecycle of Fair Value Gaps (FVGs): creation → partial fill → CE → full rebalance → expiry.
Replaces the binary `SESSION_FVG_BULL/BEAR_ACTIVE` with a lifecycle-aware model.

### Ownership

| Component | Responsibility |
|-----------|---------------|
| `scripts/smc_imbalance_lifecycle.py` | Python builder — derives from snapshot FVG history |
| `smc_enrichment_types.py` | `ImbalanceLifecycleBlock` TypedDict |
| `generate_smc_micro_profiles.py` | Pine `export const` emission (11 fields) |
| `SMC_Core_Engine.pine` | Field reads + `imbalance_ok` context gate + BUS resolver |
| — | No dedicated overlay — data surfaces in existing `SMC_Liquidity_Structure.pine` |

### Field Contract

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `IMB_ACTIVE_BULL_COUNT` | int | `0` | Active (unfilled) bullish FVGs |
| `IMB_ACTIVE_BEAR_COUNT` | int | `0` | Active (unfilled) bearish FVGs |
| `IMB_NEAREST_BULL_LEVEL` | float | `0.0` | Nearest bullish FVG midpoint |
| `IMB_NEAREST_BEAR_LEVEL` | float | `0.0` | Nearest bearish FVG midpoint |
| `IMB_FILL_RATE` | float | `0.0` | 0.0–1.0 recent FVG fill rate |
| `IMB_CE_ACTIVE` | bool | `false` | Consequent Encroachment in progress |
| `IMB_REBALANCE_PCT` | float | `0.0` | 0.0–1.0 nearest gap rebalance progress |
| `IMB_AGE_BARS` | int | `0` | Age of nearest active imbalance (bars) |
| `IMB_DENSITY` | int | `0` | 0–5 imbalance cluster density |
| `IMB_BIAS` | string | `"NEUTRAL"` | `BULLISH` / `BEARISH` / `NEUTRAL` |
| `IMB_LIFECYCLE_SCORE` | int | `0` | 0–5 composite lifecycle quality |

### Engine Gate (required)

```
imbalance_ok = lib_imb_lifecycle_score >= 2 and lib_imb_density >= 1
```

### Design Notes

- `IMB_CE_ACTIVE` flags when price has entered a gap beyond 50% (Consequent Encroachment) — a common institutional entry trigger.
- `IMB_REBALANCE_PCT` tracks how much of the nearest gap has been "healed" (0 = untouched, 1 = fully rebalanced).
- `IMB_FILL_RATE` is a rolling average — high fill rates indicate a strong rebalance tendency, which may reduce FVG entry reliability.

---

## v5.3 Layer 3 — Session-Scoped Structure (14 fields) — REQUIRED

Combines session awareness (v5.2 Session Context) with intra-session structural tracking.
Where Session Context answers *"which session is it?"*, this layer answers *"what has happened structurally inside this session?"*.

### Ownership

| Component | Responsibility |
|-----------|---------------|
| `scripts/smc_session_structure.py` | Python builder — derives from snapshot + timestamp + session boundaries |
| `smc_enrichment_types.py` | `SessionStructureBlock` TypedDict |
| `generate_smc_micro_profiles.py` | Pine `export const` emission (14 fields) |
| `SMC_Core_Engine.pine` | Field reads + `session_struct_ok` context gate + BUS resolver |
| `SMC_Session_Context.pine` | Existing overlay extended with PDH/PDL sweep markers |

### Field Contract

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `SESS_HIGH` | float | `0.0` | Current session high |
| `SESS_LOW` | float | `0.0` | Current session low |
| `SESS_OPEN_RANGE_HIGH` | float | `0.0` | Opening range high (first N minutes) |
| `SESS_OPEN_RANGE_LOW` | float | `0.0` | Opening range low |
| `SESS_OPEN_RANGE_BREAK` | string | `"NONE"` | `NONE` / `ABOVE` / `BELOW` — OR break direction |
| `SESS_IMPULSE_DIR` | string | `"NONE"` | `BULL` / `BEAR` / `NONE` — session impulse direction |
| `SESS_IMPULSE_STRENGTH` | int | `0` | 0–5 impulse conviction |
| `SESS_INTRA_BOS_COUNT` | int | `0` | Intra-session BOS events |
| `SESS_INTRA_CHOCH` | bool | `false` | Intra-session CHoCH occurred |
| `SESS_PDH` | float | `0.0` | Previous day high |
| `SESS_PDL` | float | `0.0` | Previous day low |
| `SESS_PDH_SWEPT` | bool | `false` | PDH has been swept this session |
| `SESS_PDL_SWEPT` | bool | `false` | PDL has been swept this session |
| `SESS_STRUCT_SCORE` | int | `0` | 0–5 composite session-structure quality |

### Engine Gate (required)

```
session_struct_ok = lib_sess_struct_score >= 2 and lib_sess_open_range_break != "NONE"
```

### Relationship to v5.2 Session Context

| Concern | v5.2 Session Context | v5.3 Session-Scoped Structure |
|---------|---------------------|------------------------------|
| Session identification | `SESSION_CONTEXT`, `IN_KILLZONE` | — (reads from v5.2) |
| Session MSS flags | `SESSION_MSS_BULL/BEAR` | Superseded by `SESS_INTRA_BOS_COUNT`, `SESS_INTRA_CHOCH` |
| Session FVG flags | `SESSION_FVG_BULL/BEAR_ACTIVE` | Superseded by Imbalance Lifecycle layer |
| Opening range | — | `SESS_OPEN_RANGE_*` |
| PDH/PDL | — | `SESS_PDH`, `SESS_PDL`, `*_SWEPT` |
| Session impulse | — | `SESS_IMPULSE_DIR`, `SESS_IMPULSE_STRENGTH` |

v5.2 fields remain in the library for backward compatibility. v5.3 fields are additive, not replacements.

---

## v5.3 Layer 4 — Range / Profile Regime (11 fields) — REQUIRED

Detects whether the instrument is in a ranging, trending, or breakout regime and quantifies
range boundaries. This layer answers *"is this a range day or a trend day?"* — a question that
fundamentally alters trade management (fade vs follow).

### Ownership

| Component | Responsibility |
|-----------|---------------|
| `scripts/smc_range_regime.py` | Python builder — derives from snapshot + ATR/volume profile |
| `smc_enrichment_types.py` | `RangeRegimeBlock` TypedDict |
| `generate_smc_micro_profiles.py` | Pine `export const` emission (11 fields) |
| `SMC_Core_Engine.pine` | Field reads + `range_regime_ok` context gate + BUS resolver |
| `SMC_Range_Regime.pine` | **Optional** overlay — range box visualization, VPOC/VAH/VAL lines |

### Field Contract

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `RANGE_REGIME` | string | `"UNKNOWN"` | `TRENDING` / `RANGING` / `BREAKOUT` / `UNKNOWN` |
| `RANGE_WIDTH_PCT` | float | `0.0` | Range width as % of price |
| `RANGE_POSITION` | string | `"MID"` | `HIGH` / `MID` / `LOW` — where price sits in the range |
| `RANGE_HIGH` | float | `0.0` | Upper range boundary |
| `RANGE_LOW` | float | `0.0` | Lower range boundary |
| `RANGE_DURATION_BARS` | int | `0` | How long current regime has persisted |
| `RANGE_VPOC_LEVEL` | float | `0.0` | Volume Point of Control |
| `RANGE_VAH_LEVEL` | float | `0.0` | Value Area High |
| `RANGE_VAL_LEVEL` | float | `0.0` | Value Area Low |
| `RANGE_BALANCE_STATE` | string | `"BALANCED"` | `BALANCED` / `IMBALANCED_UP` / `IMBALANCED_DOWN` |
| `RANGE_REGIME_SCORE` | int | `0` | 0–5 regime clarity / confidence |

### Engine Gate (required)

```
range_regime_ok = lib_range_regime != "UNKNOWN" and lib_range_regime_score >= 2
```

### Interaction with v5.1 Compression / ATR Regime

| Concern | v5.1 Compression | v5.3 Range Regime |
|---------|-----------------|-------------------|
| Volatility state | `ATR_REGIME`, `SQUEEZE_ON/RELEASED` | — (reads from v5.1) |
| Range detection | — | `RANGE_REGIME`, `RANGE_WIDTH_PCT` |
| Volume profile | — | `RANGE_VPOC/VAH/VAL_LEVEL` |
| Position in range | — | `RANGE_POSITION` |

The v5.1 Compression layer answers *"is volatility compressed?"* while the v5.3 Range Regime
layer answers *"is the instrument range-bound?"* — related but distinct questions.

---

## v5.3 Layer Ownership Matrix

Shows which system component owns each concern for every v5.3 layer:

| Layer | Python Builder | TypedDict Block | Pine Library | Pine Core Gate | BUS Channel | Overlay |
|-------|---------------|-----------------|--------------|----------------|-------------|---------|
| Structure State | `smc_structure_state.py` | `StructureStateBlock` | 14 fields | `struct_state_ok` | ModulePackG row 1 | `SMC_Structure_State.pine` (optional) |
| Imbalance Lifecycle | `smc_imbalance_lifecycle.py` | `ImbalanceLifecycleBlock` | 23 fields | `imbalance_ok` | ModulePackG row 2 | — (extends `SMC_Liquidity_Structure.pine`) |
| Session-Scoped Structure | `smc_session_structure.py` | `SessionStructureBlock` | 14 fields | `session_struct_ok` | ModulePackG row 3 | — (extends `SMC_Session_Context.pine`) |
| Range / Profile Regime | `smc_range_regime.py` | `RangeRegimeBlock` | 11 fields | `range_regime_ok` | ModulePackG row 4 | `SMC_Range_Regime.pine` (optional) |

### Required vs Optional Components

| Component | Status | Notes |
|-----------|--------|-------|
| Python builder + DEFAULTS | **Required** | Every layer must have a builder that returns safe defaults |
| TypedDict block + EnrichmentDict key | **Required** | Contract enforcement via type checking |
| Pine library emission | **Required** | All 228 fields always present |
| `build_enrichment()` flag | **Required** | Feature flag for CI / selective enablement |
| V5_FIELD_INVENTORY update | **Required** | Contract tests must cover all 228 fields |
| Pine core field reads | **Required** | Engine reads all fields |
| Pine core context gate | **Required** | Minimum gate per layer |
| BUS resolver + ModulePackG | **Required** | Dashboard visibility |
| Dedicated overlay | **Optional** | Useful for visual debugging, not required for trading logic |
| Extending existing overlay | **Optional** | Preferred over creating new overlays when possible |

---

## v5.3 Implementation Sequence

v5.3 follows the same work-package pattern as v5.1/v5.2:

| AP | Package | Depends on | Deliverables | Status |
|----|---------|-----------|--------------|--------|
| AP1 | Structure State Builder | — | `smc_structure_state.py`, 24 tests | **Done** |
| AP2 | Imbalance Lifecycle Builder | — | `smc_imbalance_lifecycle.py`, 24 tests | **Done** |
| AP3 | Session-Scoped Structure Builder | AP1 (reads STRUCT_TREND) | `smc_session_structure.py`, 30 tests | **Done** |
| AP4 | Range / Profile Regime Builder | — | `smc_range_regime.py`, 28 tests | **Done** |
| AP5 | Contract / Manifest v5.3 | AP1–AP4 | TypedDict blocks, EnrichmentDict keys, `write_pine_library()` sections, `build_enrichment()` flags, V5_FIELD_INVENTORY (228), manifest v5.3 | **Done** |
| AP6 | Core Integration v5.3 | AP5 | Engine field reads (62), 4 gates, 4 BUS resolvers, ModulePackG, consumer contract updated | **Done** |
| AP7 | CLI + Workflow v5.3 | AP6 | CLI args `--enrich-{structure-state,imbalance-lifecycle,session-structure,range-regime}`, `--enrich-all` wiring | **Done** |
| AP8 | Architecture Doc v5.3 | AP7 | This document — finalized with test counts | **Done** |

### Parallelization

AP1, AP2, and AP4 have no inter-dependencies and can be implemented in parallel.
AP3 depends on AP1 (`STRUCT_TREND` informs session impulse detection).
AP5–AP8 are sequential.

---

## Migration Notes: v5.2 → v5.3

### What Changes

| Concern | v5.2 | v5.3 |
|---------|------|------|
| Field count | 166 | 228 (+62) |
| Manifest version | `v5.2` | `v5.3` |
| Sections | 18 | 22 (+4) |
| Enrichment blocks | 17 keys | 21 keys (+4) |
| BUS channels | ModulePackA–F | ModulePackA–G (+1) |
| Context gates | 11 | 15 (+4) |

### What Does NOT Change

- All 166 v5.2 fields remain at their original positions and with their original types.
- v5.2 session FVG/MSS flags are retained (backward compat). The v5.3 Imbalance Lifecycle
  and Session-Scoped Structure layers *supersede* them conceptually but do not *remove* them.
- Provider policy table is unchanged — all 4 new layers are snapshot-derived.
- Secret naming, CI workflow, alert rules, and publish pipeline are unaffected.
- Existing overlays continue to work without modification.

### Breaking-Change Risk

**None.** v5.3 is purely additive. The version governance system will classify it as a `minor` change.

### Test Impact

- V5_FIELD_INVENTORY grows from 166 → 228 entries in all three test files.
- 4 new test files (106 new tests total: 24 + 24 + 30 + 28).
- `test_enrichment_contract_integration.py` and `test_v4_pipeline_e2e.py` must
  update field count assertions and manifest version checks.

---

## Roadmap Beyond v5.3

| Version | Theme | Status |
|---------|-------|--------|
| v5 | Event risk, provider policy | Shipped |
| v5.1 | Flow qualifier, compression, zone intelligence, reversal context | Shipped |
| v5.2 | Session context, liquidity structure, order blocks, zone projection, profile context | Shipped |
| **v5.3** | **Structure state, imbalance lifecycle, session-scoped structure, range regime** | **Shipped** |
| v5.4 (planned) | Multi-timeframe alignment consolidation, cross-layer composite scoring | Design phase |

## v5.1 Pine Overlays

Three optional companion overlays read the v5.1 fields:

| Overlay | File | Purpose |
|---------|------|---------|
| SMC Orderflow Overlay | `SMC_Orderflow_Overlay.pine` | Flow qualifier visualization (RelVol, Delta, ATS) |
| SMC Liquidity Context | `SMC_Liquidity_Context.pine` | Zone S/R levels, sweeps, context bias |
| SMC HTF Confluence | `SMC_HTF_Confluence.pine` | ATR regime, squeeze, reversal scores |

## v5.2 Pine Overlays

Three additional overlays read the v5.2 fields:

| Overlay | File | Purpose |
|---------|------|---------|
| SMC Session Context | `SMC_Session_Context.pine` | Session/killzone visualization, MSS markers, direction bias |
| SMC Liquidity Structure | `SMC_Liquidity_Structure.pine` | Sweep events, pool imbalance, magnet direction, quality scores |
| SMC Profile Context | `SMC_Profile_Context.pine` | Ticker grade, VWAP position, spread regime, profile score |

All overlays import `smc_micro_profiles_generated` and read `mp.*` fields. They do NOT duplicate core logic.

## v5.3 Pine Overlays

Two new optional overlays and two overlay extensions:

| Overlay | File | Status | Purpose |
|---------|------|--------|--------|
| SMC Structure State | `SMC_Structure_State.pine` | **Optional** (new) | Swing high/low markers, BOS/CHoCH event labels, protected-level lines |
| SMC Range Regime | `SMC_Range_Regime.pine` | **Optional** (new) | Range box, VPOC/VAH/VAL lines, regime label |
| SMC Session Context | `SMC_Session_Context.pine` | **Extended** | + PDH/PDL sweep markers, opening range box |
| SMC Liquidity Structure | `SMC_Liquidity_Structure.pine` | **Extended** | + FVG lifecycle shading, CE markers, fill-rate label |

## v5.1 Engine Integration

The engine reads all 44 v5.1 fields via `mp.*` bindings and derives:
- **Flow quality gate**: `flow_quality_ok = lib_flow_long_ok and lib_rel_vol >= 0.5`
- **Compression gate**: `compression_entry_ok = not lib_squeeze_on or lib_squeeze_released`
- **ATR regime gate**: `atr_regime_ok = lib_atr_regime != "EXHAUSTION"`
- **Zone context gate**: `zone_context_long_ok = lib_zone_context_bias != "RESISTANCE_HEAVY"`
- **Reversal context boost**: `reversal_context_boost = lib_reversal_active and lib_setup_score >= 3 and lib_confirm_score >= 2`

A BUS channel (`BUS ModulePackE`) publishes all 4 v5.1 context rows for dashboard consumption.

## v5.2 Engine Integration

The engine reads all 71 v5.2 fields via `mp.*` bindings and derives 6 additional context gates:
- **Session context gate**: `session_context_ok = lib_session_context != "NONE" and lib_in_killzone`
- **Sweep context gate**: `sweep_context_long_ok = not lib_recent_bear_sweep or lib_sweep_reclaim`
- **Pool magnet gate**: `pool_magnet_long_ok = lib_pool_magnet_dir != "DOWN"`
- **OB context gate**: `ob_context_long_ok = lib_ob_bias != "BEARISH" and lib_ob_ctx_score >= 2`
- **Zone projection gate**: `zone_proj_ok = lib_zone_proj_confidence >= 2 and lib_zone_proj_trap_risk != "HIGH"`
- **Profile quality gate**: `profile_quality_ok = lib_profile_grade != "D" and lib_profile_ctx_score >= 2`

4 new BUS resolver functions (`resolve_bus_session_context_row`, `resolve_bus_sweep_row`, `resolve_bus_ob_context_row`, `resolve_bus_profile_row`) and a `BUS ModulePackF` plot channel publish v5.2 rows for dashboard consumption.

## v5.3 Engine Integration

The engine reads all 62 v5.3 fields via `mp.*` bindings and derives 4 additional context gates:
- **Structure state gate**: `struct_state_ok = lib_struct_trend != "NEUTRAL" and lib_struct_freshness >= 2`
- **Imbalance lifecycle gate**: `imbalance_ok = lib_imb_lifecycle_score >= 2 and lib_imb_density >= 1`
- **Session structure gate**: `session_struct_ok = lib_sess_struct_score >= 2 and lib_sess_open_range_break != "NONE"`
- **Range regime gate**: `range_regime_ok = lib_range_regime != "UNKNOWN" and lib_range_regime_score >= 2`

4 new BUS resolver functions (`resolve_bus_struct_state_row`, `resolve_bus_imbalance_row`, `resolve_bus_session_struct_row`, `resolve_bus_range_regime_row`) and a `BUS ModulePackG` plot channel publish v5.3 rows for dashboard consumption.

Total gates after v5.3: 15 (5 from v5.1 + 6 from v5.2 + 4 from v5.3).

## Provider Policy

| Domain | Primary | Fallbacks | Provenance key |
|--------|---------|-----------|----------------|
| base_scan | Databento | — | `base_scan_provider` |
| regime | FMP | — (defaults on failure) | `regime_provider` |
| news | FMP | Benzinga | `news_provider` |
| calendar | FMP | Benzinga | `calendar_provider` |
| technical | FMP | TradingView | `technical_provider` |
| event_risk | smc_event_risk_builder (derived) | — | `event_risk_provider` |
| flow_qualifier | smc_flow_qualifier (derived) | — | snapshot-based |
| compression_regime | smc_compression_regime (derived) | — | snapshot-based |
| zone_intelligence | smc_zone_intelligence (derived) | — | snapshot-based |
| reversal_context | smc_reversal_context (derived) | — | snapshot-based |
| session_context | smc_session_context_block (derived) | — | snapshot-based |
| liquidity_sweeps | smc_liquidity_sweeps (derived) | — | snapshot-based |
| liquidity_pools | smc_liquidity_pools (derived) | — | snapshot-based |
| order_blocks | smc_order_blocks (derived) | — | snapshot-based |
| zone_projection | smc_zone_projection (derived) | — | snapshot-based |
| profile_context | smc_profile_context (derived) | — | snapshot-based |
| structure_state | smc_structure_state (derived) | — | snapshot-based |
| imbalance_lifecycle | smc_imbalance_lifecycle (derived) | — | snapshot-based |
| session_structure | smc_session_structure (derived) | — | snapshot-based |
| range_regime | smc_range_regime (derived) | — | snapshot-based |

Event risk is a **derived stage** — it reads the calendar + news results already obtained by their respective provider chains. It does not call any external API directly. `EVENT_PROVIDER_STATUS` reflects whether the upstream calendar and/or news domains delivered data.

Provider provenance is surfaced via `SMC_PROVIDER_COUNT` and `SMC_STALE_PROVIDERS` in the library.

## Runtime Boundary

The v5 generation path has **zero dependency on `open_prep`**. The FMP client is `scripts/smc_fmp_client.SMCFMPClient` — a thin stdlib-only adapter. All 22 canonical runtime modules (18 from v5.2 + 4 from v5.3) are verified `open_prep`-free via `tests/test_smc_fmp_client_isolation.py`.

## Test Coverage

| Test file | Tests | Builder / Layer |
|-----------|-------|-----------------|
| `tests/test_smc_session_context_block.py` | 25 | Session Context (v5.2) |
| `tests/test_smc_liquidity_sweeps.py` | 22 | Liquidity Sweeps (v5.2) |
| `tests/test_smc_liquidity_pools.py` | 21 | Liquidity Pools (v5.2) |
| `tests/test_smc_order_blocks.py` | 20 | Order Blocks (v5.2) |
| `tests/test_smc_zone_projection.py` | 25 | Zone Projection (v5.2) |
| `tests/test_smc_profile_context.py` | 31 | Profile Context (v5.2) |
| `tests/test_smc_structure_state.py` | 24 | Structure State (v5.3) |
| `tests/test_smc_imbalance_lifecycle.py` | 24 | Imbalance Lifecycle (v5.3) |
| `tests/test_smc_session_structure.py` | 30 | Session-Scoped Structure (v5.3) |
| `tests/test_smc_range_regime.py` | 28 | Range / Profile Regime (v5.3) |
| `tests/test_enrichment_contract_integration.py` | 36 | Contract: 228-field inventory, manifest v5.3 |
| `tests/test_v4_pipeline_e2e.py` | 38 | E2E: build_enrichment, finalize_pipeline, field count |

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

## Foundation Test Coverage (v5 / v5.1)

- `tests/test_enrichment_contract_integration.py` — field inventory (228 fields), deterministic output
- `tests/test_enrichment_provider_policy.py` — provider policy, event-risk wiring (58 tests)
- `tests/test_smc_event_risk_builder.py` — event-risk builder (40 tests)
- `tests/test_smc_flow_qualifier.py` — flow qualifier builder (23 tests)
- `tests/test_smc_compression_regime.py` — compression/ATR regime builder (13 tests)
- `tests/test_smc_zone_intelligence.py` — zone intelligence builder (19 tests)
- `tests/test_smc_reversal_context.py` — reversal context builder (22 tests)
- `tests/test_smc_fmp_client_isolation.py` — open_prep boundary (37 tests)
- `tests/test_smc_alert_notifier.py` — v5 alert rules (55 tests)
- `tests/test_pine_consumer_contract.py` — BUS channel contracts
- `tests/test_v4_pipeline_e2e.py` — end-to-end pipeline
- `tests/test_cli_pipeline_e2e.py` — CLI integration
