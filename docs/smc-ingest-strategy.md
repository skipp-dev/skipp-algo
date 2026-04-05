# SMC Ingest Strategy

## Purpose

This document defines the intended role of each external data source in the SMC
system.

The goal is to keep provider usage coherent across:

- the microstructure base generator,
- the manual Streamlit path,
- scheduled GitHub Actions refresh runs,
- operator-facing terminal workflows,
- measurement and post-trade analysis,
- TradingView publishing and validation.

The main rule is simple: structure comes from market data, while external
providers add context.

## Core Principles

1. Databento is the canonical market-data source for scanner membership,
   liquidity, volatility, and all snapshot-derived SMC context blocks.
2. Snapshot-derived blocks should be preferred over external APIs whenever the
   signal can be derived from the base scan itself.
3. External providers enrich the system with regime, catalysts, macro context,
   sentiment, and operator visibility, but they do not define market structure.
4. Manual UI, CLI, and CI must share the same provider contract so output does
   not drift by execution path.
5. TradingView is the publish and validation surface, not the truth source for
   membership or microstructure.

## Provider Roles

| Provider | Primary role | Best lane | Why it belongs there | Avoid using it for |
| --- | --- | --- | --- | --- |
| Databento | Canonical base scan and microstructure source | Generator, measurement, replay | It is the only provider in the current stack that directly owns the market microstructure needed for membership, liquidity, volatility, and derived context blocks | News, calendar, macro narrative |
| FMP | Primary slow-moving enrichment source | Generator and CI enrichment | It is broad, predictable, and already the primary contract source for regime, news, calendar, and technical enrichment | Defining structural SMC states or replacing Databento bars |
| Benzinga | Curated catalyst and news fallback | Generator fallback and operator workflows | It is strong when the system needs a second opinion on headlines and calendar-style catalysts, especially for operator review | Canonical scanner input or structural context |
| NewsAPI.ai | Breadth and long-tail news fallback | Batch enrichment and research | It is most useful as a pull-based article source for recall, backfill, thematic discovery, and low-frequency fallback coverage | Primary live feed, calendar source, structural gating |
| TradingView | Consumer runtime and publish target | Publish, validation, fallback technical context | It is the downstream runtime that must consume the generated library, and it can act as a practical fallback for technical context when external enrichment is thin | Source of truth for scanner membership, base OHLCV, or structure derivation |

## Recommended Lane Ownership

### 1. Base scan and generator

Use this ownership model:

- Databento: mandatory canonical input for the base snapshot
- Databento-derived builders: mandatory for session, structure, imbalance,
  order-block, range, profile, and related SMC context blocks
- FMP: primary source for regime, news, calendar, and technical enrichment
- Benzinga: fallback for news and calendar when FMP is stale or unavailable
- NewsAPI.ai: optional tertiary fallback for news only
- TradingView: technical fallback and final publish surface only

This keeps the library/core contract anchored to one market-data truth while
still allowing external context to degrade gracefully.

### 2. Manual Streamlit generation

The manual path should stay functionally identical to the CLI and workflow
path.

That means:

- use the same provider policy chain,
- pass the same secrets through the same resolver,
- default snapshot-derived context blocks on,
- treat manual runs as an alternate entrypoint, not a second architecture.

If manual runs and CI runs can produce materially different library surfaces,
the system will drift in exactly the place where operators trust it most.

### 3. GitHub Actions refresh

The scheduled workflow should remain conservative and deterministic:

- Databento stays mandatory
- FMP stays primary for contextual enrichment
- Benzinga remains the practical fallback for news and calendar
- NewsAPI.ai stays optional so the workflow can still run without it
- TradingView stays at the end of the chain as the publish target

This is the right balance between coverage and operational robustness. The
workflow should not become dependent on a tertiary news source for the core
library refresh to succeed.

### 4. Terminal and operator workflows

Operator workflows have a different goal from the generator: speed of review,
headline recall, and catalyst awareness.

For the live first-arrival contract, see [docs/live-news-first-arrival.md](docs/live-news-first-arrival.md).

Recommended usage:

- Benzinga as the primary live catalyst feed for operator-facing news review
- FMP as supporting macro and market-context enrichment
- NewsAPI.ai for thematic lookup, breadth checks, and historical backfill
- Databento for immediate price-reaction checks after a catalyst lands
- TradingView for final visual confirmation once a setup needs chart-level
  validation

NewsAPI.ai is useful here, but not as a continuous broad live-polling lane. It
is better used for targeted recall, theme confirmation, and filling coverage
gaps around names or sectors that the primary feed did not surface cleanly.

