# SMC Unified Architecture v5.4 — Addendum: v5 Target Gaps and v5.2 Context Expansion

## Status

Additive addendum to the unified v5.4 target architecture.

This addendum records two groups of items that were only partially explicit in the prior v5.4 draft:

1. the **repo-to-target delta for the intended v5 Event-Risk architecture**, and
2. the stronger **v5.2 concept expansion** around session, liquidity, order-block, zone, and profile context.

This document is additive. It does not supersede the canonical contract boundary described in the main v5.4 architecture.

---

## 1. Review Result

The newly provided change notes are **only partially covered** by the current v5.4 draft.

### Already present at a high level

The prior v5.4 draft already covered:

- the platform / library pipeline split,
- the enrichment lineage from v4 through v5.3,
- the canonical-only `snapshot.structure` rule,
- the newer SMC++ Phase 1 / Phase 2 gating additions,
- and the v5.3 structure / imbalance / session-structure / range-regime families at a high level.

### Not yet explicit enough before this addendum

The prior v5.4 draft did **not** yet preserve with enough specificity:

- the stronger statement that **v5 Event Risk** is still the primary unfinished architectural delta,
- the explicit **repo-reality vs target-state gap analysis**,
- the operational **artifact-truth / provider-fusion / open_prep-decoupling** priorities,
- the concrete **v5 Event-Risk work packages**,
- the stronger **v5.2 context expansion** around session, liquidity, order blocks, zone projection, and profile context,
- the richer **v5.2 reason-code families**, optional overlay guidance, and prioritization model.

This addendum merges those missing points into the v5.4 target architecture.

---

## 2. v5 Delta That Remains Architecturally Important

## 2.1 What is already especially good

The current platform direction already has several strong building blocks:

1. a cleaner shared orchestration path for base scan, enrichment, and library generation,
2. an operational runtime that aligns manual/operator and automated paths,
3. a more mature generator/manifest writer,
4. a stronger intraday workflow with governance, diffing, archival, and notifications,
5. explicit semver/governance behavior,
6. and a materially improved integration/contract test base.

Architecturally, that means the system is no longer a loose prototype. The substrate is real.

## 2.2 The central remaining delta to true v5

The main missing architectural piece is still:

> **Event Risk as a first-class contract spanning generator, library, manifest, core, dashboard, alerting, and tests.**

The v5 architecture requires a dedicated event-risk layer with explicit contract fields and lifecycle semantics.

Representative required fields include:

- `EVENT_WINDOW_STATE`
- `EVENT_RISK_LEVEL`
- `NEXT_EVENT_CLASS`
- `NEXT_EVENT_NAME`
- `NEXT_EVENT_TIME`
- `NEXT_EVENT_IMPACT`
- `EVENT_RESTRICT_BEFORE_MIN`
- `EVENT_RESTRICT_AFTER_MIN`
- `EVENT_COOLDOWN_ACTIVE`
- `MARKET_EVENT_BLOCKED`
- `SYMBOL_EVENT_BLOCKED`
- `EARNINGS_SOON_TICKERS`
- `HIGH_RISK_EVENT_TICKERS`
- `EVENT_PROVIDER_STATUS`

## 2.3 Why this matters architecturally

Without this contract layer:

- the generated library is still missing a key first-class risk surface,
- the manifest cannot truthfully claim a complete v5 contract,
- the core/dashboard cannot reason explicitly about event windows,
- the notifier cannot operate on explicit event-risk states,
- and tests cannot enforce the intended v5 boundary.

## 2.4 Additional remaining v5 gaps that now stay explicit in architecture

### Artifact truth gap

The committed generated artifacts must reflect the real generator contract. Review and runtime must not drift apart.

### Provider-fusion gap

The intended model is explicit:

- Databento primary for base data,
- FMP secondary,
- Benzinga secondary / fallback,
- TradingView fallback technical context where required.

The architecture must not silently collapse back into an FMP-centric runtime.

### `open_prep` runtime boundary gap

`open_prep` remains a source of extracted logic, not part of the runtime boundary for the v5 library-generation path.

### Alerting gap

Alerting must eventually move from broad regime/macro-state notifications to explicit event-risk state notifications.

### Test-surface gap

The contract/integration test suite must explicitly protect the event-risk field family.

---

## 3. v5 Completion Work Packages Preserved in v5.4

