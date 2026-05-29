"""End-to-end tests for the real v4 production pipeline path.

Unlike ``test_enrichment_contract_integration.py``, which injects
synthetic enrichment dicts, these tests exercise the actual call chain:

    build_enrichment(...)
        → resolve_domain() per domain (regime / news / calendar / technical)
        → _derive_volume_regime(base_snapshot)
        → meta + refresh_count

    finalize_pipeline(...)
        → build_enrichment(...)
        → generate_pine_library_from_base(...)

    generate_pine_library_from_base(...)
        → run_generation → validate → publish

with *mocked network adapters* returning realistic payloads.  This
proves the real wiring delivers correct v4 artifacts without touching
the network.

Test scope
----------
- Real provider metadata derivation (provider_count / stale_providers / provenance)
- Real stale-provider fallback behavior (primary fails → fallback wins)
- Volume-regime block derivation from a real base-snapshot DataFrame
- Manifest + Pine artifact contract after ``finalize_pipeline()``
- Smoke test: full v4 field inventory from the automated path
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from scripts.generate_smc_micro_base_from_databento import (
    _derive_volume_regime,
    build_enrichment,
    finalize_pipeline,
)
from scripts.smc_microstructure_base_runtime import generate_pine_library_from_base
from scripts.smc_provider_policy import ProviderResult
from scripts.smc_schema_resolver import resolve_microstructure_schema_path

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = resolve_microstructure_schema_path()
CONTRACT_PINE_PATH = ROOT / "tests" / "fixtures" / "generated_seed" / "pine" / "generated" / "smc_micro_profiles_generated.pine"


def _load_contract_field_inventory() -> list[str]:
    text = CONTRACT_PINE_PATH.read_text(encoding="utf-8")
    return [
        line.split(" = ", 1)[0].split()[-1]
        for line in text.splitlines()
        if line.startswith("export const")
    ]


# ── Canonical generated field inventory (checked-in artifact is source of truth) ──

V5_FIELD_INVENTORY = _load_contract_field_inventory()


# ── Shared helpers ──────────────────────────────────────────────────


def _base_row(sym: str, adv: float = 150_000_000.0) -> dict[str, object]:
    """One row matching the microstructure schema."""
    return {
        "asof_date": "2026-03-28",
        "symbol": sym,
        "exchange": "NASDAQ",
        "asset_type": "stock",
        "universe_bucket": "test_bucket",
        "history_coverage_days_20d": 20,
        "adv_dollar_rth_20d": adv,
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
    }


def _snapshot_df(
    symbols: list[str] | None = None,
    adv_overrides: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Build a realistic multi-symbol base snapshot DataFrame."""
    syms = symbols or ["AAPL", "TSLA", "META"]
    overrides = adv_overrides or {}
    rows = [_base_row(s, adv=overrides.get(s, 150_000_000.0)) for s in syms]
    return pd.DataFrame(rows)


def _daily_bars_df(symbols: list[str] | None = None) -> pd.DataFrame:
    syms = symbols or ["AAPL", "TSLA", "META"]
    trade_dates = pd.date_range("2025-12-01", periods=90, freq="B")
    rows: list[dict[str, object]] = []
    for sym_index, symbol in enumerate(syms):
        base_price = 120.0 + sym_index * 35.0
        for idx, trade_date in enumerate(trade_dates):
            drift = idx * (0.55 + sym_index * 0.05)
            swing = ((idx % 7) - 3) * 0.35
            close = base_price + drift + swing
            open_price = close - 0.6
            rows.append(
                {
                    "symbol": symbol,
                    "trade_date": trade_date,
                    "open": round(open_price, 4),
                    "high": round(close + 1.1, 4),
                    "low": round(open_price - 1.0, 4),
                    "close": round(close, 4),
                    "volume": 1_000_000 + idx * 10_000,
                }
            )
    return pd.DataFrame(rows)


@pytest.fixture
def base_csv(tmp_path: Path) -> Path:
    df = _snapshot_df()
    csv_path = tmp_path / "base_snapshot.csv"
    df.to_csv(csv_path, index=False)
    return csv_path


