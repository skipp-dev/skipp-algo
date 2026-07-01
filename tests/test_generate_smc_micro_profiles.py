from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.generate_smc_micro_profiles import (
    LISTS,
    _bucket_median,
    _bucket_quantile,
    _pine_float,
    _safe_bool,
    add_bucket_features,
    apply_candidate_rules,
    assess_csv_against_schema,
    build_lists_from_state,
    coerce_input_frame,
    load_schema,
    render_csv_export,
    run_generation,
    shard_csv_string,
    update_membership_state,
    validate_schema,
    write_pine_library,
    write_readiness_report,
)
from scripts.smc_enrichment_types import EnrichmentDict
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

SCHEMA_PATH = str(resolve_microstructure_schema_path())


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
    duplicate = pd.DataFrame([*df.to_dict("records"), dict(df.to_dict("records")[0])])

    with pytest.raises(RuntimeError, match="Duplicate primary keys"):
        validate_schema(coerce_input_frame(duplicate), schema)


def test_validate_schema_rejects_null_primary_key_values() -> None:
    schema = load_schema(Path(SCHEMA_PATH))
    df = pd.DataFrame(_base_rows())
    df.loc[0, "symbol"] = None

    with pytest.raises(RuntimeError, match="Primary key columns cannot contain null values"):
        validate_schema(coerce_input_frame(df), schema)


def test_bucket_stats_preserve_nan_for_missing_universe_bucket() -> None:
    df = pd.DataFrame(
        {
            "universe_bucket": ["bucket_a", None, None, "bucket_a"],
            "sample_metric": [1.0, 10.0, 20.0, 3.0],
        }
    )

    median = _bucket_median(df, "sample_metric")
    quantile = _bucket_quantile(df, "sample_metric", 0.5)

    assert median.tolist()[0] == pytest.approx(2.0)
    assert quantile.tolist()[0] == pytest.approx(2.0)
    assert pd.isna(median.tolist()[1])
    assert pd.isna(median.tolist()[2])
    assert pd.isna(quantile.tolist()[1])
    assert pd.isna(quantile.tolist()[2])


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
    row = next(record for record in updated.to_dict("records") if record["list_name"] == "clean_reclaim")

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
    # Normalise path separators before comparison: Windows uses backslashes
    # while the assertion was written for POSIX paths.
    assert manifest["core_import_snippet"].replace("\\", "/").endswith(
        "pine/generated/smc_micro_profiles_core_import_snippet.pine"
    )
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


def test_render_csv_export_preserves_chunk_boundaries() -> None:
    rendered = render_csv_export("TEST_EXPORT", ["AAAA", "BBBB", "CCCC"], max_chars=9)

    assert 'const string TEST_EXPORT_PART_1 = "AAAA,BBBB"' in rendered
    assert 'const string TEST_EXPORT_PART_2 = "CCCC"' in rendered
    assert 'export const string TEST_EXPORT = TEST_EXPORT_PART_1 + "," + TEST_EXPORT_PART_2' in rendered


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


# ── write_pine_library enrichment tests ─────────────────────────────

_EMPTY_LISTS: dict[str, list[str]] = {name: [] for name in LISTS}


def test_write_library_without_enrichment(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 100)
    text = out.read_text(encoding="utf-8")
    # Core fields present
    assert 'ASOF_DATE = "2026-03-28"' in text
    assert "UNIVERSE_SIZE = 100" in text
    # Enrichment defaults present
    assert 'MARKET_REGIME = "NEUTRAL"' in text
    assert "VIX_LEVEL = 0.0" in text
    assert 'NEWS_BULLISH_TICKERS = ""' in text
    assert "NEWS_HEAT_GLOBAL = 0.0" in text
    assert 'EARNINGS_TODAY_TICKERS = ""' in text
    assert "HIGH_IMPACT_MACRO_TODAY = false" in text
    assert "GLOBAL_HEAT = 0.0" in text
    assert 'TONE = "NEUTRAL"' in text
    assert 'TRADE_STATE = "ALLOWED"' in text
    assert "PROVIDER_COUNT = 0" in text
    assert 'VOLUME_LOW_TICKERS = ""' in text
    assert 'MARKET_PE_REGIME = "UNKNOWN"' in text
    assert 'VOLATILITY_REGIME = "NORMAL"' in text
    assert 'ENSEMBLE_QUALITY_TIER = "low"' in text


