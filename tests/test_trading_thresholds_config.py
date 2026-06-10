from __future__ import annotations

import json

import pytest

from skipp_config.trading_thresholds import (
    CONFIG_VERSION,
    TradingThresholds,
    load_trading_thresholds,
    trading_thresholds_to_dict,
)


def test_trading_threshold_defaults_match_legacy_public_constants() -> None:
    config = TradingThresholds()

    assert config.schema_version == CONFIG_VERSION
    assert config.long_dip.top_n == 5
    assert config.long_dip.max_gap_pct == 40.0
    assert config.open_prep_scorer.gap_cap_abs == 10.0
    assert config.open_prep_scorer.rvol_cap == 10.0
    assert config.open_prep_scorer.score_component_cap_fraction == 0.40
    assert config.open_prep_playbook.max_spread_bps_for_trade == 150.0
    assert config.smc_scoring.min_platt_events == 20
    assert config.smc_scoring.platt_l2_penalty == 0.01
    assert config.smc_scoring.sweep_reversal_threshold_pct == 0.005
    assert config.smc_scoring.bos_follow_through_threshold_pct == 0.003


def test_load_trading_thresholds_merges_valid_json_override(tmp_path) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": CONFIG_VERSION,
                "long_dip": {"top_n": 7},
                "open_prep_scorer": {
                    "rvol_cap": 8.0,
                    "news_source_tier_multipliers": {"TIER_1": 1.0, "TIER_4": 0.05},
                },
                "smc_scoring": {"platt_l2_penalty": 0.02},
            }
        ),
        encoding="utf-8",
    )

    config = load_trading_thresholds(path)

    assert config.long_dip.top_n == 7
    assert config.long_dip.max_gap_pct == 40.0
    assert config.open_prep_scorer.rvol_cap == 8.0
    assert config.open_prep_scorer.news_source_tier_multipliers == {
        "TIER_1": 1.0,
        "TIER_2": 0.70,
        "TIER_3": 0.30,
        "TIER_4": 0.05,
    }
    assert config.smc_scoring.platt_l2_penalty == 0.02


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"schema_version": "trading-thresholds/v0"}, "Unsupported trading threshold schema_version"),
        ({"open_prep_scorer": {"unknown": 1}}, "Unknown trading threshold key"),
        ({"open_prep_scorer": {"rvol_cap": 0}}, "rvol_cap must be positive"),
        ({"long_dip": {"min_gap_pct": 50.0, "max_gap_pct": 40.0}}, "min_gap_pct must be <= max_gap_pct"),
        ({"smc_scoring": {"platt_l2_penalty": -0.01}}, "platt_l2_penalty must be non-negative"),
    ],
)
def test_load_trading_thresholds_rejects_invalid_json(tmp_path, payload, expected: str) -> None:
    path = tmp_path / "thresholds.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        load_trading_thresholds(path)


def test_threshold_config_serializes_for_artifacts() -> None:
    payload = trading_thresholds_to_dict(TradingThresholds())

    assert payload["schema_version"] == CONFIG_VERSION
    assert payload["open_prep_scorer"]["gap_cap_abs"] == 10.0
    assert payload["smc_scoring"]["platt_initial_learning_rate"] == 0.5
