from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, TypeAlias

VolumeRegime: TypeAlias = Literal["NORMAL", "LOW_VOLUME", "HOLIDAY_SUSPECT"]
BosEventKind: TypeAlias = Literal["BOS", "CHOCH"]
BosDir: TypeAlias = Literal["UP", "DOWN"]
ObDir: TypeAlias = Literal["BULL", "BEAR"]
FvgDir: TypeAlias = Literal["BULL", "BEAR"]
SweepSide: TypeAlias = Literal["BUY_SIDE", "SELL_SIDE"]
EventSeverity: TypeAlias = Literal["HIGH", "MODERATE", "LOW"]
EventType: TypeAlias = Literal["EARNINGS", "FOMC", "CPI", "NFP", "OPEX", "OTHER"]
MarketRegime: TypeAlias = Literal["RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL"]
NewsCategory: TypeAlias = Literal["MACRO", "SECTOR", "COMPANY", "GEOPOLITICAL", "OTHER"]
ReasonCode: TypeAlias = Literal[
    "REGIME_NORMAL",
    "REGIME_LOW_VOLUME",
    "REGIME_HOLIDAY_SUSPECT",
    "VOLUME_STALE",
    "TECH_MISSING",
    "TECH_STALE",
    "NEWS_MISSING",
    "NEWS_STALE",
    "TECH_BULLISH",
    "TECH_BEARISH",
    "NEWS_BULLISH",
    "NEWS_BEARISH",
    "OB_INVALID",
    "FVG_INVALID",
    "BOS",
    "CHOCH",
    "SWEEP_BUY_SIDE",
    "SWEEP_SELL_SIDE",
    "EVENT_RISK_HIGH",
    "EVENT_RISK_MODERATE",
    "REGIME_RISK_ON",
    "REGIME_RISK_OFF",
    "REGIME_ROTATION",
    "NEWS_MACRO",
    "NEWS_COMPANY",
]


@dataclass(slots=True, frozen=True)
class DirectionalStrength:
    strength: float
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]


@dataclass(slots=True, frozen=True)
class VolumeInfo:
    regime: VolumeRegime
    thin_fraction: float


@dataclass(slots=True, frozen=True)
class TimedVolumeInfo:
    value: VolumeInfo
    asof_ts: float
    stale: bool


@dataclass(slots=True, frozen=True)
class TimedDirectionalStrength:
    value: DirectionalStrength
    asof_ts: float
    stale: bool


@dataclass(slots=True, frozen=True)
class EventRisk:
    event_type: EventType
    severity: EventSeverity
    window_start: float
    window_end: float


@dataclass(slots=True, frozen=True)
class EnrichedNews:
    strength: float
    bias: Literal["BULLISH", "BEARISH", "NEUTRAL"]
    category: NewsCategory
    freshness_minutes: float
    source: str


@dataclass(slots=True, frozen=True)
class TimedEnrichedNews:
    value: EnrichedNews
    asof_ts: float
    stale: bool


@dataclass(slots=True, frozen=True)
class MarketRegimeContext:
    regime: MarketRegime
    vix_level: float | None = None
    sector_breadth: float = 0.5


@dataclass(slots=True, frozen=True)
class SmcMeta:
    symbol: str
    timeframe: str
    asof_ts: float
    volume: TimedVolumeInfo
    technical: TimedDirectionalStrength | None = None
    news: TimedDirectionalStrength | None = None
    event_risk: EventRisk | None = None
    enriched_news: list[TimedEnrichedNews] = field(default_factory=list)
    market_regime: MarketRegimeContext | None = None
    provenance: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class BosEvent:
    id: str
    time: float
    price: float
    kind: BosEventKind
    dir: BosDir


@dataclass(slots=True, frozen=True)
class Orderblock:
    id: str
    low: float
    high: float
    dir: ObDir
    valid: bool


@dataclass(slots=True, frozen=True)
class Fvg:
    id: str
    low: float
    high: float
    dir: FvgDir
    valid: bool


@dataclass(slots=True, frozen=True)
class LiquiditySweep:
    id: str
    time: float
    price: float
    side: SweepSide


@dataclass(slots=True, frozen=True)
class SmcStructure:
    bos: list[BosEvent] = field(default_factory=list)
    orderblocks: list[Orderblock] = field(default_factory=list)
    fvg: list[Fvg] = field(default_factory=list)
    liquidity_sweeps: list[LiquiditySweep] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class ZoneStyle:
    opacity: float
    line_width: float
    render_state: Literal["NORMAL", "DIMMED", "HIDDEN"]
    trade_state: Literal["ALLOWED", "DISCOURAGED", "BLOCKED"]
    bias: Literal["LONG", "SHORT", "NEUTRAL"]
    strength: float
    heat: float
    tone: Literal["BULLISH", "BEARISH", "NEUTRAL", "WARNING"]
    emphasis: Literal["LOW", "MEDIUM", "HIGH"]
    reason_codes: list[ReasonCode] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SmcLayered:
    zone_styles: dict[str, ZoneStyle] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class SmcSnapshot:
    symbol: str
    timeframe: str
    generated_at: float
    schema_version: str
    structure: SmcStructure
    meta: SmcMeta
    layered: SmcLayered


@dataclass(slots=True, frozen=True)
class BaseLayerSignals:
    global_heat: float
    global_strength: float
    base_reasons: list[ReasonCode] = field(default_factory=list)