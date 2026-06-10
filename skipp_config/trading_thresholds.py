"""Versioned trading threshold configuration.

The defaults mirror the pre-M15 inline literals. Runtime callers can override
them by setting ``SKIPP_TRADING_THRESHOLDS_CONFIG`` to a JSON file with this
shape::

    {
      "schema_version": "trading-thresholds/v1",
      "open_prep_scorer": {"rvol_cap": 8.0},
      "smc_scoring": {"platt_l2_penalty": 0.02}
    }
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields, is_dataclass, replace
from pathlib import Path
from typing import Any, TypeVar, get_args, get_origin, get_type_hints

CONFIG_VERSION = "trading-thresholds/v1"
CONFIG_ENV_VAR = "SKIPP_TRADING_THRESHOLDS_CONFIG"


@dataclass(frozen=True, slots=True)
class LongDipThresholds:
    entry_early_dip_max_seconds: int = 10
    entry_early_dip_min_pct: float = -1.0
    entry_open30_volume_min: float = 0.0
    entry_reclaim_max_seconds: int = 30
    top_n: int = 5
    min_gap_pct: float = 0.0
    max_gap_pct: float = 40.0
    min_previous_close: float = 0.0
    min_premarket_dollar_volume: float = 0.0
    min_premarket_volume: int = 0
    min_premarket_trade_count: int = 0
    sparse_min_premarket_active_seconds: int = 30
    early_min_premarket_active_seconds: int = 45
    building_min_premarket_active_seconds: int = 60
    min_premarket_active_seconds: int = 90
    position_budget_usd: float = 10_000.0


@dataclass(frozen=True, slots=True)
class OpenPrepScorerThresholds:
    risk_off_extreme_threshold: float = -0.75
    gap_cap_abs: float = 10.0
    rvol_cap: float = 10.0
    freshness_half_life_seconds: float = 600.0
    premarket_spread_max_bps: float = 200.0
    min_average_volume: float = 100_000.0
    score_component_cap_fraction: float = 0.40
    counter_trend_momentum_z: float = -2.5
    counter_trend_max_penalty: float = 0.40
    counter_trend_penalty_slope: float = 0.20
    low_tier_news_rumor_penalty: float = 0.75
    low_tier_news_penalty_threshold: float = 0.5
    news_source_tier_multipliers: dict[str, float] | None = None
    low_tier_news_penalty_tiers: tuple[str, ...] = ("TIER_3", "TIER_4")

    def __post_init__(self) -> None:
        if self.news_source_tier_multipliers is None:
            object.__setattr__(
                self,
                "news_source_tier_multipliers",
                {
                    "TIER_1": 1.00,
                    "TIER_2": 0.70,
                    "TIER_3": 0.30,
                    "TIER_4": 0.10,
                },
            )


@dataclass(frozen=True, slots=True)
class OpenPrepPlaybookThresholds:
    min_gap_for_go: float = 1.0
    min_rvol_for_go: float = 1.5
    min_ext_score_for_go: float = 0.7
    fade_gap_overdone: float = 5.0
    fade_max_ext_score: float = 0.3
    drift_min_materiality: str = "MEDIUM"
    max_spread_bps_for_trade: float = 150.0
    caution_spread_bps: float = 60.0
    min_daily_dollar_volume_poor: float = 500_000.0
    min_daily_dollar_volume_caution: float = 1_000_000.0
    min_average_volume_poor: float = 50_000.0
    min_average_volume_caution: float = 100_000.0


@dataclass(frozen=True, slots=True)
class SmcScoringThresholds:
    calibration_bin_count: int = 10
    min_platt_events: int = 20
    beta_prior_alpha: float = 1.0
    beta_prior_beta: float = 1.0
    platt_feature_spread_abs_tol: float = 1e-6
    platt_l2_penalty: float = 0.01
    platt_max_iterations: int = 600
    platt_initial_learning_rate: float = 0.5
    platt_min_learning_rate: float = 1e-5
    platt_loss_tolerance: float = 1e-9
    platt_acceptance_tolerance: float = 1e-10
    sweep_reversal_threshold_pct: float = 0.005
    bos_follow_through_threshold_pct: float = 0.003


@dataclass(frozen=True, slots=True)
class TradingThresholds:
    schema_version: str = CONFIG_VERSION
    long_dip: LongDipThresholds = LongDipThresholds()
    open_prep_scorer: OpenPrepScorerThresholds = OpenPrepScorerThresholds()
    open_prep_playbook: OpenPrepPlaybookThresholds = OpenPrepPlaybookThresholds()
    smc_scoring: SmcScoringThresholds = SmcScoringThresholds()


T = TypeVar("T")


def _as_plain_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Trading thresholds config must be a JSON object")
    return dict(value)


def _coerce_value(expected: Any, value: Any, path: str) -> Any:
    origin = get_origin(expected)
    args = get_args(expected)
    if origin is dict:
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object")
        return {str(k): float(v) for k, v in value.items()}
    if origin in {tuple, list}:
        if not isinstance(value, list | tuple):
            raise ValueError(f"{path} must be a list")
        return tuple(str(item) for item in value)
    if origin is not None and type(None) in args:
        non_none = next(arg for arg in args if arg is not type(None))
        return _coerce_value(non_none, value, path)
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError(f"{path} must be boolean")
        return value
    if expected is int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{path} must be an integer")
        return value
    if expected is float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ValueError(f"{path} must be numeric")
        return float(value)
    if expected is str:
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string")
        return value
    return value


def _merge_dataclass(default: T, override: dict[str, Any], path: str) -> T:
    if not is_dataclass(default):
        raise TypeError(f"{path} is not a dataclass")
    known_fields = {item.name: item for item in fields(default)}
    type_hints = get_type_hints(type(default))
    unknown = set(override) - set(known_fields)
    if unknown:
        raise ValueError(f"Unknown trading threshold key(s) at {path}: {sorted(unknown)}")

    updates: dict[str, Any] = {}
    for key, raw_value in override.items():
        field_info = known_fields[key]
        current_value = object.__getattribute__(default, key)
        if is_dataclass(current_value):
            updates[key] = _merge_dataclass(
                current_value,
                _as_plain_mapping(raw_value),
                f"{path}.{key}",
            )
        else:
            coerced_value = _coerce_value(type_hints.get(key, field_info.type), raw_value, f"{path}.{key}")
            if isinstance(current_value, dict) and isinstance(coerced_value, dict):
                updates[key] = {**current_value, **coerced_value}
            else:
                updates[key] = coerced_value
    merged = replace(default, **updates)
    _validate_dataclass(merged, path)
    return merged


def _validate_positive(name: str, value: int | float, *, allow_zero: bool = False) -> None:
    if allow_zero:
        valid = value >= 0
    else:
        valid = value > 0
    if not valid:
        comparator = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{name} must be {comparator}")


def _validate_fraction(name: str, value: float) -> None:
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0")


def _validate_dataclass(config: Any, path: str) -> None:
    if isinstance(config, LongDipThresholds):
        _validate_positive(f"{path}.top_n", config.top_n)
        _validate_positive(f"{path}.max_gap_pct", config.max_gap_pct)
        if config.min_gap_pct > config.max_gap_pct:
            raise ValueError(f"{path}.min_gap_pct must be <= max_gap_pct")
        for field_name in (
            "min_previous_close",
            "min_premarket_dollar_volume",
            "min_premarket_volume",
            "min_premarket_trade_count",
            "sparse_min_premarket_active_seconds",
            "early_min_premarket_active_seconds",
            "building_min_premarket_active_seconds",
            "min_premarket_active_seconds",
            "position_budget_usd",
        ):
            _validate_positive(
                f"{path}.{field_name}",
                object.__getattribute__(config, field_name),
                allow_zero=True,
            )
        if not (
            config.sparse_min_premarket_active_seconds
            <= config.early_min_premarket_active_seconds
            <= config.building_min_premarket_active_seconds
            <= config.min_premarket_active_seconds
        ):
            raise ValueError(f"{path} premarket active-second thresholds must be monotonic")
    elif isinstance(config, OpenPrepScorerThresholds):
        _validate_positive(f"{path}.gap_cap_abs", config.gap_cap_abs)
        _validate_positive(f"{path}.rvol_cap", config.rvol_cap)
        _validate_positive(f"{path}.freshness_half_life_seconds", config.freshness_half_life_seconds)
        _validate_positive(f"{path}.premarket_spread_max_bps", config.premarket_spread_max_bps, allow_zero=True)
        _validate_positive(f"{path}.min_average_volume", config.min_average_volume, allow_zero=True)
        _validate_fraction(f"{path}.score_component_cap_fraction", config.score_component_cap_fraction)
        _validate_fraction(f"{path}.counter_trend_max_penalty", config.counter_trend_max_penalty)
        _validate_positive(f"{path}.counter_trend_penalty_slope", config.counter_trend_penalty_slope, allow_zero=True)
        _validate_fraction(f"{path}.low_tier_news_rumor_penalty", config.low_tier_news_rumor_penalty)
        _validate_fraction(f"{path}.low_tier_news_penalty_threshold", config.low_tier_news_penalty_threshold)
        multipliers = config.news_source_tier_multipliers or {}
        for tier, multiplier in multipliers.items():
            _validate_fraction(f"{path}.news_source_tier_multipliers.{tier}", multiplier)
    elif isinstance(config, OpenPrepPlaybookThresholds):
        for field_name in fields(config):
            value = object.__getattribute__(config, field_name.name)
            if isinstance(value, int | float):
                _validate_positive(f"{path}.{field_name.name}", value, allow_zero=True)
    elif isinstance(config, SmcScoringThresholds):
        _validate_positive(f"{path}.calibration_bin_count", config.calibration_bin_count)
        _validate_positive(f"{path}.min_platt_events", config.min_platt_events)
        _validate_positive(f"{path}.beta_prior_alpha", config.beta_prior_alpha)
        _validate_positive(f"{path}.beta_prior_beta", config.beta_prior_beta)
        _validate_positive(f"{path}.platt_feature_spread_abs_tol", config.platt_feature_spread_abs_tol)
        _validate_positive(f"{path}.platt_l2_penalty", config.platt_l2_penalty, allow_zero=True)
        _validate_positive(f"{path}.platt_max_iterations", config.platt_max_iterations)
        _validate_positive(f"{path}.platt_initial_learning_rate", config.platt_initial_learning_rate)
        _validate_positive(f"{path}.platt_min_learning_rate", config.platt_min_learning_rate)
        _validate_positive(f"{path}.platt_loss_tolerance", config.platt_loss_tolerance)
        _validate_positive(f"{path}.platt_acceptance_tolerance", config.platt_acceptance_tolerance)
        _validate_positive(f"{path}.sweep_reversal_threshold_pct", config.sweep_reversal_threshold_pct)
        _validate_positive(f"{path}.bos_follow_through_threshold_pct", config.bos_follow_through_threshold_pct)
    elif isinstance(config, TradingThresholds):
        if config.schema_version != CONFIG_VERSION:
            raise ValueError(
                f"Unsupported trading threshold schema_version {config.schema_version!r}; expected {CONFIG_VERSION!r}"
            )
        for field_name in ("long_dip", "open_prep_scorer", "open_prep_playbook", "smc_scoring"):
            _validate_dataclass(object.__getattribute__(config, field_name), f"{path}.{field_name}")


def load_trading_thresholds(path: str | Path | None = None) -> TradingThresholds:
    """Load and validate threshold overrides, preserving default parity."""
    resolved_path = Path(path) if path is not None else None
    if resolved_path is None:
        env_path = os.getenv(CONFIG_ENV_VAR)
        if not env_path:
            return TradingThresholds()
        resolved_path = Path(env_path)

    with resolved_path.open(encoding="utf-8") as handle:
        raw = _as_plain_mapping(json.load(handle))

    default = TradingThresholds()
    schema_version = raw.pop("schema_version", default.schema_version)
    merged = _merge_dataclass(
        replace(default, schema_version=schema_version),
        raw,
        "trading_thresholds",
    )
    _validate_dataclass(merged, "trading_thresholds")
    return merged


def get_trading_thresholds(path: str | Path | None = None) -> TradingThresholds:
    """Return the validated trading threshold config for this process."""
    return load_trading_thresholds(path)


def trading_thresholds_to_dict(config: TradingThresholds | None = None) -> dict[str, Any]:
    """Serialize the threshold config for artifacts/tests."""
    return asdict(config or get_trading_thresholds())
