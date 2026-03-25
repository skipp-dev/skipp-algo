from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.generate_smc_micro_profiles import (
    _safe_bool,
    add_bucket_features,
    assess_csv_against_schema,
    apply_candidate_rules,
    build_lists_from_state,
    coerce_input_frame,
    load_schema,
    run_generation,
    shard_csv_string,
    update_membership_state,
    validate_schema,
    write_readiness_report,
)


SCHEMA_PATH = "schema/schema.json"


def _base_rows() -> list[dict[str, object]]:
    return [
        {
            "asof_date": "2026-03-23",
            "symbol": "AAA",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "universe_bucket": "test_bucket",
            "history_coverage_days_20d": 20,
            "adv_dollar_rth_20d": 150_000_000.0,
            "avg_spread_bps_rth_20d": 1.2,
            "rth_active_minutes_share_20d": 0.95,
            "open_30m_dollar_share_20d": 0.20,
            "close_60m_dollar_share_20d": 0.22,
            "clean_intraday_score_20d": 0.92,
            "consistency_score_20d": 0.90,
            "close_hygiene_20d": 0.91,
            "wickiness_20d": 0.10,
            "pm_dollar_share_20d": 0.15,
            "pm_trades_share_20d": 0.14,
            "pm_active_minutes_share_20d": 0.20,
            "pm_spread_bps_20d": 3.0,
            "pm_wickiness_20d": 0.12,
            "midday_dollar_share_20d": 0.24,
            "midday_trades_share_20d": 0.23,
            "midday_active_minutes_share_20d": 0.25,
            "midday_spread_bps_20d": 2.0,
            "midday_efficiency_20d": 0.80,
            "ah_dollar_share_20d": 0.12,
            "ah_trades_share_20d": 0.11,
            "ah_active_minutes_share_20d": 0.14,
            "ah_spread_bps_20d": 3.0,
            "ah_wickiness_20d": 0.10,
            "reclaim_respect_rate_20d": 0.90,
            "reclaim_failure_rate_20d": 0.08,
            "reclaim_followthrough_r_20d": 1.60,
            "ob_sweep_reversal_rate_20d": 0.25,
            "ob_sweep_depth_p75_20d": 0.30,
            "fvg_sweep_reversal_rate_20d": 0.20,
            "fvg_sweep_depth_p75_20d": 0.28,
            "stop_hunt_rate_20d": 0.10,
            "setup_decay_half_life_bars_20d": 30.0,
            "early_vs_late_followthrough_ratio_20d": 0.90,
            "stale_fail_rate_20d": 0.10,
        },
        {
            "asof_date": "2026-03-23",
            "symbol": "BBB",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "universe_bucket": "test_bucket",
            "history_coverage_days_20d": 20,
            "adv_dollar_rth_20d": 120_000_000.0,
            "avg_spread_bps_rth_20d": 4.0,
            "rth_active_minutes_share_20d": 0.93,
            "open_30m_dollar_share_20d": 0.34,
            "close_60m_dollar_share_20d": 0.18,
            "clean_intraday_score_20d": 0.42,
            "consistency_score_20d": 0.40,
            "close_hygiene_20d": 0.43,
            "wickiness_20d": 0.92,
            "pm_dollar_share_20d": 0.10,
            "pm_trades_share_20d": 0.10,
            "pm_active_minutes_share_20d": 0.10,
            "pm_spread_bps_20d": 7.0,
            "pm_wickiness_20d": 0.35,
            "midday_dollar_share_20d": 0.12,
            "midday_trades_share_20d": 0.12,
            "midday_active_minutes_share_20d": 0.14,
            "midday_spread_bps_20d": 5.0,
            "midday_efficiency_20d": 0.36,
            "ah_dollar_share_20d": 0.10,
            "ah_trades_share_20d": 0.09,
            "ah_active_minutes_share_20d": 0.10,
            "ah_spread_bps_20d": 7.0,
            "ah_wickiness_20d": 0.40,
            "reclaim_respect_rate_20d": 0.35,
            "reclaim_failure_rate_20d": 0.30,
            "reclaim_followthrough_r_20d": 0.55,
            "ob_sweep_reversal_rate_20d": 0.90,
            "ob_sweep_depth_p75_20d": 0.88,
            "fvg_sweep_reversal_rate_20d": 0.84,
            "fvg_sweep_depth_p75_20d": 0.82,
            "stop_hunt_rate_20d": 0.92,
            "setup_decay_half_life_bars_20d": 5.0,
            "early_vs_late_followthrough_ratio_20d": 1.90,
            "stale_fail_rate_20d": 0.82,
        },
        {
            "asof_date": "2026-03-23",
            "symbol": "CCC",
            "exchange": "NASDAQ",
            "asset_type": "stock",
            "universe_bucket": "test_bucket",
            "history_coverage_days_20d": 20,
            "adv_dollar_rth_20d": 100_000_000.0,
            "avg_spread_bps_rth_20d": 1.7,
            "rth_active_minutes_share_20d": 0.94,
            "open_30m_dollar_share_20d": 0.36,
            "close_60m_dollar_share_20d": 0.21,
            "clean_intraday_score_20d": 0.84,
            "consistency_score_20d": 0.76,
            "close_hygiene_20d": 0.79,
            "wickiness_20d": 0.20,
            "pm_dollar_share_20d": 0.01,
            "pm_trades_share_20d": 0.01,
            "pm_active_minutes_share_20d": 0.02,
            "pm_spread_bps_20d": 12.0,
            "pm_wickiness_20d": 0.16,
            "midday_dollar_share_20d": 0.04,
            "midday_trades_share_20d": 0.03,
            "midday_active_minutes_share_20d": 0.05,
            "midday_spread_bps_20d": 8.0,
            "midday_efficiency_20d": 0.18,
            "ah_dollar_share_20d": 0.01,
            "ah_trades_share_20d": 0.01,
            "ah_active_minutes_share_20d": 0.02,
            "ah_spread_bps_20d": 12.0,
            "ah_wickiness_20d": 0.12,
            "reclaim_respect_rate_20d": 0.78,
            "reclaim_failure_rate_20d": 0.12,
            "reclaim_followthrough_r_20d": 1.10,
            "ob_sweep_reversal_rate_20d": 0.35,
            "ob_sweep_depth_p75_20d": 0.36,
            "fvg_sweep_reversal_rate_20d": 0.30,
            "fvg_sweep_depth_p75_20d": 0.32,
            "stop_hunt_rate_20d": 0.20,
            "setup_decay_half_life_bars_20d": 22.0,
            "early_vs_late_followthrough_ratio_20d": 1.20,
            "stale_fail_rate_20d": 0.22,
        },
    ]