def test_write_library_with_full_enrichment(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {
        "regime": {
            "regime": "RISK_ON",
            "vix_level": 18.5,
            "macro_bias": 0.33,
            "macro_bias_raw": 0.35,
            "macro_bias_pe_adjustment": -0.02,
            "market_pe_forward": 27.4,
            "market_pe_regime": "EXPENSIVE",
            "sector_breadth": 0.72,
        },
        "news": {
            "bullish_tickers": ["AAPL", "MSFT"],
            "bearish_tickers": ["TSLA"],
            "neutral_tickers": ["GOOG"],
            "news_heat_global": 0.15,
            "ticker_heat_map": "AAPL:0.72,TSLA:-0.68",
        },
        "calendar": {
            "earnings_today_tickers": "AAPL",
            "earnings_tomorrow_tickers": "MSFT",
            "earnings_bmo_tickers": "AAPL",
            "earnings_amc_tickers": "",
            "high_impact_macro_today": True,
            "macro_event_name": "FOMC Minutes",
            "macro_event_time": "14:00 ET",
        },
        "layering": {"global_heat": 0.28, "global_strength": 0.45, "tone": "BULLISH", "trade_state": "ALLOWED"},
        "providers": {"provider_count": 4, "stale_providers": ""},
        "volume_regime": {"low_tickers": ["XYZ"], "holiday_suspect_tickers": ["ABC"]},
        "volatility_regime": {
            "label": "HIGH_VOL",
            "confidence": 0.84,
            "raw_atr_ratio": 1.66,
            "model_source": "atr_fallback",
            "fallback_reason": "arch_unavailable",
            "proxy_symbol": "AAPL",
            "proxy_source": "highest_adv_symbol",
        },
        "ensemble_quality": {
            "score": 0.64,
            "tier": "good",
            "available_components": ["bias", "heuristic", "vol_regime"],
        },
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 200, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    assert 'MARKET_REGIME = "RISK_ON"' in text
    assert "VIX_LEVEL = 18.5" in text
    assert "MACRO_BIAS = 0.33" in text
    assert "MACRO_BIAS_RAW = 0.35" in text
    assert "MACRO_BIAS_PE_ADJUSTMENT = -0.02" in text
    assert "MARKET_PE_FORWARD = 27.4" in text
    assert 'MARKET_PE_REGIME = "EXPENSIVE"' in text
    assert 'NEWS_BULLISH_TICKERS = "AAPL,MSFT"' in text
    assert 'NEWS_BEARISH_TICKERS = "TSLA"' in text
    assert "NEWS_HEAT_GLOBAL = 0.15" in text
    assert 'TICKER_HEAT_MAP = "AAPL:0.72,TSLA:-0.68"' in text
    assert 'EARNINGS_TODAY_TICKERS = "AAPL"' in text
    assert 'EARNINGS_TOMORROW_TICKERS = "MSFT"' in text
    assert "HIGH_IMPACT_MACRO_TODAY = true" in text
    assert 'MACRO_EVENT_NAME = "FOMC Minutes"' in text
    assert 'MACRO_EVENT_TIME = "14:00 ET"' in text
    assert "GLOBAL_HEAT = 0.28" in text
    assert "GLOBAL_STRENGTH = 0.45" in text
    assert 'TONE = "BULLISH"' in text
    assert "PROVIDER_COUNT = 4" in text
    assert 'VOLUME_LOW_TICKERS = "XYZ"' in text
    assert 'HOLIDAY_SUSPECT_TICKERS = "ABC"' in text
    assert 'VOLATILITY_REGIME = "HIGH_VOL"' in text
    assert "VOLATILITY_REGIME_CONFIDENCE = 0.84" in text
    # VOLATILITY_PROXY_SYMBOL etc. only in debug mode
    assert "export const string VOLATILITY_PROXY_SYMBOL" not in text
    assert 'ENSEMBLE_QUALITY_TIER = "good"' in text
    assert 'ENSEMBLE_AVAILABLE_COMPONENTS = "bias,heuristic,vol_regime"' in text


def test_pine_float_maps_non_finite_to_default() -> None:
    assert _pine_float(1.5) == 1.5
    assert _pine_float(0.0) == 0.0
    assert _pine_float(None) == 0.0
    assert _pine_float("not-a-number") == 0.0
    assert _pine_float(float("nan")) == 0.0
    assert _pine_float(float("inf")) == 0.0
    assert _pine_float(float("-inf")) == 0.0
    assert _pine_float(float("nan"), 1.0) == 1.0


def test_write_library_never_emits_nan_or_inf_pine_literals(tmp_path: Path) -> None:
    """The Pine serialization boundary must never emit ``nan``/``inf`` float
    literals (a compile error in Pine), regardless of non-finite enrichment
    values reaching it.
    """
    out = tmp_path / "lib.pine"
    nan, inf = float("nan"), float("inf")
    enrichment = {
        "regime": {
            "regime": "NEUTRAL", "vix_level": 20.0, "macro_bias": 0.0,
            "macro_bias_raw": nan, "sector_breadth": 0.5,
            "market_pe_forward": nan, "macro_bias_pe_adjustment": nan,
        },
        "news": {"news_heat_global": nan},
        "layering": {"global_heat": nan, "global_strength": inf},
        "ensemble_quality": {"score": nan},
        "volatility_regime": {"confidence": nan, "raw_atr_ratio": nan},
        "short_interest": {"market_short_interest_avg": nan},
        "treasury": {
            "treasury_10y_yield": nan, "treasury_2y_yield": nan,
            "yield_curve_spread": inf, "yield_curve_inverted": False,
        },
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 200, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    offending = [
        line.strip()
        for line in text.splitlines()
        if "= nan" in line.lower()
        or "= inf" in line.lower()
        or "= -inf" in line.lower()
    ]
    assert offending == [], f"non-finite Pine literals emitted: {offending}"


def test_write_library_partial_enrichment(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {
        "regime": {"regime": "RISK_OFF", "vix_level": 35.0, "macro_bias": -0.4, "sector_breadth": 0.25},
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 50, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    # Regime populated
    assert 'MARKET_REGIME = "RISK_OFF"' in text
    assert "VIX_LEVEL = 35.0" in text
    # News defaults
    assert 'NEWS_BULLISH_TICKERS = ""' in text
    assert "NEWS_HEAT_GLOBAL = 0.0" in text
    # Calendar defaults
    assert 'EARNINGS_TODAY_TICKERS = ""' in text
    assert "HIGH_IMPACT_MACRO_TODAY = false" in text
    # Layering defaults
    assert 'TONE = "NEUTRAL"' in text
    # Provider defaults
    assert "PROVIDER_COUNT = 0" in text


def test_write_library_derives_v55_lean_blocks_from_broad_enrichment(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    snapshot = pd.DataFrame([
        {
            "symbol": "AAPL",
            "day_close": 102.0,
        }
    ])
    enrichment: EnrichmentDict = {
        "event_risk": {
            "EVENT_WINDOW_STATE": "ACTIVE",
            "EVENT_RISK_LEVEL": "HIGH",
            "NEXT_EVENT_NAME": "CPI",
            "NEXT_EVENT_TIME": "14:00",
            "MARKET_EVENT_BLOCKED": False,
            "SYMBOL_EVENT_BLOCKED": False,
            "EVENT_PROVIDER_STATUS": "ok",
        },
        "session_context": {
            "SESSION_CONTEXT": "NY_AM",
            "IN_KILLZONE": True,
            "SESSION_DIRECTION_BIAS": "BULLISH",
            "SESSION_CONTEXT_SCORE": 5,
        },
        "compression_regime": {
            "SQUEEZE_ON": True,
            "ATR_REGIME": "COMPRESSION",
        },
        "order_blocks": {
            "NEAREST_BULL_OB_LEVEL": 100.0,
            "NEAREST_BEAR_OB_LEVEL": 110.0,
            "BULL_OB_FRESHNESS": 5,
            "BEAR_OB_FRESHNESS": 1,
            "BULL_OB_MITIGATED": False,
            "BEAR_OB_MITIGATED": False,
        },
        "imbalance_lifecycle": {
            "BULL_FVG_ACTIVE": True,
            "BULL_FVG_TOP": 104.0,
            "BULL_FVG_BOTTOM": 100.0,
            "BULL_FVG_MITIGATION_PCT": 0.1,
            "BULL_FVG_FULL_MITIGATION": False,
        },
        "structure_state": {
            "STRUCTURE_STATE": "BULLISH",
            "STRUCTURE_LAST_EVENT": "BOS_BULL",
            "STRUCTURE_EVENT_AGE_BARS": 2,
            "STRUCTURE_FRESH": True,
            "BOS_BULL": True,
            "SUPPORT_ACTIVE": True,
            "RESISTANCE_ACTIVE": True,
        },
        "liquidity_sweeps": {
            "RECENT_BULL_SWEEP": True,
            "RECENT_BEAR_SWEEP": False,
            "SWEEP_QUALITY_SCORE": 8,
            "SWEEP_DIRECTION": "BULL",
        },
    }

    write_pine_library(
        out,
        _EMPTY_LISTS,
        "2026-03-28",
        5,
        enrichment=enrichment,
        snapshot=snapshot,
    )
    text = out.read_text(encoding="utf-8")

    assert 'EVENT_RISK_LEVEL = "HIGH"' in text
    assert 'SESSION_CONTEXT = "NY_AM"' in text
    assert 'SESSION_VOLATILITY_STATE = "LOW"' in text
    assert 'PRIMARY_OB_SIDE = "BEAR"' in text
    assert 'PRIMARY_OB_DISTANCE = 7.8431' in text
    assert 'PRIMARY_FVG_SIDE = "BULL"' in text
    assert 'STRUCTURE_LAST_EVENT = "BOS_BULL"' in text
    assert 'SIGNAL_QUALITY_TIER = "good"' in text
    assert 'EVENT_RISK_LIGHT_LEVEL' not in text
    assert 'SESSION_CONTEXT_LIGHT' not in text
    assert 'SESSION_LIGHT_VOLATILITY_STATE' not in text
    assert 'STRUCTURE_LIGHT_LAST_EVENT' not in text


def test_manifest_lists_derived_v55_lean_blocks(tmp_path: Path) -> None:
    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
        enrichment={
            "event_risk": {
                "EVENT_WINDOW_STATE": "ACTIVE",
                "EVENT_RISK_LEVEL": "ELEVATED",
                "NEXT_EVENT_NAME": "CPI",
                "NEXT_EVENT_TIME": "14:00",
                "MARKET_EVENT_BLOCKED": False,
                "SYMBOL_EVENT_BLOCKED": False,
                "EVENT_PROVIDER_STATUS": "ok",
            },
            "session_context": {
                "SESSION_CONTEXT": "NY_AM",
                "IN_KILLZONE": True,
                "SESSION_DIRECTION_BIAS": "BULLISH",
                "SESSION_CONTEXT_SCORE": 5,
            },
            "compression_regime": {
                "SQUEEZE_ON": True,
                "ATR_REGIME": "COMPRESSION",
            },
        },
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    enrichment_blocks = set(manifest["enrichment_blocks"])

    assert "event_risk" in enrichment_blocks
    assert "event_risk_light" in enrichment_blocks
    assert "session_context" in enrichment_blocks
    assert "session_context_light" in enrichment_blocks
    assert "signal_quality" in enrichment_blocks


def test_write_library_pine_bool_format(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {
        "calendar": {"high_impact_macro_today": True},
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 10, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    assert "HIGH_IMPACT_MACRO_TODAY = true" in text
    assert "True" not in text  # Python bool must not leak

    out2 = tmp_path / "lib2.pine"
    enrichment2: EnrichmentDict = {
        "calendar": {"high_impact_macro_today": False},
    }
    write_pine_library(out2, _EMPTY_LISTS, "2026-03-28", 10, enrichment=enrichment2)
    text2 = out2.read_text(encoding="utf-8")
    assert "HIGH_IMPACT_MACRO_TODAY = false" in text2
    assert "False" not in text2


def test_defaults_always_present(tmp_path: Path) -> None:
    out = tmp_path / "lib.pine"
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5)
    text = out.read_text(encoding="utf-8")
    required_fields = [
        "MARKET_REGIME", "VIX_LEVEL", "MACRO_BIAS", "MACRO_BIAS_RAW",
        "MACRO_BIAS_PE_ADJUSTMENT", "MARKET_PE_FORWARD", "MARKET_PE_REGIME", "SECTOR_BREADTH",
        "NEWS_BULLISH_TICKERS", "NEWS_BEARISH_TICKERS", "NEWS_NEUTRAL_TICKERS",
        "NEWS_HEAT_GLOBAL", "TICKER_HEAT_MAP",
        "EARNINGS_TODAY_TICKERS", "EARNINGS_TOMORROW_TICKERS",
        "EARNINGS_BMO_TICKERS", "EARNINGS_AMC_TICKERS",
        "HIGH_IMPACT_MACRO_TODAY", "MACRO_EVENT_NAME", "MACRO_EVENT_TIME",
        "GLOBAL_HEAT", "GLOBAL_STRENGTH", "TONE", "TRADE_STATE",
        "PROVIDER_COUNT", "STALE_PROVIDERS",
        "VOLUME_LOW_TICKERS", "HOLIDAY_SUSPECT_TICKERS",
        "VOLATILITY_REGIME", "VOLATILITY_REGIME_CONFIDENCE", "VOLATILITY_ATR_RATIO",
        "VOLATILITY_MODEL_SOURCE",
        "ENSEMBLE_QUALITY_SCORE", "ENSEMBLE_QUALITY_TIER", "ENSEMBLE_AVAILABLE_COMPONENTS",
        # v5 event-risk fields (lean surface + WP-OH9 re-exported NEXT_EVENT_CLASS, HIGH_RISK_EVENT_TICKERS)
        "EVENT_WINDOW_STATE", "EVENT_RISK_LEVEL",
        "NEXT_EVENT_NAME", "NEXT_EVENT_TIME", "NEXT_EVENT_IMPACT",
        "EVENT_RESTRICT_BEFORE_MIN", "EVENT_RESTRICT_AFTER_MIN",
        "EVENT_COOLDOWN_ACTIVE", "MARKET_EVENT_BLOCKED", "SYMBOL_EVENT_BLOCKED",
        "EARNINGS_SOON_TICKERS", "EVENT_PROVIDER_STATUS",
        "HIGH_RISK_EVENT_TICKERS", "NEXT_EVENT_CLASS",
    ]
    for field in required_fields:
        assert field in text, f"Missing field: {field}"


# ── Anti-drift tests ────────────────────────────────────────────────

_SEED_REFERENCE_PINE = Path("tests/fixtures/generated_seed/pine/generated/smc_micro_profiles_generated.pine")
_SEED_REFERENCE_MANIFEST = Path("tests/fixtures/generated_seed/pine/generated/smc_micro_profiles_generated.json")


def test_seed_reference_pine_matches_generator_output(tmp_path: Path) -> None:
    """Fail if the deterministic seed-reference Pine artifact diverges from the generator."""
    if not _SEED_REFERENCE_PINE.exists():
        pytest.skip("seed-reference pine artifact not found")

    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
    )
    fresh = outputs["pine_path"].read_text(encoding="utf-8")
    seed_reference = _SEED_REFERENCE_PINE.read_text(encoding="utf-8")
    assert fresh == seed_reference, (
        "Seed-reference Pine library has drifted from generator output. "
        "Re-run the generator to update tests/fixtures/generated_seed/."
    )


def test_seed_reference_manifest_matches_generator_output(tmp_path: Path) -> None:
    """Fail if the deterministic seed-reference manifest diverges from the generator."""
    if not _SEED_REFERENCE_MANIFEST.exists():
        pytest.skip("seed-reference manifest not found")

    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
    )
    fresh = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    seed_reference = json.loads(_SEED_REFERENCE_MANIFEST.read_text(encoding="utf-8"))

    # Paths are relative to output root, so normalise them away for comparison
    path_keys = {"input_path", "schema_path", "features_csv", "lists_csv",
                 "state_csv", "diff_report_md", "pine_library",
                 "core_import_snippet"}
    for k in path_keys:
        fresh.pop(k, None)
        seed_reference.pop(k, None)
    # schema_version_previous may differ between in-place and fresh runs
    fresh.pop("schema_version_previous", None)
    seed_reference.pop("schema_version_previous", None)
    fresh.pop("version_change_type", None)
    seed_reference.pop("version_change_type", None)

    assert fresh == seed_reference, (
        "Seed-reference manifest has drifted from generator output. "
        "Re-run the generator to update tests/fixtures/generated_seed/."
    )


def test_manifest_declares_v8_0a(tmp_path: Path) -> None:
    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["library_field_version"] == "v8.0a"


# ── Event-risk fixture coverage ─────────────────────────────────────


def test_write_library_event_risk_defaults(tmp_path: Path) -> None:
    """Without event_risk enrichment, all 12 kept fields fall back to safe defaults."""
    out = tmp_path / "lib.pine"
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5)
    text = out.read_text(encoding="utf-8")
    assert 'EVENT_WINDOW_STATE = "CLEAR"' in text
    assert 'EVENT_RISK_LEVEL = "NONE"' in text
    assert 'NEXT_EVENT_NAME = ""' in text
    assert 'NEXT_EVENT_TIME = ""' in text
    assert 'NEXT_EVENT_IMPACT = "NONE"' in text
    assert "EVENT_RESTRICT_BEFORE_MIN = 0" in text
    assert "EVENT_RESTRICT_AFTER_MIN = 0" in text
    assert "EVENT_COOLDOWN_ACTIVE = false" in text
    assert "MARKET_EVENT_BLOCKED = false" in text
    assert "SYMBOL_EVENT_BLOCKED = false" in text
    assert 'EARNINGS_SOON_TICKERS = ""' in text
    assert 'EVENT_PROVIDER_STATUS = "ok"' in text
    # NEXT_EVENT_CLASS and HIGH_RISK_EVENT_TICKERS re-exported in WP-OH9
    assert 'NEXT_EVENT_CLASS = ""' in text
    assert 'HIGH_RISK_EVENT_TICKERS = ""' in text


def test_write_library_active_macro_block(tmp_path: Path) -> None:
    """A HIGH macro event with ACTIVE window should emit blocked state."""
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {
        "event_risk": {
            "EVENT_WINDOW_STATE": "ACTIVE",
            "EVENT_RISK_LEVEL": "HIGH",
            "NEXT_EVENT_NAME": "FOMC Rate Decision",
            "NEXT_EVENT_TIME": "14:00",
            "NEXT_EVENT_IMPACT": "HIGH",
            "EVENT_RESTRICT_BEFORE_MIN": 30,
            "EVENT_RESTRICT_AFTER_MIN": 15,
            "EVENT_COOLDOWN_ACTIVE": False,
            "MARKET_EVENT_BLOCKED": True,
            "SYMBOL_EVENT_BLOCKED": False,
            "EARNINGS_SOON_TICKERS": "",
            "EVENT_PROVIDER_STATUS": "ok",
        },
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    assert 'EVENT_WINDOW_STATE = "ACTIVE"' in text
    assert 'EVENT_RISK_LEVEL = "HIGH"' in text
    assert 'NEXT_EVENT_NAME = "FOMC Rate Decision"' in text
    assert 'NEXT_EVENT_TIME = "14:00"' in text
    assert 'NEXT_EVENT_IMPACT = "HIGH"' in text
    assert "EVENT_RESTRICT_BEFORE_MIN = 30" in text
    assert "EVENT_RESTRICT_AFTER_MIN = 15" in text
    assert "MARKET_EVENT_BLOCKED = true" in text
    assert "SYMBOL_EVENT_BLOCKED = false" in text


def test_write_library_symbol_event_block(tmp_path: Path) -> None:
    """Earnings-only event should block at symbol level, not market level."""
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {
        "event_risk": {
            "EVENT_WINDOW_STATE": "CLEAR",
            "EVENT_RISK_LEVEL": "ELEVATED",
            "NEXT_EVENT_NAME": "Earnings",
            "NEXT_EVENT_TIME": "",
            "NEXT_EVENT_IMPACT": "MEDIUM",
            "EVENT_RESTRICT_BEFORE_MIN": 15,
            "EVENT_RESTRICT_AFTER_MIN": 5,
            "EVENT_COOLDOWN_ACTIVE": False,
            "MARKET_EVENT_BLOCKED": False,
            "SYMBOL_EVENT_BLOCKED": True,
            "EARNINGS_SOON_TICKERS": "AAPL,MSFT,TSLA",
            "EVENT_PROVIDER_STATUS": "ok",
        },
    }
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    assert 'NEXT_EVENT_IMPACT = "MEDIUM"' in text
    assert "MARKET_EVENT_BLOCKED = false" in text
    assert "SYMBOL_EVENT_BLOCKED = true" in text
    assert 'EARNINGS_SOON_TICKERS = "AAPL,MSFT,TSLA"' in text


def test_manifest_event_risk_provenance(tmp_path: Path) -> None:
    """Manifest records event_risk_source when enrichment provides it."""
    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
        enrichment={"event_risk": {"EVENT_WINDOW_STATE": "CLEAR"}},
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["library_field_version"] == "v8.0a"
    assert manifest["event_risk_source"] == "smc_event_risk_builder"
    assert "event_risk" in manifest["enrichment_blocks"]


def test_manifest_event_risk_defaults_provenance(tmp_path: Path) -> None:
    """Without event_risk enrichment, manifest notes 'defaults' source."""
    outputs = run_generation(
        schema_path=Path(SCHEMA_PATH),
        input_path=Path("tests/fixtures/seed_base_snapshot.csv"),
        output_root=tmp_path,
    )
    manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
    assert manifest["library_field_version"] == "v8.0a"
    assert manifest["event_risk_source"] == "defaults"


# ── Debug mode tests ────────────────────────────────────────────────


def test_debug_mode_includes_diagnostic_fields(tmp_path: Path) -> None:
    """With _debug_mode, diagnostic fields are present."""
    out = tmp_path / "lib.pine"
    enrichment: EnrichmentDict = {"_debug_mode": True}
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5, enrichment=enrichment)
    text = out.read_text(encoding="utf-8")
    assert "export const string UNIVERSE_ID" in text
    assert "export const int LOOKBACK_DAYS" in text
    assert "export const string VOLATILITY_FALLBACK_REASON" in text
    assert "export const string VOLATILITY_PROXY_SYMBOL" in text
    assert "export const string VOLATILITY_PROXY_SOURCE" in text


def test_no_debug_mode_excludes_diagnostic_fields(tmp_path: Path) -> None:
    """Without _debug_mode, diagnostic fields are absent."""
    out = tmp_path / "lib.pine"
    write_pine_library(out, _EMPTY_LISTS, "2026-03-28", 5)
    text = out.read_text(encoding="utf-8")
    assert "export const string UNIVERSE_ID" not in text
    assert "export const int LOOKBACK_DAYS" not in text
    # VOLATILITY_MODEL_SOURCE is always emitted (consumed by SMC_Core_Engine)
    assert "export const string VOLATILITY_MODEL_SOURCE" in text
    assert "export const string VOLATILITY_FALLBACK_REASON" not in text
    assert "export const string VOLATILITY_PROXY_SYMBOL" not in text
    assert "export const string VOLATILITY_PROXY_SOURCE" not in text
