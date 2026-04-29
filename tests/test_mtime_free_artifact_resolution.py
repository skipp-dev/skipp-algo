"""Positive test for ``scripts.smc_artifact_resolver``.

Asserts the resolver:
  * Picks newest by embedded ISO timestamp (not mtime).
  * Is mtime-invariant: shuffling mtimes does not change the result.
  * Falls back lexicographically when no timestamp is in the filename.
  * Returns ``None`` on empty input.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from scripts.smc_artifact_resolver import (
    latest_by_filename_iso,
    sorted_by_filename_iso,
)


def _touch(path: Path, mtime: float) -> Path:
    path.write_text("x", encoding="utf-8")
    os.utime(path, (mtime, mtime))
    return path


def test_latest_by_filename_iso_picks_newest_by_embedded_timestamp(tmp_path: Path) -> None:
    older = _touch(tmp_path / "databento_volatility_production_20260101_000000_manifest.json",
                   mtime=time.time())  # newest mtime
    newer = _touch(tmp_path / "databento_volatility_production_20260405_080817_manifest.json",
                   mtime=time.time() - 86400)  # older mtime
    chosen = latest_by_filename_iso(tmp_path.glob("*_manifest.json"))
    assert chosen == newer, (
        "Resolver must pick the file whose embedded timestamp is newest, "
        f"regardless of mtime; got {chosen!r} vs newer={newer!r} older={older!r}"
    )


def test_resolver_is_mtime_invariant(tmp_path: Path) -> None:
    a = _touch(tmp_path / "report-2026-04-04T05-11-50-564Z.json", mtime=1.0)
    b = _touch(tmp_path / "report-2026-04-05T05-11-50-564Z.json", mtime=999_999_999.0)
    c = _touch(tmp_path / "report-2026-04-06T05-11-50-564Z.json", mtime=2.0)
    chosen = latest_by_filename_iso(tmp_path.glob("report-*.json"))
    assert chosen == c, f"expected newest by filename, got {chosen}"

    # Reshuffle mtimes — must not change the result.
    os.utime(a, (10_000.0, 10_000.0))
    os.utime(b, (1.0, 1.0))
    os.utime(c, (5_000.0, 5_000.0))
    chosen2 = latest_by_filename_iso(tmp_path.glob("report-*.json"))
    assert chosen2 == c, "resolver must be mtime-invariant"


def test_sorted_by_filename_iso_returns_newest_first(tmp_path: Path) -> None:
    a = _touch(tmp_path / "x_20260101_000000_manifest.json", mtime=1.0)
    b = _touch(tmp_path / "x_20260405_080817_manifest.json", mtime=2.0)
    c = _touch(tmp_path / "x_20260301_120000_manifest.json", mtime=3.0)
    ordered = sorted_by_filename_iso(tmp_path.glob("x_*_manifest.json"))
    assert ordered == [b, c, a]


def test_unstamped_filenames_sort_after_stamped(tmp_path: Path) -> None:
    stamped = _touch(tmp_path / "x_20260101_000000.json", mtime=1.0)
    _plain = _touch(tmp_path / "canonical.json", mtime=999_999_999.0)
    chosen = latest_by_filename_iso(tmp_path.glob("*.json"))
    assert chosen == stamped, (
        "Stamped filenames must rank above unstamped ones regardless of mtime"
    )


def test_returns_none_on_empty(tmp_path: Path) -> None:
    assert latest_by_filename_iso(tmp_path.glob("nope-*")) is None
    assert sorted_by_filename_iso(tmp_path.glob("nope-*")) == []


def test_underscore_token_trailing_z_is_recognised(tmp_path: Path) -> None:
    """Backend artifacts emit ``YYYYMMDD_HHMMSSZ`` (trailing Z) too —
    the resolver must treat it as stamped and order it correctly
    (Copilot review of PR #191)."""
    older = tmp_path / "metrics_20260101_000000Z.json"
    newer = tmp_path / "metrics_20260102_000000Z.json"
    unstamped = tmp_path / "metrics_README.json"
    for p in (older, newer, unstamped):
        p.write_text("{}", encoding="utf-8")

    chosen = latest_by_filename_iso(tmp_path.glob("metrics_*.json"))
    assert chosen == newer

    ordered = sorted_by_filename_iso(tmp_path.glob("metrics_*.json"))
    assert ordered[0] == newer
    assert ordered[1] == older
    # Unstamped sorts last under reverse=True ordering.
    assert ordered[-1] == unstamped


def test_underscore_token_with_and_without_z_compare_equal(tmp_path: Path) -> None:
    """``20260405_080817`` and ``20260405_080817Z`` represent the same
    instant (UTC by repo convention) and must sort as equal — tie
    broken by filename (Copilot review of PR #191)."""
    a = tmp_path / "snap_20260405_080817.json"
    b = tmp_path / "snap_20260405_080817Z.json"
    for p in (a, b):
        p.write_text("{}", encoding="utf-8")

    ordered = sorted_by_filename_iso(tmp_path.glob("snap_*.json"))
    # Equal timestamp class — alphabetical name break gives "...Z.json"
    # second under reverse=True (since 'Z' > '.').
    assert {p.name for p in ordered} == {a.name, b.name}
    assert ordered[0].name == b.name  # snap_..._080817Z.json wins on name break
