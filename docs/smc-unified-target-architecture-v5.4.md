# SMC Unified Target Architecture v5.4

## Status

Target architecture.

This document is the current, self-contained architecture for the SMC platform and the SMC++ TradingView stack. It is written as a single readable target document. It intentionally avoids historical split-document structure and does not require the reader to reconstruct the system from earlier notes.

## Purpose

The architecture has one primary objective:

**Deliver a contract-first SMC system in which upstream market context is generated, validated, published, and consumed in a deterministic way, while the TradingView core stays modular, explainable, and operationally safe.**

The system must satisfy five conditions at the same time:

1. canonical market structure stays stable and machine-readable
2. all additional intelligence remains additive and explainable
3. generator, manifest, committed artifacts, and TradingView consumers stay synchronized
4. operational runtime stays fail-closed under provider degradation
5. the Pine core remains a signal engine, not a research-terminal monolith

---

## 1. Reading Guide

This document is organized in the order the system actually works:

1. **System boundary and design rules**
2. **Platform and library pipeline**
3. **Contract and enrichment model**
4. **Signal-engine consumption model**
5. **Dashboard, alerts, and overlays**
6. **Testing, governance, and operational priorities**
7. **Implementation workstreams**

If you need only one rule to orient yourself, use this one:

> `snapshot.structure` stays canonical-only. Everything else is additive.

---

## 2. System Boundary

### In scope

- `smc_core/` as the canonical domain core
- `smc_adapters/` as the boundary layer between producer and consumer surfaces
- `smc_integration/` as orchestration, provider policy, health, and release layer
- enrichment builders, typed contracts, manifest logic, and generated Pine artifacts
- TradingView consumers such as the core engine, dashboard, strategy wrapper, and optional overlays
- runtime governance, publish flow, anti-drift checks, and alert delivery

### Out of scope

- changing the canonical structure categories
- embedding planning metrics into canonical structure rows
- discretionary Fib workflows as core architecture
- giant visual research terminals inside the Pine core
- hidden fallback chains that are not represented in code, artifacts, and tests

---

## 3. Architecture Principles

### 3.1 Canonical structure is minimal and stable

Canonical `snapshot.structure` contains only the stable structure categories:

- `bos`
- `orderblocks`
- `fvg`
- `liquidity_sweeps`

These categories define what happened structurally. They are not the place for session state, event state, provider provenance, reward geometry, or UI-driven annotations.

### 3.2 Everything else is additive

The following belong outside canonical structure:

- provider provenance and health
- event risk
- session context
- liquidity-pool and sweep context
- order-block context and mitigation summaries
- profile and range regime
- planning metrics such as headroom and risk geometry
- lifecycle state, reason codes, dashboard fields, and alert payloads

### 3.3 Contract-first generation

Every additive block must follow the same pattern:

1. safe defaults
2. typed contract
3. dedicated builder
4. explicit feature flag where applicable
5. deterministic writer behavior
6. contract and anti-drift tests

### 3.4 The Pine core stays modular

The core may consume many context families, but it must keep a clear separation between:

- structure
- context
- setup planning
- lifecycle state
- output surfaces

The core may use context to gate or explain a setup. It must not collapse into a single giant all-in-one script that mixes detection, rendering, dashboarding, and research logic indiscriminately.

### 3.5 The runtime must fail closed

When providers degrade, the system must:

- emit safe defaults
- surface degraded status in artifacts
- preserve deterministic consumer behavior
- avoid silent optimistic assumptions

---

## 4. High-Level Architecture Model

The system has three connected planes.

| Plane | Primary responsibility | Key question |
|---|---|---|
| Platform and library pipeline | ingest, enrich, normalize, generate, publish, govern | How does context reach TradingView consumers safely? |
| Contract and enrichment layer | additive field families, defaults, typing, versioned artifacts | How does the system evolve without breaking the contract? |
| Signal and execution layer | core gating, setup planning, lifecycle, dashboard, alerts | How is the contract used to make and explain decisions? |

These planes are linked, but they are not interchangeable. The generator is not the dashboard. The dashboard is not the contract. The contract is not canonical structure.

---

## 5. Platform and Library Pipeline

### 5.1 Role of the pipeline

The pipeline is the only supported path that:

1. gathers source data
2. enriches it into typed, additive context
3. writes the generated Pine library and manifest
4. validates the result
5. publishes or withholds it under governance rules

### 5.2 Runtime paths

Two operator paths are supported.

#### Manual/operator path

Used for controlled runs and investigation.

Typical flow:

1. select base data or base CSV
2. choose enrichment options
3. run generation from the same orchestration path used by automation
4. review outputs
5. optionally publish

#### Automated path

Used for scheduled refreshes and governed publish.

Typical flow:

1. run scheduled workflow
2. refresh source data
3. execute enrichment builders
4. generate library and manifest
5. run evidence gates and anti-drift checks
6. publish only when rules permit
7. archive and notify

### 5.3 Core pipeline components

Representative component families:

- canonical domain core
- boundary adapters
- integration/orchestration layer
- generation scripts
- runtime wrapper / operator entry
- TradingView publish automation
- artifact and manifest generation

### 5.4 Provider policy

The target provider model is explicit.

| Domain | Intended role |
|---|---|
| Databento | primary source for base scan, bars, and microstructure |
| FMP | secondary source for regime, technical context, articles, and calendar-derived context |
| Benzinga | secondary / fallback source for news and calendar context |
| TradingView | explicit fallback for technical context where required |

Two rules follow from this:

1. no implicit fallback chains
2. every participating provider must be visible in code, artifacts, and tests

### 5.5 Runtime boundary discipline

The generation path may reuse logic extracted from other projects, but the runtime boundary of the library pipeline must remain inside the SMC pipeline itself. External projects may remain sources of extracted ideas or code patterns; they must not remain hidden operational dependencies in the live generation path.

---

## 6. Generated Artifacts and Manifest

### 6.1 Generated outputs

The generator produces at least two authoritative outputs:

- the generated Pine library
- the manifest that describes contract and release metadata

### 6.2 Artifact truth rule

Committed generated artifacts must match the real generator output. Review, CI, and production must not drift apart.

That means:

- no hand-edited generated files
- no stale committed examples presented as current truth
- no manifest that advertises an older contract while the architecture expects a newer one

### 6.3 Manifest responsibilities

The manifest should surface:

- schema and contract version metadata
- included enrichment blocks
- publish/governance decisions
- previous schema/version reference where applicable
- refresh timing and operator metadata
- provider participation/degradation metadata

### 6.4 Required runtime metadata

The architecture assumes the generated library and/or manifest can carry useful operational context such as:

- as-of date and time
- refresh count
- provider count
- stale providers
- field-version truth
- release/governance metadata

If these fields exist but are always empty in committed artifacts, the architecture should treat that as an implementation gap, not as acceptable steady-state behavior.

---

## 7. Enrichment Model

The system uses additive context families. These are grouped here by operational purpose rather than by historical document lineage.

### 7.1 Market and platform context

This family includes:

- regime
- news and sentiment context
- calendar and macro context
- layering outputs
- provider health and volume regime context

These fields shape broad operating conditions and are the first layer of non-structural context.

### 7.2 Event risk context

This is a first-class contract family. It is not optional at the architecture level.

Its job is to model the event window around macro releases, earnings, and similar high-impact calendar states in a way that is easy for Pine to consume.

Representative fields:

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

This family exists to support four surfaces at once:

1. generator output
2. manifest truth
3. core and dashboard gating
4. notifier and state-change alerting

### 7.3 Session context

This family makes session-aware logic first-class.

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

This family should allow the system to answer:

- which session matters right now
- whether the current bar is inside a relevant killzone
- whether session structure aligns with the intended trade direction

### 7.4 Liquidity sweep context

This family captures sweep and reclaim state.

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

This family should remain explicit and auditable. It should not hide a large amount of visual-state complexity inside opaque heuristics.

### 7.5 Liquidity pool context

This family represents repeated-contact and pool-dominance context.

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

### 7.6 Order-block context

This family captures active and mitigated order-block state in a Pine-friendly form.

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

### 7.7 Zone projection context

This family captures lightweight directional zones and internal levels without turning the system into a giant zone-rendering platform.

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

### 7.8 Imbalance lifecycle context

This family tracks FVG, BPR, and related imbalance state as objects with lifecycle.

Representative concepts and fields include:

- active bullish / bearish FVG state
- gap top and bottom levels
- partial and full mitigation state
- active counts and mitigation percentage
- BPR state and direction
- liquidity-void state
- lifecycle state such as active, partial-fill, filled, or invalidated

This family exists to prevent the architecture from treating FVGs as one-off flags.

### 7.9 Structure state context

This family expresses CHoCH/BOS as a rolling structural state rather than only as isolated events.

Representative concepts and fields include:

- `STRUCTURE_STATE`
- `CHOCH_BULL`
- `CHOCH_BEAR`
- `BOS_BULL`
- `BOS_BEAR`
- `STRUCTURE_LAST_EVENT`
- `STRUCTURE_EVENT_AGE_BARS`
- `STRUCTURE_FRESH`
- `ACTIVE_SUPPORT`
- `ACTIVE_RESISTANCE`

### 7.10 Range and profile regime context

This family provides the acceptance, balance, and predictive-range view of the market.

Representative fields:

- `RANGE_ACTIVE`
- `RANGE_TOP`
- `RANGE_BOTTOM`
- `RANGE_MID`
- `RANGE_BREAK_DIRECTION`
- `PROFILE_POC`
- `PROFILE_VALUE_AREA_TOP`
- `PROFILE_VALUE_AREA_BOTTOM`
- `PROFILE_VALUE_AREA_ACTIVE`
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

## 8. Signal and Execution Stack

### 8.1 Internal layer model

The Pine-side system should keep five layers distinct.

| Layer | Responsibility |
|---|---|
| Canonical structure | what happened structurally |
| Additive context | under what conditions it happened |
| Setup planning | whether a valid trade plan exists |
| Lifecycle and gating | whether the setup is actionable now |
| Delivery and UX | how the state is surfaced to users and downstream systems |

### 8.2 Lifecycle model

The lifecycle should remain explicit and progression-based.

Representative states:

- `Watchlist`
- `Ready`
- `Entry Best`
- `Entry Strict`

Earlier preparatory states such as armed/building/confirmed may still exist, but the architecture should keep the promotion rules into actionable states explainable and auditable.

### 8.3 Four roles for context families

Every context family should serve one or more of four roles:

#### Gate

Examples:

- event blocked
- hostile structure state
- hostile dominant liquidity-pool side
- unsuitable session or range regime

#### Qualifier

Examples:

- bullish session MSS
- bullish sweep reclaim
- bullish FVG active
- active supportive order block

#### Confidence booster

Examples:

- aligned profile sentiment bias
- supportive predictive-range location
- fresh structure
- favorable headroom to mean

#### Explainer

Examples:

- why allowed
- why blocked
- why discouraged
- which context family supplied the decision

### 8.4 Current planning extensions

The target architecture keeps two explicit planning/regime additions:

#### Mean-headroom gate

Representative fields:

- `mean_headroom_pts`
- `mean_headroom_r`
- `mean_headroom_best_ok`
- `mean_headroom_strict_ok`

Representative intent:

- do not promote structurally valid setups when the available move back to mean is too small relative to risk

#### Stretch compression / breakout-risk state

Representative fields:

- `stretch_std_baseline`
- `stretch_std_ratio`
- `stretch_compressed`
- `stretch_breakout_risk`

Representative intent:

- distinguish a clean stretched reversion setup from a compressed coil that has unresolved expansion risk

---

## 9. Reason Codes, Dashboard, and Alerts

### 9.1 Reason-code families

The architecture expects reason codes to be grouped by context family rather than emitted as an ad hoc flat list.

Representative families:

#### Event risk

- `EVENT_RISK_INCOMING`
- `EVENT_RISK_RELEASE`
- `EVENT_RISK_ONGOING`
- `EVENT_RISK_COOLDOWN`
- `EVENT_RISK_MACRO_HIGH`
- `EVENT_RISK_EARNINGS`
- `EVENT_RISK_BLOCKED_MARKET`
- `EVENT_RISK_BLOCKED_SYMBOL`

#### Session

- `SESSION_CONTEXT_ACTIVE`
- `SESSION_MSS_BULL`
- `SESSION_MSS_BEAR`
- `SESSION_FVG_BULL`
- `SESSION_FVG_BEAR`

#### Sweep and reclaim

- `LIQ_SWEEP_BULL`
- `LIQ_SWEEP_BEAR`
- `LIQ_RECLAIM_ACTIVE`

#### Liquidity pools

- `BULL_LIQ_POOL_ACTIVE`
- `BEAR_LIQ_POOL_ACTIVE`
- `DOMINANT_LIQ_POOL_BULL`
- `DOMINANT_LIQ_POOL_BEAR`

#### Order blocks

- `BULL_OB_ACTIVE`
- `BEAR_OB_ACTIVE`
- `OB_MITIGATED`

#### Profile, range, and zone bias

- `PROFILE_BULLISH`
- `PROFILE_BEARISH`
- `PROFILE_IMBALANCE_UP`
- `PROFILE_IMBALANCE_DOWN`
- `PRED_RANGE_EXTREME`
- `ZONE_CONTEXT_SUPPORT`
- `ZONE_CONTEXT_RESISTANCE`

#### Structure and imbalance

- `STRUCTURE_BULL_ACTIVE`
- `STRUCTURE_BEAR_ACTIVE`
- `CHOCH_BULL_ACTIVE`
- `CHOCH_BEAR_ACTIVE`
- `BOS_BULL_ACTIVE`
- `BOS_BEAR_ACTIVE`
- `STRUCTURE_STALE`
- `FVG_BULL_ACTIVE`
- `FVG_BEAR_ACTIVE`
- `FVG_PARTIAL_MITIGATION`
- `FVG_FULL_MITIGATION`
- `BPR_ACTIVE`
- `LIQ_VOID_ACTIVE`

