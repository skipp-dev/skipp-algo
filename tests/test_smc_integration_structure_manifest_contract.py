from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from smc_integration.structure_batch import write_structure_artifacts_from_workbook

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def _sample_symbols(limit: int = 2) -> list[str]:
    daily = pd.read_excel(WORKBOOK, sheet_name="daily_bars")
    symbols = sorted({str(item).strip().upper() for item in daily["symbol"].dropna().tolist() if str(item).strip()})
    return symbols[:limit]


def test_structure_manifest_contract_has_profile_version_and_aggregates() -> None:
    symbols = _sample_symbols(2)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_contract"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
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

    payload = json.loads((ROOT / first["artifact_path"]).read_text(encoding="utf-8"))
    assert first["structure_profile_used"] == payload["diagnostics"]["structure_profile_used"]
    assert first["event_logic_version"] == payload["diagnostics"]["event_logic_version"]


def test_structure_manifest_contract_is_deterministic() -> None:
    symbols = _sample_symbols(1)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_contract_stable"
    output_dir.mkdir(parents=True, exist_ok=True)

    one = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="hybrid_default",
    )
    two = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="hybrid_default",
    )

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