@pytest.fixture
def base_result(tmp_path: Path, base_csv: Path) -> dict[str, Any]:
    """Simulate a ``base_result`` dict as returned by the scan pipeline."""
    return {
        "output_paths": {"base_csv": str(base_csv)},
        "base_snapshot": _snapshot_df(),
    }


def _make_mock_fmp() -> MagicMock:
    """Build a mock FMP client with realistic return payloads."""
    fmp = MagicMock()
    fmp.get_index_quote.return_value = {"price": 18.5}
    fmp.get_sector_performance.return_value = [
        {"sector": "Technology", "changesPercentage": 1.2},
        {"sector": "Healthcare", "changesPercentage": 0.5},
        {"sector": "Energy", "changesPercentage": -0.3},
        {"sector": "Financials", "changesPercentage": 0.8},
        {"sector": "Consumer Discretionary", "changesPercentage": -0.1},
    ]
    fmp.get_stock_latest_news.return_value = [
        {
            "title": "Apple announces record earnings",
            "tickers": ["AAPL"],
            "symbol": "AAPL",
        },
        {
            "title": "Tesla faces regulatory scrutiny",
            "tickers": ["TSLA"],
            "symbol": "TSLA",
        },
    ]
    fmp.get_earnings_calendar.return_value = [
        {"symbol": "AAPL", "date": "2026-03-28", "time": "After Market Close"},
    ]
    fmp.get_macro_calendar.return_value = [
        {"event": "FOMC Meeting", "date": "2026-03-28T18:00:00Z"},
    ]
    fmp.get_technical_indicator.return_value = {"rsi": 62.0}
    fmp.get_market_pe_forward.return_value = 21.3
    fmp._last_market_pe_forward_diagnostics = {
        "status": "ok",
        "symbol": "SPY",
        "source_category": "approximate_ttm",
        "field": "pe",
        "price": 510.0,
        "forward_eps": None,
        "estimate_count": 0,
        "error": "",
    }
    return fmp


# ── 1. build_enrichment e2e ─────────────────────────────────────────


