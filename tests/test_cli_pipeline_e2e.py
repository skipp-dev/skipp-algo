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


# ── finalize_pipeline unit tests ────────────────────────────────

class TestFinalizePipeline:
    """Unit tests for the finalize_pipeline orchestration helper."""

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

    @patch("scripts.generate_smc_micro_base_from_databento.finalize_pipeline")
    @patch("scripts.generate_smc_micro_base_from_databento.generate_base_from_bundle")
    def test_bundle_calls_finalize(self, mock_bundle, mock_finalize, tmp_path):
        from scripts.generate_smc_micro_base_from_databento import main

        mock_bundle.return_value = _fake_base_result(tmp_path)
        mock_finalize.return_value = {"status": "ok"}

        test_args = [
            "--bundle", str(tmp_path / "some_bundle"),
            "--export-dir", str(tmp_path),
        ]
        with patch("sys.argv", ["prog"] + test_args):
            main()

        mock_bundle.assert_called_once()
        mock_finalize.assert_called_once()
        call_kwargs = mock_finalize.call_args.kwargs
        assert call_kwargs["base_result"] is mock_bundle.return_value


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
