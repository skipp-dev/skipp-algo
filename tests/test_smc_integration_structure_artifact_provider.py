from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_smc_structure_artifact import export_structure_artifact
from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from smc_adapters import build_structure_from_raw
from smc_core.schema_version import SCHEMA_VERSION
from smc_integration.sources import structure_artifact_json

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def test_structure_artifact_provider_loads_explicit_structure(monkeypatch, tmp_path: Path) -> None:
    artifact_path = tmp_path / "smc_structure_artifact.json"
    export_structure_artifact(
        workbook=WORKBOOK_PATH,
        output=artifact_path,
        generated_at=1709253600.0,
    )

    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", artifact_path)

    payload = structure_artifact_json._load_payload()  # noqa: SLF001
    entry = next((item for item in payload["entries"] if item["structure"]["bos"]), payload["entries"][0])
    symbol = str(entry["symbol"])

    raw_structure = structure_artifact_json.load_raw_structure_input(symbol, "15m")
    structure = build_structure_from_raw(raw_structure)

    assert set(raw_structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure.bos, list)
    assert isinstance(structure.orderblocks, list)
    assert isinstance(structure.fvg, list)
    assert isinstance(structure.liquidity_sweeps, list)


def test_structure_artifact_provider_has_no_meta_domain() -> None:
    with pytest.raises(ValueError, match="does not provide raw meta"):
        structure_artifact_json.load_raw_meta_input("AAPL", "15m")


def test_structure_artifact_provider_resolves_manifest_artifact(monkeypatch, tmp_path: Path) -> None:
    artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK_PATH,
        timeframe="15m",
        symbols=["AAPL"],
        output_dir=artifact_dir,
        generated_at=1709253600.0,
    )
    assert manifest["counts"]["artifacts_written"] == 1

    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

    raw_structure = structure_artifact_json.load_raw_structure_input("AAPL", "15m")
    structure = build_structure_from_raw(raw_structure)

    assert set(raw_structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert isinstance(structure.bos, list)


def test_structure_artifact_provider_category_coverage_is_honest(monkeypatch, tmp_path: Path) -> None:
    artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK_PATH,
        timeframe="15m",
        symbols=["AAPL"],
        output_dir=artifact_dir,
        generated_at=1709253600.0,
    )

    monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
    monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

    coverage = structure_artifact_json.discover_category_coverage()
    assert set(coverage.keys()) == {"bos", "choch", "orderblocks", "fvg", "liquidity_sweeps"}
    assert coverage["bos"] is True
    assert coverage["choch"] is True
    assert isinstance(coverage["orderblocks"], bool)
    assert isinstance(coverage["fvg"], bool)
    assert isinstance(coverage["liquidity_sweeps"], bool)


def test_structure_artifact_provider_coverage_ignores_empty_bos_lists(monkeypatch, tmp_path: Path) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = artifact_dir / "AAPL_15m.structure.json"
        artifact_path.write_text(
                f"""
{{
    "schema_version": "{SCHEMA_VERSION}",
    "generated_at": 1709253600.0,
    "symbol": "AAPL",
    "timeframe": "15m",
    "source": {{
        "workbook_path": "x",
        "canonical_upstream": "workbook_fallback",
        "sheet": "daily_bars",
        "event_logic": "scripts.explicit_structure_from_bars.build_full_structure_from_bars"
    }},
    "coverage_mode": "none",
    "coverage": {{
        "mode": "none",
        "has_bos": false,
        "has_orderblocks": false,
        "has_fvg": false,
        "has_liquidity_sweeps": false
    }},
    "event_evidence": {{
        "last_event": "none",
        "trend_state": 0,
        "reference_close": 100.0
    }},
    "structure": {{
        "bos": [],
        "orderblocks": [],
        "fvg": [],
        "liquidity_sweeps": []
    }}
}}
""".strip()
                + "\n",
                encoding="utf-8",
        )

        manifest_path = artifact_dir / "manifest_15m.json"
        manifest_path.write_text(
                json.dumps({
                    "schema_version": SCHEMA_VERSION,
                    "generated_at": 1709253600.0,
                    "timeframe": "15m",
                    "producer": {"name": "test", "upstream": "x"},
                    "counts": {"symbols_requested": 1, "artifacts_written": 1, "errors": 0},
                    "artifacts": [{
                        "symbol": "AAPL",
                        "timeframe": "15m",
                        "artifact_path": "reports/smc_structure_artifacts/AAPL_15m.structure.json",
                        "coverage_mode": "none",
                        "has_bos": False,
                        "has_orderblocks": False,
                        "has_fvg": False,
                        "has_liquidity_sweeps": False,
                    }],
                    "errors": [],
                }, indent=4) + "\n",
                encoding="utf-8",
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

        coverage = structure_artifact_json.discover_category_coverage()
        assert coverage["bos"] is False
        assert coverage["choch"] is False


def test_structure_artifact_provider_manifest_row_with_missing_path_is_not_silent(monkeypatch, tmp_path: Path) -> None:
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
                            "artifact_path": "reports/smc_structure_artifacts/DOES_NOT_EXIST.structure.json",
                        }
                    ],
                }, indent=4) + "\n",
                encoding="utf-8",
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

        with pytest.raises(ValueError, match="artifact_path does not exist"):
                structure_artifact_json.load_raw_structure_input("AAPL", "15m")


def test_structure_artifact_provider_detects_symbol_mismatch(monkeypatch, tmp_path: Path) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = artifact_dir / "AAPL_15m.structure.json"
        artifact_path.write_text(
                """
{
    "symbol": "MSFT",
    "timeframe": "15m",
    "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
    "auxiliary": {},
    "diagnostics": {}
}
""".strip()
                + "\n",
                encoding="utf-8",
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

        with pytest.raises(ValueError, match="symbol mismatch"):
                structure_artifact_json.load_raw_structure_input("AAPL", "15m")


def test_structure_artifact_provider_detects_timeframe_mismatch(monkeypatch, tmp_path: Path) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        artifact_path = artifact_dir / "AAPL_15m.structure.json"
        artifact_path.write_text(
                """
{
    "symbol": "AAPL",
    "timeframe": "1D",
    "structure": {"bos": [], "orderblocks": [], "fvg": [], "liquidity_sweeps": []},
    "auxiliary": {},
    "diagnostics": {}
}
""".strip()
                + "\n",
                encoding="utf-8",
        )

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

        with pytest.raises(ValueError, match="timeframe mismatch"):
                structure_artifact_json.load_raw_structure_input("AAPL", "15m")


def test_discover_normalized_contract_summary_reports_manifest_health_issues(monkeypatch, tmp_path: Path) -> None:
        artifact_dir = tmp_path / "reports" / "smc_structure_artifacts"
        artifact_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = artifact_dir / "manifest_15m.json"
        manifest_path.write_text("{ not-valid-json", encoding="utf-8")

        monkeypatch.setattr(structure_artifact_json, "REPO_ROOT", tmp_path)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACTS_DIR", artifact_dir)
        monkeypatch.setattr(structure_artifact_json, "STRUCTURE_ARTIFACT_JSON", tmp_path / "does_not_exist.json")

        summary = structure_artifact_json.discover_normalized_contract_summary()

        assert summary["mapped_structure_categories"]["bos"] is False
        assert summary["mapped_structure_categories"]["choch"] is False
        assert summary["health"]["issue_count"] >= 1
        codes = {str(item.get("code", "")) for item in summary["health"]["issues"]}
        assert "INVALID_MANIFEST_JSON" in codes
