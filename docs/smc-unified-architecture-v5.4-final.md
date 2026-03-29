# SMC Unified Architecture v5.4

## Status

Draft target revision.

This document is the unified v5.4 architecture for the SMC platform and the SMC++ TradingView signal stack.

It consolidates four previously separate threads:

1. the SMC library pipeline architecture
2. the v5 / v5.1 / v5.2 / v5.3 enrichment architecture lineage
3. the v4 → v5 enrichment migration guarantees
4. the newer SMC++ long-side gating additions:
   - Phase 1: Mean-Headroom Gate
   - Phase 2: Stretch Compression / Breakout-Risk State

Where implementation behavior differs from this document, this target architecture wins until explicitly revised.

Use this document together with:

- `docs/smc-snapshot-target-architecture.md`
- `docs/structure_contract_architecture.md`
- `docs/v4-enrichment-migration.md`
- `docs/v5-enrichment-architecture.md`
- the current SMC++ Pine / strategy lifecycle implementation

---

## 1. Goal

v5.4 has two goals:

1. preserve a clean, contract-first SMC library pipeline from Python generation to TradingView consumption
2. improve long-entry selectivity in the SMC++ stack without destabilizing the canonical structure contract

The architecture therefore keeps the platform split into two linked but distinct planes:

- **Platform / library plane**: provider ingest, enrichment, contract normalization, library generation, publishing, release governance
- **Signal / execution plane**: Pine-side structure consumption, context gating, setup planning, lifecycle progression, alerts, dashboard exposure

The critical rule is unchanged:

> Canonical structure remains canonical-only. New intelligence is additive.

---

## 2. System Boundary

### 2.1 In scope

- `smc_core/` as canonical domain core
- `smc_adapters/` as boundary layer
- `smc_integration/` as orchestration / provider / release-policy layer
- enrichment builders and their typed contracts
- Pine library generation and TradingView publish path
- SMC Core Engine / Dashboard / Strategy as consumers
- SMC++ lifecycle, context gates, dashboard rows, alert payloads

### 2.2 Out of scope

- redefining canonical structure categories
- embedding planning fields into `snapshot.structure`
- discretionary Fib workflows
- external zero-lag timing engines as first-class architecture components
- legacy monolith behavior that bypasses the split contract

---

## 3. Canonical Contract Boundary

### 3.1 Canonical structure remains unchanged

Canonical `snapshot.structure` contains only:

- `bos`
- `orderblocks`
- `fvg`
- `liquidity_sweeps`

No Phase 1 or Phase 2 field is allowed inside canonical structure rows.

### 3.2 Additive data remains outside canonical structure

The following belong to additive context or delivery layers:

- provider provenance
- enrichment blocks
- structure qualifiers
- session / profile / range regime data
- event risk / flow / compression / reversal context
- planning metrics such as headroom and risk geometry
- lifecycle state projections
- dashboard and alert payload fields

### 3.3 Contract principles

Every additive layer follows the same rules:

1. safe neutral defaults exist
2. typed contract exists
3. builder is feature-flag controlled
4. generated library always emits all required fields
5. downstream consumers must tolerate defaults and missing upstream execution
6. additive layers may influence gating, but not redefine canonical structure semantics

---

## 4. Platform / Library Plane

## 4.1 Vision

The SMC base generator is the only pipeline that gathers provider data, applies enrichment and layering, and emits the generated Pine library used by TradingView consumers.

Two equivalent paths may produce the library:

- **Manual path** via Streamlit UI for local/operator control
- **Automated path** via GitHub Actions for scheduled refreshes and publish

The generated library is the primary bridge between Python-side enrichment and TradingView-side consumption.

## 4.2 Core components

### Domain core

- `smc_core/` — canonical types, IDs, layering rules

### Boundary / delivery

- `smc_adapters/` — ingest and Pine/dashboard boundary adapters
- `smc_integration/` — orchestration, health, provider policy, release policy

### Enrichment and generation

- `scripts/smc_regime_classifier.py`
- `scripts/smc_news_scorer.py`
- `scripts/smc_calendar_collector.py`
- `scripts/smc_library_layering.py`
- `scripts/generate_smc_micro_profiles.py`
- `scripts/generate_smc_micro_base_from_databento.py`
- `scripts/smc_microstructure_base_runtime.py`

### Consumers

- `SMC_Core_Engine.pine`
- `SMC_Dashboard.pine`
- `SMC_Long_Strategy.pine`
- companion Pine libraries and optional overlays

## 4.3 Provider policy

Primary / secondary / fallback policy remains explicit.

