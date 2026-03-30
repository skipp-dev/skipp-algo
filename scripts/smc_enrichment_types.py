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


class FlowQualifierBlock(TypedDict, total=False):
    REL_VOL: float
    REL_ACTIVITY: float
    REL_SIZE: float
    DELTA_PROXY_PCT: float
    FLOW_LONG_OK: bool
    FLOW_SHORT_OK: bool
    ATS_VALUE: float
    ATS_CHANGE_PCT: float
    ATS_ZSCORE: float
    ATS_STATE: str           # "ACCUMULATION" | "DISTRIBUTION" | "TRANSITION" | "NEUTRAL"
    ATS_SPIKE_UP: bool
    ATS_SPIKE_DOWN: bool
    ATS_BULLISH_SEQUENCE: bool
    ATS_BEARISH_SEQUENCE: bool


class CompressionRegimeBlock(TypedDict, total=False):
    SQUEEZE_ON: bool
    SQUEEZE_RELEASED: bool
    SQUEEZE_MOMENTUM_BIAS: str   # "BULLISH" | "BEARISH" | "NEUTRAL"
    ATR_REGIME: str              # "COMPRESSION" | "NORMAL" | "EXPANSION" | "EXHAUSTION"
    ATR_RATIO: float


class ZoneIntelligenceBlock(TypedDict, total=False):
    ACTIVE_SUPPORT_COUNT: int
    ACTIVE_RESISTANCE_COUNT: int
    ACTIVE_ZONE_COUNT: int
    PRIMARY_SUPPORT_LEVEL: float
    PRIMARY_RESISTANCE_LEVEL: float
    PRIMARY_SUPPORT_STRENGTH: int
    PRIMARY_RESISTANCE_STRENGTH: int
    SUPPORT_SWEEP_COUNT: int
    RESISTANCE_SWEEP_COUNT: int
    SUPPORT_MITIGATION_PCT: float
    RESISTANCE_MITIGATION_PCT: float
    ZONE_CONTEXT_BIAS: str       # "SUPPORT_HEAVY" | "RESISTANCE_HEAVY" | "NEUTRAL"
    ZONE_LIQUIDITY_IMBALANCE: float


class ReversalContextBlock(TypedDict, total=False):
    REVERSAL_CONTEXT_ACTIVE: bool
    SETUP_SCORE: int
    CONFIRM_SCORE: int
    FOLLOW_THROUGH_SCORE: int
    HTF_STRUCTURE_OK: bool
    HTF_BULLISH_PATTERN: bool
    HTF_BEARISH_PATTERN: bool
    HTF_BULLISH_DIVERGENCE: bool
    HTF_BEARISH_DIVERGENCE: bool
    FVG_CONFIRM_OK: bool
    VWAP_HOLD_OK: bool
    RETRACE_OK: bool


class SessionContextBlock(TypedDict, total=False):
    SESSION_CONTEXT: str          # "ASIA" | "LONDON" | "NY_AM" | "NY_PM" | "NONE"
    IN_KILLZONE: bool
    SESSION_MSS_BULL: bool
    SESSION_MSS_BEAR: bool
    SESSION_STRUCTURE_STATE: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    SESSION_FVG_BULL_ACTIVE: bool
    SESSION_FVG_BEAR_ACTIVE: bool
    SESSION_BPR_ACTIVE: bool
    SESSION_RANGE_TOP: float
    SESSION_RANGE_BOTTOM: float
    SESSION_MEAN: float
    SESSION_VWAP: float
    SESSION_TARGET_BULL: float
    SESSION_TARGET_BEAR: float
    SESSION_DIRECTION_BIAS: str   # "BULLISH" | "BEARISH" | "NEUTRAL"
    SESSION_CONTEXT_SCORE: int


class LiquiditySweepsBlock(TypedDict, total=False):
    RECENT_BULL_SWEEP: bool
    RECENT_BEAR_SWEEP: bool
    SWEEP_TYPE: str              # "NONE" | "STOP_HUNT" | "LIQUIDITY_GRAB" | "INDUCEMENT"
    SWEEP_DIRECTION: str         # "NONE" | "BULL" | "BEAR"
    SWEEP_ZONE_TOP: float
    SWEEP_ZONE_BOTTOM: float
    SWEEP_RECLAIM_ACTIVE: bool
    LIQUIDITY_TAKEN_DIRECTION: str  # "NONE" | "BUY_SIDE" | "SELL_SIDE"
    SWEEP_QUALITY_SCORE: int


