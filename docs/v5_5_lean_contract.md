# v5.5a Lean Contract

**Status**: Active  
**Date**: 2026-03-30  
**Schema Version**: 2.0.0  
**Library Field Version**: v5.5a  
**Supersedes**: v5.5 Lean Contract Freeze  

> Refinement details: see [v5_5a_lean_contract_refinement_en.md](v5_5a_lean_contract_refinement_en.md)  
> Architecture overview: see [SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md](SMC_Unified_Lean_Architecture_v5_5a_DE_EN.md)

## Design Principles

1. Canonical structure remains unchanged
2. Additive context is allowed
3. Prefer scoring over blocking
4. Few, clear, user-facing fields
5. No new heavy governance
6. No new large platform logic
7. **One Primary Decision Surface** — lifecycle + signal quality + event state + bias + warnings
8. **Signal Quality Primacy** — primary interpretation layer for lean runtime
9. **Event Risk User Semantics** — blocked / caution / clear
10. **No Shadow Logic** — Pine must not rebuild competing interpretation layers
11. **Field Semantics Integrity** — names must match actual computation precision
12. **Pine Runtime Budget** — runtime efficiency is architectural, not incidental
13. **UX Modes** — Compact Mode is the reference; Advanced Mode is optional
14. **Support Family Admission Rule** — must prove value vs. runtime cost

## v5.5 Lean Families

### 1. Event Risk Light (7 fields)
| Field | Type | Values |
|-------|------|--------|
| EVENT_WINDOW_STATE | string | CLEAR / PRE_EVENT / ACTIVE / COOLDOWN |
| EVENT_RISK_LEVEL | string | NONE / LOW / ELEVATED / HIGH |
| NEXT_EVENT_NAME | string | e.g. "FOMC Rate Decision" |
| NEXT_EVENT_TIME | string | e.g. "14:00" |
| MARKET_EVENT_BLOCKED | bool | true / false |
| SYMBOL_EVENT_BLOCKED | bool | true / false |
| EVENT_PROVIDER_STATUS | string | ok / no_data / calendar_missing / news_missing |

### 2. Session Context Light (4 required + 1 optional)
| Field | Type | Values | Required |
|-------|------|--------|----------|
| SESSION_CONTEXT | string | ASIA / LONDON / NY_AM / NY_PM / NONE | yes |
| IN_KILLZONE | bool | true / false | yes |
| SESSION_DIRECTION_BIAS | string | BULLISH / BEARISH / NEUTRAL | yes |
| SESSION_CONTEXT_SCORE | int | 0-7 | yes |
| SESSION_VOLATILITY_STATE | string | LOW / NORMAL / HIGH / EXTREME | **optional** |

`SESSION_VOLATILITY_STATE` is optional. The lean runtime must remain fully functional when only the 4 required session fields are present.

### 3. Order Block Context Light (5 fields)
| Field | Type | Values |
|-------|------|--------|
| PRIMARY_OB_SIDE | string | BULL / BEAR / NONE |
| PRIMARY_OB_DISTANCE | float | % distance from price |
| OB_FRESH | bool | true / false |
| OB_AGE_BARS | int | bars since creation |
| OB_MITIGATION_STATE | string | fresh / touched / mitigated / stale |

**OB_MITIGATION_STATE semantics**: States are **age-derived lifecycle stages**:
- `fresh` — OB is ≤ 10 bars old and not mitigated
- `touched` — OB is 11-30 bars old; this is an **aging lifecycle label**, not a price-touch event
- `mitigated` — the broad OB block reports actual mitigation (price filled the zone)
- `stale` — OB is > 30 bars old

### 4. FVG / Imbalance Lifecycle Light (6 fields)
| Field | Type | Values |
|-------|------|--------|
| PRIMARY_FVG_SIDE | string | BULL / BEAR / NONE |
| PRIMARY_FVG_DISTANCE | float | % distance from price |
| FVG_FILL_PCT | float | 0.0-1.0 |
| FVG_MATURITY_LEVEL | int | 0-3 fill-derived maturity proxy (not bar age) |
| FVG_FRESH | bool | true / false |
| FVG_INVALIDATED | bool | true / false |

### 5. Structure State Light (4 fields)
| Field | Type | Values |
|-------|------|--------|
| STRUCTURE_LAST_EVENT | string | NONE / BOS_BULL / BOS_BEAR / CHOCH_BULL / CHOCH_BEAR |
| STRUCTURE_EVENT_AGE_BARS | int | bars since last event |
| STRUCTURE_FRESH | bool | true / false |
| STRUCTURE_TREND_STRENGTH | int | 0-100 |

