"""Buffered, atomic PRE-A0 snapshot persistence for shadow collection."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .a0_stream_state import A0StreamFeatureSnapshot
from .pre_a0 import PreA0Estimate
from .pre_a0_schema import PreA0SnapshotRow, write_snapshot_partition


def snapshot_row(
    snapshot: A0StreamFeatureSnapshot,
    estimate: PreA0Estimate,
    *,
    selection_reason: str,
    sample_weight: float,
    episode_id: str | None,
) -> PreA0SnapshotRow:
    features = estimate.features
    return PreA0SnapshotRow.create(
        feature_version=features.feature_version,
        session_date=features.session_date,
        source=snapshot.market.source,
        market_session="regular",
        symbol=features.symbol,
        prediction_time=features.observed_at,
        max_feature_time=features.observed_at,
        direction=features.direction,
        state=estimate.state.name,
        price_progress=features.price_progress,
        volume_progress=features.volume_progress,
        price_slope_15s=features.slope("price", 15),
        volume_slope_15s=features.slope("volume", 15),
        direction_stability=features.direction_stability,
        data_age_ms=features.data_age_ms,
        gap_complete=features.gap_complete,
        selection_reason=selection_reason,
        sample_weight=sample_weight,
        episode_id=episode_id,
    )


@dataclass(frozen=True, slots=True)
class SnapshotFlush:
    rows: int
    manifests: tuple[dict[str, object], ...]


class PreA0SnapshotBuffer:
    """Bound memory and atomically flush homogeneous Parquet partitions."""

    def __init__(
        self,
        root: Path,
        *,
        code_revision: str,
        max_rows: int = 500,
    ) -> None:
        if max_rows < 1 or max_rows > 100_000:
            raise ValueError("max_rows must be between 1 and 100000")
        self.root = Path(root)
        self.code_revision = code_revision.strip() or "unknown"
        self.max_rows = max_rows
        self._partitions: dict[tuple[str, str, str], list[PreA0SnapshotRow]] = defaultdict(list)
        self._seen: set[str] = set()

    @property
    def pending_rows(self) -> int:
        return sum(len(rows) for rows in self._partitions.values())

    def add(self, row: PreA0SnapshotRow) -> SnapshotFlush | None:
        if row.record_id in self._seen:
            return None
        self._seen.add(row.record_id)
        key = (row.session_date, row.source, row.market_session)
        self._partitions[key].append(row)
        if self.pending_rows >= self.max_rows:
            return self.flush()
        return None

    def flush(self) -> SnapshotFlush:
        manifests: list[dict[str, object]] = []
        flushed = 0
        for key in sorted(self._partitions):
            rows = self._partitions[key]
            if not rows:
                continue
            build_id = _build_id(rows)
            manifest = write_snapshot_partition(
                rows,
                self.root,
                build_id=build_id,
                code_revision=self.code_revision,
            )
            manifests.append(manifest)
            flushed += len(rows)
            rows.clear()
        return SnapshotFlush(flushed, tuple(manifests))


def _build_id(rows: Sequence[PreA0SnapshotRow]) -> str:
    identity = "\n".join(sorted(row.record_id for row in rows))
    return hashlib.sha256(identity.encode()).hexdigest()[:20]
