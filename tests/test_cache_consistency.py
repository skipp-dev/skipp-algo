"""Audit tests for cache.py internal consistency and defensive copying."""
from __future__ import annotations

import copy
from collections import deque

import pytest


@pytest.fixture(autouse=True)
def _restore_cache_module_state() -> None:
    import services.live_overlay_daemon.cache as cache

    with cache._bar_lock:
        bars_snapshot = {
            sym: (list(dq), dq.maxlen)
            for sym, dq in cache._bars.items()
        }
        bar_last_update_snapshot = dict(cache._bar_last_update)
        rolling_bars_cap_snapshot = cache._rolling_bars_cap
        max_symbols_snapshot = cache._max_symbols
        last_eviction_at_snapshot = cache._last_eviction_at

    with cache._overlay_lock:
        overlay_snapshot = copy.deepcopy(cache._overlay)
        overlay_computed_at_snapshot = cache._overlay_computed_at

    with cache._vix_lock:
        vix_level_snapshot = cache._vix_level

    yield

    with cache._bar_lock:
        cache._bars.clear()
        cache._bars.update(
            {
                sym: deque(items, maxlen=maxlen)
                for sym, (items, maxlen) in bars_snapshot.items()
            }
        )
        cache._bar_last_update.clear()
        cache._bar_last_update.update(bar_last_update_snapshot)
        cache._rolling_bars_cap = rolling_bars_cap_snapshot
        cache._max_symbols = max_symbols_snapshot
        cache._last_eviction_at = last_eviction_at_snapshot

    with cache._overlay_lock:
        cache._overlay.clear()
        cache._overlay.update(overlay_snapshot)
        cache._overlay_computed_at = overlay_computed_at_snapshot

    with cache._vix_lock:
        cache._vix_level = vix_level_snapshot


def test_get_overlay_returns_deep_copy() -> None:
    import services.live_overlay_daemon.cache as cache

    payload = {
        "symbol": "AAPL",
        "nested": {"list": [1, 2, 3]},
    }
    cache.set_overlay({"AAPL": payload})

    snapshot = cache.get_overlay("AAPL")
    assert snapshot is not None
    snapshot["nested"]["list"].append(4)

    # Shared cache must remain unchanged
    cached = cache.get_overlay("AAPL")
    assert cached["nested"]["list"] == [1, 2, 3]


def test_set_overlay_replaces_atomically() -> None:
    import services.live_overlay_daemon.cache as cache

    cache.set_overlay({"AAPL": {"x": 1}, "MSFT": {"x": 2}})
    cache.set_overlay({"TSLA": {"x": 3}})

    assert cache.overlay_symbol_count() == 1
    assert cache.get_overlay("AAPL") is None
    assert cache.get_overlay("TSLA") == {"x": 3}


def test_eviction_keeps_bar_and_last_update_consistent() -> None:
    import services.live_overlay_daemon.cache as cache

    with cache._bar_lock:
        cache._bars.clear()
        cache._bar_last_update.clear()
        cache._last_eviction_at = 0.0

    cache.init_bar_cache(rolling_bars=10, max_symbols=3)

    for sym in ["AAPL", "MSFT", "TSLA"]:
        cache.push_bar(sym, {"open": 1.0, "close": 1.0})

    cache.push_bar("NVDA", {"open": 1.0, "close": 1.0})

    with cache._bar_lock:
        assert "NVDA" in cache._bars
        assert len(cache._bars) == 3
        assert len({"AAPL", "MSFT", "TSLA"} - set(cache._bars.keys())) >= 1
        assert set(cache._bars.keys()) == set(cache._bar_last_update.keys())


def test_init_bar_cache_downscale_cleans_last_update() -> None:
    import services.live_overlay_daemon.cache as cache

    with cache._bar_lock:
        cache._bars.clear()
        cache._bar_last_update.clear()
        cache._last_eviction_at = 0.0

    cache.init_bar_cache(rolling_bars=10, max_symbols=10)
    for sym in ["A", "B", "C", "D", "E"]:
        cache.push_bar(sym, {"open": 1.0, "close": 1.0})

    cache.init_bar_cache(rolling_bars=10, max_symbols=2)

    with cache._bar_lock:
        assert len(cache._bars) <= 2
        assert set(cache._bars.keys()) == set(cache._bar_last_update.keys())
