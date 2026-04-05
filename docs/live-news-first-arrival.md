# Live News First-Arrival Architecture

## Purpose

This document defines the live-news ingest model for terminal workflows,
operator alerting, and any future score adjustments that depend on the first
provider to surface a story.

It is intentionally separate from the batch generator model.

Batch enrichment wants deterministic and conservative output.
Live ingestion wants the fastest trustworthy arrival, regardless of which
provider published first.

## Core Rule

Use different contracts for batch and live lanes:

- Batch generator and CI: primary and fallback provider order
- Live terminal and alerting: parallel provider fan-out with per-provider
  cursors

This keeps the library refresh deterministic without making the live operator
experience depend on a single upstream provider.

## Live Bus Design

### 1. Parallel fan-out

Poll all configured live-capable providers in parallel:

- Benzinga live news
- FMP stock news
- FMP press releases
- TradingView headlines for configured or watchlist-derived symbols

The bus should not wait for a preferred provider before accepting another.

### 2. Per-provider cursors

Each provider keeps its own watermark.

Required cursor buckets:

- `benzinga`
- `fmp_stock`
- `fmp_press`
- `tv`

A single shared cursor is not enough because providers publish at different
times and with different timestamp semantics. One global cursor can suppress
fresh items from a slower or differently timestamped provider.

### 3. Canonical cross-provider story dedup

Before classification, merge raw articles into canonical stories using:

- normalized headline
- sorted ticker set
- coarse time bucket

This prevents the same catalyst from producing multiple alerts just because it
arrived from two providers with different item IDs.

### 4. First arrival wins

For live alerting, the first accepted canonical story becomes the event shown to
the operator.

Later arrivals from other providers may still improve metadata quality, but they
must not re-trigger the same story as a new live event.

### 5. Legacy cursor is compatibility only

If older UI code still expects one cursor, derive it as the max timestamp across
provider cursors.

That value is for compatibility and status display only. It must not replace the
real provider-specific cursor state.

## Provider Roles In The Live Lane

### Benzinga

Useful for curated catalyst flow and broad operator review.

### FMP

Useful as an additional fast lane for stock news and press releases.

### TradingView

Useful only as a symbol-scoped supplemental lane.

TradingView headlines are not a broad global feed in this repository. They are a
watchlist-driven source and should be treated that way.

### NewsAPI.ai

Not the primary live lane in the current repository.

It remains better suited to:

- breadth checks
- historical recall
- thematic lookup
- research and backfill

## Current First Implementation Step

The first production-oriented step is:

1. move terminal polling to a provider-neutral live bus
2. track per-provider cursors in foreground and background polling
3. remove Benzinga-only gating from the Streamlit terminal path
4. merge raw stories across providers before classification

That gives the system a correct foundation for:

- faster first-arrival detection
- fewer duplicate alerts
- cleaner provider failover
- future score adjustments based on live catalyst arrival

## Guardrails

- Do not reuse batch provider ordering as the live decision model.
- Do not collapse provider cursors back into one internal cursor.
- Do not treat TradingView as a market-wide live-news backbone.
- Do not make NewsAPI.ai a mandatory low-latency dependency for terminal mode.

## Summary

The live-news contract should be:

- parallel provider fan-out
- per-provider watermarks
- canonical cross-provider story merge
- earliest accepted arrival as the operator-facing live event

That is the minimum architecture needed if current news should influence
operator actions, alerts, or future score adjustments without being bottlenecked
by one provider.