class LiquidityPoolsBlock(TypedDict, total=False):
    BUY_SIDE_POOL_LEVEL: float
    SELL_SIDE_POOL_LEVEL: float
    BUY_SIDE_POOL_STRENGTH: int
    SELL_SIDE_POOL_STRENGTH: int
    POOL_PROXIMITY_PCT: float
    POOL_CLUSTER_DENSITY: int
    UNTESTED_BUY_POOLS: int
    UNTESTED_SELL_POOLS: int
    POOL_IMBALANCE: float
    POOL_MAGNET_DIRECTION: str   # "NONE" | "UP" | "DOWN"
    POOL_QUALITY_SCORE: int


class OrderBlocksBlock(TypedDict, total=False):
    NEAREST_BULL_OB_LEVEL: float
    NEAREST_BEAR_OB_LEVEL: float
    BULL_OB_FRESHNESS: int
    BEAR_OB_FRESHNESS: int
    BULL_OB_MITIGATED: bool
    BEAR_OB_MITIGATED: bool
    BULL_OB_FVG_CONFLUENCE: bool
    BEAR_OB_FVG_CONFLUENCE: bool
    OB_DENSITY: int
    OB_BIAS: str                 # "BULLISH" | "BEARISH" | "NEUTRAL"
    OB_NEAREST_DISTANCE_PCT: float
    OB_STRENGTH_SCORE: int
    OB_CONTEXT_SCORE: int


class ZoneProjectionBlock(TypedDict, total=False):
    ZONE_PROJ_TARGET_BULL: float
    ZONE_PROJ_TARGET_BEAR: float
    ZONE_PROJ_RETEST_EXPECTED: bool
    ZONE_PROJ_TRAP_RISK: str     # "NONE" | "LOW" | "MEDIUM" | "HIGH"
    ZONE_PROJ_SPREAD_QUALITY: str  # "TIGHT" | "NORMAL" | "WIDE"
    ZONE_PROJ_HTF_ALIGNED: bool
    ZONE_PROJ_BIAS: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    ZONE_PROJ_CONFIDENCE: int
    ZONE_PROJ_DECAY_BARS: int
    ZONE_PROJ_SCORE: int


class ProfileContextBlock(TypedDict, total=False):
    PROFILE_VOLUME_NODE: str     # "HVN" | "LVN" | "POC" | "NONE"
    PROFILE_VWAP_POSITION: str   # "ABOVE" | "BELOW" | "AT"
    PROFILE_VWAP_DISTANCE_PCT: float
    PROFILE_SPREAD_REGIME: str   # "TIGHT" | "NORMAL" | "WIDE"
    PROFILE_AVG_SPREAD_BPS: float
    PROFILE_SESSION_BIAS: str    # "BULLISH" | "BEARISH" | "NEUTRAL"
    PROFILE_RTH_DOMINANCE_PCT: float
    PROFILE_PM_QUALITY: str      # "STRONG" | "NORMAL" | "WEAK"
    PROFILE_AH_QUALITY: str      # "STRONG" | "NORMAL" | "WEAK"
    PROFILE_MIDDAY_EFFICIENCY: float
    PROFILE_DECAY_HALFLIFE: float
    PROFILE_CONSISTENCY: float
    PROFILE_WICKINESS: float
    PROFILE_CLEAN_SCORE: float
    PROFILE_RECLAIM_RATE: float
    PROFILE_STOP_HUNT_RATE: float
    PROFILE_TICKER_GRADE: str    # "A" | "B" | "C" | "D"
    PROFILE_CONTEXT_SCORE: int


# ── v5.3 blocks ────────────────────────────────────────────────


