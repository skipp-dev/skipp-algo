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


class VolumeRegimeBlock(TypedDict, total=False):
    low_tickers: list[str]
    holiday_suspect_tickers: list[str]


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
