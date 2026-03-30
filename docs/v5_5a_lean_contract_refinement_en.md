# v5.5a Lean Contract Refinement

**Status**: Active  
**Date**: 2026-03-30  
**Schema Version**: 2.0.0  
**Library Field Version**: v5.5a  

## Purpose

v5.5a is a sharpening patch on top of v5.5.

It preserves the lean generator-first model but improves:
- prioritization
- semantic clarity
- product form
- runtime discipline
- compact/shared usability

The governing rule remains:

> `snapshot.structure` stays canonical-only.  
> Everything else is additive and must simplify the decision, not complicate it.

## Design Principles

1. Canonical structure remains unchanged
2. Additive context is allowed
3. Prefer scoring over blocking
4. Few, clear, user-facing fields
5. No new heavy governance
6. No new large platform logic
7. One primary decision surface
8. Signal Quality is the primary interpretation layer
9. Pine runtime efficiency is part of the architecture
10. Compact mode is the reference UX mode for shared/public scripts

## Primary Decision Surface

The system exposes one primary user-facing decision surface.

That surface consists of:
- lifecycle state
- signal quality tier
- event state
- directional bias
- up to 2–3 concise warnings

All other context families are support layers. They exist to feed this surface, not to compete with it as parallel dashboards or interpretation systems.

## Signal Quality Primacy

Signal Quality is the primary interpretation layer of the lean architecture.

Preferred consumption order:
1. lifecycle state
2. signal quality
3. event state
4. bias
5. concise warnings

Lean support families such as Session Context Light, Order Block Context Light, FVG Lifecycle Light, and Structure State Light should primarily feed Signal Quality and should only rarely be consumed as independent user-facing decision layers.

## v5.5a Lean Families

### 1. Event Risk Light (7 required fields)
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
| Field | Type | Values |
|-------|------|--------|
| SESSION_CONTEXT | string | ASIA / LONDON / NY_AM / NY_PM / NONE |
| IN_KILLZONE | bool | true / false |
| SESSION_DIRECTION_BIAS | string | BULLISH / BEARISH / NEUTRAL |
| SESSION_CONTEXT_SCORE | int | 0-7 |
| SESSION_VOLATILITY_STATE | string | LOW / NORMAL / HIGH / EXTREME | optional |

`SESSION_VOLATILITY_STATE` is optional and must not be required for lean runtime consumption. The system must remain fully functional when only the 4 required session fields are present.

### 3. Order Block Context Light (5 required fields)
| Field | Type | Values |
|-------|------|--------|
| PRIMARY_OB_SIDE | string | BULL / BEAR / NONE |
| PRIMARY_OB_DISTANCE | float | % distance from price |
| OB_FRESH | bool | true / false |
| OB_AGE_BARS | int | bars since creation |
| OB_MITIGATION_STATE | string | fresh / touched / mitigated / stale |

### 4. FVG / Imbalance Lifecycle Light (6 required fields)
| Field | Type | Values |
|-------|------|--------|
| PRIMARY_FVG_SIDE | string | BULL / BEAR / NONE |
| PRIMARY_FVG_DISTANCE | float | % distance from price |
| FVG_FILL_PCT | float | 0.0-1.0 |
| FVG_MATURITY_LEVEL | int | 0-3 fill-derived maturity proxy (not bar age) |
| FVG_FRESH | bool | true / false |
| FVG_INVALIDATED | bool | true / false |

### 5. Structure State Light (4 required fields)
| Field | Type | Values |
|-------|------|--------|
| STRUCTURE_LAST_EVENT | string | NONE / BOS_BULL / BOS_BEAR / CHOCH_BULL / CHOCH_BEAR |
| STRUCTURE_EVENT_AGE_BARS | int | bars since last event |
| STRUCTURE_FRESH | bool | true / false |
| STRUCTURE_TREND_STRENGTH | int | 0-100 |

### 6. Signal Quality (5 required fields)
| Field | Type | Values |
|-------|------|--------|
| SIGNAL_QUALITY_SCORE | int | 0-100 |
| SIGNAL_QUALITY_TIER | string | low / ok / good / high |
| SIGNAL_WARNINGS | string | pipe-separated, max 3, priority-ordered |
| SIGNAL_BIAS_ALIGNMENT | string | bull / bear / mixed / neutral |
| SIGNAL_FRESHNESS | string | fresh / aging / stale |

## Event Risk User Semantics

Event Risk Light should map to three user-facing states only:
- blocked
- caution
- clear

The underlying fields may remain more detailed, but the default user-facing interpretation should stay compact and fast to read.

## No Shadow Logic

The Pine consumer must not rebuild a competing interpretation layer that materially overrides the lean generator contract.

If a concept already exists as a v5.5 lean field, Pine should prefer consuming that field over recomputing an alternative meaning locally.

