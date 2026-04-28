"""Tests for the TTL cache wrapping
:func:`terminal_tabs.drift_loader.load_recent_drift_artifacts`.

The cache is process-local and keyed on
``(cache_dir, n, live_dir_entry_count, live_dir_mtime_ns)``. Tests
verify three behaviours:

* repeated calls for the same key reuse the cached list (no re-read);
* writing a new artifact under ``cache/live/`` invalidates the key
  via the directory fingerprint;
* :func:`invalidate_recent_drift_cache` clears the table explicitly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from terminal_tabs import drift_loader


def _write_drift(cache_dir: Path, date: str, *, variants: int = 0) -> None:
    live = cache_dir / "live"
    live.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": "1.0.0",
        "as_of_date": date,
        "computed_at": f"{date}T00:00:00Z",
        "live_window_days": 30,
        "variants": [
            {"variant": f"v{i}", "verdict": "pass"} for i in range(variants)
        ],
    }
    (live / f"drift_{date}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _clear_cache() -> None:
    drift_loader.invalidate_recent_drift_cache()
    yield
    drift_loader.invalidate_recent_drift_cache()


def test_load_recent_drift_artifacts_caches_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_drift(tmp_path, "2026-04-25")
    _write_drift(tmp_path, "2026-04-26")

    calls = {"n": 0}
    real_load = drift_loader.load_drift_artifact

    def counting_load(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(drift_loader, "load_drift_artifact", counting_load)

    first = drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    after_first = calls["n"]
    assert after_first >= 2  # one per artifact

    second = drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert calls["n"] == after_first, "second call must be a cache hit"
    assert second == first
    # Returned list is a copy (mutations don't poison the cache).
    second.clear()
    third = drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert third == first


def test_new_artifact_invalidates_cache_via_dir_fingerprint(
    tmp_path: Path,
) -> None:
    _write_drift(tmp_path, "2026-04-25")
    first = drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert len(first) == 1

    _write_drift(tmp_path, "2026-04-26")
    second = drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert len(second) == 2
    # Newest first.
    assert second[0]["as_of_date"] == "2026-04-26"


def test_invalidate_recent_drift_cache_forces_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_drift(tmp_path, "2026-04-25")
    calls = {"n": 0}
    real_load = drift_loader.load_drift_artifact

    def counting_load(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(drift_loader, "load_drift_artifact", counting_load)

    drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    after_first = calls["n"]
    drift_loader.invalidate_recent_drift_cache()
    drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert calls["n"] > after_first


def test_ttl_expiry_evicts_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_drift(tmp_path, "2026-04-25")

    fake_now = {"t": 1000.0}

    def fake_monotonic() -> float:
        return fake_now["t"]

    monkeypatch.setattr(drift_loader.time, "monotonic", fake_monotonic)

    calls = {"n": 0}
    real_load = drift_loader.load_drift_artifact

    def counting_load(*args: Any, **kwargs: Any) -> Any:
        calls["n"] += 1
        return real_load(*args, **kwargs)

    monkeypatch.setattr(drift_loader, "load_drift_artifact", counting_load)

    drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    after_first = calls["n"]

    # Within TTL → cache hit.
    fake_now["t"] += drift_loader.DRIFT_RECENT_CACHE_TTL_SECONDS / 2
    drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert calls["n"] == after_first

    # Past TTL → eviction + reload.
    fake_now["t"] += drift_loader.DRIFT_RECENT_CACHE_TTL_SECONDS + 1.0
    drift_loader.load_recent_drift_artifacts(tmp_path, n=7)
    assert calls["n"] > after_first


def test_zero_n_short_circuits_without_cache(tmp_path: Path) -> None:
    _write_drift(tmp_path, "2026-04-25")
    assert drift_loader.load_recent_drift_artifacts(tmp_path, n=0) == []


def test_negative_n_still_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-negative"):
        drift_loader.load_recent_drift_artifacts(tmp_path, n=-1)
