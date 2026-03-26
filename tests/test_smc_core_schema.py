from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

from smc_core import apply_layering, snapshot_to_dict
from smc_core.types import BosEvent, SmcMeta, SmcStructure, TimedVolumeInfo, VolumeInfo

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


def test_apply_layering_snapshot_serializes_and_validates_schema() -> None:
    structure = SmcStructure(
        bos=[BosEvent(id="bos:AAPL:15m:1709250000:BOS:UP:185.25", time=1709250000, price=185.25, kind="BOS", dir="UP")]
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580, stale=False),
    )

    snapshot = apply_layering(structure, meta, generated_at=1709253600.0)
    payload = snapshot_to_dict(snapshot)
    _validate(payload)
