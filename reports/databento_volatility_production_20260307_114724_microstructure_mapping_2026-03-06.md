# Databento Workbook To Microstructure Base Mapping: databento_volatility_production_20260307_114724.xlsx

- Workbook: databento_volatility_production_20260307_114724.xlsx
- Selected asof_date: 2026-03-06
- Output rows: 97
- Direct fields: 3
- Derived fields: 4
- Missing fields: 34

|Contract field|Status|Source sheet|Source columns|Note|
|---|---|---|---|---|
|asof_date|direct|summary|trade_date|Latest trade_date snapshot selected from workbook summary.|
|symbol|direct|summary|symbol|Copied from workbook summary.|
|exchange|direct|summary|exchange|Copied from workbook summary.|
|asset_type|derived|summary,daily_bars||Derived heuristically from company_name ETF/fund keywords; defaults to stock when no ETF marker is present.|
|universe_bucket|derived|summary,daily_bars||Derived from asset_type plus market_cap bands: ETF -> us_etf, else large/mid/small-cap buckets.|
|history_coverage_days_20d|derived|summary,daily_bars||Derived as trailing daily_bars row count up to the selected asof_date, capped at 20 sessions.|
|adv_dollar_rth_20d|derived|summary,daily_bars||Derived as mean(close * volume) over trailing daily_bars rows up to the selected asof_date, capped at 20 sessions.|
|avg_spread_bps_rth_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|rth_active_minutes_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|open_30m_dollar_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|close_60m_dollar_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|clean_intraday_score_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|consistency_score_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|close_hygiene_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|wickiness_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|pm_dollar_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|pm_trades_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|pm_active_minutes_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|pm_spread_bps_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|pm_wickiness_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|midday_dollar_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|midday_trades_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|midday_active_minutes_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|midday_spread_bps_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|midday_efficiency_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ah_dollar_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ah_trades_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ah_active_minutes_share_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ah_spread_bps_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ah_wickiness_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|reclaim_respect_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|reclaim_failure_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|reclaim_followthrough_r_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ob_sweep_reversal_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|ob_sweep_depth_p75_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|fvg_sweep_reversal_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|fvg_sweep_depth_p75_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|stop_hunt_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|setup_decay_half_life_bars_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|early_vs_late_followthrough_ratio_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
|stale_fail_rate_20d|missing|||Current production workbook does not expose this 20-day microstructure feature; it must be added or derived from richer Databento/market-structure source data.|
