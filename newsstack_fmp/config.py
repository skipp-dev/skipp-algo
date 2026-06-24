"""Global configuration for the newsstack multi-source poller.

Supports FMP (polling) + Benzinga (REST delta + WebSocket streaming).
All tunables can be overridden via environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# SSOT for ENABLE_* feature flags (audit-L-1 R4). Imported at module
# load (cheap, leaf module with no transitive deps) so the dataclass
# field default_factory can reference the helper directly without a
# dynamic ``__import__(...)`` (which the dunder-import budget pin
# would flag).
from open_prep.feature_flags import (
    is_benzinga_rest_enabled,
    is_benzinga_rss_enabled,
    is_benzinga_ws_enabled,
    is_fmp_8k_enabled,
    is_fmp_13f_enabled,
    is_fmp_articles_enabled,
    is_fmp_enabled,
    is_fmp_general_enabled,
    is_fmp_house_trades_enabled,
    is_fmp_senate_trades_enabled,
    is_newsapi_ai_enabled,
    is_opra_uoa_enabled,
    is_tradingview_news_enabled,
    is_uw_news_enabled,
)


def _env_float(key: str, default: float) -> float:
    """Read an env var as float, returning *default* on parse failure."""
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    """Read an env var as int, returning *default* on parse failure."""
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


@dataclass(frozen=True)
class Config:
    """Central configuration – one instance per process.

    Environment variables are read at **instantiation** time (not module
    import time) so callers can set them programmatically before
    creating a ``Config``.
    """

    # ── FMP credentials (repr=False to prevent accidental logging) ──
    fmp_api_key: str = field(default_factory=lambda: os.getenv("FMP_API_KEY", ""), repr=False)

    # ── Benzinga credentials (repr=False to prevent accidental logging)
    benzinga_api_key: str = field(default_factory=lambda: os.getenv("BENZINGA_API_KEY", ""), repr=False)

    # ── Additional news credentials ────────────────────────────
    newsapi_ai_key: str = field(default_factory=lambda: os.getenv("NEWSAPI_KEY", ""), repr=False)

    # ── Feature flags ───────────────────────────────────────────
    enable_fmp: bool = field(default_factory=is_fmp_enabled)
    enable_fmp_articles: bool = field(default_factory=is_fmp_articles_enabled)
    enable_benzinga_rest: bool = field(default_factory=is_benzinga_rest_enabled)
    enable_benzinga_ws: bool = field(default_factory=is_benzinga_ws_enabled)
    enable_benzinga_rss: bool = field(default_factory=is_benzinga_rss_enabled)
    enable_tradingview_news: bool = field(default_factory=is_tradingview_news_enabled)
    enable_newsapi_ai: bool = field(default_factory=is_newsapi_ai_enabled)
    # B1: Unusual Whales /news/headlines (default-OFF — endpoint availability
    # depends on UW plan tier; DISABLED-pattern auto-suppresses on 401/403/404).
    enable_uw_news: bool = field(default_factory=is_uw_news_enabled)
    # OPRA UOA replacement (2026-05-12 provider audit). When ON, the
    # streamlit_monitor options-flow tab consumes ``ingest_opra_options_flow``
    # (Databento OPRA.PILLAR) instead of the now-defunct UW flow-alerts path.
    # Flipped 1 (2026-05-12 post-audit follow-up): UW subscription cancelled
    # and replacement code path is the new canonical route. The downstream
    # ``_cached_bz_options_op`` selector still requires ``DATABENTO_API_KEY``
    # to be present, so missing-entitlement environments degrade to an empty
    # list instead of hitting the dead UW endpoint. Override to 0 only when
    # explicitly forcing the legacy Benzinga shim during local debug.
    # SSOT: routes through ``open_prep.feature_flags.is_opra_uoa_enabled``
    # (audit-L-1 R4) to keep the four call sites uniform.
    enable_opra_uoa: bool = field(default_factory=is_opra_uoa_enabled)
    # B4/B5/B7 (PR3 2026-05-09) — FMP extras. general-latest is default-ON
    # (pure value-add macro coverage); Senate/House/8-K default-OFF since
    # they require dedicated FMP plan tiers (DISABLED-pattern auto-suppresses).
    enable_fmp_general: bool = field(default_factory=is_fmp_general_enabled)
    enable_fmp_senate_trades: bool = field(default_factory=is_fmp_senate_trades_enabled)
    enable_fmp_house_trades: bool = field(default_factory=is_fmp_house_trades_enabled)
    enable_fmp_8k: bool = field(default_factory=is_fmp_8k_enabled)
    # B6 (PR5 2026-05-09) — FMP /sec-filings/13F-HR-latest follow-up to PR3.
    enable_fmp_13f: bool = field(default_factory=is_fmp_13f_enabled)

    # ── Polling cadence ─────────────────────────────────────────
    poll_interval_s: float = field(default_factory=lambda: _env_float("POLL_INTERVAL_S", 2.0))

    # ── FMP endpoints (stable) ──────────────────────────────────
    stock_latest_page: int = field(default_factory=lambda: _env_int("FMP_STOCK_LATEST_PAGE", 0))
    stock_latest_limit: int = field(default_factory=lambda: _env_int("FMP_STOCK_LATEST_LIMIT", 200))
    press_latest_page: int = field(default_factory=lambda: _env_int("FMP_PRESS_LATEST_PAGE", 0))
    press_latest_limit: int = field(default_factory=lambda: _env_int("FMP_PRESS_LATEST_LIMIT", 50))
    fmp_articles_limit: int = field(default_factory=lambda: _env_int("FMP_ARTICLES_LIMIT", 250))

    # ── Benzinga REST settings ──────────────────────────────────
    benzinga_rest_page_size: int = field(default_factory=lambda: _env_int("BENZINGA_REST_PAGE_SIZE", 100))

    # Comma-separated channel names to filter Benzinga news.
    # When empty (default), no channel filter is applied (all channels).
    benzinga_channels: str = field(default_factory=lambda: os.getenv("BENZINGA_CHANNELS", ""))

    # Comma-separated topic names to filter Benzinga news.
    # When empty (default), no topic filter is applied.
    benzinga_topics: str = field(default_factory=lambda: os.getenv("BENZINGA_TOPICS", ""))

    # ── Benzinga WebSocket settings ─────────────────────────────
    benzinga_ws_url: str = field(default_factory=lambda: os.getenv(
        "BENZINGA_WS_URL",
        "wss://api.benzinga.com/api/v1/news/stream",
    ))

    # ── Universe (optional) ─────────────────────────────────────
    universe_path: str = field(default_factory=lambda: os.getenv("UNIVERSE_PATH", "universe.txt"))
    filter_to_universe: bool = field(default_factory=lambda: os.getenv("FILTER_TO_UNIVERSE", "0") == "1")
    tv_symbol_limit: int = field(default_factory=lambda: _env_int("TV_SYMBOL_LIMIT", 20))
    tv_max_per_ticker: int = field(default_factory=lambda: _env_int("TV_MAX_PER_TICKER", 3))
    tv_max_total: int = field(default_factory=lambda: _env_int("TV_MAX_TOTAL", 25))
    newsapi_ai_lookback_days: int = field(default_factory=lambda: _env_int("NEWSAPI_AI_LOOKBACK_DAYS", 2))
    newsapi_ai_articles_per_request: int = field(default_factory=lambda: _env_int("NEWSAPI_AI_ARTICLES_PER_REQUEST", 100))
    uw_news_limit: int = field(default_factory=lambda: _env_int("UW_NEWS_LIMIT", 100))
    # PR3: FMP extras pagination/limits
    fmp_general_limit: int = field(default_factory=lambda: _env_int("FMP_GENERAL_LIMIT", 50))
    fmp_general_page: int = field(default_factory=lambda: _env_int("FMP_GENERAL_PAGE", 0))
    fmp_political_pages: int = field(default_factory=lambda: _env_int("FMP_POLITICAL_PAGES", 1))
    fmp_8k_limit: int = field(default_factory=lambda: _env_int("FMP_8K_LIMIT", 50))
    fmp_13f_limit: int = field(default_factory=lambda: _env_int("FMP_13F_LIMIT", 50))

    # ── State ───────────────────────────────────────────────────
    sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_PATH", "newsstack_fmp/state.db"))
    shared_news_cache_dir: str = field(default_factory=lambda: os.getenv("SHARED_NEWS_CACHE_DIR", "artifacts/shared_news_cache"))
    shared_news_cache_ttl_seconds: float = field(default_factory=lambda: _env_float("SHARED_NEWS_CACHE_TTL_SECONDS", 90.0))

    # ── Export ──────────────────────────────────────────────────
    export_path: str = field(default_factory=lambda: os.getenv("EXPORT_PATH", "artifacts/open_prep/latest/news_result.json"))
    top_n_export: int = field(default_factory=lambda: _env_int("TOP_N_EXPORT", 300))

    # ── Thresholds ──────────────────────────────────────────────
    # Default 2.0 effectively disables enrichment (max score is 1.0).
    # Set SCORE_ENRICH_THRESHOLD <= 1.0 (e.g. 0.7) to enable URL enrichment.
    score_enrich_threshold: float = field(default_factory=lambda: _env_float("SCORE_ENRICH_THRESHOLD", 2.0))

    # ── Retention ───────────────────────────────────────────────
    keep_seen_seconds: float = field(default_factory=lambda: _env_float("KEEP_SEEN_SECONDS", 2 * 86400))
    keep_clusters_seconds: float = field(default_factory=lambda: _env_float("KEEP_CLUSTERS_SECONDS", 2 * 3600))

    # ── Derived helpers ─────────────────────────────────────────

    @property
    def active_sources(self) -> list[str]:
        """List of enabled source labels for export metadata."""
        sources: list[str] = []
        if self.enable_fmp:
            sources.extend(["fmp_stock_latest", "fmp_press_latest"])
            if self.enable_fmp_articles:
                sources.append("fmp_articles")
            if self.enable_fmp_general:
                sources.append("fmp_general_latest")
        if self.enable_benzinga_rest:
            sources.append("benzinga_rest")
        if self.enable_benzinga_ws:
            sources.append("benzinga_ws")
        if self.enable_benzinga_rss:
            sources.append("benzinga_rss")
        if self.enable_tradingview_news:
            sources.append("tradingview")
        if self.enable_newsapi_ai and self.newsapi_ai_key:
            sources.append("newsapi_ai")
        if self.enable_uw_news and os.getenv("UNUSUAL_WHALES_API_KEY", "").strip():
            sources.append("uw_news")
        # PR3: FMP political/filings extras (require fmp_api_key)
        if self.fmp_api_key:
            if self.enable_fmp_senate_trades:
                sources.append("fmp_senate_trade")
            if self.enable_fmp_house_trades:
                sources.append("fmp_house_trade")
            if self.enable_fmp_8k:
                sources.append("fmp_8k_latest")
            if self.enable_fmp_13f:
                sources.append("fmp_13f_latest")
        return sources
