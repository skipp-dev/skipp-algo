from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_smc_structure_artifact import (
    build_structure_artifact_payload,
    export_structure_artifact,
    validate_artifact_provenance,
)
from smc_core.schema_version import SCHEMA_VERSION
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]


def test_structure_producer_emits_honest_structure_payload(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    payload = build_structure_artifact_payload(workbook=workbook, generated_at=1709253600.0)

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
    workbook = make_minimal_workbook(tmp_path)
    output = tmp_path / "smc_structure_artifact.json"
    written = export_structure_artifact(
        workbook=workbook,
        output=output,
        generated_at=1780000000.0,  # after the 2026-03 workbook (provenance guard)
    )

    assert written == output
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == SCHEMA_VERSION
    assert payload["source"]["sheet"] == "daily_bars"


def test_structure_producer_records_selected_profile(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    payload = build_structure_artifact_payload(
        workbook=workbook,
        generated_at=1709253600.0,
        structure_profile="conservative",
    )
    assert payload["source"]["structure_profile"] == "conservative"
    assert payload["entries"][0]["diagnostics"]["structure_profile_used"] == "conservative"


def test_validate_artifact_provenance_rejects_generated_at_before_data() -> None:
    # generated_at 2024-03 over entry asof_ts 2026-03 — the impossible provenance
    # that shipped the stale committed artifact. Must fail closed at write time.
    payload = {"generated_at": 1709253600.0, "entries": [{"asof_ts": 1772755200.0}]}
    with pytest.raises(ValueError, match="impossible provenance"):
        validate_artifact_provenance(payload)


def test_validate_artifact_provenance_accepts_consistent_provenance() -> None:
    payload = {"generated_at": 1772800000.0, "entries": [{"asof_ts": 1772755200.0}]}
    validate_artifact_provenance(payload)  # generated_at >= max asof_ts -> no raise


def test_validate_artifact_provenance_noop_without_bounds() -> None:
    # No entries or no generated_at -> nothing to check, must not raise.
    validate_artifact_provenance({"entries": []})
    validate_artifact_provenance({"generated_at": None, "entries": [{"asof_ts": 1.0}]})


def test_export_structure_artifact_rejects_impossible_provenance(tmp_path: Path) -> None:
    # End-to-end: a 2026 workbook with a 2024 generated_at is refused at write.
    workbook = make_minimal_workbook(tmp_path)
    output = tmp_path / "smc_structure_artifact.json"
    with pytest.raises(ValueError, match="impossible provenance"):
        export_structure_artifact(workbook=workbook, output=output, generated_at=1709253600.0)
    assert not output.exists()
