from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCHEMA_PATH = _REPO_ROOT / "spec" / "smc_snapshot.schema.json"
_EXAMPLES_DIR = _REPO_ROOT / "spec" / "examples"


def _load_schema() -> dict:
    return cast(dict, json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")))


def _validate(payload: dict) -> None:
    jsonschema.validate(instance=payload, schema=_load_schema())


def test_example_snapshots_validate_against_schema() -> None:
    for path in sorted(_EXAMPLES_DIR.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        _validate(payload)


def test_schema_uses_line_width_field_name() -> None:
    schema = _load_schema()
    zone_style = schema["properties"]["layered"]["properties"]["zone_styles"]["additionalProperties"]
    required = zone_style["required"]
    assert "line_width" in required
    assert "lineWidth" not in required
