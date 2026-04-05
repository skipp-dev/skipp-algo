"""Regression tests for finalize_pipeline() and the end-to-end CLI flow.

Verifies that:
- ``--run-scan`` no longer returns early and instead produces enriched Pine output
- ``--bundle`` path flows through finalize_pipeline identically
- finalize_pipeline returns a well-structured result dict
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


# ── Helpers ─────────────────────────────────────────────────────

def _fake_base_result(tmp_path: Path) -> dict[str, Any]:
    """Minimal base_result dict matching the contract from generate_base_from_bundle."""
    csv_path = tmp_path / "base.csv"
    df = pd.DataFrame({"symbol": ["AAPL", "MSFT", "TSLA"], "close": [150.0, 300.0, 250.0]})
    df.to_csv(csv_path, index=False)
    return {
        "output_paths": {"base_csv": csv_path},
        "base_snapshot": df,
        "mapping_payload": {},
    }


def _fake_pine_paths() -> dict[str, Path]:
    return {"library": Path("out/library.pine"), "indicator": Path("out/indicator.pine")}


def _write_real_bundle(tmp_path: Path) -> Path:
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir(parents=True, exist_ok=True)
    base_prefix = "databento_volatility_production_fake"
    manifest_path = bundle_dir / f"{base_prefix}_manifest.json"

    daily_features = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "company_name": "Alpha Holdings",
                "asset_type": "stock",
                "market_cap": 3_200_000_000,
                "day_open": 10.0,
                "day_high": 10.8,
                "day_low": 9.7,
                "day_close": 10.5,
                "day_volume": 1_500_000,
                "previous_close": 9.8,
                "close_trade_hygiene_score": 0.82,
                "reclaimed_start_price_within_30s": True,
                "early_dip_pct_10s": -0.8,
                "open_to_current_pct": 1.6,
                "window_return_pct": 1.6,
                "close_preclose_return_pct": 0.4,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "exchange": "NASDAQ",
                "company_name": "Alpha Holdings",
                "asset_type": "stock",
                "market_cap": 3_200_000_000,
                "day_open": 10.7,
                "day_high": 11.2,
                "day_low": 10.1,
                "day_close": 10.4,
                "day_volume": 1_900_000,
                "previous_close": 10.5,
                "close_trade_hygiene_score": 0.76,
                "reclaimed_start_price_within_30s": False,
                "early_dip_pct_10s": -1.0,
                "open_to_current_pct": -0.5,
                "window_return_pct": -0.5,
                "close_preclose_return_pct": -0.3,
            },
        ]
    )
    daily_bars = daily_features[
        ["trade_date", "symbol", "day_open", "day_high", "day_low", "day_close", "day_volume", "previous_close"]
    ].rename(
        columns={
            "day_open": "open",
            "day_high": "high",
            "day_low": "low",
            "day_close": "close",
            "day_volume": "volume",
        }
    )
    session_minute_detail = pd.DataFrame(
        [
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T13:30:00Z"),
                "session": "regular",
                "open": 10.0,
                "high": 10.2,
                "low": 9.9,
                "close": 10.1,
                "volume": 50_000,
                "trade_count": 75,
            },
            {
                "trade_date": "2026-03-19",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-19T21:10:00Z"),
                "session": "afterhours",
                "open": 10.5,
                "high": 10.55,
                "low": 10.45,
                "close": 10.48,
                "volume": 18_000,
                "trade_count": 20,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T13:30:00Z"),
                "session": "regular",
                "open": 10.7,
                "high": 10.8,
                "low": 10.5,
                "close": 10.6,
                "volume": 80_000,
                "trade_count": 95,
            },
            {
                "trade_date": "2026-03-20",
                "symbol": "AAA",
                "timestamp": pd.Timestamp("2026-03-20T21:25:00Z"),
                "session": "afterhours",
                "open": 10.35,
                "high": 10.4,
                "low": 10.2,
                "close": 10.28,
                "volume": 21_000,
                "trade_count": 22,
            },
        ]
    )

    manifest_path.write_text(
        json.dumps({"trade_dates_covered": ["2026-03-19", "2026-03-20"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    daily_bars.to_parquet(bundle_dir / f"{base_prefix}__daily_bars.parquet", index=False)
    daily_features.to_parquet(bundle_dir / f"{base_prefix}__daily_symbol_features_full_universe.parquet", index=False)
    session_minute_detail.to_parquet(bundle_dir / f"{base_prefix}__session_minute_detail_full_universe.parquet", index=False)
    return manifest_path


# ── finalize_pipeline unit tests ────────────────────────────────

class TestFinalizePipeline:
    """Unit tests for the finalize_pipeline orchestration helper."""

    @patch("scripts.generate_smc_micro_base_from_databento.export_live_news_snapshot")
    @patch("scripts.generate_smc_micro_base_from_databento.resolve_live_news_symbols")
    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_live_news_sidecar_emitted_when_enabled(self, mock_enrich, mock_pine, mock_resolve, mock_export, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = None
        mock_pine.return_value = _fake_pine_paths()
        mock_resolve.return_value = (["AAPL", "MSFT"], {"mode": "base_csv"})
        mock_export.return_value = {
            "summary": {
                "active_story_count": 2,
                "new_story_count": 1,
                "actionable_symbols": ["AAPL"],
            },
            "providers": {
                "benzinga": {"error": ""},
                "fmp_stock": {"error": ""},
            },
            "symbol_scope": {"mode": "base_csv"},
        }
        base_result = _fake_base_result(tmp_path)

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
            emit_live_news_snapshot=True,
        )

        assert result["live_news_snapshot"]["status"] == "ok"
        assert result["live_news_snapshot"]["active_story_count"] == 2
        assert result["live_news_snapshot"]["actionable_symbols"] == ["AAPL"]
        assert mock_resolve.call_args.kwargs["base_csv_path"] == base_result["output_paths"]["base_csv"]
        assert mock_export.call_args.kwargs["output_path"] == tmp_path / "smc_live_news_snapshot.json"
        assert mock_export.call_args.kwargs["state_path"] == tmp_path / "smc_live_news_state.json"

    @patch("scripts.generate_smc_micro_base_from_databento.export_live_news_snapshot")
    @patch("scripts.generate_smc_micro_base_from_databento.resolve_live_news_symbols")
    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_live_news_sidecar_failure_is_non_blocking(self, mock_enrich, mock_pine, mock_resolve, mock_export, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = None
        mock_pine.return_value = _fake_pine_paths()
        mock_resolve.return_value = (["AAPL"], {"mode": "base_csv"})
        mock_export.side_effect = RuntimeError("live lane down")

        result = finalize_pipeline(
            base_result=_fake_base_result(tmp_path),
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
            emit_live_news_snapshot=True,
        )

        assert result["status"] == "ok"
        assert result["live_news_snapshot"]["status"] == "error"
        assert "RuntimeError: live lane down" in result["live_news_snapshot"]["error"]

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_returns_structured_result(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = {"regime": {"regime": "RISK_ON"}}
        mock_pine.return_value = _fake_pine_paths()
        base_result = _fake_base_result(tmp_path)

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
        )

        assert result["status"] == "ok"
        assert result["symbols_count"] == 3
        assert "regime" in result["enrichment_keys"]
        assert "library" in result["pine_paths"]
        assert isinstance(result["base_result_keys"], list)

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_no_enrichment_when_flags_off(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = None
        mock_pine.return_value = _fake_pine_paths()
        base_result = _fake_base_result(tmp_path)

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
        )

        assert result["status"] == "ok"
        assert result["enrichment_keys"] == []
        assert result["stale_providers"] == ""
        mock_enrich.assert_called_once()
        mock_pine.assert_called_once()

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_enrichment_flags_forwarded(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = {"regime": {}, "news": {}}
        mock_pine.return_value = _fake_pine_paths()
        base_result = _fake_base_result(tmp_path)

        finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
            enrich_regime=True,
            enrich_news=True,
            enrich_calendar=False,
            enrich_layering=False,
            enrich_session_context=True,
            enrich_order_blocks=True,
        )

        call_kwargs = mock_enrich.call_args.kwargs
        assert call_kwargs["enrich_regime"] is True
        assert call_kwargs["enrich_news"] is True
        assert call_kwargs["enrich_calendar"] is False
        assert call_kwargs["enrich_layering"] is False
        assert call_kwargs["enrich_session_context"] is True
        assert call_kwargs["enrich_order_blocks"] is True

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_finalize_pipeline_forwards_newsapi_key(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = {"news": {}}
        mock_pine.return_value = _fake_pine_paths()

        finalize_pipeline(
            base_result=_fake_base_result(tmp_path),
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
            newsapi_ai_key="news-key",
            enrich_news=True,
        )

        assert mock_enrich.call_args.kwargs["newsapi_ai_key"] == "news-key"

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_pine_paths_serializable(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = None
        mock_pine.return_value = _fake_pine_paths()
        base_result = _fake_base_result(tmp_path)

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
        )

        # Must be JSON-serializable (no Path objects)
        serialized = json.dumps(result)
        assert "library" in serialized

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_stale_providers_populated(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = {
            "regime": {},
            "providers": {"stale_providers": "news,calendar"},
        }
        mock_pine.return_value = _fake_pine_paths()
        base_result = _fake_base_result(tmp_path)

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
        )

        assert result["stale_providers"] == "news,calendar"

    @patch("scripts.generate_smc_micro_base_from_databento.generate_pine_library_from_base")
    @patch("scripts.generate_smc_micro_base_from_databento.build_enrichment")
    def test_symbols_sorted(self, mock_enrich, mock_pine, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import finalize_pipeline

        mock_enrich.return_value = None
        mock_pine.return_value = _fake_pine_paths()
        csv_path = tmp_path / "base.csv"
        df = pd.DataFrame({"symbol": ["TSLA", "AAPL", "MSFT"], "close": [1, 2, 3]})
        df.to_csv(csv_path, index=False)
        base_result = {"output_paths": {"base_csv": csv_path}, "base_snapshot": df}

        result = finalize_pipeline(
            base_result=base_result,
            schema_path=Path("schema/smc_microstructure_base.json"),
            output_root=tmp_path,
        )

        # Symbols passed to build_enrichment should be sorted
        symbols_arg = mock_enrich.call_args.kwargs["symbols"]
        assert symbols_arg == ["AAPL", "MSFT", "TSLA"]


# ── main() integration tests ───────────────────────────────────

class TestMainRunScan:
    """Verify --run-scan now flows through finalize_pipeline."""

    @patch("scripts.generate_smc_micro_base_from_databento.finalize_pipeline")
    @patch("scripts.generate_smc_micro_base_from_databento.run_databento_base_scan_pipeline")
    def test_run_scan_calls_finalize(self, mock_scan, mock_finalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        mock_scan.return_value = _fake_base_result(tmp_path)
        mock_finalize.return_value = {"status": "ok"}

        test_args = [
            "--run-scan",
            "--databento-api-key", "test-key",
            "--fmp-api-key", "test-fmp",
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            main()

        mock_scan.assert_called_once()
        mock_finalize.assert_called_once()
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["base_result"] is mock_scan.return_value
        assert call_kwargs["emit_live_news_snapshot"] is True

    @patch("scripts.generate_smc_micro_base_from_databento.finalize_pipeline")
    @patch("scripts.generate_smc_micro_base_from_databento.run_databento_base_scan_pipeline")
    def test_run_scan_passes_enrichment_flags(self, mock_scan, mock_finalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        mock_scan.return_value = _fake_base_result(tmp_path)
        mock_finalize.return_value = {"status": "ok"}

        test_args = [
            "--run-scan",
            "--databento-api-key", "test-key",
            "--enrich-regime",
            "--enrich-news",
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            main()

        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["enrich_regime"] is True
        assert call_kwargs["enrich_news"] is True
        assert call_kwargs["enrich_calendar"] is False

    @patch("scripts.generate_smc_micro_base_from_databento.finalize_pipeline")
    @patch("scripts.generate_smc_micro_base_from_databento.run_databento_base_scan_pipeline")
    def test_run_scan_enrich_all(self, mock_scan, mock_finalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        mock_scan.return_value = _fake_base_result(tmp_path)
        mock_finalize.return_value = {"status": "ok"}

        test_args = [
            "--run-scan",
            "--databento-api-key", "test-key",
            "--enrich-all",
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            main()

        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["enrich_regime"] is True
        assert call_kwargs["enrich_news"] is True
        assert call_kwargs["enrich_calendar"] is True
        assert call_kwargs["enrich_layering"] is True
        assert call_kwargs["enrich_event_risk"] is True
        assert call_kwargs["enrich_flow_qualifier"] is True
        assert call_kwargs["enrich_compression_regime"] is True
        assert call_kwargs["enrich_session_context"] is True
        assert call_kwargs["enrich_order_blocks"] is True
        assert call_kwargs["enrich_structure_state"] is True
        assert call_kwargs["enrich_range_profile_regime"] is True

    @patch("scripts.generate_smc_micro_base_from_databento.finalize_pipeline")
    @patch("scripts.generate_smc_micro_base_from_databento.run_databento_base_scan_pipeline")
    def test_run_scan_passes_newsapi_key(self, mock_scan, mock_finalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        mock_scan.return_value = _fake_base_result(tmp_path)
        mock_finalize.return_value = {"status": "ok"}

        test_args = [
            "--run-scan",
            "--databento-api-key", "test-key",
            "--newsapi-ai-key", "news-key",
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            main()

        assert mock_finalize.call_args.kwargs["newsapi_ai_key"] == "news-key"


class TestMainBundle:
    """Verify --bundle path also flows through finalize_pipeline."""

    def test_bundle_runs_real_generation_before_finalize(self, tmp_path, monkeypatch):
        from scripts import generate_smc_micro_base_from_databento as cli

        manifest_path = _write_real_bundle(tmp_path)
        output_dir = tmp_path / "output"
        captured: dict[str, Path] = {}

        def _fake_generate_pine_library_from_base(*, base_csv_path: Path, output_root: Path, **_: Any) -> dict[str, Path]:
            captured["base_csv_path"] = base_csv_path
            library_path = output_root / "pine" / "generated" / "smc_micro_profiles_generated.pine"
            library_path.parent.mkdir(parents=True, exist_ok=True)
            library_path.write_text("// synthetic test library\n", encoding="utf-8")
            return {"library": library_path}

        monkeypatch.setattr(cli, "build_enrichment", lambda **_: None)
        monkeypatch.setattr(cli, "generate_pine_library_from_base", _fake_generate_pine_library_from_base)
        monkeypatch.setattr(
            cli,
            "_export_live_news_sidecar",
            lambda **_: {"status": "ok", "snapshot_path": str(output_dir / "smc_live_news_snapshot.json")},
        )

        test_args = [
            "--bundle", str(manifest_path),
            "--export-dir", str(output_dir),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            cli.main()

        base_csv_candidates = sorted(output_dir.glob("*__smc_microstructure_base_*.csv"))
        base_manifest_candidates = sorted(output_dir.glob("*__smc_microstructure_base_manifest.json"))
        mapping_candidates = sorted(output_dir.glob("*__smc_microstructure_mapping_*.json"))

        assert len(base_csv_candidates) == 1
        assert len(base_manifest_candidates) == 1
        assert len(mapping_candidates) == 1
        assert captured["base_csv_path"] == base_csv_candidates[0]

        base_frame = pd.read_csv(base_csv_candidates[0])
        assert list(base_frame["symbol"]) == ["AAA"]
        assert int(base_frame.loc[0, "history_coverage_days_20d"]) == 2

        manifest_payload = json.loads(base_manifest_candidates[0].read_text(encoding="utf-8"))
        assert manifest_payload["canonical_upstream_artifact"] == "databento_production_export_bundle"
        assert manifest_payload["bundle_manifest_path"].endswith("databento_volatility_production_fake_manifest.json")


class TestMainMissingArgs:
    """Verify appropriate errors for missing arguments."""

    def test_run_scan_without_databento_key_raises(self, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        test_args = [
            "--run-scan",
            "--databento-api-key", "",
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            with pytest.raises(ValueError, match="Databento API key"):
                main()