### WP1 — Event-Risk Builder

Goal:

- add the dedicated event-risk builder as a first-class generator/runtime component

### WP2 — Generator and Manifest Upgrade to v5

Goal:

- emit the full event-risk contract from the real generation path
- move manifest metadata to the intended v5 truth state
- add anti-drift checks for committed artifacts

### WP3 — Core and Dashboard Integration

Goal:

- integrate event-risk fields into `SMC_Core_Engine.pine` and dashboard surfaces

Representative reason-code family:

- `EVENT_RISK_INCOMING`
- `EVENT_RISK_RELEASE`
- `EVENT_RISK_ONGOING`
- `EVENT_RISK_COOLDOWN`
- `EVENT_RISK_MACRO_HIGH`
- `EVENT_RISK_EARNINGS`
- `EVENT_RISK_BLOCKED_MARKET`
- `EVENT_RISK_BLOCKED_SYMBOL`

### WP4 — Alert Notifier Upgrade

Goal:

- upgrade the notifier to parse and act on the explicit event-risk contract

### WP5 — Provider Fusion Refactor

Goal:

- make fallback/provider roles explicit and testable

### WP6 — Remove `open_prep` from the runtime boundary

Goal:

- keep `open_prep` out of the operational v5 library-generation path

### WP7 — Workflow / Secrets / Terminology Alignment

Goal:

- align workflow summaries, naming, and compatibility notes with the intended v5 architecture

### WP8 — Optional Event Overlay and Snippet Hygiene

Goal:

- optionally add a lightweight event overlay and improve generated import-snippet hygiene

---

## 4. v5.2 Concept Expansion Preserved in v5.4

The stronger v5.2 concept note is now explicitly preserved in architecture instead of only being implied by the historical lineage summary.

## 4.1 v5.2 focus

v5.2 is the stage where SMC becomes not only structure- and event-aware, but also:

- session-aware,
- liquidity-aware,
- order-block-aware,
- zone-aware,
- and profile-aware,

without turning the core into a visual/research monolith.

## 4.2 v5.2 context layers

### Session Context Layer

Intent:

- sessions,
- killzones,
- session MSS,
- session FVGs,
- session targets,
- session-driven gating relevance.

### Liquidity Sweep Layer

Intent:

- wick sweeps,
- break + retest sweeps,
- sweep-area state,
- liquidity taken direction,
- reclaim-after-sweep logic.

### Liquidity Pool Layer

Intent:

- repeated-contact liquidity zones,
- optional pool-volume accumulation,
- active bull/bear pool state,
- dominant pool side.

### Order Block Layer

Intent:

- active bull/bear order blocks,
- average level,
- mitigation state,
- dominant OB context.

### Zone Projection / Algo Zone Context

Intent:

- primary bull/bear zones,
- internal zone levels,
- zone source and overlap state,
- directional support/resistance bias.

### Profile Context Layer

Intent:

- POC and value area,
- sentiment / money-flow bias,
- liquidity imbalance,
- delta / max-volume-price where data quality permits,
- predictive range context.

---

## 5. v5.2 Module Map Preserved in v5.4

Recommended/recognized module family:

- `scripts/smc_session_context.py`
- `scripts/smc_liquidity_sweeps.py`
- `scripts/smc_liquidity_pools.py`
- `scripts/smc_order_blocks.py`
- `scripts/smc_zone_projection.py`
- `scripts/smc_profile_context.py`

These modules remain additive generator/runtime builders. They do not bypass the contract-first enrichment path.

---

## 6. v5.2 Field-Family Coverage Map

### Session Context

Representative fields:

- `SESSION_CONTEXT`
- `IN_KILLZONE`
- `SESSION_MSS_BULL`
- `SESSION_MSS_BEAR`
- `SESSION_FVG_BULL_ACTIVE`
- `SESSION_FVG_BEAR_ACTIVE`
- `SESSION_TARGET_BULL`
- `SESSION_TARGET_BEAR`
- `SESSION_DIRECTION_BIAS`
- `SESSION_CONTEXT_SCORE`

### Liquidity Sweeps

Representative fields:

- `RECENT_BULL_SWEEP`
- `RECENT_BEAR_SWEEP`
- `SWEEP_TYPE`
- `SWEEP_DIRECTION`
- `SWEEP_ZONE_TOP`
- `SWEEP_ZONE_BOTTOM`
- `SWEEP_RECLAIM_ACTIVE`
- `LIQUIDITY_TAKEN_DIRECTION`
- `SWEEP_QUALITY_SCORE`

