from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

from scripts.export_smc_structure_artifact import build_structure_artifact_payload
from tests.helpers.smc_test_artifacts import make_minimal_workbook

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "smc_structure_artifact.schema.json"


def _load_schema() -> dict:
    return cast(dict, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_structure_artifact_payload_matches_schema(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    payload = build_structure_artifact_payload(workbook=workbook, generated_at=1709253600.0)
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_structure_artifact_payload_has_deterministic_output_for_fixed_time(tmp_path: Path) -> None:
    workbook = make_minimal_workbook(tmp_path)
    one = build_structure_artifact_payload(workbook=workbook, generated_at=1709253600.0)
    two = build_structure_artifact_payload(workbook=workbook, generated_at=1709253600.0)
    assert one == two
