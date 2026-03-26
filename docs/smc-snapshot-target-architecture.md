# SMC Snapshot Target Architecture

## Status

This document is the canonical target architecture for the SMC snapshot, layering, and TradingView bridge stack.

Any future implementation work in this repository must conform to this contract unless this document is explicitly revised.

Current bridge code under [../smc_tv_bridge](../smc_tv_bridge) should be treated as a prototype integration layer. Where prototype behavior differs from this document, this target architecture wins.

Use this document together with:

- [smc-microstructure-ui-architecture.md](smc-microstructure-ui-architecture.md)
- [smc-microstructure-ui-operator-runbook.md](smc-microstructure-ui-operator-runbook.md)
- [../spec/smc_snapshot.schema.json](../spec/smc_snapshot.schema.json)

## Goal

The system builds one canonical `SmcSnapshot` per `symbol + timeframe`.

That snapshot is the only architecture boundary that downstream consumers should depend on.

Downstream consumers include:

1. TradingView / Pine overlays
2. Node HTTP bridge endpoints
3. dashboards and operator UIs
4. future alerting or execution layers

## Architecture Overview

The target architecture is split into four layers.

## Official Home

The official home for this contract is a dedicated root-level Python package:

- `smc_core`

`smc_core` is the only intended source of truth for snapshot-domain logic.

It owns:

1. canonical snapshot types
2. deterministic ID generation
3. meta normalization
4. base signal derivation
5. layering
6. stable snapshot serialization helpers

It does not own:

1. HTTP transport
2. Node bridge logic
3. UI rendering
4. Pine formatting concerns
5. dashboard color policy outside semantic tokens already captured in `ZoneStyle`

Current bridge code under [../smc_tv_bridge](../smc_tv_bridge) remains an adapter layer and must migrate toward `smc_core`, not become the long-term home of the contract.

## Preferred Module Layout

The preferred root-level package layout is:

1. `smc_core/types.py`
2. `smc_core/ids.py`
3. `smc_core/layering.py`
4. `smc_core/__init__.py`

Optional later splits are allowed if the module grows, but the following responsibilities must remain clear.

### smc_core/types.py

Owns the public domain types for:

1. `SmcStructure`
2. `SmcMeta`
3. `SmcSnapshot`
4. `ZoneStyle`
5. concrete timed wrapper types

### smc_core/ids.py

Owns deterministic ID generation directly and from day one.

It must expose dedicated helpers such as:

1. `bos_id(...)`
2. `ob_id(...)`
3. `fvg_id(...)`
4. `sweep_id(...)`

ID generation must not be deferred to ad hoc call sites.

### smc_core/layering.py

Owns:

1. `normalize_meta(...)`
2. `derive_base_signals(...)`
3. `apply_layering(...)`
4. internal-only normalization helpers

### smc_core/__init__.py

Exports only the public API.

Internal helper-only types must not be re-exported automatically.

### 1. Structure Layer

The structure layer produces pure SMC structure objects:

1. `bos`
2. `orderblocks`
3. `fvg`
4. `liquidity_sweeps`

This layer must not encode UI colors, dashboard styles, or trade gating decisions.

### 2. Meta Layer

The meta layer attaches normalized context for the same `symbol + timeframe`:

1. volume regime
2. technical directional strength
3. news directional strength
4. provenance

Each source carries its own `asof_ts` and `stale` status.

### 3. Layering Layer

The layering layer maps `structure + meta` to a pure overlay description:

1. style
2. trade gating
3. heat
4. bias
5. reason codes

This layer must not mutate input structure or input meta.

### 4. Transport Layer

The transport layer may expose the canonical snapshot through:

1. nested JSON for internal consumers
2. compact encoded formats for Pine / TradingView
3. a thin Node bridge in front of Python services

Transport must not redefine semantics.

## Canonical Types

### DirectionalStrength

Tech and news are directional signals, not unsigned scores.