def test_validate_schema_rejects_duplicate_primary_keys() -> None:
    schema = load_schema(Path(SCHEMA_PATH))
    df = pd.DataFrame(_base_rows())
    duplicate = pd.concat([df, df.iloc[[0]]], ignore_index=True)

    with pytest.raises(RuntimeError, match="Duplicate primary keys"):
        validate_schema(coerce_input_frame(duplicate), schema)


def test_update_membership_state_bootstraps_first_snapshot() -> None:
    schema = load_schema(Path(SCHEMA_PATH))
    df = apply_candidate_rules(add_bucket_features(coerce_input_frame(pd.DataFrame(_base_rows())), schema), schema)
    state = update_membership_state(df, pd.DataFrame(), "2026-03-23", schema)
    lists = build_lists_from_state(state)

    assert lists["clean_reclaim"] == ["AAA"]
    assert lists["stop_hunt_prone"] == ["BBB"]
    assert lists["fast_decay"] == ["BBB"]
    assert lists["midday_dead"] == ["CCC"]
    assert lists["rth_only"] == ["CCC"]
    assert lists["weak_premarket"] == ["CCC"]
    assert lists["weak_afterhours"] == ["CCC"]


def test_safe_bool_rejects_false_like_strings() -> None:
    assert _safe_bool("0") is False
    assert _safe_bool("False") is False
    assert _safe_bool("") is False
    assert _safe_bool("true") is True


