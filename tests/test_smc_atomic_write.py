"""Tests for ``scripts/smc_atomic_write.py`` (audit finding A-1).

Verifies that ``atomic_write_parquet`` / ``atomic_write_csv`` either
materialise the target file completely or leave it untouched (no truncated
output) when the underlying writer raises mid-flight.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.smc_atomic_write import atomic_write_csv, atomic_write_parquet


def _df() -> pd.DataFrame:
    return pd.DataFrame({"symbol": ["AAPL", "MSFT"], "value": [1.5, 2.5]})


def test_atomic_write_parquet_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "out.parquet"
    atomic_write_parquet(_df(), target, index=False)
    assert target.exists()
    round_trip = pd.read_parquet(target)
    assert list(round_trip.columns) == ["symbol", "value"]
    assert len(round_trip) == 2


def test_atomic_write_csv_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    atomic_write_csv(_df(), target, index=False)
    assert target.exists()
    round_trip = pd.read_csv(target)
    assert list(round_trip.columns) == ["symbol", "value"]
    assert len(round_trip) == 2


def test_atomic_write_parquet_creates_parent_dir(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "deeper" / "out.parquet"
    atomic_write_parquet(_df(), target, index=False)
    assert target.exists()


def test_atomic_write_parquet_leaves_target_untouched_on_writer_failure(tmp_path: Path) -> None:
    """If to_parquet raises, the destination must remain in its prior state
    and no .tmp leftovers may remain in the target directory."""
    target = tmp_path / "out.parquet"
    # Pre-existing good payload that must survive a failed atomic overwrite.
    atomic_write_parquet(_df(), target, index=False)
    original_bytes = target.read_bytes()

    def _boom(self, *args, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated writer crash")

    with patch.object(pd.DataFrame, "to_parquet", _boom):
        with pytest.raises(RuntimeError, match="simulated writer crash"):
            atomic_write_parquet(_df(), target, index=False)

    # Target unchanged.
    assert target.read_bytes() == original_bytes
    # No leftover tempfile siblings.
    siblings = [p for p in target.parent.iterdir() if p != target]
    assert siblings == [], f"unexpected tempfile leftovers: {siblings}"


def test_atomic_write_csv_leaves_target_untouched_on_writer_failure(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    atomic_write_csv(_df(), target, index=False)
    original_bytes = target.read_bytes()

    def _boom(self, *args, **kwargs):  # noqa: ARG001
        raise RuntimeError("simulated csv crash")

    with patch.object(pd.DataFrame, "to_csv", _boom):
        with pytest.raises(RuntimeError, match="simulated csv crash"):
            atomic_write_csv(_df(), target, index=False)

    assert target.read_bytes() == original_bytes
    siblings = [p for p in target.parent.iterdir() if p != target]
    assert siblings == []
