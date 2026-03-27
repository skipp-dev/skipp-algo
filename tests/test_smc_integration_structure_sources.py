from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

import smc_integration.repo_sources as repo_sources_module
from smc_integration.provider_matrix import build_provider_summary
from smc_integration.repo_sources import discover_structure_source_status, load_raw_structure_input
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.service import build_snapshot_bundle_for_symbol_timeframe
from smc_integration.sources import structure_artifact_json


ROOT = Path(__file__).resolve().parents[1]


def _first_symbol() -> str:
    csv_path = ROOT / "reports" / "databento_watchlist_top5_pre1530.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle), None)
    if row is None or not row.get("symbol"):
        raise AssertionError("watchlist CSV must contain at least one symbol")
    return str(row["symbol"]).strip().upper()


def test_structure_source_status_is_deterministic() -> None:
    one = discover_structure_source_status()
    two = discover_structure_source_status()
    assert one == two


def test_structure_status_and_provider_summary_are_honest() -> None:
    status = discover_structure_source_status()
    symbol_status = discover_structure_source_status(symbol=_first_symbol(), timeframe="15m")
    summary = build_provider_summary()

    if status["any_registered_explicit_structure_provider"]:
        assert summary["best_current_structure_provider"] in status["explicit_structure_provider_names"]
    else:
        assert summary["best_current_structure_provider"] is None
        assert status["selected_structure_mode"] in {"partial", "none"}

    assert symbol_status["selected_structure_source"] in {"structure_artifact_json", "databento_watchlist_csv", "fmp_watchlist_json", "tradingview_watchlist_json", "benzinga_watchlist_json"}


def test_no_fabricated_structure_for_partial_source() -> None:
    symbol = _first_symbol()
    raw_structure = load_raw_structure_input(symbol, "15m", source="databento_watchlist_csv")

    assert raw_structure["bos"] == []
    assert raw_structure["orderblocks"] == []
    assert raw_structure["fvg"] == []
    assert raw_structure["liquidity_sweeps"] == []


def test_snapshot_bundle_includes_structure_status() -> None:
    symbol = _first_symbol()
    bundle = build_snapshot_bundle_for_symbol_timeframe(symbol, "15m", generated_at=1709253600.0)

    assert "structure_status" in bundle
    assert isinstance(bundle["structure_status"], dict)
    assert "selected_structure_source" in bundle["structure_status"]


def test_auto_structure_loading_does_not_silently_fallback_on_invalid_manifest_row(
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = artifact_dir / "manifest_15m.json"
        manifest_path.write_text(
                json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "timeframe": "15m",
                    "artifacts": [
                        {
                            "symbol": "AAPL",
                            "timeframe": "15m",
                            "artifact_path": "reports/smc_structure_artifacts/MISSING.structure.json",
                        }
                    ],
                }, indent=4) + "\n",
                encoding="utf-8",
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "missing_legacy.json")

        with pytest.raises(ValueError, match="artifact_path does not exist"):
                repo_sources_module.load_raw_structure_input("AAPL", "15m", source="auto")