class TestBuildEnrichmentE2E:
    """Tests that exercise the real ``build_enrichment()`` orchestration
    with mocked network calls — proving provider metadata, provenance,
    stale handling, and volume-regime derivation work end-to-end.
    """

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_all_domains_enabled_produces_full_enrichment(self, mock_make, tmp_path: Path):
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        assert result is not None
        assert "regime" in result
        assert "news" in result
        assert "calendar" in result
        assert "layering" in result
        assert "providers" in result
        assert "volume_regime" in result
        assert "meta" in result

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_provider_count_matches_active_domains(self, mock_make):
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        # All 4 domains use FMP as primary → should succeed → provider_count >= 1
        prov = result["providers"]
        assert prov["provider_count"] >= 1

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_provenance_records_per_domain(self, mock_make):
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        prov = result["providers"]
        assert prov.get("regime_provider") == "fmp"
        assert prov.get("news_provider") == "fmp"
        assert prov.get("calendar_provider") == "fmp"
        assert prov.get("technical_provider") == "fmp"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_stale_providers_empty_on_full_success(self, mock_make):
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        assert result["providers"]["stale_providers"] == ""

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_stale_provider_on_regime_vix_failure(self, mock_make):
        """When VIX fetch fails, regime still resolves but stale includes fmp_vix."""
        fmp = _make_mock_fmp()
        fmp.get_index_quote.side_effect = RuntimeError("VIX unavailable")
        mock_make.return_value = fmp
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        # Regime domain uses fmp — the individual sub-call (VIX) failed
        assert "fmp_vix" in result["providers"]["stale_providers"]

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_volume_regime_from_real_snapshot(self, mock_make):
        """Volume regime is derived from the actual base_snapshot DataFrame."""
        mock_make.return_value = _make_mock_fmp()
        snapshot = _snapshot_df(
            symbols=["AAPL", "TSLA", "PENNY"],
            adv_overrides={"PENNY": 500_000.0},  # below 5M threshold
        )
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "PENNY"],
            enrich_regime=True,
            base_snapshot=snapshot,
        )
        vol = result["volume_regime"]
        assert "PENNY" in vol["low_tickers"]
        assert "AAPL" not in vol["low_tickers"]

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_build_enrichment_wires_real_macro_bias_and_regime_diagnostics(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_macro_calendar.return_value = [
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-03-28",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            }
        ]
        mock_make.return_value = fmp

        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            base_snapshot=_snapshot_df(),
        )

        assert result is not None
        assert result["regime"]["macro_bias"] == pytest.approx(-0.5)
        assert result["regime"]["sector_breadth"] == pytest.approx(0.6)
        diagnostics = result["providers"]["domain_diagnostics"]["regime"]["diagnostics"]
        assert diagnostics["vix_present"] is True
        assert diagnostics["sector_row_count"] == 5
        assert diagnostics["macro_event_count"] == 1
        assert diagnostics["macro_inputs_used"] == ["Core CPI MoM"]
        assert result["regime"]["market_pe_forward"] == pytest.approx(21.3)
        assert result["regime"]["market_pe_regime"] == "FAIR"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_build_enrichment_activates_volatility_and_ensemble_quality_with_daily_bars(self, mock_make):
        mock_make.return_value = _make_mock_fmp()

        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
            daily_bars=_daily_bars_df(),
        )

        assert result is not None
        assert result["volatility_regime"]["label"] in {"LOW_VOL", "NORMAL", "HIGH_VOL", "EXTREME"}
        assert result["volatility_regime"]["proxy_symbol"] in {"AAPL", "TSLA", "META"}
        assert result["ensemble_quality"]["tier"] in {"low", "ok", "good", "high"}
        assert 0.0 <= result["ensemble_quality"]["score"] <= 1.0

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_build_enrichment_exposes_news_payload_diagnostics(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_stock_latest_news.return_value = [
            {
                "title": "Apple beats earnings, strong growth outlook",
                "tickers": ["AAPL"],
                "symbol": "AAPL",
            },
            {
                "title": "Tesla misses estimates, weak outlook warning",
                "tickers": ["TSLA"],
                "symbol": "TSLA",
            },
        ]
        mock_make.return_value = fmp

        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_news=True,
            base_snapshot=_snapshot_df(),
        )

        assert result is not None
        assert result["news"]["bullish_tickers"] == ["AAPL"]
        assert result["news"]["bearish_tickers"] == ["TSLA"]
        assert result["news"]["ticker_heat_map"]
        diagnostics = result["providers"]["domain_diagnostics"]["news"]["diagnostics"]
        assert diagnostics["article_count"] == 2
        assert diagnostics["matched_article_count"] == 2
        assert diagnostics["empty_headline_count"] == 0
        assert diagnostics["unique_recognized_ticker_count"] == 2
        assert diagnostics["polarity_distribution"] == {
            "positive": 1,
            "negative": 1,
            "neutral": 0,
        }

    def test_refresh_count_increments_from_manifest(self, tmp_path: Path):
        """refresh_count reads from a prior manifest and increments by 1."""
        manifest_path = tmp_path / "pine" / "generated" / "smc_micro_profiles_generated.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps({"refresh_count": 7}), encoding="utf-8",
        )
        result = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL"],
            enrich_regime=True,
            manifest_path=manifest_path,
        )
        assert result is not None
        assert result["meta"]["refresh_count"] == 8

    def test_no_domains_enabled_returns_none(self):
        result = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL"],
        )
        assert result is None

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_regime_only_omits_news_calendar_layering(self, mock_make):
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        assert "regime" in result
        assert "news" not in result
        assert "calendar" not in result
        assert "layering" not in result

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_layering_derives_trade_state(self, mock_make):
        """Layering computes tone and trade_state from regime + news + technical."""
        mock_make.return_value = _make_mock_fmp()
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_layering=True,
        )
        lay = result["layering"]
        assert lay["tone"] in ("BULLISH", "BEARISH", "NEUTRAL")
        assert lay["trade_state"] in ("ALLOWED", "BLOCKED")
        assert isinstance(lay["global_heat"], float)
        assert isinstance(lay["global_strength"], float)


# ── 2. _derive_volume_regime unit tests ─────────────────────────────