```ts
type DirectionalStrength = {
  strength: number;                    // 0..1, 0 = no signal, 1 = very strong
  bias: 'BULLISH' | 'BEARISH' | 'NEUTRAL';
};
```

### VolumeRegime

Use upstream regime names exactly.

```ts
type VolumeRegime = 'NORMAL' | 'LOW_VOLUME' | 'HOLIDAY_SUSPECT';
```

### SmcMeta

```ts
type TimedVolumeInfo = {
  value: {
    regime: VolumeRegime;
    thin_fraction: number;
  };
  asof_ts: number;
  stale: boolean;
};

type TimedDirectionalStrength = {
  value: DirectionalStrength;
  asof_ts: number;
  stale: boolean;
};

type TimedNewsDirectionalStrength = {
  value: DirectionalStrength & { category?: string };
  asof_ts: number;
  stale: boolean;
};

type SmcMeta = {
  symbol: string;
  timeframe: string;
  asof_ts: number;

  volume: TimedVolumeInfo;

  technical?: TimedDirectionalStrength;
  news?: TimedNewsDirectionalStrength;

  provenance?: string[];
};
```

Open generic `TimedValue<T>` is not the preferred official public contract.

Concrete timed wrapper types are preferred so runtime consumers and tests have a narrower and more explicit shape.

### Structure Types

```ts
type BosEventKind = 'BOS' | 'CHOCH';

type BosEvent = {
  id: string;
  time: number;
  price: number;
  kind: BosEventKind;
  dir: 'UP' | 'DOWN';
};

type Orderblock = {
  id: string;
  low: number;
  high: number;
  dir: 'BULL' | 'BEAR';
  valid: boolean;
};

type Fvg = {
  id: string;
  low: number;
  high: number;
  dir: 'BULL' | 'BEAR';
  valid: boolean;
};

type LiquiditySweep = {
  id: string;
  time: number;
  price: number;
  side: 'BUY_SIDE' | 'SELL_SIDE';
};

type SmcStructure = {
  bos: BosEvent[];
  orderblocks: Orderblock[];
  fvg: Fvg[];
  liquidity_sweeps: LiquiditySweep[];
};
```

## ID Rules

IDs are not just stable in spirit. They are contractual.

Required components:

1. per-type prefix: `bos:`, `ob:`, `fvg:`, `sweep:`
2. symbol
3. timeframe
4. quantized time anchor
5. direction or kind
6. quantized price or price range

Examples:

1. `bos:AAPL:15m:1709251200:BOS:UP:185.25`
2. `ob:AAPL:15m:1709251200:BULL:185.25:186.10`
3. `sweep:AAPL:5m:1709250900:SELL_SIDE:103.20`

Recompute of the same logical event must produce the same ID.

The ID contract must be implemented directly in `smc_core/ids.py` and consumed everywhere else.

The rules are:

1. type prefix is mandatory
2. symbol and timeframe are mandatory
3. time anchor must be deterministic and quantized to the bar/event anchor
4. prices must be quantized deterministically before formatting
5. recomputing the same logical event must return the same ID string byte-for-byte

## ZoneStyle

Core semantics must not hard-code UI colors.

```ts
type ReasonCode =
  | 'REGIME_NORMAL'
  | 'REGIME_LOW_VOLUME'
  | 'REGIME_HOLIDAY_SUSPECT'
  | 'VOLUME_STALE'
  | 'TECH_MISSING'
  | 'TECH_STALE'
  | 'NEWS_MISSING'
  | 'NEWS_STALE'
  | 'TECH_BULLISH'
  | 'TECH_BEARISH'
  | 'NEWS_BULLISH'
  | 'NEWS_BEARISH'
  | 'OB_INVALID'
  | 'FVG_INVALID'
  | 'BOS'
  | 'CHOCH'
  | 'SWEEP_BUY_SIDE'
  | 'SWEEP_SELL_SIDE';

type ZoneStyle = {
  opacity: number;
  lineWidth: number;
  render_state: 'NORMAL' | 'DIMMED' | 'HIDDEN';
  trade_state: 'ALLOWED' | 'DISCOURAGED' | 'BLOCKED';
  bias: 'LONG' | 'SHORT' | 'NEUTRAL';
  strength: number;
  heat: number;
  tone: 'BULLISH' | 'BEARISH' | 'NEUTRAL' | 'WARNING';
  emphasis: 'LOW' | 'MEDIUM' | 'HIGH';
  reason_codes: ReasonCode[];
};
```

