"""Universe-version drift detector tests for ``databento_volatility_screener``.

Verifies the #2339 contract on the screener's cache helpers:

1. ``_write_cached_frame(..., captured_universe_symbols=...)`` embeds
   ``skipp.*`` metadata into the parquet schema and ``_read_universe_metadata``
   round-trips it.
2. ``_cached_frame_coverage(..., current_universe_symbols=...)`` returns
   ``(None, requested_set)`` and removes the cache file when the current
   universe contains symbols not present at capture time (silent
   under-coverage guard).
3. When the current universe is a subset or equal to the captured one,
   the cache is treated as a hit (no spurious drift refetch).
4. Backwards compatibility: omitting ``current_universe_symbols`` preserves
   the legacy hit/miss path even on caches written without metadata.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from databento_volatility_screener import (
    _build_universe_metadata,
    _cached_frame_coverage,
    _read_universe_metadata,
    _write_cached_frame,
)


def _make_frame(symbols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "symbol": symbols,
            "close": [100.0 + i for i, _ in enumerate(symbols)],
        }
    )


def test_universe_metadata_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "roundtrip.parquet"
    symbols = ["AAPL", "MSFT", "NVDA"]
    _write_cached_frame(path, _make_frame(symbols), captured_universe_symbols=symbols)
    meta = _read_universe_metadata(path)
    assert meta is not None
    assert meta["skipp.captured_universe_size"] == "3"
    assert meta["skipp.captured_universe_symbols"] == "AAPL,MSFT,NVDA"
    expected_hash = _build_universe_metadata(symbols)["skipp.captured_universe_hash"]
    assert meta["skipp.captured_universe_hash"] == expected_hash
    assert "skipp.captured_at" in meta


def test_drift_refetch_when_current_has_new_symbol(tmp_path: Path) -> None:
    path = tmp_path / "drift.parquet"
    captured = ["AAPL", "MSFT", "NVDA"]
    _write_cached_frame(path, _make_frame(captured), captured_universe_symbols=captured)
    assert path.exists()
    cached_frame, missing = _cached_frame_coverage(
        path,
        requested_symbols=captured,
        current_universe_symbols=["AAPL", "MSFT", "NVDA", "TSLA"],
    )
    assert cached_frame is None, "drift must force a refetch"
    assert missing == {"AAPL", "MSFT", "NVDA"}
    assert not path.exists(), "drifted cache file must be removed"


def test_no_drift_when_current_is_subset(tmp_path: Path) -> None:
    path = tmp_path / "subset.parquet"
    captured = ["AAPL", "MSFT", "NVDA", "TSLA"]
    _write_cached_frame(path, _make_frame(captured), captured_universe_symbols=captured)
    cached_frame, missing = _cached_frame_coverage(
        path,
        requested_symbols=["AAPL", "MSFT"],
        current_universe_symbols=["AAPL", "MSFT"],
    )
    assert cached_frame is not None, "subset universe must not trigger refetch"
    assert missing == set(), "subset is fully covered"
    assert path.exists()


def test_no_drift_when_current_equals_captured(tmp_path: Path) -> None:
    path = tmp_path / "equal.parquet"
    captured = ["AAPL", "MSFT"]
    _write_cached_frame(path, _make_frame(captured), captured_universe_symbols=captured)
    cached_frame, missing = _cached_frame_coverage(
        path,
        requested_symbols=captured,
        current_universe_symbols=captured,
    )
    assert cached_frame is not None
    assert missing == set()


def test_legacy_cache_without_metadata_still_serves_hits(tmp_path: Path) -> None:
    """Pre-#2339 parquet files have no skipp metadata; behaviour must not regress."""
    path = tmp_path / "legacy.parquet"
    _write_cached_frame(path, _make_frame(["AAPL", "MSFT"]))
    assert _read_universe_metadata(path) is None
    cached_frame, missing = _cached_frame_coverage(
        path,
        requested_symbols=["AAPL", "MSFT"],
        current_universe_symbols=["AAPL", "MSFT", "NVDA"],
    )
    assert cached_frame is not None, (
        "legacy cache without metadata must not be invalidated by the drift check"
    )
    assert missing == set()
    assert path.exists()


def test_drift_check_skipped_when_current_universe_not_provided(tmp_path: Path) -> None:
    """Callers that opt out of the drift check (no kwarg) keep legacy semantics."""
    path = tmp_path / "no_kwarg.parquet"
    captured = ["AAPL", "MSFT"]
    _write_cached_frame(path, _make_frame(captured), captured_universe_symbols=captured)
    cached_frame, missing = _cached_frame_coverage(path, requested_symbols=captured)
    assert cached_frame is not None
    assert missing == set()


def test_drift_logs_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "log.parquet"
    captured = ["AAPL", "MSFT"]
    _write_cached_frame(path, _make_frame(captured), captured_universe_symbols=captured)
    with caplog.at_level("WARNING", logger="databento_volatility_screener"):
        _cached_frame_coverage(
            path,
            requested_symbols=captured,
            current_universe_symbols=["AAPL", "MSFT", "TSLA"],
        )
    assert any("cache drift refetch" in record.message for record in caplog.records), (
        f"expected drift warning, got: {[r.message for r in caplog.records]}"
    )