class StructureStateBlock(TypedDict, total=False):
    STRUCTURE_STATE: str          # "BULLISH" | "BEARISH" | "NEUTRAL"
    STRUCTURE_BULL_ACTIVE: bool
    STRUCTURE_BEAR_ACTIVE: bool
    CHOCH_BULL: bool
    CHOCH_BEAR: bool
    BOS_BULL: bool
    BOS_BEAR: bool
    STRUCTURE_LAST_EVENT: str     # "NONE" | "BOS_BULL" | "BOS_BEAR" | "CHOCH_BULL" | "CHOCH_BEAR"
    STRUCTURE_EVENT_AGE_BARS: int
    STRUCTURE_FRESH: bool
    ACTIVE_SUPPORT: float
    ACTIVE_RESISTANCE: float
    SUPPORT_ACTIVE: bool
    RESISTANCE_ACTIVE: bool


class ImbalanceLifecycleBlock(TypedDict, total=False):
    BULL_FVG_ACTIVE: bool
    BEAR_FVG_ACTIVE: bool
    BULL_FVG_TOP: float
    BULL_FVG_BOTTOM: float
    BEAR_FVG_TOP: float
    BEAR_FVG_BOTTOM: float
    BULL_FVG_PARTIAL_MITIGATION: bool
    BEAR_FVG_PARTIAL_MITIGATION: bool
    BULL_FVG_FULL_MITIGATION: bool
    BEAR_FVG_FULL_MITIGATION: bool
    BULL_FVG_COUNT: int
    BEAR_FVG_COUNT: int
    BULL_FVG_MITIGATION_PCT: float
    BEAR_FVG_MITIGATION_PCT: float
    BPR_ACTIVE: bool
    BPR_DIRECTION: str            # "NONE" | "BULL" | "BEAR"
    BPR_TOP: float
    BPR_BOTTOM: float
    LIQ_VOID_BULL_ACTIVE: bool
    LIQ_VOID_BEAR_ACTIVE: bool
    LIQ_VOID_TOP: float
    LIQ_VOID_BOTTOM: float
    IMBALANCE_STATE: str          # "NONE" | "FVG_BULL" | "FVG_BEAR" | "BPR" | "LIQ_VOID"


class SessionStructureBlock(TypedDict, total=False):
    SESS_HIGH: float
    SESS_LOW: float
    SESS_OPEN_RANGE_HIGH: float
    SESS_OPEN_RANGE_LOW: float
    SESS_OPEN_RANGE_BREAK: str    # "NONE" | "ABOVE" | "BELOW"
    SESS_IMPULSE_DIR: str         # "NONE" | "BULL" | "BEAR"
    SESS_IMPULSE_STRENGTH: int
    SESS_INTRA_BOS_COUNT: int
    SESS_INTRA_CHOCH: bool
    SESS_PDH: float
    SESS_PDL: float
    SESS_PDH_SWEPT: bool
    SESS_PDL_SWEPT: bool
    SESS_STRUCT_SCORE: int


class RangeRegimeBlock(TypedDict, total=False):
    RANGE_REGIME: str             # "TRENDING" | "RANGING" | "BREAKOUT" | "UNKNOWN"
    RANGE_WIDTH_PCT: float
    RANGE_POSITION: str           # "HIGH" | "MID" | "LOW"
    RANGE_HIGH: float
    RANGE_LOW: float
    RANGE_DURATION_BARS: int
    RANGE_VPOC_LEVEL: float
    RANGE_VAH_LEVEL: float
    RANGE_VAL_LEVEL: float
    RANGE_BALANCE_STATE: str      # "BALANCED" | "IMBALANCED_UP" | "IMBALANCED_DOWN"
    RANGE_REGIME_SCORE: int


class RangeProfileRegimeBlock(TypedDict, total=False):
    RANGE_ACTIVE: bool
    RANGE_TOP: float
    RANGE_BOTTOM: float
    RANGE_MID: float
    RANGE_WIDTH_ATR: float
    RANGE_BREAK_DIRECTION: str    # "NONE" | "UP" | "DOWN"
    PROFILE_POC: float
    PROFILE_VALUE_AREA_TOP: float
    PROFILE_VALUE_AREA_BOTTOM: float
    PROFILE_VALUE_AREA_ACTIVE: bool
    PROFILE_BULLISH_SENTIMENT: float
    PROFILE_BEARISH_SENTIMENT: float
    PROFILE_SENTIMENT_BIAS: str   # "BULL" | "BEAR" | "NEUTRAL"
    LIQUIDITY_ABOVE_PCT: float
    LIQUIDITY_BELOW_PCT: float
    LIQUIDITY_IMBALANCE: float
    PRED_RANGE_MID: float
    PRED_RANGE_UPPER_1: float
    PRED_RANGE_UPPER_2: float
    PRED_RANGE_LOWER_1: float
    PRED_RANGE_LOWER_2: float
    IN_PREDICTIVE_RANGE_EXTREME: bool