class TestDeriveVolumeRegime:
    """Direct tests for volume-regime derivation from base snapshot data."""

    def test_low_tickers_below_threshold(self):
        df = _snapshot_df(
            symbols=["AAPL", "LOW1", "LOW2"],
            adv_overrides={"LOW1": 1_000_000.0, "LOW2": 3_000_000.0},
        )
        result = _derive_volume_regime(df)
        assert "LOW1" in result["low_tickers"]
        assert "LOW2" in result["low_tickers"]
        assert "AAPL" not in result["low_tickers"]

    def test_holiday_suspect_below_20pct_median(self):
        # AAPL and TSLA at 150M, TINY at 1M (< 0.2 * 150M = 30M)
        df = _snapshot_df(
            symbols=["AAPL", "TSLA", "TINY"],
            adv_overrides={"TINY": 1_000_000.0},
        )
        result = _derive_volume_regime(df)
        assert "TINY" in result["holiday_suspect_tickers"]
        assert "AAPL" not in result["holiday_suspect_tickers"]

    def test_empty_snapshot_returns_empty(self):
        result = _derive_volume_regime(pd.DataFrame())
        assert result["low_tickers"] == []
        assert result["holiday_suspect_tickers"] == []

    def test_none_snapshot_returns_empty(self):
        result = _derive_volume_regime(None)
        assert result["low_tickers"] == []
        assert result["holiday_suspect_tickers"] == []

    def test_missing_adv_column_returns_empty(self):
        df = pd.DataFrame({"symbol": ["AAPL"], "other_col": [42]})
        result = _derive_volume_regime(df)
        assert result["low_tickers"] == []


# ── 3. finalize_pipeline e2e ────────────────────────────────────────


