# TradingView upstream retirement

TradingView remains a consumer-facing chart and validation surface, but it is
not a runtime upstream source for the system.

Effective 2026-07-18:

- runtime news ingestion uses FMP and Benzinga only;
- the newsstack and Open-Prep pollers no longer contain a TradingView upstream
  branch, cursor, merger lane, or headline normalizer;
- the legacy `ENABLE_TRADINGVIEW_NEWS` and
  `OPEN_PREP_ENABLE_TRADINGVIEW_NEWS` variables are retained for manifest
  compatibility but are permanently fail-closed;
- the live-news bus accepts the former `include_tradingview` argument only as
  a compatibility no-op and records `provider_retired` when called;
- equity technicals use FMP and return an explicit retired-provider error when
  FMP is unavailable;
- the Bitcoin technicals return the same fail-closed compatibility result;
- no runtime path may issue an HTTP request to a TradingView endpoint.

The `terminal_tradingview_news` module and historical TradingView artifacts are
kept only where existing imports, validation evidence, or consumer UI schemas
need a stable compatibility surface. They are not enabled by feature flags and
must not be treated as provider availability or a product commitment.

Any future provider addition requires a separate architecture decision, a
security/privacy review, and a new explicit implementation approval.