| Domain | Primary | Secondary / Fallback |
|---|---|---|
| base scan / bars / microstructure | Databento | — |
| regime / technical context | FMP | TradingView fallback where applicable |
| news | FMP | Benzinga |
| calendar | FMP | Benzinga |
| event risk / flow / compression / structure-derived blocks | derived from snapshot + upstream results | defaults on failure |

Event risk is a derived stage. It does not call an external provider directly.

## 4.4 Manual path

Representative manual flow:

1. run Streamlit UI
2. configure dataset, universe, API keys, enrichment flags
3. run base scan
4. build enrichment blocks
5. write generated Pine library
6. optionally publish to TradingView

## 4.5 Automated path

Representative automated flow:

1. scheduled GitHub Actions run during US market hours
2. collect provider data
3. execute enrichment builders
4. generate Pine library
5. run evidence gates / contract checks
6. produce diff / artifact snapshot
7. publish to TradingView when gates pass
8. archive / notify / version-govern

## 4.6 Delivery contract

The platform delivers a snapshot bundle and a generated Pine library.

The delivery layer must continue to surface:

- what was structurally present
- what was derived additively
- what provider state was degraded
- whether defaults were substituted

No consumer may infer missing canonical structure from additive context.

---

## 5. Enrichment Architecture Lineage

v5.4 preserves the full additive lineage.

### 5.1 Version progression

| Version | Theme |
|---|---|
| v4 | core + meta, regime, news, calendar, layering, providers, volume |
| v5 | event risk |
| v5.1 | flow qualifier, compression / ATR regime, zone intelligence, reversal context |
| v5.2 | session context, liquidity sweeps, liquidity pools, order blocks, zone projection, profile context |
| v5.3 | structure state, imbalance lifecycle, session-scoped structure, range / profile regime |
| v5.4 | unified architecture + SMC++ gating extensions |

### 5.2 Migration guarantee from v4 → v5+

The historical migration guarantees remain valid:

- v4 fields remain additive-compatible with later versions
- no v4 secret renames are required
- later versions add fields rather than reordering core contract surfaces
- the runtime generation path uses the current dedicated SMC adapters rather than legacy `open_prep` runtime coupling

### 5.3 Contract-first builder pattern

Each enrichment block continues to follow the same pattern:

1. canonical defaults dict
2. typed block / `TypedDict`
3. single top-level enrichment key
4. dedicated builder function
5. generated Pine section
6. feature flag in `build_enrichment()`
7. inventory coverage in contract tests

This remains mandatory in v5.4.

---

## 6. Enrichment Blocks by Family

The major enrichment families retained by v5.4 are:

### Core platform families

- Core + Meta
- Microstructure lists
- Regime
- News
- Calendar
- Layering
- Providers + Volume

### v5 family

- Event Risk

### v5.1 families

- Flow Qualifier
- Compression / ATR Regime
- Zone Intelligence
- Reversal Context

### v5.2 families

- Session Context
- Liquidity Sweeps
- Liquidity Pools
- Order Blocks
- Zone Projection
- Profile Context

### v5.3 families

- Structure State
- Imbalance Lifecycle
- Session-Scoped Structure
- Range / Profile Regime

These remain additive. They are not substitutes for canonical structure rows.

---

## 7. v5.3 Layers That Remain Foundational in v5.4

The following v5.3 layers are still required architectural building blocks.

## 7.1 Structure State

Purpose:

- persistent structure direction
- BOS / CHoCH recency
- swing integrity
- structure freshness and score

Representative gate:

```text
struct_state_ok = lib_struct_trend != "NEUTRAL" and lib_struct_freshness >= 2
```

## 7.2 Imbalance Lifecycle

Purpose:

- track active FVGs through fill / CE / rebalance lifecycle
- replace simplistic binary FVG-active thinking with lifecycle-aware context

Representative gate:

```text
imbalance_ok = lib_imb_lifecycle_score >= 2 and lib_imb_density >= 1
```

## 7.3 Session-Scoped Structure

Purpose:

- combine session identity with intra-session structure
- opening range, impulse, PDH/PDL sweeps, intra-session BOS / CHoCH

Representative gate:

```text
session_struct_ok = lib_sess_struct_score >= 2 and lib_sess_open_range_break != "NONE"
```

## 7.4 Range / Profile Regime

Purpose:

- detect ranging vs trending vs breakout conditions
- quantify range boundaries and value references

Representative gate:

```text
range_regime_ok = lib_range_regime != "UNKNOWN" and lib_range_regime_score >= 2
```

These layers remain active in v5.4 and are not superseded by Phase 1 / Phase 2.

---

## 8. Signal / Execution Plane

v5.4 assumes the current Pine-side architecture is split into five layers.

