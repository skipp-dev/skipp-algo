# RFC: Bullish-Quality Premarket Scanner

## Decision Summary

The Bullish-Quality scanner is implemented as a separate scanner domain next to the existing Long-Dip watchlist.
The canonical export contract is row-based and keyed by trade_date, symbol, and window_tag.

## Canonical Window Tags

- pm_0400_0500
- pm_0500_0600
- pm_0600_0700
- pm_0700_0800
- pm_0800_0900
- pm_0900_0930

## Export Contract

The primary Bullish-Quality input artifact is premarket_window_features_full_universe.parquet.
Each row represents one symbol-day-window and includes:

- raw window OHLCV metrics
- previous-close and market-open context
- stability, liquidity, structure, and extension subscores
- window_quality_score
- passes_quality_filter
- quality_filter_reason
- quality_rank_within_window
- quality_selected_top_n

quality_window_status_latest.parquet is a latest-trade-date compatibility/status view derived from the canonical window feature export.

Legacy early/late candidate exports are non-canonical and should not be part of the operational output contract.

## UI Contract

The Streamlit app must expose two explicit modes:

- Long-Dip Watchlist
- Bullish-Quality Scanner

Bullish-Quality mode must load the canonical export artifacts and render:

- latest-window top-N rankings
- all-window rankings
- filter diagnostics
- full window-feature detail

## Compatibility Rules

Long-Dip behavior remains intact.
Bullish-Quality logic must not overload Long-Dip ranking semantics.
The status artifact may retain its existing filename for compatibility, but its source must be the canonical Bullish-Quality window-feature export.

## Validation Requirements

- exact-named export artifacts exist
- Bullish-Quality scanner loads from exact-named artifacts
- top-N ranking is computed per trade_date and window_tag
- export writes are atomic to avoid corrupt parquet outputs
- tests cover ranking and empty-result paths