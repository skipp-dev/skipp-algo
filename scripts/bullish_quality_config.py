from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import pandas as pd


DEFAULT_BULLISH_QUALITY_SCORE_PROFILE = "balanced"
BULLISH_QUALITY_SCORE_PROFILES: tuple[str, ...] = ("conservative", "balanced", "aggressive")


def normalize_bullish_quality_score_profile(
    score_profile: str | None,
    *,
    fallback: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE,
) -> str:
    normalized_fallback = str(fallback or DEFAULT_BULLISH_QUALITY_SCORE_PROFILE).strip().lower()
    if normalized_fallback not in BULLISH_QUALITY_SCORE_PROFILES:
        normalized_fallback = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE
    normalized = str(score_profile or normalized_fallback).strip().lower()
    if normalized in BULLISH_QUALITY_SCORE_PROFILES:
        return normalized
    return normalized_fallback


def build_bullish_quality_weights(score_profile: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE) -> dict[str, float]:
    normalized = normalize_bullish_quality_score_profile(score_profile)
    profiles: dict[str, dict[str, float]] = {
        "conservative": {
            "structure": 0.35,
            "stability": 0.25,
            "liquidity": 0.25,
            "extension": 0.15,
        },
        "balanced": {
            "structure": 0.45,
            "stability": 0.20,
            "liquidity": 0.20,
            "extension": 0.15,
        },
        "aggressive": {
            "structure": 0.55,
            "stability": 0.15,
            "liquidity": 0.15,
            "extension": 0.15,
        },
    }
    if normalized not in profiles or normalized != str(score_profile or DEFAULT_BULLISH_QUALITY_SCORE_PROFILE).strip().lower():
        raise ValueError(f"Unsupported bullish-quality score profile: {score_profile}")
    return dict(profiles[normalized])


@dataclass(frozen=True)
class PremarketWindowDefinition:
    tag: str
    start_time_et: str
    end_time_et: str
    label: str = ""


@dataclass(frozen=True)
class BullishQualityConfig:
    top_n: int = 5
    score_profile: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE
    min_previous_close: float = 5.0
    min_gap_pct: float = 0.0
    min_window_dollar_volume: float = 500_000.0
    min_window_trade_count: float = 60.0
    min_window_close_position_pct: float = 70.0
    min_window_return_pct: float = 0.0
    max_window_pullback_pct: float = 35.0
    require_close_above_vwap: bool = True
    weights: dict[str, float] = field(
        default_factory=lambda: build_bullish_quality_weights(DEFAULT_BULLISH_QUALITY_SCORE_PROFILE)
    )
    window_definitions: tuple[PremarketWindowDefinition, ...] = field(
        default_factory=lambda: build_default_premarket_window_definitions()
    )


@dataclass(frozen=True)
class BullishQualityScannerResult:
    generated_at: str
    trade_date: date | None
    source_data_fetched_at: str | None
    config_snapshot: dict[str, object]
    rankings_table: pd.DataFrame
    latest_window_table: pd.DataFrame
    filter_diagnostics_table: pd.DataFrame
    window_feature_table: pd.DataFrame
    warnings: list[str]


def build_default_premarket_window_definitions() -> tuple[PremarketWindowDefinition, ...]:
    return (
        PremarketWindowDefinition(tag="pm_0400_0500", start_time_et="04:00:00", end_time_et="05:00:00", label="04:00-05:00 ET"),
        PremarketWindowDefinition(tag="pm_0500_0600", start_time_et="05:00:00", end_time_et="06:00:00", label="05:00-06:00 ET"),
        PremarketWindowDefinition(tag="pm_0600_0700", start_time_et="06:00:00", end_time_et="07:00:00", label="06:00-07:00 ET"),
        PremarketWindowDefinition(tag="pm_0700_0800", start_time_et="07:00:00", end_time_et="08:00:00", label="07:00-08:00 ET"),
        PremarketWindowDefinition(tag="pm_0800_0900", start_time_et="08:00:00", end_time_et="09:00:00", label="08:00-09:00 ET"),
        PremarketWindowDefinition(tag="pm_0900_0930", start_time_et="09:00:00", end_time_et="09:30:00", label="09:00-09:30 ET"),
    )


def build_default_bullish_quality_config(*, score_profile: str = DEFAULT_BULLISH_QUALITY_SCORE_PROFILE) -> BullishQualityConfig:
    normalized = normalize_bullish_quality_score_profile(score_profile)
    if normalized != str(score_profile or DEFAULT_BULLISH_QUALITY_SCORE_PROFILE).strip().lower():
        raise ValueError(f"Unsupported bullish-quality score profile: {score_profile}")
    return BullishQualityConfig(
        score_profile=normalized,
        weights=build_bullish_quality_weights(normalized),
    )