Liquidity sweeps remain warnings, not direct long/short commands.

Required sweep defaults:

1. `bias = 'NEUTRAL'`
2. `tone = 'WARNING'`
3. `reason_codes += ['SWEEP_BUY_SIDE' | 'SWEEP_SELL_SIDE']`

## SmcSnapshot

This is the canonical contract.

```ts
type SmcLayered = {
  zone_styles: Record<string, ZoneStyle>;
};

type SmcSnapshot = {
  symbol: string;
  timeframe: string;
  generated_at: number;
  schema_version: string;
  structure: SmcStructure;
  meta: SmcMeta;
  layered: SmcLayered;
};
```

## Hard Invariants

The following invariants are mandatory.

1. `applyLayering(structure, meta)` is pure.
2. `applyLayering(structure, meta)` is deterministic for the same inputs.
3. `structure` must not be mutated.
4. `meta` must not be mutated.
5. every structure item ID must have exactly one corresponding `layered.zone_styles[id]` entry.
6. no meta source may delete structure elements.
7. no transport format may redefine core semantics.

## applyLayering Contract

Public contract:

```ts
function applyLayering(structure: SmcStructure, meta: SmcMeta, generated_at?: number): SmcSnapshot;
```

Internal decomposition:

```ts
type NormalizedMeta = {
  symbol: string;
  timeframe: string;
  asof_ts: number;
  volume_regime: VolumeRegime;
  volume_stale: boolean;
  thin_fraction: number;
  signed_tech: number;
  tech_present: boolean;
  tech_stale: boolean;
  signed_news: number;
  news_present: boolean;
  news_stale: boolean;
  provenance: string[];
};

type BaseLayerSignals = {
  global_heat: number;
  global_strength: number;
  base_reasons: ReasonCode[];
};

function normalizeMeta(meta: SmcMeta): NormalizedMeta;
function deriveBaseSignals(nm: NormalizedMeta): BaseLayerSignals;
function applyLayering(structure: SmcStructure, meta: SmcMeta, generated_at?: number): SmcSnapshot;
```

`NormalizedMeta` is an internal `smc_core.layering` type.

It may be imported directly by tests from the layering module when needed, but it is not part of the public package API.

Python form:

```py
def apply_layering(
    structure: SmcStructure,
    meta: SmcMeta,
    *,
    generated_at: float | None = None,
) -> SmcSnapshot: ...
```

`generated_at` exists specifically so tests can fix output timestamps deterministically.

## Signed Strength And Heat

```ts
function signedStrength(ds?: DirectionalStrength): number {
  if (!ds) return 0;
  if (ds.bias === 'BULLISH') return ds.strength;
  if (ds.bias === 'BEARISH') return -ds.strength;
  return 0;
}
```

Heat aggregation:

```ts
const techVal = meta.technical && !meta.technical.stale ? meta.technical.value : undefined;
const newsVal = meta.news && !meta.news.stale ? meta.news.value : undefined;

const signedTech = signedStrength(techVal);
const signedNews = signedStrength(newsVal);

const heatRaw = signedTech * 0.7 + signedNews * 0.3;
const heat = Math.max(-1, Math.min(1, heatRaw));
```

## normalize_meta Requirements

`normalize_meta` must clamp and validate defensively.

Required behavior:

