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
    if len(symbols) < limit:
        raise AssertionError("workbook daily_bars must contain enough symbols")
    return symbols[:limit]


def test_structure_batch_writes_one_artifact_per_symbol() -> None:
    symbols = _sample_symbols(limit=2)
    output_dir = ROOT / "reports" / "_tmp_structure_batch_test"
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
    assert manifest["counts"]["errors"] == 0

    for symbol in symbols:
        path = output_dir / f"{symbol}_15m.structure.json"
        assert path.exists()


def test_structure_batch_file_naming_is_deterministic() -> None:
    symbols = _sample_symbols(limit=2)
    output_dir = ROOT / "reports" / "_tmp_structure_batch_names"
    output_dir.mkdir(parents=True, exist_ok=True)

    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    names = sorted(item.name for item in output_dir.glob("*.structure.json"))
    assert names == sorted([f"{symbols[0]}_15m.structure.json", f"{symbols[1]}_15m.structure.json"])


def test_structure_batch_is_stable_for_fixed_generated_at() -> None:
    symbols = _sample_symbols(limit=1)

    out_one = ROOT / "reports" / "_tmp_structure_batch_stable_one"
    out_two = ROOT / "reports" / "_tmp_structure_batch_stable_two"
    out_one.mkdir(parents=True, exist_ok=True)
    out_two.mkdir(parents=True, exist_ok=True)

    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=out_one,
        generated_at=1709254000.0,
    )
    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=out_two,
        generated_at=1709254000.0,
    )

    one_payload = json.loads((out_one / f"{symbols[0]}_15m.structure.json").read_text(encoding="utf-8"))
    two_payload = json.loads((out_two / f"{symbols[0]}_15m.structure.json").read_text(encoding="utf-8"))
    assert one_payload == two_payload


def test_structure_batch_keeps_categories_honest() -> None:
    symbols = _sample_symbols(limit=1)
    output_dir = ROOT / "reports" / "_tmp_structure_batch_honest"
    output_dir.mkdir(parents=True, exist_ok=True)

    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
    )

    payload = json.loads((output_dir / f"{symbols[0]}_15m.structure.json").read_text(encoding="utf-8"))
    structure = payload["structure"]
    coverage = payload["coverage"]

    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert payload["coverage_mode"] in {"full", "partial", "none"}
    assert coverage["has_bos"] == bool(structure["bos"])
    assert coverage["has_orderblocks"] == bool(structure["orderblocks"])
    assert coverage["has_fvg"] == bool(structure["fvg"])
    assert coverage["has_liquidity_sweeps"] == bool(structure["liquidity_sweeps"])


def test_structure_batch_records_selected_profile_in_source() -> None:
    symbols = _sample_symbols(limit=1)
    output_dir = ROOT / "reports" / "_tmp_structure_batch_profile"
    output_dir.mkdir(parents=True, exist_ok=True)

    write_structure_artifacts_from_workbook(
        workbook=WORKBOOK,
        timeframe="15m",
        symbols=symbols,
        output_dir=output_dir,
        generated_at=1709254000.0,
        structure_profile="conservative",
    )

    payload = json.loads((output_dir / f"{symbols[0]}_15m.structure.json").read_text(encoding="utf-8"))
    assert payload["source"]["structure_profile"] == "conservative"