### 6. Signal Quality (5 fields)
| Field | Type | Values |
|-------|------|--------|
| SIGNAL_QUALITY_SCORE | int | 0-100 |
| SIGNAL_QUALITY_TIER | string | low / ok / good / high |
| SIGNAL_WARNINGS | string | pipe-separated, max 3 |
| SIGNAL_BIAS_ALIGNMENT | string | bull / bear / mixed / neutral |
| SIGNAL_FRESHNESS | string | fresh / aging / stale |

## Keep / Deprecate / Remove Later

### Signal Quality — Support Block Inputs

Signal Quality (Family 6) consumes lean families 1-5 as primary inputs.
Additionally, it reads two **non-lean support blocks**:

| Support Block | Fields Used | Component | Max Weight |
|---------------|-------------|-----------|------------|
| `liquidity_sweeps` | RECENT_BULL_SWEEP, RECENT_BEAR_SWEEP, SWEEP_QUALITY_SCORE, SWEEP_DIRECTION | Liquidity/sweep support | 15 |
| `compression_regime` | SQUEEZE_ON, ATR_REGIME | Compression regime | 15 |

**Why these are acceptable:**
- Both blocks are **read-only inputs** from upstream enrichment — SQ does not modify them.
- Both contribute to scoring only; neither can block or gate alone.
- Missing data safe-defaults to zero contribution (no warning, no error).
- Replacing them with lean fields would add complexity without improving UX or testability.
- Session Context Light's optional `SESSION_VOLATILITY_STATE` already derives from
  `compression_regime`, so SQ's direct read avoids double-derivation.

**Admission rule** (Design Principle 14): A non-lean support block is admitted when
it provides scoring data that cannot be derived from the 5 lean families, safe-defaults
to neutral on absence, and does not introduce gating or blocking logic.

### KEEP (v5.5 Lean Surface)
All fields listed above in the 6 lean families.

Plus existing canonical fields that are still needed:
- Core/Meta: ASOF_DATE, ASOF_TIME, UNIVERSE_SIZE, REFRESH_COUNT
- Microstructure Lists: all 7 *_TICKERS lists
- Regime: MARKET_REGIME, VIX_LEVEL
- Layering: TONE, TRADE_STATE
- Providers: PROVIDER_COUNT, STALE_PROVIDERS

### DEPRECATE (keep exporting, mark as deprecated)
- Event Risk internal fields: NEXT_EVENT_CLASS, NEXT_EVENT_IMPACT, EVENT_RESTRICT_BEFORE_MIN, EVENT_RESTRICT_AFTER_MIN, EVENT_COOLDOWN_ACTIVE, EARNINGS_SOON_TICKERS, HIGH_RISK_EVENT_TICKERS
- Session Context internal fields: SESSION_MSS_BULL, SESSION_MSS_BEAR, SESSION_STRUCTURE_STATE, SESSION_FVG_BULL_ACTIVE, SESSION_FVG_BEAR_ACTIVE, SESSION_BPR_ACTIVE, SESSION_RANGE_TOP, SESSION_RANGE_BOTTOM, SESSION_MEAN, SESSION_VWAP, SESSION_TARGET_BULL, SESSION_TARGET_BEAR
- Full OB block: broad NEAREST_*_OB_LEVEL, *_OB_FRESHNESS, *_OB_MITIGATED, *_OB_FVG_CONFLUENCE, OB_DENSITY, OB_BIAS, OB_NEAREST_DISTANCE_PCT, OB_STRENGTH_SCORE, OB_CONTEXT_SCORE
- Full Imbalance block: all 23 broad fields (BULL_FVG_*, BEAR_FVG_*, BPR_*, LIQ_VOID_*)
- Zone Intelligence (v5.1): all 13 fields
- Reversal Context (v5.1): all 12 fields
- Zone Projection (v5.2): all 10 fields
- Profile Context (v5.2): all 18 fields
- Liquidity Pools (v5.2): all 11 fields
- Session Structure (v5.3): all 14 fields
- Range Regime (v5.3): all 11 fields
- Range Profile Regime (v5.3): all 22 fields

### REMOVE LATER (not in v5.5, target v6.0)
- Deprecated fields above after consumers are migrated
- Calendar block (folded into Event Risk)
- News sentiment tickers (superseded by Signal Quality)

## Mapping: Old → New