# ── v5.5 Lean blocks ───────────────────────────────────────────


class SignalQualityBlock(TypedDict, total=False):
    SIGNAL_QUALITY_SCORE: int        # 0-100
    SIGNAL_QUALITY_TIER: str         # "low" | "ok" | "good" | "high"
    SIGNAL_WARNINGS: str             # pipe-separated, max 3
    SIGNAL_BIAS_ALIGNMENT: str       # "bull" | "bear" | "mixed" | "neutral"
    SIGNAL_FRESHNESS: str            # "fresh" | "aging" | "stale"


class EventRiskLightBlock(TypedDict, total=False):
    EVENT_WINDOW_STATE: str          # "CLEAR" | "PRE_EVENT" | "ACTIVE" | "COOLDOWN"
    EVENT_RISK_LEVEL: str            # "NONE" | "LOW" | "ELEVATED" | "HIGH"
    NEXT_EVENT_NAME: str
    NEXT_EVENT_TIME: str
    MARKET_EVENT_BLOCKED: bool
    SYMBOL_EVENT_BLOCKED: bool
    EVENT_PROVIDER_STATUS: str


class SessionContextLightBlock(TypedDict, total=False):
    SESSION_CONTEXT: str             # "ASIA" | "LONDON" | "NY_AM" | "NY_PM" | "NONE"
    IN_KILLZONE: bool
    SESSION_DIRECTION_BIAS: str      # "BULLISH" | "BEARISH" | "NEUTRAL"
    SESSION_CONTEXT_SCORE: int
    SESSION_VOLATILITY_STATE: str    # "LOW" | "NORMAL" | "HIGH" | "EXTREME"


class OBContextLightBlock(TypedDict, total=False):
    PRIMARY_OB_SIDE: str             # "BULL" | "BEAR" | "NONE"
    PRIMARY_OB_DISTANCE: float
    OB_FRESH: bool
    OB_AGE_BARS: int
    OB_MITIGATION_STATE: str         # "fresh" | "touched" | "mitigated" | "stale"


class FVGLifecycleLightBlock(TypedDict, total=False):
    PRIMARY_FVG_SIDE: str            # "BULL" | "BEAR" | "NONE"
    PRIMARY_FVG_DISTANCE: float
    FVG_FILL_PCT: float
    FVG_MATURITY_LEVEL: int          # 0-3 fill-derived maturity proxy
    FVG_FRESH: bool
    FVG_INVALIDATED: bool


class StructureStateLightBlock(TypedDict, total=False):
    STRUCTURE_LAST_EVENT: str        # "NONE" | "BOS_BULL" | "BOS_BEAR" | "CHOCH_BULL" | "CHOCH_BEAR"
    STRUCTURE_EVENT_AGE_BARS: int
    STRUCTURE_FRESH: bool
    STRUCTURE_TREND_STRENGTH: int    # 0-100


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
    flow_qualifier: FlowQualifierBlock
    compression_regime: CompressionRegimeBlock
    zone_intelligence: ZoneIntelligenceBlock
    reversal_context: ReversalContextBlock
    session_context: SessionContextBlock
    liquidity_sweeps: LiquiditySweepsBlock
    liquidity_pools: LiquidityPoolsBlock
    order_blocks: OrderBlocksBlock
    zone_projection: ZoneProjectionBlock
    profile_context: ProfileContextBlock
    structure_state: StructureStateBlock
    imbalance_lifecycle: ImbalanceLifecycleBlock
    session_structure: SessionStructureBlock
    range_regime: RangeRegimeBlock
    range_profile_regime: RangeProfileRegimeBlock
    meta: MetaBlock
    # v5.5 Lean blocks
    signal_quality: SignalQualityBlock
    event_risk_light: EventRiskLightBlock
    session_context_light: SessionContextLightBlock
    ob_context_light: OBContextLightBlock
    fvg_lifecycle_light: FVGLifecycleLightBlock
    structure_state_light: StructureStateLightBlock
