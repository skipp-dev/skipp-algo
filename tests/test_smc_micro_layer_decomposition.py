"""Tests for the generator / validator / publisher layer decomposition.

Verifies that:
- The generator produces correct results without any file I/O.
- The validator catches schema violations and succeeds on valid input.
- The publisher writes all expected artifacts from a GenerationResult.
- The orchestrator (run_generation) chains all three correctly.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.generate_smc_micro_profiles import (
    coerce_input_frame,
    load_schema,
    LISTS,
)
from scripts.smc_micro_generator import GenerationResult, generate
from scripts.smc_micro_publisher import publish_generation_result, publish_readiness_report
from scripts.smc_micro_validator import (
    assess_input_coverage,
    validate_generation_input,
    validate_publish_readiness,
)
from scripts.smc_schema_resolver import resolve_microstructure_schema_path


SCHEMA_PATH = resolve_microstructure_schema_path()


# ---------------------------------------------------------------------------
# Shared fixture: 3-symbol base snapshot (reused from existing tests)
# ---------------------------------------------------------------------------


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


@pytest.fixture
def schema() -> dict:
    return load_schema(SCHEMA_PATH)


@pytest.fixture
def raw_df() -> pd.DataFrame:
    return pd.DataFrame(_base_rows())


@pytest.fixture
def coerced_df(raw_df: pd.DataFrame) -> pd.DataFrame:
    return coerce_input_frame(raw_df)


# ===================================================================
# Generator tests — pure computation, no file I/O
# ===================================================================


class TestGenerator:
    def test_generate_returns_generation_result(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )
        assert isinstance(result, GenerationResult)

    def test_generate_produces_correct_lists_bootstrap(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )
        assert result.lists["clean_reclaim"] == ["AAA"]
        assert result.lists["stop_hunt_prone"] == ["BBB"]
        assert result.lists["fast_decay"] == ["BBB"]
        assert result.lists["midday_dead"] == ["CCC"]
        assert result.lists["rth_only"] == ["CCC"]
        assert result.lists["weak_premarket"] == ["CCC"]
        assert result.lists["weak_afterhours"] == ["CCC"]

    def test_generate_populates_metadata(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )
        assert result.asof_date == "2026-03-23"
        assert result.universe_size == 3
        assert not result.overrides_applied

    def test_generate_does_not_write_files(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        """Generator must be side-effect free — no new files created."""
        before = set(tmp_path.rglob("*"))
        generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )
        after = set(tmp_path.rglob("*"))
        assert after == before

    def test_generate_with_prior_state(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        """When state_path exists, generator should load prior state (non-bootstrap)."""
        state_path = tmp_path / "state.csv"
        state_path.write_text(
            "symbol,list_name,is_active,active_since,add_streak,remove_streak,"
            "last_score,last_run_date,candidate_active,decision_source,decision_reason\n"
            "AAA,clean_reclaim,1,2026-03-10,3,0,0.9,2026-03-22,1,generator,retained\n",
            encoding="utf-8",
        )
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
            state_path=state_path,
        )
        # AAA should still be active (retained)
        active_aaa = result.state_df[
            (result.state_df["symbol"] == "AAA") & (result.state_df["list_name"] == "clean_reclaim")
        ]
        assert not active_aaa.empty
        assert int(active_aaa.iloc[0]["is_active"]) == 1

    def test_generate_with_overrides(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        overrides_path = tmp_path / "overrides.csv"
        overrides_path.write_text(
            "asof_date,symbol,list_name,action,reason\n"
            "2026-03-23,AAA,stop_hunt_prone,add,manual test override\n",
            encoding="utf-8",
        )
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
            overrides_path=overrides_path,
        )
        assert result.overrides_applied is True
        assert "AAA" in result.lists["stop_hunt_prone"]

    def test_features_df_contains_score_columns(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )
        for score_col in [
            "clean_reclaim_score",
            "stop_hunt_score",
            "midday_dead_score",
            "rth_only_score",
            "weak_premarket_score",
            "weak_afterhours_score",
            "fast_decay_score",
        ]:
            assert score_col in result.features_df.columns, f"Missing score column: {score_col}"


# ===================================================================
# Validator tests — no file I/O (except CSV reads for assessment)
# ===================================================================


class TestValidator:
    def test_validate_generation_input_passes_valid_data(self, schema: dict, coerced_df: pd.DataFrame) -> None:
        validate_generation_input(coerced_df, schema)

    def test_validate_generation_input_rejects_missing_columns(self, schema: dict, coerced_df: pd.DataFrame) -> None:
        df = coerced_df.drop(columns=["symbol"])
        with pytest.raises(RuntimeError, match="Missing required columns"):
            validate_generation_input(df, schema)

    def test_validate_generation_input_rejects_duplicates(self, schema: dict, coerced_df: pd.DataFrame) -> None:
        df = pd.concat([coerced_df, coerced_df.iloc[[0]]], ignore_index=True)
        with pytest.raises(RuntimeError, match="Duplicate primary keys"):
            validate_generation_input(df, schema)

    def test_validate_generation_input_rejects_multiple_asof_dates(self, schema: dict, coerced_df: pd.DataFrame) -> None:
        df = coerced_df.copy()
        df.loc[0, "asof_date"] = "2026-03-24"
        with pytest.raises(RuntimeError, match="exactly one asof_date"):
            validate_generation_input(df, schema)

    def test_assess_input_coverage_reports_gaps(self, schema: dict, tmp_path: Path) -> None:
        csv = tmp_path / "partial.csv"
        csv.write_text("symbol,exchange,asset_type\nABC,NASDAQ,stock\n", encoding="utf-8")
        assessment = assess_input_coverage(schema, csv)
        assert "symbol" in assessment["present_required"]
        assert "asof_date" in assessment["missing_required"]
        assert assessment["required_coverage"] < 1.0

    def test_validate_publish_readiness_raises_on_missing_manifest(self, tmp_path: Path) -> None:
        fake_manifest = tmp_path / "missing.json"
        fake_core = tmp_path / "core.pine"
        fake_core.write_text("// placeholder", encoding="utf-8")
        with pytest.raises((RuntimeError, FileNotFoundError)):
            validate_publish_readiness(manifest_path=fake_manifest, core_path=fake_core)


# ===================================================================
# Publisher tests — file I/O only, trusts GenerationResult
# ===================================================================


class TestPublisher:
    def _make_result(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> GenerationResult:
        return generate(
            schema=schema,
            input_df=coerced_df,
            schema_path=SCHEMA_PATH,
            input_path=tmp_path / "snapshot.csv",
        )

    def test_publish_writes_all_expected_artifacts(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        assert paths["features_path"].exists()
        assert paths["lists_path"].exists()
        assert paths["state_path"].exists()
        assert paths["diff_report_path"].exists()
        assert paths["pine_path"].exists()
        assert paths["manifest_path"].exists()
        assert paths["core_import_snippet_path"].exists()

    def test_publish_pine_library_content(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        pine = paths["pine_path"].read_text(encoding="utf-8")
        assert 'library("smc_micro_profiles_generated")' in pine
        assert 'export const string CLEAN_RECLAIM_TICKERS = "AAA"' in pine
        assert 'export const string STOP_HUNT_PRONE_TICKERS = "BBB"' in pine

    def test_publish_manifest_content(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
        assert manifest["universe_size"] == 3
        assert manifest["recommended_import_path"] == "preuss_steffen/smc_micro_profiles_generated/1"
        assert manifest["list_counts"]["clean_reclaim"] == 1

    def test_publish_snippet_content(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        snippet = paths["core_import_snippet_path"].read_text(encoding="utf-8")
        assert "import preuss_steffen/smc_micro_profiles_generated/1 as mp" in snippet
        # The snippet aliases use shortened names (e.g. stop_hunt not stop_hunt_prone)
        assert "clean_reclaim_tickers_effective" in snippet
        assert "stop_hunt_tickers_effective" in snippet
        assert "midday_dead_tickers_effective" in snippet
        assert "fast_decay_tickers_effective" in snippet

    def test_publish_diff_report_content(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        diff = paths["diff_report_path"].read_text(encoding="utf-8")
        assert "### Added details" in diff
        assert "bootstrap activation on first snapshot" in diff

    def test_publish_lists_csv_content(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(result, output_root=tmp_path)

        lists_csv = pd.read_csv(paths["lists_path"])
        assert set(lists_csv["list_name"]) == set(LISTS)
        assert {"decision_source", "decision_reason"}.issubset(lists_csv.columns)

    def test_publish_with_custom_library_owner(self, schema: dict, coerced_df: pd.DataFrame, tmp_path: Path) -> None:
        result = self._make_result(schema, coerced_df, tmp_path)
        paths = publish_generation_result(
            result,
            output_root=tmp_path,
            library_owner="test_owner",
            library_version=42,
        )

        manifest = json.loads(paths["manifest_path"].read_text(encoding="utf-8"))
        assert manifest["library_owner"] == "test_owner"
        assert manifest["library_version"] == 42
        assert manifest["recommended_import_path"] == "test_owner/smc_micro_profiles_generated/42"

        snippet = paths["core_import_snippet_path"].read_text(encoding="utf-8")
        assert "import test_owner/smc_micro_profiles_generated/42 as mp" in snippet

    def test_publish_readiness_report(self, schema: dict, tmp_path: Path) -> None:
        csv = tmp_path / "partial.csv"
        csv.write_text("symbol,exchange\nABC,NASDAQ\n", encoding="utf-8")

        assessment = assess_input_coverage(schema, csv)
        report_path = tmp_path / "readiness.md"
        publish_readiness_report(assessment, output_path=report_path)

        report = report_path.read_text(encoding="utf-8")
        assert "## Missing required columns" in report
        assert "- asof_date" in report


# ===================================================================
# Integration: orchestrator chains all three correctly
# ===================================================================


class TestOrchestrator:
    def test_run_generation_backward_compat(self, tmp_path: Path) -> None:
        """run_generation still works end-to-end with the same interface."""
        from scripts.generate_smc_micro_profiles import run_generation

        schema_path = tmp_path / "schema.json"
        schema_path.write_text(Path(SCHEMA_PATH).read_text(encoding="utf-8"), encoding="utf-8")

        input_path = tmp_path / "snapshot.csv"
        pd.DataFrame(_base_rows()).to_csv(input_path, index=False)

        outputs = run_generation(
            schema_path=schema_path,
            input_path=input_path,
            output_root=tmp_path,
        )

        assert all(path.exists() for path in outputs.values())
        manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
        assert manifest["universe_size"] == 3
