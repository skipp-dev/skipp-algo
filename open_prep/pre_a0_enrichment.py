"""Fail-closed PRE-A0 enrichment and ablation contracts.

Provider adapters may populate these records, but no enrichment can confirm A0
or bypass the timestamp and promotion gates defined here.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from enum import StrEnum


class EnrichmentFamily(StrEnum):
    VOLUME_PROFILE = "volume_profile"
    MICROSTRUCTURE = "microstructure"
    NEWS = "news"
    OPENING_AUCTION = "opening_auction"
    OPTIONS_FLOW = "options_flow"
    DEEP_LEARNING = "deep_learning"


@dataclass(frozen=True, slots=True)
class TimedFeature:
    family: EnrichmentFamily
    name: str
    value: float
    event_time: float
    receive_time: float
    source: str

    def validate_for(self, prediction_time: float) -> None:
        if self.event_time > prediction_time or self.receive_time > prediction_time:
            raise ValueError("enrichment contains future information")


@dataclass(frozen=True, slots=True)
class VolumeProfile:
    profile_id: str
    as_of_session: str
    fractions_by_minute: tuple[tuple[int, float], ...]
    liquidity_class: str | None = None
    weekday: int | None = None

    def expected_fraction(self, minute_from_open: int, *, session_date: str) -> float:
        if self.as_of_session >= session_date:
            raise ValueError("volume profile is not strictly historical")
        curve = dict(self.fractions_by_minute)
        eligible = [minute for minute in curve if minute <= minute_from_open]
        if not eligible:
            raise ValueError("profile does not cover requested minute")
        value = curve[max(eligible)]
        if not 0 < value <= 1:
            raise ValueError("invalid cumulative volume fraction")
        return value


@dataclass(frozen=True, slots=True)
class MicrostructureSample:
    symbol: str
    event_time: float
    receive_time: float
    bid: float
    ask: float
    bid_size: float
    ask_size: float
    aggressive_buy_rate: float
    aggressive_sell_rate: float
    event_rate: float


def microstructure_features(sample: MicrostructureSample, *, prediction_time: float) -> tuple[TimedFeature, ...]:
    if sample.event_time > prediction_time or sample.receive_time > prediction_time:
        raise ValueError("microstructure sample is from the future")
    if sample.ask < sample.bid or min(sample.bid_size, sample.ask_size) < 0:
        raise ValueError("invalid BBO")
    depth = sample.bid_size + sample.ask_size
    imbalance = (sample.bid_size - sample.ask_size) / depth if depth else 0.0
    microprice = (
        (sample.ask * sample.bid_size + sample.bid * sample.ask_size) / depth
        if depth
        else (sample.bid + sample.ask) / 2
    )
    flow = sample.aggressive_buy_rate - sample.aggressive_sell_rate
    values = {
        "spread": sample.ask - sample.bid,
        "size_imbalance": imbalance,
        "microprice": microprice,
        "order_flow_imbalance": flow,
        "event_rate": sample.event_rate,
    }
    return tuple(
        TimedFeature(EnrichmentFamily.MICROSTRUCTURE, name, value, sample.event_time, sample.receive_time, "bbo")
        for name, value in values.items()
    )


class WarmSet:
    """Bounded, LRU-like symbol set for expensive event data."""

    def __init__(self, *, max_symbols: int = 250, ttl_s: float = 300) -> None:
        if max_symbols <= 0 or ttl_s <= 0:
            raise ValueError("warm-set limits must be positive")
        self.max_symbols = max_symbols
        self.ttl_s = ttl_s
        self._symbols: OrderedDict[str, float] = OrderedDict()

    def touch(self, symbol: str, *, now: float) -> tuple[str, ...]:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be empty")
        self.expire(now=now)
        self._symbols.pop(normalized, None)
        self._symbols[normalized] = now
        evicted: list[str] = []
        while len(self._symbols) > self.max_symbols:
            evicted.append(self._symbols.popitem(last=False)[0])
        return tuple(evicted)

    def expire(self, *, now: float) -> tuple[str, ...]:
        expired = [symbol for symbol, touched in self._symbols.items() if now - touched > self.ttl_s]
        for symbol in expired:
            self._symbols.pop(symbol, None)
        return tuple(expired)

    def contains(self, symbol: str) -> bool:
        return symbol.strip().upper() in self._symbols


@dataclass(frozen=True, slots=True)
class CatalystEvent:
    event_id: str
    symbol: str
    event_time: float
    receive_time: float
    relevance: float
    source: str

    def as_feature(self, *, prediction_time: float) -> TimedFeature:
        feature = TimedFeature(
            EnrichmentFamily.NEWS,
            "news_relevance",
            self.relevance,
            self.event_time,
            self.receive_time,
            self.source,
        )
        feature.validate_for(prediction_time)
        return feature


@dataclass(frozen=True, slots=True)
class AuctionSample:
    event_time: float
    receive_time: float
    indicative_price: float
    paired_quantity: float
    net_imbalance: float

    def features(self, *, prediction_time: float, opening_window: bool) -> tuple[TimedFeature, ...]:
        if not opening_window:
            raise ValueError("auction features are isolated to the opening model")
        rows = (
            TimedFeature(EnrichmentFamily.OPENING_AUCTION, "indicative_price", self.indicative_price, self.event_time, self.receive_time, "auction"),
            TimedFeature(EnrichmentFamily.OPENING_AUCTION, "paired_quantity", self.paired_quantity, self.event_time, self.receive_time, "auction"),
            TimedFeature(EnrichmentFamily.OPENING_AUCTION, "net_imbalance", self.net_imbalance, self.event_time, self.receive_time, "auction"),
        )
        for row in rows:
            row.validate_for(prediction_time)
        return rows


@dataclass(frozen=True, slots=True)
class AblationMetrics:
    pr_auc: float
    brier: float
    ece: float
    mean_lead_s: float
    missing_fraction: float
    stable_slices_fraction: float


@dataclass(frozen=True, slots=True)
class AblationDecision:
    family: EnrichmentFamily
    promote: bool
    reasons: tuple[str, ...]


def evaluate_ablation(
    family: EnrichmentFamily,
    baseline: AblationMetrics,
    candidate: AblationMetrics,
    *,
    max_missing_fraction: float = 0.10,
) -> AblationDecision:
    reasons: list[str] = []
    if candidate.pr_auc <= baseline.pr_auc:
        reasons.append("no_pr_auc_gain")
    if candidate.brier >= baseline.brier:
        reasons.append("no_brier_gain")
    if candidate.ece > baseline.ece:
        reasons.append("calibration_regression")
    if candidate.mean_lead_s < baseline.mean_lead_s:
        reasons.append("lead_regression")
    if candidate.missing_fraction > max_missing_fraction:
        reasons.append("missingness_budget_exceeded")
    if candidate.stable_slices_fraction < 0.8:
        reasons.append("slice_instability")
    return AblationDecision(family, not reasons, tuple(reasons))


def decide_advanced_workstream(
    *, remaining_error_cluster: bool, sufficient_samples: bool, justified_cost: bool
) -> dict[str, object]:
    proceed = remaining_error_cluster and sufficient_samples and justified_cost
    return {
        "options_flow": proceed,
        "deep_learning": proceed,
        "decision": "evaluate" if proceed else "stop",
        "reason": None if proceed else "incremental_value_not_yet_justified",
    }
