# ADR-001: Open Prep Integration Boundary

| Field       | Value                              |
|-------------|------------------------------------|
| Status      | Accepted                           |
| Date        | 2026-03-27                         |
| Deciders    | skipp-dev                          |
| Supersedes  | (none — first formal ADR)          |

## Context

`smc_tv_bridge/smc_api.py` imports three classes directly from Open Prep:

| Import                           | Source module               | Purpose in bridge             |
|----------------------------------|-----------------------------|-------------------------------|
| `FMPClient`                      | `open_prep.macro`           | Fetch intraday OHLCV candles  |
| `VolumeRegimeDetector`           | `open_prep.realtime_signals`| Detect thin/holiday volume    |
| `TechnicalScorer`                | `open_prep.realtime_signals`| Score RSI/MACD/ADX/MA         |

This creates an implicit runtime coupling: the bridge cannot start
without Open Prep on `sys.path`, and the specific class interfaces
are assumed rather than declared.

Meanwhile, **structure detection** (BOS, order blocks, FVG, liquidity
sweeps) is already canonical — it lives in `smc_core` / `smc_integration`
and is produced by `scripts/explicit_structure_from_bars`.  The bridge
correctly delegates to the canonical producer.

The problem is that the *enrichment* layer (candle data, regime, technical
scores) has no declared interface and is hard-wired to Open Prep
implementations.

## Decision

### 1. Ownership split

| Domain                        | Canonical owner                          | May adapt from         |
|-------------------------------|------------------------------------------|------------------------|
| Structure detection           | `smc_core` + `smc_integration`           | —                      |
| Candle / OHLCV data           | **adapter interface** in `smc_tv_bridge` | `open_prep.macro`      |
| Volume regime classification  | **adapter interface** in `smc_tv_bridge` | `open_prep.realtime_signals` |
| Technical score enrichment    | **adapter interface** in `smc_tv_bridge` | `open_prep.realtime_signals` |
| News score enrichment         | **adapter interface** in `smc_tv_bridge` | `newsstack_fmp`        |

### 2. Adapter pattern

Introduce `smc_tv_bridge/adapters.py` with three protocol classes:

- `CandleProvider` — fetch OHLCV candle dicts for a symbol + interval
- `RegimeProvider` — update regime state from quotes, expose regime + thresholds
- `TechnicalScoreProvider` — return technical score dict for a symbol + interval

`smc_tv_bridge/adapters_open_prep.py` implements these protocols by
wrapping the existing Open Prep classes.  The bridge imports *only* from
the adapter layer.

### 3. Open Prep role

Open Prep is an **adapter / provider** — it is *not* a parallel domain.

- Open Prep may supply data (candles, regime, scores) via adapter
  implementations.
- Open Prep must **not** supply structure detection — that is
  `smc_core`'s job.
- If Open Prep is unavailable at runtime, a mock adapter is used
  (already supported via `SMC_USE_MOCK=1`).

### 4. What does NOT change

- No business logic rewrite.
- `open_prep` package code is untouched.
- The `/smc_snapshot` and `/smc_tv` response shapes are unchanged.
- `SMC_USE_MOCK=1` continues to work.
- All existing tests pass without modification.

## Consequences

- The bridge no longer has `from open_prep…` imports; those move into
  `adapters_open_prep.py`.
- Future providers (e.g. Databento candles, Alpaca regime) can implement
  the same protocols without touching the bridge.
- Adapter implementations are independently testable.
- Next migration slice: extract news enrichment into a `NewsProvider`
  adapter and migrate `newsstack_fmp` behind the same boundary.
