from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from smc_integration.structure_batch import write_structure_artifacts_from_workbook
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]


def _sample_symbols(workbook: Path, limit: int = 2) -> list[str]:
    daily = pd.read_excel(workbook, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[:limit]


def test_structure_manifest_contract_has_profile_version_and_aggregates(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, 2)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_contract"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="conservative",
    )

    assert "coverage_summary" in manifest
    assert "profile_summary" in manifest
    assert "event_logic_versions" in manifest

    assert manifest["profile_summary"] == {"conservative": 2}
    assert manifest["event_logic_versions"] == ["v2"]

    cov = manifest["coverage_summary"]
    assert set(cov.keys()) == {
        "symbols_with_bos",
        "symbols_with_orderblocks",
        "symbols_with_fvg",
        "symbols_with_liquidity_sweeps",
    }

    first = manifest["artifacts"][0]
    assert set(first.keys()) >= {
        "symbol",
        "timeframe",
        "artifact_path",
        "structure_profile_used",
        "event_logic_version",
        "has_bos",
        "has_orderblocks",
        "has_fvg",
        "has_liquidity_sweeps",
        "bos_count",
        "orderblocks_count",
        "fvg_count",
        "liquidity_sweeps_count",
        "warnings_count",
    }

    payload = json.loads((tmp_path / first["artifact_path"]).read_text(encoding="utf-8"))
    assert first["structure_profile_used"] == payload["diagnostics"]["structure_profile_used"]
    assert first["event_logic_version"] == payload["diagnostics"]["event_logic_version"]


def test_structure_manifest_contract_is_deterministic(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    symbols = _sample_symbols(workbook, 1)
    output_dir = tmp_path / "reports" / "_tmp_structure_manifest_contract_stable"
    output_dir.mkdir(parents=True, exist_ok=True)

    one = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="hybrid_default",
    )
    two = write_structure_artifacts_from_workbook(
        workbook=workbook,
        timeframe="1D",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="hybrid_default",
    )

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
