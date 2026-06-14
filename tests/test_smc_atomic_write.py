"""Tests for ``scripts/smc_atomic_write.py`` (audit finding A-1).

Verifies that ``atomic_write_parquet`` / ``atomic_write_csv`` either
materialise the target file completely or leave it untouched (no truncated
output) when the underlying writer raises mid-flight.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from scripts.smc_atomic_write import (
    atomic_write_csv,
    atomic_write_json,
    atomic_write_parquet,
    atomic_write_text,
)


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

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated writer crash")

    with patch.object(pd.DataFrame, "to_parquet", _boom), pytest.raises(RuntimeError, match="simulated writer crash"):
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

    def _boom(self, *args, **kwargs):
        raise RuntimeError("simulated csv crash")

    with patch.object(pd.DataFrame, "to_csv", _boom), pytest.raises(RuntimeError, match="simulated csv crash"):
        atomic_write_csv(_df(), target, index=False)

    assert target.read_bytes() == original_bytes
    siblings = [p for p in target.parent.iterdir() if p != target]
    assert siblings == []


# ---------------------------------------------------------------------------
# Permission preservation (Copilot review of PR #189).
# ``tempfile.mkstemp`` creates files with mode 0o600 by default; without
# explicit chmod, every atomic write would silently downgrade existing
# files to owner-only access. Verify the chmod restores both umask-derived
# defaults for new files and the existing mode bits when overwriting.
# ---------------------------------------------------------------------------

@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_atomic_write_text_preserves_existing_target_mode(tmp_path: Path) -> None:
    target = tmp_path / "out.txt"
    target.write_text("seed", encoding="utf-8")
    os.chmod(target, 0o644)

    atomic_write_text("after", target)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o644, f"expected 0o644 preserved, got {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_atomic_write_text_honours_umask_for_new_file(tmp_path: Path) -> None:
    target = tmp_path / "fresh.txt"
    saved_umask = os.umask(0o022)
    try:
        atomic_write_text("hello", target)
    finally:
        os.umask(saved_umask)

    mode = stat.S_IMODE(target.stat().st_mode)
    # 0o666 & ~0o022 == 0o644
    assert mode == 0o644, (
        f"expected 0o644 from umask 022, got {oct(mode)} "
        "(mkstemp default 0o600 leaked through)"
    )


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_atomic_write_csv_preserves_existing_target_mode(tmp_path: Path) -> None:
    target = tmp_path / "out.csv"
    target.write_text("seed", encoding="utf-8")
    os.chmod(target, 0o640)

    atomic_write_csv(_df(), target, index=False)

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o640, f"expected 0o640 preserved, got {oct(mode)}"


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission semantics only")
def test_atomic_write_json_honours_umask_for_new_file(tmp_path: Path) -> None:
    target = tmp_path / "fresh.json"
    saved_umask = os.umask(0o027)
    try:
        atomic_write_json({"k": "v"}, target)
    finally:
        os.umask(saved_umask)

    mode = stat.S_IMODE(target.stat().st_mode)
    # 0o666 & ~0o027 == 0o640
    assert mode == 0o640, f"expected 0o640 from umask 027, got {oct(mode)}"


# ---------------------------------------------------------------------------
# Durability: the ``fsync`` flag (Copilot review of PR #2754).
# When ``fsync=True`` the temp file must be flushed to disk via ``os.fsync``
# before the atomic ``os.replace``; with the default ``fsync=False`` no fsync
# call must be issued (hot-path writers stay fast).
# ---------------------------------------------------------------------------


def test_atomic_write_text_fsyncs_when_requested(tmp_path: Path) -> None:
    target = tmp_path / "durable.txt"
    with patch("scripts.smc_atomic_write.os.fsync") as mock_fsync:
        atomic_write_text("payload", target, fsync=True)
    assert mock_fsync.call_count == 1
    assert target.read_text(encoding="utf-8") == "payload"


def test_atomic_write_text_skips_fsync_by_default(tmp_path: Path) -> None:
    target = tmp_path / "fast.txt"
    with patch("scripts.smc_atomic_write.os.fsync") as mock_fsync:
        atomic_write_text("payload", target)
    mock_fsync.assert_not_called()
    assert target.read_text(encoding="utf-8") == "payload"


def test_atomic_write_json_fsyncs_when_requested(tmp_path: Path) -> None:
    target = tmp_path / "durable.json"
    with patch("scripts.smc_atomic_write.os.fsync") as mock_fsync:
        atomic_write_json({"k": "v"}, target, fsync=True)
    assert mock_fsync.call_count == 1