def test_update_membership_state_uses_remove_threshold_for_active_rows() -> None:
    schema = load_schema(Path(SCHEMA_PATH))
    df = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "clean_reclaim_score": 0.62,
                "stop_hunt_score": 0.0,
                "midday_dead_score": 0.0,
                "rth_only_score": 0.0,
                "weak_premarket_score": 0.0,
                "weak_afterhours_score": 0.0,
                "fast_decay_score": 0.0,
                "cand_clean_reclaim": False,
                "cand_stop_hunt_prone": False,
                "cand_midday_dead": False,
                "cand_rth_only": False,
                "cand_weak_premarket": False,
                "cand_weak_afterhours": False,
                "cand_fast_decay": False,
            }
        ]
    )
    previous_state = pd.DataFrame(
        [
            {
                "symbol": "AAA",
                "list_name": "clean_reclaim",
                "is_active": "1",
                "active_since": "2026-03-10",
                "add_streak": 0,
                "remove_streak": 2,
                "last_score": 0.9,
                "last_run_date": "2026-03-22",
                "candidate_active": 1,
                "decision_source": "generator",
                "decision_reason": "retained",
            }
        ]
    )

    updated = update_membership_state(df, previous_state, "2026-03-23", schema)
    row = updated.loc[updated["list_name"] == "clean_reclaim"].iloc[0]

    assert row["is_active"] == 1
    assert row["remove_streak"] == 0
    assert row["candidate_active"] == 1
    assert row["decision_reason"] == "retained by remove threshold"


def test_run_generation_writes_expected_outputs(tmp_path) -> None:
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(Path(SCHEMA_PATH).read_text(encoding="utf-8"), encoding="utf-8")

    input_path = tmp_path / "snapshot.csv"
    pd.DataFrame(_base_rows()).to_csv(input_path, index=False)

    overrides_path = tmp_path / "overrides.csv"
    overrides_path.write_text("asof_date,symbol,list_name,action,reason\n", encoding="utf-8")

    outputs = run_generation(
        schema_path=schema_path,
        input_path=input_path,
        overrides_path=overrides_path,
        output_root=tmp_path,
    )

    pine_source = outputs["pine_path"].read_text(encoding="utf-8")
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    lists_csv = pd.read_csv(outputs["lists_path"])
    diff_report = outputs["diff_report_path"].read_text(encoding="utf-8")
    snippet = outputs["core_import_snippet_path"].read_text(encoding="utf-8")

    assert 'library("smc_micro_profiles_generated")' in pine_source
    assert 'export const string CLEAN_RECLAIM_TICKERS = "AAA"' in pine_source
    assert 'export const string STOP_HUNT_PRONE_TICKERS = "BBB"' in pine_source
    assert 'export const string RTH_ONLY_TICKERS = "CCC"' in pine_source
    assert manifest["universe_size"] == 3
    assert manifest["list_counts"]["weak_afterhours"] == 1
    assert manifest["recommended_import_path"] == "preuss_steffen/smc_micro_profiles_generated/1"
    assert manifest["core_import_snippet"].endswith("pine/generated/smc_micro_profiles_core_import_snippet.pine")
    assert "import preuss_steffen/smc_micro_profiles_generated/1 as mp" in snippet
    assert set(lists_csv["list_name"]) == {
        "clean_reclaim",
        "stop_hunt_prone",
        "midday_dead",
        "rth_only",
        "weak_premarket",
        "weak_afterhours",
        "fast_decay",
    }
    assert {"decision_source", "decision_reason"}.issubset(lists_csv.columns)
    assert "### Added details" in diff_report
    assert "| AAA | generator | bootstrap activation on first snapshot |" in diff_report


def test_shard_csv_string_respects_max_chars() -> None:
    chunks = shard_csv_string(["AAAA", "BBBB", "CCCC"], max_chars=9)

    assert chunks == ["AAAA,BBBB", "CCCC"]


def test_assess_csv_against_schema_reports_missing_columns(tmp_path) -> None:
    schema = load_schema(Path(SCHEMA_PATH))
    candidate = tmp_path / "candidate.csv"
    candidate.write_text("symbol,exchange,asset_type,premarket_volume\nABC,NASDAQ,stock,1000\n", encoding="utf-8")

    assessment = assess_csv_against_schema(schema, candidate)
    report_path = tmp_path / "readiness.md"
    write_readiness_report(report_path, assessment)
    report = report_path.read_text(encoding="utf-8")

    assert assessment["required_coverage"] > 0
    assert "symbol" in assessment["present_required"]
    assert "asof_date" in assessment["missing_required"]
    assert "premarket_volume" in assessment["extra_columns"]
    assert "## Missing required columns" in report
    assert "- asof_date" in report