class TestFinalizePipelineE2E:
    """Tests the complete ``finalize_pipeline()`` orchestration.

    This is the closest to the real ``--run-scan`` / ``--bundle`` CLI path:
    it takes a ``base_result`` dict (like the scan produces), runs
    enrichment, and generates Pine artifacts.
    """

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_returns_ok_status(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        assert result["status"] == "ok"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_symbols_count_correct(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
        )
        assert result["symbols_count"] == 3

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_enrichment_keys_populated(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        expected_keys = {"regime", "news", "calendar", "layering", "providers", "volume_regime", "meta"}
        assert expected_keys.issubset(set(result["enrichment_keys"]))

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_pine_artifacts_exist_on_disk(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
        )
        for name, path_str in result["pine_paths"].items():
            assert Path(path_str).exists(), f"Pine artifact missing: {name} → {path_str}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_generated_pine_has_all_v4_fields(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        pine_text = Path(result["pine_paths"]["pine_path"]).read_text(encoding="utf-8")
        for field in V5_FIELD_INVENTORY:
            assert field in pine_text, f"finalize_pipeline missing v5 field: {field}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_stale_providers_in_return(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
        )
        # All providers succeed → stale_providers should be empty
        assert result["stale_providers"] == ""

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_stale_providers_propagated_on_vix_failure(self, mock_make, base_result, tmp_path):
        fmp = _make_mock_fmp()
        fmp.get_index_quote.side_effect = RuntimeError("VIX down")
        mock_make.return_value = fmp
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
        )
        assert "fmp_vix" in result["stale_providers"]

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_manifest_written_with_v7_0a_marker(self, mock_make, base_result, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
        )
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        assert manifest_files, "No manifest file written by finalize_pipeline"
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        assert manifest.get("library_field_version") == "v7.0a"

    def test_no_enrichment_still_generates_pine(self, base_result, tmp_path):
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
        )
        assert result["status"] == "ok"
        assert result["enrichment_keys"] == []
        pine_text = Path(result["pine_paths"]["pine_path"]).read_text(encoding="utf-8")
        assert pine_text.startswith("//@version=6\n")

    def test_finalize_pipeline_without_credentials_writes_default_provider_artifacts(self, base_result, tmp_path):
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
        )

        assert result["status"] == "ok"
        assert result["stale_providers"] == "benzinga,calendar,fmp,newsapi_ai"

        pine_text = Path(result["pine_paths"]["pine_path"]).read_text(encoding="utf-8")
        assert "PROVIDER_COUNT = 1" in pine_text
        assert 'STALE_PROVIDERS = "benzinga,calendar,fmp,newsapi_ai"' in pine_text

        manifest_path = Path(result["pine_paths"]["manifest_path"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert manifest["enrichment_blocks"] == ["calendar", "hero_state", "meta", "news", "providers", "regime", "volume_regime"]

    def test_finalize_pipeline_writes_library_provider_diagnostics_report(self, base_result, tmp_path):
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
        )

        report_path = Path(result["provider_diagnostics_report"])
        assert report_path.exists()

        report = json.loads(report_path.read_text(encoding="utf-8"))
        assert report["report_kind"] == "library_provider_diagnostics"
        assert report["overall_status"] == "warn"
        assert report["stale_providers"] == ["benzinga", "calendar", "fmp", "newsapi_ai"]

        news_diag = next(row for row in report["provider_domain_results"] if row["domain"] == "news")
        assert news_diag["provider_status"] == "no_data"
        assert news_diag["selected_provider"] == "none"
        assert news_diag["attempts"][-1]["provider"] == "newsapi_ai"
        assert news_diag["attempts"][-1]["provider_status"] == "config_missing"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    @patch("scripts.smc_provider_policy.fetch_news_newsapi_ai")
    @patch("scripts.smc_provider_policy.fetch_news_benzinga")
    @patch("scripts.smc_provider_policy.fetch_news_fmp")
    def test_finalize_pipeline_reports_newsapi_fallback_semantics(
        self,
        mock_news_fmp,
        mock_news_benzinga,
        mock_news_newsapi,
        mock_make,
        base_result,
        tmp_path,
    ):
        mock_make.return_value = MagicMock()
        mock_news_fmp.side_effect = RuntimeError("FMP timeout")
        mock_news_benzinga.side_effect = RuntimeError("Benzinga timeout")
        mock_news_newsapi.return_value = ProviderResult(
            data={
                "bullish_tickers": [],
                "bearish_tickers": [],
                "neutral_tickers": [],
                "news_heat_global": 0.0,
                "ticker_heat_map": "",
            },
            provider="newsapi_ai",
            meta={
                "provider_status": "ok_no_recent_matches",
                "status_detail": "Event Registry reachable, but no recent symbol-matching NewsAPI.ai items were returned for the current feed window.",
                "last_seen_epoch": 0.0,
                "last_seen_news_uri": "",
                "raw_record_count": 0,
                "matched_record_count": 0,
                "cursor_before_epoch": 123.0,
                "cursor_before_uri": "uri-feed-1",
            },
        )

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            benzinga_api_key="bz-key",
            newsapi_ai_key="news-key",
            enrich_news=True,
        )

        report_path = Path(result["provider_diagnostics_report"])
        report = json.loads(report_path.read_text(encoding="utf-8"))

        assert report["report_kind"] == "library_provider_diagnostics"
        assert report["overall_status"] == "warn"
        assert report["stale_providers"] == ["benzinga", "fmp"]

        news_diag = next(row for row in report["provider_domain_results"] if row["domain"] == "news")
        assert news_diag["selected_provider"] == "newsapi_ai"
        assert news_diag["provider_status"] == "ok_no_recent_matches"
        assert news_diag["stale_providers"] == ["fmp", "benzinga"]
        assert [attempt["provider"] for attempt in news_diag["attempts"]] == ["fmp", "benzinga", "newsapi_ai"]
        assert news_diag["attempts"][0]["provider_status"] == "timeout"
        assert news_diag["attempts"][1]["provider_status"] == "timeout"
        assert news_diag["attempts"][2]["provider_status"] == "ok_no_recent_matches"
        assert news_diag["attempts"][2]["cursor_before_uri"] == "uri-feed-1"

        assert report["failure_reasons"] == [{
            "domain": "news",
            "provider": "newsapi_ai",
            "code": "LIBRARY_NEWS_OK_NO_RECENT_MATCHES",
            "detail": "Event Registry reachable, but no recent symbol-matching NewsAPI.ai items were returned for the current feed window.",
        }]


# ── 4. generate_pine_library_from_base with real enrichment ─────────


