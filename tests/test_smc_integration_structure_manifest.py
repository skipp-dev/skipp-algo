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


def test_structure_manifest_contains_required_keys() -> None:
    symbols = _sample_symbols(limit=2)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_keys"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert set(["schema_version", "generated_at", "timeframe", "producer", "counts", "artifacts", "errors"]).issubset(set(manifest.keys()))


def test_structure_manifest_counts_and_flags_are_correct() -> None:
    symbols = _sample_symbols(limit=2)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_counts"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["counts"]["symbols_requested"] == 2
    assert manifest["counts"]["artifacts_written"] == 2
    assert manifest["counts"]["errors"] == len(manifest["errors"])

    assert [row["symbol"] for row in manifest["artifacts"]] == sorted(symbols)
    for row in manifest["artifacts"]:
        assert row["coverage_mode"] in {"partial", "none"}
        assert row["has_orderblocks"] is False
        assert row["has_fvg"] is False
        assert row["has_liquidity_sweeps"] is False


def test_structure_manifest_paths_are_deterministic() -> None:
    symbols = _sample_symbols(limit=1)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_paths"
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert manifest["artifacts"][0]["artifact_path"].endswith(f"{symbols[0]}_15m.structure.json")
    assert str(manifest["manifest_path"]).endswith("manifest_15m.json")


def test_structure_manifest_is_json_stable() -> None:
    symbols = _sample_symbols(limit=1)
    output_dir = ROOT / "reports" / "_tmp_structure_manifest_stable"
    output_dir.mkdir(parents=True, exist_ok=True)

    one = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )
    two = write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    assert json.dumps(one, sort_keys=True) == json.dumps(two, sort_keys=True)