1. `strength` values are hard-clamped to `[0, 1]`
2. `thin_fraction` is hard-clamped to `[0, 1]`
3. unknown volume regimes must either:
  - fall back to `NORMAL`, or
  - raise a defined, testable error
4. broken or partial inputs must degrade toward neutral meta rather than leaking undefined behavior downstream

The implementation must prefer predictable neutral fallback over implicit partial corruption.

## Default Behavior For Missing Meta

These defaults are contractual.

1. If volume meta is missing or stale:
   - `volume_regime = 'NORMAL'`
   - add `VOLUME_STALE`
2. If tech is missing:
   - `signed_tech = 0`
   - add `TECH_MISSING`
3. If news is missing:
   - `signed_news = 0`
   - add `NEWS_MISSING`

Only volume regime may globally block or dim tradeability.

### HOLIDAY_SUSPECT

1. `render_state = 'DIMMED'`
2. `trade_state = 'BLOCKED'`

### LOW_VOLUME

1. `render_state` may be at most `DIMMED`
2. `trade_state` may be at most `DISCOURAGED`

No other meta source may remove a structure element or hide it by definition.

## apply_layering Requirements

`apply_layering` must emit a `zone_styles` entry for every entity type in `SmcStructure`:

1. orderblocks
2. fvg
3. BOS events
4. CHOCH events
5. liquidity sweeps

It must not:

1. mutate `structure`
2. mutate `meta`
3. omit a style for a known structure ID
4. create orphan styles that do not map to a structure ID

## Serialization Helper

A small central serialization helper belongs in `smc_core` early:

```py
def snapshot_to_dict(snapshot: SmcSnapshot) -> dict: ...
```

The purpose is to keep serialization and transport adapters consistent.

Adapters such as FastAPI endpoints, Node bridge projections, and any dashboard payload builders should prefer this shared helper instead of ad hoc serialization logic.

## Transport Guidance

Nested JSON is the source contract.

Compact transport for Pine may project the canonical snapshot into encoded fields such as:

1. `bos`
2. `ob`
3. `fvg`
4. `sweeps`
5. `regime`
6. `tech`
7. `news`

That compact transport is a projection only. It is not the canonical architecture contract.

## Validation Artifacts

The source-of-truth schema is:

- [../spec/smc_snapshot.schema.json](../spec/smc_snapshot.schema.json)

Reference examples are:

1. [../spec/examples/smc_snapshot_aapl_15m_normal.json](../spec/examples/smc_snapshot_aapl_15m_normal.json)
2. [../spec/examples/smc_snapshot_aapl_15m_holiday_suspect.json](../spec/examples/smc_snapshot_aapl_15m_holiday_suspect.json)
3. [../spec/examples/smc_snapshot_aapl_5m_low_volume_sweep_only.json](../spec/examples/smc_snapshot_aapl_5m_low_volume_sweep_only.json)

## Implementation Rule

Future work on the SMC snapshot, layering, and TradingView bridge must follow this precedence order:

1. this document
2. [../spec/smc_snapshot.schema.json](../spec/smc_snapshot.schema.json)
3. example snapshots under [../spec/examples](../spec/examples)
4. implementation code under [../smc_tv_bridge](../smc_tv_bridge)

If implementation code diverges from this target architecture, the code must be updated to match the contract.

## Test Invariants

The following test families are mandatory once `smc_core` is implemented.

### Purity And Determinism

1. `apply_layering` must not mutate `structure`
2. `apply_layering` must not mutate `meta`
3. equal inputs plus fixed `generated_at` must produce equal outputs

### Coverage

1. every ID in `structure.*` must appear exactly once in `layered.zone_styles`
2. no `layered.zone_styles` entry may exist without a corresponding structure ID

### Schema Conformance

1. every produced snapshot must validate against [../spec/smc_snapshot.schema.json](../spec/smc_snapshot.schema.json)

### ID Stability

1. repeated ID generation for the same logical event must yield the same string
2. quantization must be deterministic and test-covered