from __future__ import annotations

from open_prep.pre_a0_events import PreA0SnapshotBuffer
from open_prep.pre_a0_schema import PreA0SnapshotRow


def _row(second: int) -> PreA0SnapshotRow:
    return PreA0SnapshotRow.create(
        feature_version="pre-a0-features-v1",
        session_date="2026-07-20",
        source="databento:live",
        market_session="regular",
        symbol="NVDA",
        prediction_time=1_800_000_000 + second,
        max_feature_time=1_800_000_000 + second,
        direction="up",
        state="WATCH",
        price_progress=0.6,
        volume_progress=0.7,
        price_slope_15s=0.01,
        volume_slope_15s=0.02,
        direction_stability=1.0,
        data_age_ms=50,
        gap_complete=True,
        selection_reason="warm_1s",
        sample_weight=1.0,
        episode_id="episode",
    )


def test_snapshot_buffer_is_bounded_idempotent_and_atomic(tmp_path) -> None:
    store = PreA0SnapshotBuffer(tmp_path, code_revision="test", max_rows=2)
    first = _row(1)
    assert store.add(first) is None
    assert store.add(first) is None
    assert store.pending_rows == 1
    flushed = store.add(_row(2))
    assert flushed is not None
    assert flushed.rows == 2
    assert store.pending_rows == 0
    assert len(list(tmp_path.rglob("*.parquet"))) == 1
    assert len(list(tmp_path.rglob("*.manifest.json"))) == 1