class TestGeneratePineWithRealEnrichment:
    """Feeds enrichment produced by the *real* ``build_enrichment()``
    (not a synthetic dict) into ``generate_pine_library_from_base()``
    and verifies the generated Pine artifact.
    """

    def test_uncredentialed_enrichment_renders_default_provider_metadata(self, base_csv, tmp_path):
        enrichment = build_enrichment(
            fmp_api_key="",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            base_snapshot=_snapshot_df(),
        )

        assert enrichment is not None
        providers = enrichment["providers"]
        assert providers["provider_count"] == 1
        assert providers["base_scan_provider"] == "databento"
        assert providers["regime_provider"] == "none"
        assert providers["news_provider"] == "none"
        assert providers["calendar_provider"] == "none"
        assert providers["stale_providers"] == "benzinga,calendar,fmp,newsapi_ai"

        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")

        assert "PROVIDER_COUNT = 1" in pine_text
        assert 'STALE_PROVIDERS = "benzinga,calendar,fmp,newsapi_ai"' in pine_text

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_real_enrichment_renders_to_pine(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        for field in V5_FIELD_INVENTORY:
            assert field in pine_text, f"Missing v5 field from real enrichment: {field}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_rendered_regime_matches_enrichment(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        regime_value = enrichment["regime"]["regime"]
        assert f'MARKET_REGIME = "{regime_value}"' in pine_text

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_rendered_library_contains_non_default_macro_bias_and_sector_breadth(self, mock_make, base_csv, tmp_path):
        fmp = _make_mock_fmp()
        fmp.get_macro_calendar.return_value = [
            {
                "country": "US",
                "currency": "USD",
                "date": "2026-03-28",
                "event": "Core CPI MoM",
                "actual": 0.3,
                "consensus": 0.2,
                "impact": "High",
            }
        ]
        mock_make.return_value = fmp

        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")

        assert "MACRO_BIAS = -0.5" in pine_text
        assert "SECTOR_BREADTH = 0.6" in pine_text

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_rendered_provider_count_matches_enrichment(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        count = enrichment["providers"]["provider_count"]
        assert f"PROVIDER_COUNT = {count}" in pine_text

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_volume_low_tickers_rendered_from_real_derivation(self, mock_make, tmp_path):
        """Build enrichment with a snapshot containing a low-ADV ticker,
        then verify it appears in the generated Pine VOLUME_LOW_TICKERS."""
        mock_make.return_value = _make_mock_fmp()
        snapshot = _snapshot_df(
            symbols=["AAPL", "PENNY"],
            adv_overrides={"PENNY": 500_000.0},
        )
        csv_path = tmp_path / "base_snapshot.csv"
        snapshot.to_csv(csv_path, index=False)

        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "PENNY"],
            enrich_regime=True,
            base_snapshot=snapshot,
        )
        result = generate_pine_library_from_base(
            base_csv_path=csv_path,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        vol_match = re.search(r'VOLUME_LOW_TICKERS = "([^"]*)"', pine_text)
        assert vol_match is not None
        assert "PENNY" in vol_match.group(1)


# ── 5. Stale-provider fallback behavior ────────────────────────────


class TestStaleProviderBehavior:
    """Tests that prove the real provider chain delivers correct metadata
    when individual sub-providers fail.
    """

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_vix_failure_still_classifies_regime(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_index_quote.side_effect = RuntimeError("VIX down")
        mock_make.return_value = fmp
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        # Regime domain should still succeed (vix_level=None path)
        assert result["regime"]["regime"] in ("RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL")
        assert "fmp_vix" in result["providers"]["stale_providers"]

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_sector_failure_still_classifies_regime(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_sector_performance.side_effect = RuntimeError("Sectors down")
        mock_make.return_value = fmp
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        assert "fmp_sectors" in result["providers"]["stale_providers"]
        assert result["regime"]["regime"] in ("RISK_ON", "RISK_OFF", "ROTATION", "NEUTRAL")

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_earnings_failure_records_stale(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_earnings_calendar.side_effect = RuntimeError("Earnings down")
        mock_make.return_value = fmp
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_calendar=True,
        )
        assert "fmp_earnings" in result["providers"]["stale_providers"]
        # Calendar domain still resolves with defaults
        assert "calendar" in result

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_all_vix_and_sectors_fail_regime_still_resolves(self, mock_make):
        fmp = _make_mock_fmp()
        fmp.get_index_quote.side_effect = RuntimeError("VIX down")
        fmp.get_sector_performance.side_effect = RuntimeError("Sectors down")
        mock_make.return_value = fmp
        result = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
        )
        stale = result["providers"]["stale_providers"]
        assert "fmp_vix" in stale
        assert "fmp_sectors" in stale
        # Should fall to NEUTRAL with no data
        assert result["regime"]["regime"] == "NEUTRAL"


# ── 6. Smoke: full v4 pipeline end-to-end ───────────────────────────


class TestSmokeFullV4Pipeline:
    """Smoke test: the automated generation path produces the complete
    v4 field set with correct Pine syntax.
    """

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_full_pipeline_produces_all_37_fields(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()

        # 1. Build enrichment (real orchestration)
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )

        # 2. Generate Pine library (real generation)
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )

        pine_text = result["pine_path"].read_text(encoding="utf-8")

        # 3. Verify all v5 fields
        for field in V5_FIELD_INVENTORY:
            assert field in pine_text, f"Smoke: missing v5 field: {field}"

        # 4. Verify field count
        export_lines = [ln for ln in pine_text.splitlines() if ln.startswith("export const")]
        assert len(export_lines) == len(V5_FIELD_INVENTORY), (
            f"Expected {len(V5_FIELD_INVENTORY)} exports, got {len(export_lines)}"
        )

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_full_pipeline_no_unexpected_fields(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        export_lines = [ln for ln in pine_text.splitlines() if ln.startswith("export const")]
        found_names = set()
        for line in export_lines:
            parts = line.split(" = ", 1)[0].split()
            if len(parts) >= 4:
                found_names.add(parts[3])
        unexpected = found_names - set(V5_FIELD_INVENTORY)
        assert not unexpected, f"Unexpected export fields: {unexpected}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_full_pipeline_valid_pine_syntax(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL", "TSLA", "META"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        assert pine_text.startswith("//@version=6\n")
        export_pat = re.compile(r'^export const (string|int|float|bool) [A-Z0-9_]+ = .+')
        for line in pine_text.splitlines():
            if line.startswith("export const"):
                assert export_pat.match(line), f"Invalid export syntax: {line}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_full_pipeline_no_python_booleans(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        result = generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        pine_text = result["pine_path"].read_text(encoding="utf-8")
        for line in pine_text.splitlines():
            if "const bool " in line:
                assert "True" not in line and "False" not in line, (
                    f"Python boolean leaked into Pine: {line}"
                )

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_full_pipeline_manifest_enrichment_blocks(self, mock_make, base_csv, tmp_path):
        mock_make.return_value = _make_mock_fmp()
        enrichment = build_enrichment(
            fmp_api_key="test-key",
            symbols=["AAPL"],
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
            base_snapshot=_snapshot_df(),
        )
        generate_pine_library_from_base(
            base_csv_path=base_csv,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            enrichment=enrichment,
        )
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        assert manifest_files
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        blocks = manifest.get("enrichment_blocks", [])
        for expected in ("regime", "news", "calendar", "layering", "providers", "volume_regime", "meta"):
            assert expected in blocks, f"Manifest missing enrichment block: {expected}"

    @patch("scripts.generate_smc_micro_base_from_databento._make_fmp_client")
    def test_finalize_pipeline_full_round_trip(self, mock_make, base_result, tmp_path):
        """Exercises the complete finalize_pipeline → Pine → artifact round-trip."""
        mock_make.return_value = _make_mock_fmp()
        result = finalize_pipeline(
            base_result=base_result,
            schema_path=SCHEMA_PATH,
            output_root=tmp_path,
            fmp_api_key="test-key",
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=True,
            enrich_layering=True,
        )
        assert result["status"] == "ok"
        assert result["symbols_count"] == 3
        assert result["stale_providers"] == ""

        # Verify Pine content
        pine_text = Path(result["pine_paths"]["pine_path"]).read_text(encoding="utf-8")
        export_lines = [ln for ln in pine_text.splitlines() if ln.startswith("export const")]
        assert len(export_lines) == len(V5_FIELD_INVENTORY)

        # Verify manifest
        manifest_files = list(tmp_path.rglob("smc_micro_profiles_generated.json"))
        assert manifest_files
        manifest = json.loads(manifest_files[0].read_text(encoding="utf-8"))
        assert manifest.get("library_field_version") == "v7.0a"