### 8.1 Canonical Structure Layer

Owns only pure structure events:

- `bos`
- `orderblocks`
- `fvg`
- `liquidity_sweeps`

Question answered:

**What happened structurally?**

### 8.2 Additive Context Layer

Owns context such as:

- structure qualifiers
- HTF context
- session context
- volatility context
- stretch context
- DDVI context
- risk overlays
- enrichment fields read from generated library

Question answered:

**Under what conditions is the structure occurring?**

### 8.3 Setup Planning Layer

Owns:

- trigger planning
- stop planning
- target planning
- reward / risk geometry
- setup quality metrics

Question answered:

**Can the setup be converted into a trade plan?**

### 8.4 Lifecycle / Gating Layer

Owns progression such as:

- `Watchlist`
- `Ready`
- `Entry Best`
- `Entry Strict`

Question answered:

**Is the plan actionable now?**

### 8.5 Delivery / UX Layer

Owns:

- dashboard rows
- labels / debug states
- alert payloads
- consumer-facing additive surfaces

Question answered:

**How is the architecture exposed to users and downstream systems?**

---

## 9. Existing SMC++ Long-Dip Layer Model

The long-dip engine continues to use a layered model to avoid double-counting the same confluence.

### 9.1 Lifecycle

Representative progression:

`Armed -> Building -> Confirmed -> Ready -> Entry Best -> Entry Strict`

### 9.2 Hard gates

Representative classes:

- setup hard gate
- trade hard gate
- environment hard gate

### 9.3 Quality

Representative classes:

- context quality score
- context quality gate

### 9.4 Upgrade modules

Representative modules:

- acceleration
- standard deviation / stretch context
- volatility context
- DDVI
- HTF / LTF strict modules

The principle remains:

> Upgrade modules may improve a setup that is already valid. They do not create canonical structure.

---

## 10. New in v5.4 — Phase 1: Mean-Headroom Gate

## 10.1 Problem statement

The current stack already knows the active stretch / mean context, but does not formalize whether the move back to mean still offers enough usable reward relative to planned risk.

That creates a failure mode where:

1. structure is valid
2. context is supportive
3. trigger is technically acceptable
4. but the move back to mean is too small relative to risk

## 10.2 Architectural intent

Phase 1 introduces a **reward-sanity layer**. It does not replace structure or context quality.

## 10.3 Derived fields

### `mean_headroom_pts`

Distance between active long setup trigger and current stretch mean.

Conceptually:

```text
mean_headroom_pts = stretch_mean - long_setup_trigger
```

### `mean_headroom_r`

Headroom normalized by planned risk.

```text
mean_headroom_r = mean_headroom_pts / long_risk_r
```

### `mean_headroom_best_ok`

Best-entry policy flag.

### `mean_headroom_strict_ok`

Strict-entry policy flag.

## 10.4 Layer placement

- canonical structure: no change
- additive context: consumes existing stretch context only
- setup planning: primary home for headroom calculations
- lifecycle: gates `Entry Best` and `Entry Strict`
- delivery / UX: surfaces headroom points, R multiple, pass/fail state

## 10.5 Recommended policy

- `Watchlist`: unchanged
- `Ready`: informational use only
- `Entry Best`: requires `mean_headroom_best_ok`
- `Entry Strict`: requires `mean_headroom_strict_ok`

## 10.6 Recommended inputs

- `use_mean_headroom_gate`
- `min_mean_headroom_r_best`
- `min_mean_headroom_r_strict`

Representative defaults:

- Best: `0.8R`
- Strict: `1.2R`

---

## 11. New in v5.4 — Phase 2: Stretch Compression / Breakout-Risk State

## 11.1 Problem statement

Existing stretch logic identifies downside overextension and anti-chase conditions, but does not explicitly classify compressed stretch regimes where mean-reversion quality is lower until release / expansion becomes clearer.

## 11.2 Architectural intent

Phase 2 introduces a **regime guard** that separates:

1. clean stretched reversion conditions
2. compressed unresolved coil conditions

## 11.3 Derived fields

### `stretch_std_baseline`

Baseline reference for current stretch dispersion.

### `stretch_std_ratio`

Current stretch dispersion relative to baseline.

```text
stretch_std_ratio = stretch_std / stretch_std_baseline
```

### `stretch_compressed`

Compression-state boolean.

### `stretch_breakout_risk`

Primary Phase 2 decision flag indicating compressed unresolved expansion risk.

## 11.4 Layer placement

- canonical structure: no change
- additive context: primary home
- setup planning: may affect setup quality but not trigger construction
- lifecycle: may downgrade / block high-confidence entries
- delivery / UX: visible as regime badge / row

