# Databento Structure Features

## Purpose

The Databento volatility scanner now uses a shared market-structure feature layer inspired by the structure logic from SMC++.
The goal is not to port TradingView visuals, but to expose reusable ranking features for:

- daily symbol scoring
- Long-Dip watchlist ranking
- Bullish-Quality window ranking
- UI inspection and diagnostics

## Core Feature Groups

The shared feature builder computes the following fields from second-detail OHLCV data.

### Trend State

- `structure_trend_state`
- `window_structure_trend_state`

Meaning:

- `1` = bullish structure state
- `-1` = bearish structure state
- `0` = neutral / unresolved

The trend state is derived from EMA slope, net move, and the latest swing break context.

### Last Structure Event

- `structure_last_event`
- `window_structure_last_event`

Possible values:

- `bos_up`
- `bos_down`
- `choch_up`
- `choch_down`
- `range`
- `none`

This field captures the latest resolved structure interpretation for the group.

### Break Quality

- `structure_break_quality_score`
- `window_structure_break_quality_score`

Range: `0-100`

This score reflects whether the most recent directional bar or break had:

- a meaningful body
- supportive close location in the range
- supportive volume relative to recent average
- limited adverse wick behavior

### Pressure Proxy

- `structure_pressure_score`
- `window_structure_pressure_score`

Range: `0-100`

This is an intrabar flow proxy built from signed close-to-close movement weighted by volume.
Higher values mean more sustained directional buying pressure.

### Compression

- `structure_compression_score`
- `window_structure_compression_score`

Range: `0-100`

This estimates whether recent true range has compressed relative to the broader sample.
Higher values indicate tighter, more compressed action.

### Swing Distance

- `structure_distance_to_swing_high_pct`
- `structure_distance_to_swing_low_pct`
- `window_structure_distance_to_swing_high_pct`
- `window_structure_distance_to_swing_low_pct`

These fields measure how far the latest close is from the most recent detected swing high/low.

### Reclaim / Failed Break Flags

- `structure_reclaim_flag`
- `structure_failed_break_flag`
- `window_structure_reclaim_flag`
- `window_structure_failed_break_flag`

`reclaim_flag` is set when price traded below the opening reference and finished back above the opening reference or VWAP.

`failed_break_flag` is set when price traded above a prior swing high but failed to hold above the opening reference or VWAP by the close.

### Alignment and Bias

- `structure_alignment_score`
- `structure_bias_score`
- `window_structure_alignment_score`
- `window_structure_bias_score`

Range: `0-100`

`alignment_score` measures whether the internal directional components agree.

`bias_score` is the main aggregate structure metric. It combines:

- trend state
- break quality
- pressure
- alignment
- reclaim bonus
- failed-break penalty

## Where The Features Live

### Daily Symbol Features

The following are added to `daily_symbol_features_full_universe`:

- `structure_trend_state`
- `structure_last_event`
- `structure_break_quality_score`
- `structure_pressure_score`
- `structure_compression_score`
- `structure_distance_to_swing_high_pct`
- `structure_distance_to_swing_low_pct`
- `structure_reclaim_flag`
- `structure_failed_break_flag`
- `structure_alignment_score`
- `structure_bias_score`

### Premarket Window Features

The following are added to `premarket_window_features_full_universe`:

- `window_structure_trend_state`
- `window_structure_last_event`
- `window_structure_break_quality_score`
- `window_structure_pressure_score`
- `window_structure_compression_score`
- `window_structure_distance_to_swing_high_pct`
- `window_structure_distance_to_swing_low_pct`
- `window_structure_reclaim_flag`
- `window_structure_failed_break_flag`
- `window_structure_alignment_score`
- `window_structure_bias_score`

The window alignment and bias metrics are further blended with the parent daily structure context so the window signal does not float completely detached from the broader symbol-day state.

## Score Composition

### Bullish-Quality Window Score

`window_structure_score` now includes both legacy candle-shape information and the new structure layer.

Current blend:

- return strength
- close position in range
- close vs high
- pullback control
- structure break quality
- structure pressure
- structure alignment
- structure bias

Default `window_quality_score` weights are now:

- `balanced` (default): `structure = 0.45`, `stability = 0.20`, `liquidity = 0.20`, `extension = 0.15`
- `conservative`: `structure = 0.35`, `stability = 0.25`, `liquidity = 0.25`, `extension = 0.15`
- `aggressive`: `structure = 0.55`, `stability = 0.15`, `liquidity = 0.15`, `extension = 0.15`

The default profile is `balanced`.
This makes the scanner more selective for names with cleaner directional structure while still preserving liquidity and extension constraints.

## Ranking Semantics

### Long-Dip Watchlist

The watchlist now ranks by:

1. `structure_bias_score` descending
2. `structure_alignment_score` descending
3. `structure_reclaim_flag` descending
4. `prev_close_to_premarket_pct` descending
5. `premarket_dollar_volume` descending
6. `symbol` ascending

This keeps the original premarket gap and liquidity logic intact, but prefers symbols whose structure context is stronger and cleaner.

### Bullish-Quality Scanner

The Bullish-Quality scanner now ranks by:

1. `window_quality_score` descending
2. `window_structure_bias_score` descending
3. `window_structure_alignment_score` descending
4. `window_dollar_volume` descending
5. `symbol` ascending

This means structure acts as a deterministic tie-breaker without replacing the primary quality score.

## UI Exposure

The Streamlit app surfaces the most useful structure fields in both scanner modes.
It also exposes a `Bullish score profile` selector in the sidebar with:

- `conservative`
- `balanced`
- `aggressive`

The selected profile is used both for Bullish-Quality ranking and for refresh jobs that regenerate premarket window artifacts from the UI.

### Long-Dip Watchlist

- trend state
- last structure event
- structure bias
- structure alignment
- break quality
- pressure
- reclaim flag
- failed-break flag

### Bullish-Quality Latest Window

- structure bias
- alignment
- last event

## Practical Interpretation

In practice, the new structure layer helps separate:

- thin, noisy premarket movers from orderly trend continuations
- one-bar spikes from cleaner break-and-hold behavior
- apparent momentum from moves that already show failed-break characteristics

The result should be a more robust shortlist, especially when raw gap/volume metrics alone would otherwise over-rank unstable names.

## CLI / Export Flow

The production export script now accepts:

```bash
python scripts/databento_production_export.py --bullish-score-profile balanced
```

Supported values:

- `conservative`
- `balanced`
- `aggressive`

Example production runs:

### Balanced Profile

Use this as the default daily production mode when you want structure to matter more without over-penalizing borderline liquidity or stability cases.

```bash
source .venv/bin/activate && python scripts/databento_production_export.py \
	--dataset DBEQ.BASIC \
	--lookback-days 30 \
	--top-fraction 0.20 \
	--bullish-score-profile balanced
```

### Aggressive Profile

Use this when you want the Bullish-Quality export to strongly favor names with clean directional structure and stronger break-and-hold behavior.

```bash
source .venv/bin/activate && python scripts/databento_production_export.py \
	--dataset DBEQ.BASIC \
	--lookback-days 30 \
	--top-fraction 0.20 \
	--bullish-score-profile aggressive
```

Practical guidance:

- `balanced` is the safer default for recurring export jobs.
- `aggressive` is useful when the raw shortlist is still too noisy and you want cleaner momentum/structure names.
- `conservative` is useful when you want broader coverage and fewer rejections from the structure layer.

The active score profile is written into the export metadata so downstream consumers can see which weighting profile produced the artifacts.