| Old Field(s) | New v5.5 Field | Notes |
|---|---|---|
| STRUCTURE_STATE, CHOCH_*, BOS_* | STRUCTURE_LAST_EVENT | Derived from existing structure_state builder |
| STRUCTURE_EVENT_AGE_BARS | STRUCTURE_EVENT_AGE_BARS | Unchanged |
| STRUCTURE_FRESH | STRUCTURE_FRESH | Unchanged |
| (new) | STRUCTURE_TREND_STRENGTH | New composite from structure state |
| BULL_FVG_ACTIVE, BEAR_FVG_ACTIVE | PRIMARY_FVG_SIDE | Picks nearest active FVG |
| BULL_FVG_TOP/BOTTOM, BEAR_FVG_TOP/BOTTOM | PRIMARY_FVG_DISTANCE | Distance as pct |
| BULL_FVG_MITIGATION_PCT, BEAR_FVG_MITIGATION_PCT | FVG_FILL_PCT | From primary FVG |
| (new) | FVG_MATURITY_LEVEL | From primary FVG (fill-derived proxy, 0-3; not bar age) |
| (new) | FVG_FRESH | Age < 10 bars |
| BULL_FVG_FULL_MITIGATION | FVG_INVALIDATED | >= 100% filled |
| NEAREST_BULL_OB_LEVEL, NEAREST_BEAR_OB_LEVEL | PRIMARY_OB_SIDE, PRIMARY_OB_DISTANCE | Picks nearest/freshest |
| BULL_OB_FRESHNESS, BEAR_OB_FRESHNESS | OB_AGE_BARS, OB_FRESH | From primary OB |
| BULL_OB_MITIGATED, BEAR_OB_MITIGATED | OB_MITIGATION_STATE | Lifecycle states |
| EVENT_* (7 of 14) | EVENT_* Light (7) | Surface subset |
| SESSION_CONTEXT, IN_KILLZONE, SESSION_DIRECTION_BIAS, SESSION_CONTEXT_SCORE | Same names | Direct pass-through |
| (new) | SESSION_VOLATILITY_STATE | Derived from ATR/session range |
| (new) | SIGNAL_QUALITY_SCORE | New composite |
| (new) | SIGNAL_QUALITY_TIER | Tier from score |
| (new) | SIGNAL_WARNINGS | Aggregated warnings |
| (new) | SIGNAL_BIAS_ALIGNMENT | Consensus of biases |
| (new) | SIGNAL_FRESHNESS | Freshness composite |

## Migration Notes

1. All v5.3 fields continue to be exported — no breaking changes
2. New v5.5a fields are additive
3. Pine consumers should migrate to reading v5.5a lean fields
4. Deprecated fields will show `// DEPRECATED v5.5` comments in generated Pine
5. Signal Quality provides a single-number alternative to checking multiple gates
6. The `library_field_version` in the manifest changes from `v5.5` to `v5.5a`
7. Schema version stays at `2.0.0` (v5.5a is a sharpening patch, not structural)
8. `SESSION_VOLATILITY_STATE` is optional and must not be required for runtime
9. Compact Mode is the reference UX mode for shared/public scripts
10. No Shadow Logic: Pine must not rebuild competing interpretation layers

## Compact Mode — Hero-Surface Reference

Compact Mode (`compact_mode = true`) is the recommended UX for shared or
public scripts. It suppresses secondary visual elements while retaining
full filter and lifecycle logic.

**Kept active** (Hero Surface):
- Direction / Bias (HTF trend summary)
- Lifecycle markers (Reclaim, Confirmation, Ready)
- Signal Quality dashboard rows
- Event State (blocked / caution / clear)
- Warnings (volume quality, strict LTF)
- Health Badge
- Risk Levels
- Main dashboard

**Suppressed** (debug + secondary overlays):
- OB / FVG / Engine debug labels
- Microstructure debug markers
- Strict debug markers
- LTF dashboard details
- EMA support plot lines (filter logic stays active)
- Session VWAP plot line (VWAP filter stays active)
- Mean-target overlay line

All suppression uses `_eff` variables. Filter logic (EMA support gate,
VWAP filter, BUS export) is **not** affected by compact mode.

## Version Rationale

`library_field_version` is `v5.5a` (not `v5.6`) because:
- No new fields were added
- No fields were removed
- The change is semantic (hierarchy, optionality, naming precision)
- Generator field set is identical to v5.5
- `a` suffix signals "sharpening patch" not "new surface"