## 11.5 Recommended policy

- `Watchlist`: unchanged, but regime surfaced
- `Ready`: caution only
- `Entry Best`: allowed when breakout-risk is absent or resolved
- `Entry Strict`: blocked when `stretch_breakout_risk` is true

## 11.6 Recommended inputs

- `use_stretch_compression`
- `compression_baseline_len`
- `stretch_compression_ratio`
- `strict_block_on_breakout_risk`

Representative defaults:

- baseline length: `50`
- compressed threshold: `0.70`

---

## 12. Cross-Layer Interpretation Rules

The required order of interpretation is:

1. canonical structure decides whether a setup candidate exists
2. additive context decides whether the setup is occurring in favorable or hostile conditions
3. planning metrics decide whether the trade geometry is acceptable
4. lifecycle gates decide whether the setup may be promoted to `Entry Best` or `Entry Strict`

Practical consequence:

A setup must not be promoted into high-conviction state merely because structure, HTF, DDVI, volatility, or profile context are supportive when:

- mean headroom is too small, or
- compression breakout-risk remains unresolved

---

## 13. Dashboard / Alert / BUS Impact

### 13.1 Dashboard expectations

v5.4 should visibly surface:

- canonical structure status
- key additive context status
- `Mean Headroom`:
  - points
  - R multiple
  - Best pass/fail
  - Strict pass/fail
- `Stretch Regime`:
  - expanded
  - normal
  - compressed
  - breakout-risk

### 13.2 Alert expectations

Alert payloads should be able to expose:

- `mean_headroom_pts`
- `mean_headroom_r`
- `mean_headroom_best_ok`
- `mean_headroom_strict_ok`
- `stretch_std_ratio`
- `stretch_compressed`
- `stretch_breakout_risk`

If data is unavailable, the payload must make absence explicit rather than implying success.

### 13.3 BUS / consumer compatibility

Existing consumer patterns remain valid.

v5.4 adds new additive surfaces; it does not redefine the existing consumer expectation that canonical structure categories remain stable and machine-readable.

---

## 14. Backward Compatibility

v5.4 is backward compatible by design.

### Stable

The following remain stable:

- canonical structure categories
- structure normalization semantics
- snapshot consumer boundary
- provider / release-policy model
- additive enrichment pattern from earlier versions

### Additive in v5.4

The following are new but optional:

- Phase 1 planning metrics
- Phase 2 regime metrics
- corresponding dashboard rows
- corresponding alert fields

Consumers that do not understand the new additive fields may ignore them without breaking.

---

## 15. Testing Requirements

### 15.1 Platform / contract tests

The following remain required:

- field inventory tests
- manifest / version tests
- provider policy tests
- pipeline E2E tests
- consumer contract tests
- open_prep boundary / runtime isolation tests

### 15.2 Phase 1 tests

Minimum families:

1. `mean_headroom_pts` deterministic for fixed inputs
2. `mean_headroom_r` safe under `na` and zero-risk paths
3. Best / Strict thresholds respected
4. strategy / indicator parity preserved

### 15.3 Phase 2 tests

Minimum families:

1. compression baseline deterministic
2. compressed / not-compressed boundary covered
3. breakout-risk resolves correctly once release conditions become true
4. strategy / indicator parity preserved

### 15.4 Regression expectations

1. earlier-version-compatible setups still appear in `Watchlist` / `Ready` when appropriate
2. v5.4 reduces or reclassifies higher-conviction entries; it does not invent a second setup family
3. alert payloads remain backward compatible when new fields are absent

---

## 16. Rollout Plan

Recommended rollout order:

1. keep the unified architecture document authoritative
2. implement / validate Phase 1 first
3. implement / validate Phase 2 second
4. expose both in dashboard/debug first
5. validate parity and regressions
6. only then enable by default

For repo hygiene, future architecture changes should continue to prefer:

- new authoritative target docs over ambiguous note fragments
- additive revisions over silent contract drift
- explicit PRs for architectural changes

---

## 17. Decision Summary

v5.4 keeps the existing architecture intact and unifies the previously split documentation into one target architecture.

It does three things at once:

1. preserves the platform / pipeline architecture for provider ingest, enrichment, generation, publish, and governance
2. preserves the full enrichment lineage from v4 through v5.3, including contract-first additive blocks
3. adds two focused SMC++ execution-plane improvements:
   - **Phase 1** formalizes whether the move back to mean is worth current risk
   - **Phase 2** formalizes whether the stretch regime is clean for reversion or still compressed and expansion-prone

The governing rule remains unchanged:

> `snapshot.structure` stays canonical-only. All new intelligence is additive outside that boundary.