### Liquidity Pools

Representative fields:

- `ACTIVE_BULL_LIQ_POOL_TOP`
- `ACTIVE_BULL_LIQ_POOL_BOTTOM`
- `ACTIVE_BEAR_LIQ_POOL_TOP`
- `ACTIVE_BEAR_LIQ_POOL_BOTTOM`
- `BULL_LIQ_CONTACTS`
- `BEAR_LIQ_CONTACTS`
- `BULL_LIQ_POOL_VOLUME`
- `BEAR_LIQ_POOL_VOLUME`
- `BULL_LIQ_POOL_ACTIVE`
- `BEAR_LIQ_POOL_ACTIVE`
- `DOMINANT_LIQ_POOL_SIDE`

### Order Blocks

Representative fields:

- `BULL_OB_ACTIVE`
- `BEAR_OB_ACTIVE`
- `BULL_OB_TOP`
- `BULL_OB_BOTTOM`
- `BEAR_OB_TOP`
- `BEAR_OB_BOTTOM`
- `BULL_OB_AVG`
- `BEAR_OB_AVG`
- `BULL_OB_MITIGATED`
- `BEAR_OB_MITIGATED`
- `ACTIVE_BULL_OB_COUNT`
- `ACTIVE_BEAR_OB_COUNT`
- `DOMINANT_OB_SIDE`

### Zone Projection / Algo Zone Context

Representative fields:

- `PRIMARY_BULL_ZONE_TOP`
- `PRIMARY_BULL_ZONE_BOTTOM`
- `PRIMARY_BEAR_ZONE_TOP`
- `PRIMARY_BEAR_ZONE_BOTTOM`
- `ZONE_FIB_30`
- `ZONE_FIB_50`
- `ZONE_FIB_70`
- `ZONE_SOURCE`
- `ZONE_CONTEXT_BIAS`
- `ZONE_OVERLAP_STATE`

### Profile Context

Representative fields:

- `PROFILE_POC`
- `PROFILE_VALUE_AREA_TOP`
- `PROFILE_VALUE_AREA_BOTTOM`
- `PROFILE_VALUE_AREA_ACTIVE`
- `PROFILE_BULLISH_SENTIMENT`
- `PROFILE_BEARISH_SENTIMENT`
- `PROFILE_SENTIMENT_BIAS`
- `LIQUIDITY_ABOVE_PCT`
- `LIQUIDITY_BELOW_PCT`
- `LIQUIDITY_IMBALANCE`
- `BAR_DELTA_PCT`
- `MAX_VOLUME_PRICE`
- `PRED_RANGE_MID`
- `PRED_RANGE_UPPER_1`
- `PRED_RANGE_UPPER_2`
- `PRED_RANGE_LOWER_1`
- `PRED_RANGE_LOWER_2`
- `IN_PREDICTIVE_RANGE_EXTREME`

---

## 7. How the Core Should Use v5.2 Context

The v5.2 concept note articulated a useful four-role model that is now explicitly part of the target architecture.

### Gate

Examples:

- killzone required or prohibited,
- order-block context missing,
- dominant liquidity-pool side misaligned,
- hostile zone-context bias.

### Qualifier

Examples:

- bullish sweep present,
- bullish session MSS active,
- bullish session FVG active.

### Confidence Booster

Examples:

- bullish profile sentiment bias,
- positive delta / volume-price alignment,
- predictive range band aligning with support / OB / liquidity context.

### Explainer

Examples:

- why a setup is allowed,
- why a setup is blocked,
- why a setup is only discouraged.

---

## 8. v5.2 Reason-Code Families Preserved in v5.4

### Session

- `SESSION_CONTEXT_ACTIVE`
- `SESSION_MSS_BULL`
- `SESSION_MSS_BEAR`
- `SESSION_FVG_BULL`
- `SESSION_FVG_BEAR`

### Liquidity Sweep / Reclaim

- `LIQ_SWEEP_BULL`
- `LIQ_SWEEP_BEAR`
- `LIQ_RECLAIM_ACTIVE`

### Liquidity Pools

