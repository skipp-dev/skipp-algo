"""Global configuration for the newsstack multi-source poller.

Supports FMP (polling) + Benzinga (REST delta + WebSocket streaming).
All tunables can be overridden via environment variables.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


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

    # ── Feature flags ───────────────────────────────────────────
    enable_fmp: bool = field(default_factory=lambda: os.getenv("ENABLE_FMP", "1") == "1")
    enable_benzinga_rest: bool = field(default_factory=lambda: os.getenv("ENABLE_BENZINGA_REST", "0") == "1")
    enable_benzinga_ws: bool = field(default_factory=lambda: os.getenv("ENABLE_BENZINGA_WS", "0") == "1")

    # ── Polling cadence ─────────────────────────────────────────
    poll_interval_s: float = field(default_factory=lambda: _env_float("POLL_INTERVAL_S", 2.0))

    # ── FMP endpoints (stable) ──────────────────────────────────
    stock_latest_page: int = field(default_factory=lambda: _env_int("FMP_STOCK_LATEST_PAGE", 0))
    stock_latest_limit: int = field(default_factory=lambda: _env_int("FMP_STOCK_LATEST_LIMIT", 200))
    press_latest_page: int = field(default_factory=lambda: _env_int("FMP_PRESS_LATEST_PAGE", 0))
    press_latest_limit: int = field(default_factory=lambda: _env_int("FMP_PRESS_LATEST_LIMIT", 50))

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
    filter_to_universe: bool = field(default_factory=lambda: os.getenv("FILTER_TO_UNIVERSE", "1") == "1")

    # ── State ───────────────────────────────────────────────────
    sqlite_path: str = field(default_factory=lambda: os.getenv("SQLITE_PATH", "newsstack_fmp/state.db"))

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
        if self.enable_benzinga_rest:
            sources.append("benzinga_rest")
        if self.enable_benzinga_ws:
            sources.append("benzinga_ws")
        return sources
