from __future__ import annotations

from pathlib import Path

import pytest

from scripts.export_smc_structure_artifact import export_structure_artifact
from smc_adapters import build_structure_from_raw
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
    assert structure.orderblocks == []
    assert structure.fvg == []
    assert structure.liquidity_sweeps == []


def test_structure_artifact_provider_has_no_meta_domain() -> None:
    with pytest.raises(ValueError, match="does not provide raw meta"):
        structure_artifact_json.load_raw_meta_input("AAPL", "15m")
