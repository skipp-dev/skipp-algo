"""Tests for terminal_tabs.dashboard_cache (C7/T7)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from terminal_tabs.dashboard_cache import (
    DEFAULT_TTL_SECONDS,
    TTLCache,
    load_json_cached,
    payload_cache_key,
)

# ── TTLCache ────────────────────────────────────────────────────────


def test_ttl_cache_default_matches_sprint_plan() -> None:
    # 5 minutes — pinned because the user-guide doc references it.
    assert DEFAULT_TTL_SECONDS == 300


def test_ttl_cache_rejects_non_positive_ttl() -> None:
    with pytest.raises(ValueError, match="positive"):
        TTLCache(ttl_seconds=0)
    with pytest.raises(ValueError, match="positive"):
        TTLCache(ttl_seconds=-5)


def test_ttl_cache_get_or_compute_calls_factory_once() -> None:
    cache = TTLCache(ttl_seconds=60)
    calls = {"n": 0}

    def factory() -> str:
        calls["n"] += 1
        return "value"

    assert cache.get_or_compute("k", factory) == "value"
    assert cache.get_or_compute("k", factory) == "value"
    assert calls["n"] == 1


def test_ttl_cache_expires_after_ttl() -> None:
    now = {"t": 100.0}
    cache = TTLCache(ttl_seconds=10, clock=lambda: now["t"])
    calls = {"n": 0}

    def factory() -> int:
        calls["n"] += 1
        return calls["n"]

    assert cache.get_or_compute("k", factory) == 1
    now["t"] = 109.0  # still within TTL
    assert cache.get_or_compute("k", factory) == 1
    now["t"] = 111.0  # past TTL
    assert cache.get_or_compute("k", factory) == 2


def test_ttl_cache_invalidate_specific_key() -> None:
    cache = TTLCache(ttl_seconds=60)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    cache.invalidate("a")
    assert len(cache) == 1


def test_ttl_cache_invalidate_all() -> None:
    cache = TTLCache(ttl_seconds=60)
    cache.get_or_compute("a", lambda: 1)
    cache.get_or_compute("b", lambda: 2)
    cache.invalidate()
    assert len(cache) == 0


# ── payload_cache_key ──────────────────────────────────────────────


def test_payload_cache_key_distinguishes_dirs(tmp_path: Path) -> None:
    a = payload_cache_key(tmp_path / "a", as_of_date="2026-04-26")
    b = payload_cache_key(tmp_path / "b", as_of_date="2026-04-26")
    assert a != b


def test_payload_cache_key_distinguishes_dates(tmp_path: Path) -> None:
    a = payload_cache_key(tmp_path, as_of_date="2026-04-26")
    b = payload_cache_key(tmp_path, as_of_date="2026-04-27")
    assert a != b


def test_payload_cache_key_default_date_is_none(tmp_path: Path) -> None:
    assert payload_cache_key(tmp_path)[1] is None


# ── load_json_cached ────────────────────────────────────────────────


def test_load_json_cached_returns_none_for_missing(tmp_path: Path) -> None:
    cache = TTLCache(ttl_seconds=60)
    assert load_json_cached(tmp_path / "nope.json", cache=cache) is None


def test_load_json_cached_returns_payload(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"hello": "world"}), encoding="utf-8")
    cache = TTLCache(ttl_seconds=60)
    assert load_json_cached(p, cache=cache) == {"hello": "world"}


def test_load_json_cached_picks_up_mtime_changes(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text(json.dumps({"v": 1}), encoding="utf-8")
    cache = TTLCache(ttl_seconds=60)
    assert load_json_cached(p, cache=cache) == {"v": 1}
    # Sleep just enough that mtime_ns changes on every reasonable FS.
    time.sleep(0.01)
    p.write_text(json.dumps({"v": 2}), encoding="utf-8")
    assert load_json_cached(p, cache=cache) == {"v": 2}


def test_load_json_cached_returns_none_on_corrupt(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    p.write_text("{not valid json", encoding="utf-8")
    cache = TTLCache(ttl_seconds=60)
    assert load_json_cached(p, cache=cache) is None


# ── smoke perf ──────────────────────────────────────────────────────


def test_payload_aggregate_smoke_under_3s() -> None:
    """Sprint-plan acceptance: initial render < 3s with 24 mock variants."""
    from terminal_tabs.tab_track_record import build_summary

    payload = {
        "as_of_date": "2026-04-26",
        "variants": [
            {
                "variant": f"v{i:02d}",
                "gate_status": ("green", "amber", "red")[i % 3],
                "n_trades": 100 + i,
                "sharpe": 0.5 + i * 0.01,
                "sharpe_ci_low": 0.2,
                "sharpe_ci_high": 0.9,
                "permutation_p_value": 0.01 + i * 0.001,
            }
            for i in range(24)
        ],
        "warnings": [],
    }
    start = time.perf_counter()
    out = build_summary(payload)
    elapsed = time.perf_counter() - start
    assert out["status"] == "ok"
    assert len(out["rows"]) == 24
    assert elapsed < 3.0