### 5. Measurement and research

Measurement should remain as close to the market-data truth as possible.

Recommended usage:

- Databento for replay, event windows, liquidity reaction, and structural label
  generation
- FMP, Benzinga, and NewsAPI.ai only as explanatory annotations around those
  event windows
- NewsAPI.ai specifically for topic clustering, theme persistence, and long-tail
  historical article recall

This prevents the measurement lane from confusing market structure with text
coverage quality.

### 6. Publish and runtime validation

TradingView should only own the last mile:

- publish generated libraries,
- validate consumer bindings,
- smoke-test the runtime surface,
- provide fallback technical context when needed.

It should not own base data generation and it should not become the hidden
source of structure fields that the generator could not reproduce.

## What NewsAPI.ai Is Good For

NewsAPI.ai is useful, but only in the right shape.

Best current uses:

- optional tertiary fallback for generator-side news sentiment
- broad article recall when FMP and Benzinga are thin on a symbol or theme
- historical research around sectors, macro narratives, and recurring company
  topics
- pre-open or post-event thematic sweeps across a watchlist

Good future uses:

- sector and theme concentration scoring
- multi-symbol catalyst clustering for watchlist prioritization
- persistence scoring that measures whether a story is isolated or part of a
  broader narrative wave
- historical context packs for measurement reviews and post-mortems

Bad uses:

- primary live feed for the terminal
- calendar or earnings-source replacement
- direct structural gating in the SMC engine
- mandatory dependency for CI refresh success

## Where Each Provider Adds The Most Value

### Databento

Highest-value next uses:

- event-study windows around macro releases and earnings timestamps
- reaction-quality metrics for contextual calibration and score review
- richer replay bundles for scanner false-positive and false-negative analysis
- cross-symbol liquidity and volatility regime snapshots for watchlist ranking

### FMP

Highest-value next uses:

- pre-open market regime snapshots for operator briefing
- stable macro and earnings context for event-risk derivation
- low-frequency technical summary where a market-data-only derivation is not
  yet worth building

### Benzinga

Highest-value next uses:

- operator-facing catalyst stream
- fallback macro and earnings awareness when FMP is thin
- review-time headline confirmation before manual action or publish sign-off

### NewsAPI.ai

Highest-value next uses:

- broad recall on symbols with weak primary-feed coverage
- sector and basket narrative scans
- event-linked theme clustering that can explain why multiple symbols moved
  together
- archive-style research for quality-control and dashboard review

### TradingView

Highest-value next uses:

- consumer-surface smoke checks before publish
- fast operator validation that the generated library still binds cleanly into
  the runtime
- selective technical fallback where the enrichment contract allows it

## Recommended Near-Term Extensions

The next useful ingest applications for the SMC system are not more raw feeds.
They are better compositions of the feeds already present.

### 1. Theme risk layer

Build a derived theme-risk block from Benzinga plus NewsAPI.ai:

- detect repeated topic concentration across the watchlist,
- tag names that are moving inside a broader narrative cluster,
- expose a compact theme pressure field for dashboards and review tooling.

This belongs in Python-side artifacts first, not in the Pine lean surface.

### 2. Catalyst persistence score

Combine:

- Benzinga recency,
- NewsAPI.ai breadth,
- Databento reaction quality.

The purpose is to separate one-off headlines from persistent tradeable
information.

### 3. Event-conditioned measurement review

Use Databento reaction windows plus external catalyst annotations to answer:

- which setups fail more often near macro releases,
- which sessions overreact to narrative bursts,
- whether contextual calibration should be conditioned on catalyst presence.

### 4. Pre-open operator brief

Build one operator-focused artifact that merges:

- FMP regime,
- Benzinga and NewsAPI.ai catalyst summary,
- Databento watchlist liquidity and volatility shifts.

That is likely more valuable than adding more standalone dashboards.

## Guardrails

Keep these boundaries hard:

- Do not replace Databento as the canonical base scan input.
- Do not let news providers write structural SMC fields directly.
- Do not make NewsAPI.ai a required CI dependency.
- Do not let TradingView become a hidden upstream source for generator fields.
- Do not split manual and automated generation into separate provider contracts.

## Summary

The clean operating model is:

- Databento defines the market truth.
- Snapshot-derived builders define structural SMC context.
- FMP defines the primary enrichment baseline.
- Benzinga improves catalyst resilience and operator review.
- NewsAPI.ai improves breadth, recall, and research depth.
- TradingView consumes, validates, and publishes the result.

That separation is the right foundation for expanding ingest coverage without
blurring ownership of the actual signal surface.