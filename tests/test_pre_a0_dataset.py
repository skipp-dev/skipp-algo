from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest

from open_prep.pre_a0_labels import (
    audit_dataset,
    build_walk_forward_manifest,
    label_snapshots,
)
from open_prep.pre_a0_outcomes import ConfirmedA0
from open_prep.pre_a0_schema import PRE_A0_SCHEMA_VERSION, PreA0SnapshotRow, write_snapshot_partition


def _row(day: int, second: int = 0, *, episode: str | None = None) -> PreA0SnapshotRow:
    return PreA0SnapshotRow.create(
        feature_version="pre-a0-features-v1",
        session_date=f"2026-07-{day:02d}",
        source="databento-live",
        market_session="regular",
        symbol="XYZ",
        prediction_time=1_800_000_000 + day * 86_400 + second,
        max_feature_time=1_800_000_000 + day * 86_400 + second,
        direction="up",
        state="WATCH",
        price_progress=0.6,
        volume_progress=0.7,
        price_slope_15s=0.01,
        volume_slope_15s=0.02,
        direction_stability=1.0,
        data_age_ms=10,
        gap_complete=True,
        selection_reason="base_5s",
        sample_weight=1.0,
        episode_id=episode,
    )


def test_atomic_partition_and_manifest(tmp_path) -> None:
    row = _row(1)
    manifest = write_snapshot_partition([row], tmp_path, build_id="b1", code_revision="abc")
    assert manifest["status"] == "complete"
    assert manifest["schema_version"] == PRE_A0_SCHEMA_VERSION
    partition = tmp_path / "session_date=2026-07-01/source=databento-live/market_session=regular"
    assert len(pd.read_parquet(partition / "part-b1.parquet")) == 1
    assert (partition / "part-b1.manifest.json").exists()
    with pytest.raises(ValueError, match="duplicate"):
        write_snapshot_partition([row, row], tmp_path, build_id="b2", code_revision="abc")


def test_labels_censor_at_session_end_and_never_cross_horizon() -> None:
    row = _row(1)
    event = ConfirmedA0("XYZ", row.prediction_time + 45, "up", ("core_a0_thresholds",))
    labels = label_snapshots(
        [row], [event], session_end_by_date={row.session_date: row.prediction_time + 90}
    )
    assert labels[0].y_30 is False
    assert labels[0].y_60 is True
    assert labels[0].y_180 is None
    assert labels[0].censor_reason == "session_end"


def test_audit_and_split_manifest_are_deterministic() -> None:
    rows = [_row(day, episode=f"e{day}") for day in range(1, 5)]
    first = build_walk_forward_manifest(rows, code_revision="abc")
    second = build_walk_forward_manifest(list(reversed(rows)), code_revision="abc")
    assert first["split_sha256"] == second["split_sha256"]
    assert first["final_test_sealed"] is True
    assert first["embargo_seconds"] >= 180
    assert audit_dataset(rows, split_by_record=first["assignments"])["passed"] is True

    leaked = replace(rows[0], max_feature_time=rows[0].prediction_time + 1)
    report = audit_dataset([leaked, *rows[1:]])
    assert report["passed"] is False
    assert report["findings"][0]["code"] == "future_feature"