### 9.2 Dashboard expectations

The dashboard should surface compact, readable state for at least:

- event risk
- next event
- session context
- sweep / reclaim context
- liquidity pools
- order blocks
- imbalance state
- range/profile regime
- mean headroom
- stretch regime

### 9.3 Alerting expectations

The alerting layer should understand state transitions, not only static conditions.

That is especially important for event risk, where the architecture expects transitions such as:

- high-impact event incoming
- release window entered
- cooldown started
- cooldown ended
- symbol-specific event block activated

Duplicate suppression must remain state-aware.

---

## 10. Optional Overlays

Optional overlays are valid and useful, but they must stay separate from the main signal engine.

Representative optional modules:

- session context overlay
- liquidity structure overlay
- profile context overlay
- event overlay
- delta context overlay when data quality is sufficient

These overlays exist to improve operator understanding, not to redefine the core contract.

---

## 11. Testing and Governance

### 11.1 Required test surfaces

The architecture assumes the following classes of tests exist and remain authoritative:

- field-inventory tests
- contract/manifest tests
- provider policy and fallback tests
- pipeline end-to-end tests
- alert-notifier tests
- consumer contract tests
- runtime-boundary tests proving no hidden external runtime dependency remains
- anti-drift checks comparing committed artifacts to real generator output

### 11.2 Governance rules

Release governance must be able to decide at minimum:

- whether a change is additive or breaking
- whether auto-commit is allowed
- whether operator/PR review is required
- whether publishing should be blocked on failed gates

### 11.3 Workflow expectations

The automated workflow should explicitly show these steps in its summary/output:

1. generation
2. enrichment
3. event-risk generation
4. evidence gates
5. governance evaluation
6. publish decision
7. artifact archival
8. notification

---

## 12. Current Operational Priorities

This section expresses what should be treated as the most important architecture-to-implementation priorities.

### Priority 1: event risk as a first-class contract

This is the most important remaining target-state requirement.

The system should not rely on broad regime or calendar proxies where explicit event-risk state is architecturally intended.

### Priority 2: artifact truth first

The committed library and manifest must match the actual generator contract. Documentation, CI, and production need one truth source.

### Priority 3: explicit provider fusion

The runtime should make it easy to tell:

- which provider supplied which domain
- which fallback path fired
- which domains degraded to defaults

### Priority 4: runtime-boundary cleanup

The operational path should not depend on hidden external runtime imports for its core data path.

### Priority 5: context-rich but modular Pine consumption

The core should gain context depth without becoming a monolithic visual research stack.

---

## 13. Implementation Workstreams

The architecture is easiest to execute through six workstreams.

### Workstream A — Event risk

Build the dedicated event-risk builder, emit the contract, integrate it into the core, dashboard, notifier, and tests.

### Workstream B — Context families

Keep the session, sweep, pool, order-block, imbalance, structure, and profile/range builders split by concern, typed, and deterministic.

### Workstream C — Artifact and manifest truth

Make generated outputs authoritative, drift-tested, and release-governed.

### Workstream D — Provider and runtime boundary

Make provider participation explicit and keep the operational generation path inside the SMC pipeline boundary.

### Workstream E — Core and dashboard integration

Consume context as gates, qualifiers, confidence boosters, and explainers without rewriting the long engine into a monolith.

### Workstream F — Optional overlays and operator UX

Keep overlays lightweight, modular, and clearly secondary to the contract and core.

### Recommended order

1. event risk contract
2. session/sweep/pool/OB/imbalance/profile builders where missing or incomplete
3. artifact and manifest truth
4. provider/runtime cleanup
5. core/dashboard/notifier integration
6. optional overlays and UX polish

---

## 14. Explicit Non-Goals

The architecture should not drift into the following:

1. giant Pine monoliths that combine every research idea into the core
2. hidden fallback/provider behavior that is not reflected in artifacts and tests
3. mandatory dependence on exotic tick/footprint data for baseline operation
4. profile, delta, or visual context becoming the primary signal engine
5. hand-maintained generated artifacts that no longer come from the real generator path

---

## 15. Decision Summary

This architecture defines one coherent target system.

It expects:

- a contract-first generator pipeline
- stable canonical structure
- additive context families for event risk, session, liquidity, order blocks, imbalance, structure state, and profile/range regime
- a modular Pine consumption model built around gates, qualifiers, confidence boosters, and explainers
- governed artifacts, explicit provider participation, and fail-closed runtime behavior

The governing rule remains the same from beginning to end:

> `snapshot.structure` stays canonical-only. All additional intelligence is additive, typed, testable, and visible in delivery surfaces.
