"""Shared type definitions for the SMC enrichment pipeline.

The canonical ``EnrichmentDict`` describes the shape that
``build_enrichment()`` produces and that ``write_pine_library()``
consumes.  Every intermediate function
(``generate_pine_library_from_base``, ``run_generation``,
``publish_generation_result``) passes this dict through unchanged.

Usage::

    from scripts.smc_enrichment_types import EnrichmentDict

All sub-dicts are ``TypedDict`` with ``total=False`` so callers may
omit any block — the consumer (``write_pine_library``) falls back to
safe defaults for every missing key.
"""
from __future__ import annotations

from typing import TypedDict


class RegimeBlock(TypedDict, total=False):
    regime: str        # e.g. "RISK_ON", "RISK_OFF", "NEUTRAL"
    vix_level: float
    macro_bias: float
    sector_breadth: float


class NewsBlock(TypedDict, total=False):
    bullish_tickers: list[str]
    bearish_tickers: list[str]
    neutral_tickers: list[str]
    news_heat_global: float
    ticker_heat_map: str  # "AAPL:0.8,MSFT:0.5"


class CalendarBlock(TypedDict, total=False):
    earnings_today_tickers: str
    earnings_tomorrow_tickers: str
    earnings_bmo_tickers: str
    earnings_amc_tickers: str
    high_impact_macro_today: bool
    macro_event_name: str
    macro_event_time: str


class LayeringBlock(TypedDict, total=False):
    global_heat: float
    global_strength: float
    tone: str       # "NEUTRAL" | "BULLISH" | "BEARISH"
    trade_state: str  # "ALLOWED" | "BLOCKED"


class ProviderBlock(TypedDict, total=False):
    provider_count: int
    stale_providers: str  # comma-separated provider names
    # Per-domain provenance: which provider actually delivered data
    regime_provider: str
    news_provider: str
    calendar_provider: str
    technical_provider: str
    event_risk_provider: str


class VolumeRegimeBlock(TypedDict, total=False):
    low_tickers: list[str]
    holiday_suspect_tickers: list[str]


class MetaBlock(TypedDict, total=False):
    asof_time: str        # ISO-8601 UTC timestamp of generation, e.g. "2026-03-28T14:30:00Z"
    refresh_count: int    # monotonically increasing generation counter


class EventRiskBlock(TypedDict, total=False):
    EVENT_WINDOW_STATE: str        # "CLEAR" | "PRE_EVENT" | "ACTIVE" | "COOLDOWN"
    EVENT_RISK_LEVEL: str          # "NONE" | "LOW" | "ELEVATED" | "HIGH"
    NEXT_EVENT_CLASS: str          # "MACRO" | "EARNINGS" | ""
    NEXT_EVENT_NAME: str           # e.g. "FOMC Rate Decision"
    NEXT_EVENT_TIME: str           # e.g. "14:00"
    NEXT_EVENT_IMPACT: str         # "NONE" | "LOW" | "MEDIUM" | "HIGH"
    EVENT_RESTRICT_BEFORE_MIN: int
    EVENT_RESTRICT_AFTER_MIN: int
    EVENT_COOLDOWN_ACTIVE: bool
    MARKET_EVENT_BLOCKED: bool
    SYMBOL_EVENT_BLOCKED: bool
    EARNINGS_SOON_TICKERS: str     # CSV, e.g. "AAPL,MSFT"
    HIGH_RISK_EVENT_TICKERS: str   # CSV
    EVENT_PROVIDER_STATUS: str     # "ok" | "no_data" | "calendar_missing" | "news_missing"


class EnrichmentDict(TypedDict, total=False):
    """Top-level enrichment payload flowing through the Pine generation chain.

    Produced by ``build_enrichment()`` in
    ``scripts/generate_smc_micro_base_from_databento.py``.
    Consumed by ``write_pine_library()`` in
    ``scripts/generate_smc_micro_profiles.py``.
    """
    regime: RegimeBlock
    news: NewsBlock
    calendar: CalendarBlock
    layering: LayeringBlock
    providers: ProviderBlock
    volume_regime: VolumeRegimeBlock
    event_risk: EventRiskBlock
    meta: MetaBlock
