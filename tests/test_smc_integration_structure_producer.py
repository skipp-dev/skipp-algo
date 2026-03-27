from __future__ import annotations

import json
from pathlib import Path

from scripts.export_smc_structure_artifact import (
    build_structure_artifact_payload,
    export_structure_artifact,
)
from smc_core.schema_version import SCHEMA_VERSION

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def test_structure_producer_emits_honest_structure_payload() -> None:
    payload = build_structure_artifact_payload(workbook=WORKBOOK_PATH, generated_at=1709253600.0)

    assert payload["structure_coverage"] in {"full", "partial", "none"}
    assert isinstance(payload["entries"], list)
    assert payload["entries"]

    first = payload["entries"][0]
    structure = first["structure"]
    assert set(structure.keys()) == {"bos", "orderblocks", "fvg", "liquidity_sweeps"}
    assert set(first["auxiliary"].keys()) == {
        "liquidity_lines",
        "session_ranges",
        "session_pivots",
        "ipda_range",
        "htf_fvg_bias",
        "broken_fractal_signals",
    }
    assert first["diagnostics"]["structure_profile_used"] == "hybrid_default"
    assert first["diagnostics"]["event_logic_version"] == "v2"
    assert first["diagnostics"]["counts"]["bos"] == len(structure["bos"])

    assert payload["coverage"]["mode"] in {"full", "partial", "none"}
    assert payload["coverage"]["has_bos"] == any(entry["structure"]["bos"] for entry in payload["entries"])
    assert payload["coverage"]["has_orderblocks"] == any(entry["structure"]["orderblocks"] for entry in payload["entries"])
    assert payload["coverage"]["has_fvg"] == any(entry["structure"]["fvg"] for entry in payload["entries"])
    assert payload["coverage"]["has_liquidity_sweeps"] == any(entry["structure"]["liquidity_sweeps"] for entry in payload["entries"])

    assert first["coverage_detail"]["mode"] == first["coverage"]
    assert first["coverage_detail"]["has_bos"] == bool(structure["bos"])
    assert first["coverage_detail"]["has_orderblocks"] == bool(structure["orderblocks"])
    assert first["coverage_detail"]["has_fvg"] == bool(structure["fvg"])
    assert first["coverage_detail"]["has_liquidity_sweeps"] == bool(structure["liquidity_sweeps"])


def test_structure_producer_can_write_json_artifact(tmp_path: Path) -> None:
    output = tmp_path / "smc_structure_artifact.json"
    written = export_structure_artifact(
        workbook=WORKBOOK_PATH,
        output=output,
        generated_at=1709253600.0,
    )

    assert written == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["source"]["sheet"] == "daily_bars"


def test_structure_producer_records_selected_profile() -> None:
    payload = build_structure_artifact_payload(
        workbook=WORKBOOK_PATH,
        generated_at=1709253600.0,
        structure_profile="conservative",
    )
    assert payload["source"]["structure_profile"] == "conservative"
    assert payload["entries"][0]["diagnostics"]["structure_profile_used"] == "conservative"
