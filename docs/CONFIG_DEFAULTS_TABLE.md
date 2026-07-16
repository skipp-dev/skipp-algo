# Newsstack configuration defaults

This table mirrors the environment-backed dataclass fields in
`newsstack_fmp/config.py`. Run `python tools/check_defaults_table.py --strict`
after changing a field. `SSOT helper` means the default is owned by the named
helper in `open_prep.feature_flags`, rather than duplicated here.

| Config attribute | Environment variable | Default / owner |
|---|---|---|
| `benzinga_api_key` | `BENZINGA_API_KEY` | empty |
| `benzinga_channels` | `BENZINGA_CHANNELS` | empty |
| `benzinga_direct_api_key` | `BENZINGA_DIRECT_API_KEY` | empty |
| `benzinga_rest_page_size` | `BENZINGA_REST_PAGE_SIZE` | `100` |
| `benzinga_topics` | `BENZINGA_TOPICS` | empty |
| `benzinga_ws_url` | `BENZINGA_WS_URL` | `wss://api.benzinga.com/api/v1/news/stream` |
| `enable_benzinga_rest` | `ENABLE_BENZINGA_REST` | SSOT helper `is_benzinga_rest_enabled` |
| `enable_benzinga_rss` | `ENABLE_BENZINGA_RSS` | SSOT helper `is_benzinga_rss_enabled` |
| `enable_benzinga_ws` | `ENABLE_BENZINGA_WS` | SSOT helper `is_benzinga_ws_enabled` |
| `enable_fmp` | `ENABLE_FMP` | SSOT helper `is_fmp_enabled` |
| `enable_fmp_13f` | `ENABLE_FMP_13F` | SSOT helper `is_fmp_13f_enabled` |
| `enable_fmp_8k` | `ENABLE_FMP_8K` | SSOT helper `is_fmp_8k_enabled` |
| `enable_fmp_articles` | `ENABLE_FMP_ARTICLES` | SSOT helper `is_fmp_articles_enabled` |
| `enable_fmp_general` | `ENABLE_FMP_GENERAL` | SSOT helper `is_fmp_general_enabled` |
| `enable_fmp_house_trades` | `ENABLE_FMP_HOUSE_TRADES` | SSOT helper `is_fmp_house_trades_enabled` |
| `enable_fmp_senate_trades` | `ENABLE_FMP_SENATE_TRADES` | SSOT helper `is_fmp_senate_trades_enabled` |
| `enable_newsapi_ai` | `ENABLE_NEWSAPI_AI` | SSOT helper `is_newsapi_ai_enabled` |
| `enable_opra_uoa` | `ENABLE_OPRA_UOA` | SSOT helper `is_opra_uoa_enabled` |
| `enable_tradingview_news` | `ENABLE_TRADINGVIEW_NEWS` | SSOT helper `is_tradingview_news_enabled` |
| `enable_uw_news` | `ENABLE_UW_NEWS` | SSOT helper `is_uw_news_enabled` |
| `export_path` | `EXPORT_PATH` | `artifacts/open_prep/latest/news_result.json` |
| `filter_to_universe` | `FILTER_TO_UNIVERSE` | `0` |
| `fmp_13f_limit` | `FMP_13F_LIMIT` | `50` |
| `fmp_8k_limit` | `FMP_8K_LIMIT` | `50` |
| `fmp_api_key` | `FMP_API_KEY` | empty |
| `fmp_articles_limit` | `FMP_ARTICLES_LIMIT` | `250` |
| `fmp_general_limit` | `FMP_GENERAL_LIMIT` | `50` |
| `fmp_general_page` | `FMP_GENERAL_PAGE` | `0` |
| `fmp_political_pages` | `FMP_POLITICAL_PAGES` | `1` |
| `newsapi_ai_articles_per_request` | `NEWSAPI_AI_ARTICLES_PER_REQUEST` | `100` |
| `newsapi_ai_key` | `NEWSAPI_KEY` | empty; stable public name |
| `newsapi_ai_lookback_days` | `NEWSAPI_AI_LOOKBACK_DAYS` | `2` |
| `poll_interval_s` | `POLL_INTERVAL_S` | `2.0` |
| `press_latest_limit` | `FMP_PRESS_LATEST_LIMIT` | `50` |
| `press_latest_page` | `FMP_PRESS_LATEST_PAGE` | `0` |
| `score_enrich_threshold` | `SCORE_ENRICH_THRESHOLD` | `2.0` |
| `shared_news_cache_dir` | `SHARED_NEWS_CACHE_DIR` | `artifacts/shared_news_cache` |
| `shared_news_cache_ttl_seconds` | `SHARED_NEWS_CACHE_TTL_SECONDS` | `90.0` |
| `sqlite_path` | `SQLITE_PATH` | `newsstack_fmp/state.db` |
| `stock_latest_limit` | `FMP_STOCK_LATEST_LIMIT` | `200` |
| `stock_latest_page` | `FMP_STOCK_LATEST_PAGE` | `0` |
| `top_n_export` | `TOP_N_EXPORT` | `300` |
| `tv_max_per_ticker` | `TV_MAX_PER_TICKER` | `3` |
| `tv_max_total` | `TV_MAX_TOTAL` | `25` |
| `tv_symbol_limit` | `TV_SYMBOL_LIMIT` | `20` |
| `universe_path` | `UNIVERSE_PATH` | `universe.txt` |
| `uw_news_limit` | `UW_NEWS_LIMIT` | `100` |
