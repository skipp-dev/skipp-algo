# Close Imbalance Implementation Blueprint

## Goal

Add a first production-grade close_imbalance feature block to the existing Databento volatility export pipeline without breaking the current premarket/open workflow.

The implementation remains intentionally additive:

- keep the current open-window ranking logic unchanged
- collect a dedicated close window from 15:50:00 to 16:05:00 ET
- compute raw close-imbalance features on 1-second OHLCV detail
- merge those features into daily_symbol_features_full_universe
- export dedicated close detail and close feature artifacts
- document semantics in the run manifest for downstream research and backtesting

## Why This Shape

The current codebase already has three reusable assets:

- generic 1-second window collection via collect_full_universe_open_window_second_detail(...)
- full-universe feature assembly via build_daily_features_full_universe(...)
- export/manifest plumbing via run_production_export_pipeline(...)

That makes a separate subsystem unnecessary. The cleanest path is to reuse the existing full-universe assembly path and inject close-specific aggregates from three additive inputs:

- 1-second close-window OHLCV detail
- trade-schema close detail
- 1-minute afterhours outcome detail

## Close Window Definition

V1 fixed ET times:

- close_window_start: 15:50:00 ET
- close_auction_time: 16:00:00 ET
- close_window_end: 16:05:00 ET

Interpretation:

- pre-close segment: [15:50:00, 16:00:00)
- last-minute segment: [15:59:00, 16:00:00)
- post-close segment: [16:00:00, 16:05:00)

These boundaries were chosen to match the research hypothesis: late close-consistent activity matters more than generic intraday spikes, and post-close continuation or rejection should be measured separately.

## Implemented Feature Specification

The first close block now spans three layers.

### 1-second close-window OHLCV layer

Core coverage fields:

- has_close_window_detail
- close_window_second_rows
- close_preclose_second_rows
- close_last_minute_second_rows
- close_postclose_second_rows

Volume concentration fields:

- close_10m_volume
- close_last_1m_volume
- close_postclose_5m_volume
- close_last_1m_volume_share
- close_postclose_volume_share

Price structure fields:

- close_reference_price: first open in the 15:50-16:00 ET segment
- close_auction_reference_price: last close before 16:00 ET
- close_preclose_return_pct
- close_postclose_return_pct
- close_postclose_high_pct
- close_postclose_low_pct

### Trade-level hygiene and venue layer

Hygiene fields:

- close_trade_print_count
- close_trade_share_volume
- close_trade_clean_print_count
- close_trade_clean_share_volume
- close_trade_bad_ts_recv_count
- close_trade_maybe_bad_book_count
- close_trade_publisher_specific_flag_count
- close_trade_sequence_break_count
- close_trade_event_time_regression_count
- close_trade_unknown_side_count
- close_trade_unknown_side_share
- close_trade_hygiene_score

Venue-mix fields:

- close_trade_unique_publishers
- close_trade_trf_print_count
- close_trade_trf_share_volume
- close_trade_lit_print_count
- close_trade_lit_share_volume
- close_trade_trf_volume_share
- close_trade_lit_volume_share
- close_trade_has_trf_activity
- close_trade_has_lit_activity
- close_trade_has_lit_followthrough

Venue semantics:

- publishers containing TRF are treated as off-exchange/TRF activity
- non-TRF publishers in the XNAS.BASIC mix are treated as lit exchange confirmation
- lit followthrough is true when close-window activity includes lit prints after TRF participation

### Outcome layer

Same-day afterhours outcomes:

- close_afterhours_minute_rows
- close_afterhours_volume
- close_last_price_2000
- close_high_price_1600_2000
- close_low_price_1600_2000
- close_to_2000_return_pct
- close_to_2000_high_pct
- close_to_2000_low_pct

Next-day outcomes:

- next_trade_date
- next_day_open_price
- next_day_window_end_price (prefers exact 10:00 ET when present, otherwise falls back to the latest available price inside the dedicated 09:30-10:00 ET snapshot)
- close_to_next_open_return_pct
- next_open_to_window_end_return_pct
- close_to_next_window_end_return_pct
- has_next_day_outcome

Context fields reused from the existing universe/fundamental layer:

- market_cap
- float_shares
- shares_outstanding
- news_score
- news_category
- earnings_date
- earnings_time
- filing_date
- filing_type
- mna_flag

This gives downstream research enough information to test the requested hypothesis without prematurely hard-coding a trading score.

## Data Flow

1. run_production_export_pipeline(...) still collects the normal open-window detail.
2. The same collector is called again with 15:50-16:05 ET.
3. A dedicated close trade collector fetches Databento trades for the same close window.
4. A dedicated outcome collector fetches 1-minute bars from 16:00-20:00 ET.
5. A dedicated next-day intraday snapshot is collected with fixed window_end at 10:00 ET.
6. build_daily_features_full_universe(...) receives all close-related detail frames.
7. _build_close_imbalance_aggregates(...), _build_close_trade_aggregates(...), and _build_close_outcome_aggregates(...) compute the derived metrics.
8. Those metrics are merged into daily_symbol_features_full_universe.
9. Next-day open and next-day 10:00 ET outcomes are derived by symbol/date shifting inside the merged feature frame.
10. The export pipeline writes dedicated research artifacts and annotates formulas in the manifest.

## Hygiene Rules

Current clean-trade logic excludes prints flagged as bad receive timestamp or maybe bad book. Publisher-specific flags are counted separately but retained for analysis.

Additional anomaly counters track:

- sequence regressions
- event-time regressions
- unknown side values

This is intentionally conservative: it surfaces questionable activity without overfitting to undocumented publisher-specific behavior.

## Export Artifacts

The pipeline now exports:

- full_universe_second_detail_close
- full_universe_close_trade_detail
- full_universe_close_outcome_minute
- close_imbalance_features_full_universe
- close_imbalance_outcomes_full_universe

It also extends:

- daily_symbol_features_full_universe with close OHLCV, hygiene, venue, and outcome columns
- manifest metadata with close window, hygiene, venue, and outcome formulas

## Remaining Non-Goals

The following are still explicitly deferred:

- trade-condition-specific interpretation beyond the generic Databento flags already used
- exact auction imbalance feeds or NOII-style auction messages
- auction imbalance schema integration

Those require additional schema coverage beyond the current implemented close-trade and 1-minute detail layers.

## Recommended Next Steps

1. Validate the new close-trade hygiene thresholds on real Databento samples once an API key is available in the runtime environment.
2. The next-day window-end label now prefers an exact 10:00 ET observation but falls back to the latest available in-window snapshot when that boundary second is missing; any future alternate horizon should be added as a separate label family rather than overloading this one.
3. Add auction-specific data, if available, to separate closing-cross behavior from generic late prints.
4. Add a dedicated close_imbalance ranking/export mode once raw feature quality is validated.