- `BULL_LIQ_POOL_ACTIVE`
- `BEAR_LIQ_POOL_ACTIVE`
- `DOMINANT_LIQ_POOL_BEAR`
- `DOMINANT_LIQ_POOL_BULL`

### Order Blocks

- `BULL_OB_ACTIVE`
- `BEAR_OB_ACTIVE`
- `OB_MITIGATED`

### Profile / Predictive Range / Zone Bias

- `PROFILE_BULLISH`
- `PROFILE_BEARISH`
- `PROFILE_IMBALANCE_UP`
- `PROFILE_IMBALANCE_DOWN`
- `PRED_RANGE_EXTREME`
- `ZONE_CONTEXT_SUPPORT`
- `ZONE_CONTEXT_RESISTANCE`

These stay additive diagnostic surfaces.

---

## 9. Optional Pine Modules Preserved as Guidance

Representative optional modules:

- `SMC_Session_Context.pine`
- `SMC_Liquidity_Structure.pine`
- `SMC_Profile_Context.pine`
- optional `SMC_Delta_Context.pine`

These remain optional and separate from the main trade-state engine.

---

## 10. Explicit v5.2 Non-Goals

v5.2 should not:

1. import giant visual monoliths into the core,
2. require tick / footprint / exotic LTF data for mandatory baseline fields,
3. treat every zone family as equally important from day one,
4. turn money-flow/profile context into the main signal engine.

The intended posture remains:

> SMC first, context additive.

---

## 11. v5.2 Prioritization Model Preserved in v5.4

### Highest priority

1. Session Context
2. Liquidity Sweeps
3. Liquidity Pools
4. Order Blocks

### Medium priority

5. Zone Projection / Algo Zone Context
6. Profile Context

### Later / optional

7. Delta / max-volume-price overlay
8. large visual overlays

---

## 12. v5.2 Implementation Work Packages Preserved in v5.4

### WP1 — Session Context Builder

Goal:

- add the dedicated session context layer with session, killzone, MSS, session FVG, targets, and score.

### WP2 — Liquidity Sweeps Builder

Goal:

- add the dedicated sweep layer with wick sweep, break-retest sweep, reclaim logic, and sweep quality state.

### WP3 — Liquidity Pools Builder

Goal:

- add the dedicated liquidity-pool layer with repeated-contact and dominant-side logic.

### WP4 — Order Block Layer

Goal:

- add the dedicated order-block layer with active state, ranges, mitigation, and count/dominance fields.

### WP5 — Zone Projection Layer

Goal:

- add the zone-projection/context layer from existing structure logic.

### WP6 — Profile Context Builder

Goal:

- add the deterministic profile context layer with POC, value area, bias, and predictive range context.

### WP7 — Core Integration

Goal:

- consume v5.2 fields in `SMC_Core_Engine.pine` as gates, confidence boosters, dashboard rows, and reason codes.

### WP8 — Optional Pine Context Modules

Goal:

- add lightweight optional overlays that reuse generated library fields and remain separate from the main engine.

### WP9 — Contract / Manifest / Version Bump to v5.2

Goal:

- update writer, manifest, artifacts, and anti-drift checks so the committed generated contract reflects the v5.2 step.

### WP10 — Architecture Document v5.2

Goal:

- update the architecture docs with layer ownership, field contracts, roadmap changes, and migration notes from v5.1.

### Recommended work order

**1 → 2 → 3 → 4 → 5 → 9 → 7 → 8 → 10**

Meaning:

1. session context
2. liquidity sweeps
3. liquidity pools
4. order blocks
5. profile / zone context
6. contract / artifact update
7. core integration
8. optional overlays
9. architecture documentation

---

## 13. Consolidated Addendum Decision Summary

This addendum explicitly merges the two missing change clusters into the v5.4 architecture:

1. the **v5 Event-Risk completion gap**, including artifact truth, provider fusion, alerting, tests, and runtime-boundary implications,
2. the stronger **v5.2 concept expansion** for session, liquidity, order-block, zone, and profile context.

Together with the main v5.4 document, the architecture now preserves:

- the platform/library plane,
- the enrichment contract lineage,
- the v5.2 context expansion,
- the v5.3 stateful structure expansion,
- and the v5.4 SMC++ gating additions.

The governing rule remains unchanged:

> `snapshot.structure` stays canonical-only. All new intelligence is additive outside that boundary.
