"""Property-based / boundary tests for the bar-cache eviction log throttle."""
from __future__ import annotations

import logging
import time
from collections import deque

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import services.live_overlay_daemon.cache as cache


@pytest.fixture(autouse=True)
def _reset_evict_summary() -> None:
    """Reset the module-level throttle state before and after each test."""
    with cache._bar_lock:
        bars_snapshot = {
            sym: (list(dq), dq.maxlen)
            for sym, dq in cache._bars.items()
        }
        bar_last_update_snapshot = dict(cache._bar_last_update)
        rolling_bars_cap_snapshot = cache._rolling_bars_cap
        max_symbols_snapshot = cache._max_symbols
        last_eviction_at_snapshot = cache._last_eviction_at
        evict_summary_pending_snapshot = cache._evict_summary.pending
        evict_summary_at_snapshot = cache._evict_summary.at
        # Reset the mutable cache state to a clean slate BEFORE the test (the
        # snapshot above is restored after). This fixture is file-scoped, so
        # tests in OTHER files push bars / trigger evictions without it and can
        # leave _bars and _evict_summary dirty. In CI's fixed cross-file order
        # (unlike local isolation) that residue made
        # test_first_eviction_charge_is_not_lost_but_held_until_window_expires
        # see _evict_summary.pending == 2 under coverage; init_bar_cache is a
        # reconfigure (it preserves _bars), so it does not clear it.
        cache._bars.clear()
        cache._bar_last_update.clear()
        cache._last_eviction_at = 0.0
        cache._evict_summary.pending = 0
        cache._evict_summary.at = 0.0
    yield
    with cache._bar_lock:
        cache._bars.clear()
        cache._bars.update(
            {sym: deque(items, maxlen=maxlen) for sym, (items, maxlen) in bars_snapshot.items()}
        )
        cache._bar_last_update.clear()
        cache._bar_last_update.update(bar_last_update_snapshot)
        cache._rolling_bars_cap = rolling_bars_cap_snapshot
        cache._max_symbols = max_symbols_snapshot
        cache._last_eviction_at = last_eviction_at_snapshot
        cache._evict_summary.pending = evict_summary_pending_snapshot
        cache._evict_summary.at = evict_summary_at_snapshot


@settings(max_examples=50, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    max_symbols=st.integers(min_value=1, max_value=20),
    unique_new_symbols=st.lists(
        st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ", min_size=1, max_size=4),
        min_size=1,
        max_size=100,
    ),
)
def test_cap_eviction_never_floods_info_logs(
    caplog: pytest.LogCaptureFixture,
    max_symbols: int,
    unique_new_symbols: list[str],
) -> None:
    """Pushing a burst of new symbols while at capacity must not emit more than
    one INFO eviction line per throttle window (the window here is unexpired)."""
    cache.init_bar_cache(rolling_bars=5, max_symbols=max_symbols)
    for i in range(max_symbols):
        cache.push_bar(f"SEED{i}", {"open": 1.0, "close": 1.0})

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="services.live_overlay_daemon.cache"):
        for sym in unique_new_symbols:
            cache.push_bar(sym, {"open": 1.0, "close": 1.0})

    info_evicted = [
        r for r in caplog.records
        if r.levelno == logging.INFO and "evicted" in r.getMessage().lower()
    ]
    # Because all pushes happen inside one unexpired window, there should be
    # either zero or one INFO summary (zero if the window was unseeded and we
    # never crossed the interval, which is the expected steady-state behaviour).
    assert len(info_evicted) <= 1, f"INFO eviction log flooded: {len(info_evicted)} lines"


def test_summary_reports_all_pending_evictions_when_window_expires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Once the throttle window expires, exactly one summary reports the total
    number of evictions that accumulated since the previous summary."""
    cache.init_bar_cache(rolling_bars=5, max_symbols=3)
    for sym in ("A", "B", "C"):
        cache.push_bar(sym, {"open": 1.0, "close": 1.0})

    with caplog.at_level(logging.INFO, logger="services.live_overlay_daemon.cache"):
        for i in range(10):
            cache.push_bar(f"N{i}", {"open": 1.0, "close": 1.0})

    with cache._bar_lock:
        pending = cache._evict_summary.pending
        cache._evict_summary.at = time.monotonic() - (cache._EVICT_SUMMARY_INTERVAL_SECS + 1)

    caplog.clear()
    with caplog.at_level(logging.INFO, logger="services.live_overlay_daemon.cache"):
        cache.push_bar("Z", {"open": 1.0, "close": 1.0})

    summaries = [
        r for r in caplog.records
        if r.levelno == logging.INFO and "evicted" in r.getMessage().lower()
    ]
    assert len(summaries) == 1
    msg = summaries[0].getMessage()
    assert f"evicted {pending + 1} stale" in msg


def test_first_eviction_charge_is_not_lost_but_held_until_window_expires(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The throttle seeds the window on the first eviction. Until the window
    expires, the pending count is retained (not dropped)."""
    cache.init_bar_cache(rolling_bars=5, max_symbols=3)
    for sym in ("A", "B", "C"):
        cache.push_bar(sym, {"open": 1.0, "close": 1.0})

    with caplog.at_level(logging.INFO, logger="services.live_overlay_daemon.cache"):
        cache.push_bar("D", {"open": 1.0, "close": 1.0})

    with cache._bar_lock:
        assert cache._evict_summary.pending == 1
        first_at = cache._evict_summary.at
        assert first_at > 0.0

    # No INFO line yet because the window was just seeded.
    info_evicted = [
        r for r in caplog.records
        if r.levelno == logging.INFO and "evicted" in r.getMessage().lower()
    ]
    assert info_evicted == []