Local Pine logic may still handle visualization, lifecycle transitions, and runtime constraints, but should not silently replace the generator-defined lean interpretation layer.

## Field Semantics Integrity

Lean lifecycle and age fields must not imply more precision than their underlying computation supports.

If a field represents true bar age, it should be named as an age field.
If a field represents a heuristic maturity proxy, it should be named accordingly and documented as such.

This applies especially to:
- OB_AGE_BARS
- FVG_MATURITY_LEVEL
- STRUCTURE_EVENT_AGE_BARS
- SIGNAL_FRESHNESS

## Pine Runtime Budget

The lean architecture must remain inside a practical Pine runtime budget.

Design expectations:
- prefer one compact primary surface over multiple dashboards
- centralize repeated request logic
- avoid duplicate request.* paths for the same information
- keep optional overlays secondary
- avoid new context families unless they deliver clear value relative to runtime cost
- prefer support-family condensation over new visible UI surfaces

Runtime efficiency is part of the architecture, not just an implementation detail.

## UX Modes

The architecture supports two user-facing modes.

### Compact Mode
Default mode for solo operation and shared/public scripts.

Emphasizes:
- lifecycle
- signal quality
- event state
- bias
- concise warnings
- compact health status

### Advanced Mode
Optional mode for private/internal use.

May expose:
- additional context surfaces
- debug details
- secondary diagnostics
- developer-oriented state views

Compact Mode is the reference mode for lean product quality.

## Keep / Deprecate / Remove Later

### KEEP (v5.5a Lean Surface)
All fields listed above in the 6 lean families.

Plus existing canonical/compact support fields that are still needed:
- Core/Meta: ASOF_DATE, ASOF_TIME, UNIVERSE_SIZE, REFRESH_COUNT
- Microstructure Lists: all 7 `*_TICKERS` lists
- Regime: MARKET_REGIME, VIX_LEVEL
- Layering: TONE, TRADE_STATE
- Providers: PROVIDER_COUNT, STALE_PROVIDERS

### DEPRECATE (keep exporting, mark as deprecated)
- Event Risk internal fields beyond the light surface: NEXT_EVENT_CLASS, NEXT_EVENT_IMPACT, EVENT_RESTRICT_BEFORE_MIN, EVENT_RESTRICT_AFTER_MIN, EVENT_COOLDOWN_ACTIVE, EARNINGS_SOON_TICKERS, HIGH_RISK_EVENT_TICKERS
- Session Context internal fields beyond the light surface: SESSION_MSS_BULL, SESSION_MSS_BEAR, SESSION_STRUCTURE_STATE, SESSION_FVG_BULL_ACTIVE, SESSION_FVG_BEAR_ACTIVE, SESSION_BPR_ACTIVE, SESSION_RANGE_TOP, SESSION_RANGE_BOTTOM, SESSION_MEAN, SESSION_VWAP, SESSION_TARGET_BULL, SESSION_TARGET_BEAR
- Full OB block: broad NEAREST_*_OB_LEVEL, *_OB_FRESHNESS, *_OB_MITIGATED, *_OB_FVG_CONFLUENCE, OB_DENSITY, OB_BIAS, OB_NEAREST_DISTANCE_PCT, OB_STRENGTH_SCORE, OB_CONTEXT_SCORE
- Full Imbalance block: all broad BULL_FVG_*, BEAR_FVG_*, BPR_*, LIQ_VOID_* fields
- Zone Intelligence (v5.1): all fields
- Reversal Context (v5.1): all fields
- Zone Projection (v5.2): all fields
- Profile Context (v5.2): all fields
- Liquidity Pools (v5.2): all fields
- Session Structure (v5.3): all fields
- Range Regime (v5.3): all fields
- Range Profile Regime (v5.3): all fields

### REMOVE LATER (target v6.0+)
- Deprecated fields above after consumers are fully migrated
- Calendar block as separate surfaced concept (fold into Event Risk only)
- legacy news sentiment ticker interpretations if Signal Quality fully supersedes them

## Support Family Admission Rule

A support family should remain in the lean architecture only if it clearly improves at least one of the following:
- signal timing
- signal quality
- visual interpretation
- user trust
- runtime efficiency
- maintainability

If a support family adds interpretation overhead without improving the primary decision surface, it should be demoted, made optional, or removed later.

## Migration Notes

1. Existing broad v5.3/v5.4 fields may continue to be exported during migration — no forced breaking change is required.
2. v5.5a sharpens hierarchy and semantics but does not require abandoning the generator-first model.
3. Pine consumers should prefer the v5.5a lean fields and should avoid rebuilding competing interpretation logic.
4. `SESSION_VOLATILITY_STATE` is optional and should not become a required runtime dependency.
5. Compact Mode should be treated as the reference UX mode for shared/public scripts.
6. Runtime budget and no-shadow-logic rules are now explicit architectural requirements.
