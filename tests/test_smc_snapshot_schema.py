from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import jsonschema

from smc_core import apply_layering, snapshot_to_dict
from smc_core.types import BosEvent, SmcMeta, SmcStructure, TimedVolumeInfo, VolumeInfo

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "spec" / "smc_snapshot.schema.json"


def _load_schema() -> dict:
    return cast(dict, json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def test_generated_snapshot_validates_against_schema() -> None:
    structure = SmcStructure(
        bos=[BosEvent(id="bos:AAPL:15m:1709250000:BOS:UP:185.25", time=1709250000.0, price=185.25, kind="BOS", dir="UP")]
    )
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580.0,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580.0, stale=False),
    )

    snapshot = apply_layering(structure, meta, generated_at=1709253600.0)
    payload = snapshot_to_dict(snapshot)
    jsonschema.validate(instance=payload, schema=_load_schema())
