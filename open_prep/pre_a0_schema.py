"""Versioned PRE-A0 snapshot schema and crash-safe partition writer."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from scripts.smc_atomic_write import atomic_write_json, atomic_write_parquet

PRE_A0_SCHEMA_VERSION = "pre-a0-snapshot-v1"


@dataclass(frozen=True, slots=True)
class PreA0SnapshotRow:
    record_id: str
    schema_version: str
    feature_version: str
    session_date: str
    source: str
    market_session: str
    symbol: str
    prediction_time: float
    max_feature_time: float
    direction: str
    state: str
    price_progress: float
    volume_progress: float
    price_slope_15s: float | None
    volume_slope_15s: float | None
    direction_stability: float
    data_age_ms: float | None
    gap_complete: bool
    selection_reason: str
    sample_weight: float
    episode_id: str | None = None

    @classmethod
    def create(cls, **values: Any) -> PreA0SnapshotRow:
        identity = {
            "schema_version": PRE_A0_SCHEMA_VERSION,
            "session_date": values["session_date"],
            "source": values["source"],
            "symbol": values["symbol"],
            "prediction_time": values["prediction_time"],
        }
        digest = hashlib.sha256(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:24]
        return cls(record_id=digest, schema_version=PRE_A0_SCHEMA_VERSION, **values)


def _rows_hash(rows: Sequence[PreA0SnapshotRow]) -> str:
    canonical = json.dumps(
        [asdict(row) for row in sorted(rows, key=lambda value: value.record_id)],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def write_snapshot_partition(
    rows: Sequence[PreA0SnapshotRow],
    root: Path,
    *,
    build_id: str,
    code_revision: str,
) -> dict[str, Any]:
    """Atomically write one homogeneous partition and its completion manifest."""
    if not rows:
        raise ValueError("rows must not be empty")
    if len({row.record_id for row in rows}) != len(rows):
        raise ValueError("duplicate record_id")
    expected = {
        (row.schema_version, row.feature_version, row.session_date, row.source, row.market_session)
        for row in rows
    }
    if len(expected) != 1 or next(iter(expected))[0] != PRE_A0_SCHEMA_VERSION:
        raise ValueError("schema drift or mixed partition")
    schema, feature, session, source, market_session = next(iter(expected))
    partition = (
        Path(root)
        / f"session_date={session}"
        / f"source={source}"
        / f"market_session={market_session}"
    )
    data_path = partition / f"part-{build_id}.parquet"
    manifest_path = partition / f"part-{build_id}.manifest.json"
    import pandas as pd

    frame = pd.DataFrame(asdict(row) for row in rows)
    atomic_write_parquet(frame, data_path, index=False)
    manifest: dict[str, Any] = {
        "status": "complete",
        "build_id": build_id,
        "schema_version": schema,
        "feature_version": feature,
        "session_date": session,
        "source": source,
        "market_session": market_session,
        "row_count": len(rows),
        "rows_sha256": _rows_hash(rows),
        "code_revision": code_revision,
        "data_file": data_path.name,
    }
    atomic_write_json(manifest, manifest_path, sort_keys=True)
    return manifest
