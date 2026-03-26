from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

from scripts.export_smc_structure_artifact import build_structure_artifact_payload

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "smc_structure_artifact.schema.json"
WORKBOOK_PATH = ROOT / "databento_volatility_production_20260307_114724.xlsx"


def _load_schema() -> dict:
    return cast(dict, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_structure_artifact_payload_matches_schema() -> None:
    payload = build_structure_artifact_payload(workbook=WORKBOOK_PATH, generated_at=1709253600.0)
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_structure_artifact_payload_has_deterministic_output_for_fixed_time() -> None:
    one = build_structure_artifact_payload(workbook=WORKBOOK_PATH, generated_at=1709253600.0)
    two = build_structure_artifact_payload(workbook=WORKBOOK_PATH, generated_at=1709253600.0)
    assert one == two
