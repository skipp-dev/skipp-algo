"""Bar-cache retention must follow DEMAND, not bar-arrival recency.

Production finding 2026-07-22: the daemon reported ``bar_symbols=2000``
(exactly ``OVERLAY_MAX_SYMBOLS``) with ``bar_count=2000`` — i.e. **one bar per
symbol** — sustained across minutes of healthy uptime with fresh bars
arriving. Cause: the feed subscribes to ``ALL_SYMBOLS`` (thousands), the cache
caps at 2000, and eviction picked victims by least-recent BAR ARRIVAL. Since
every tracked symbol ticks about once a minute that ordering is near-uniform,
so eviction was effectively random and constantly dropped the handful of
symbols actually being watched. Consequence: no symbol ever accumulated the
~20 bars that relative volume, the squeeze and the ATS z-score need, so the
sidecar's technical feed rendered "—" for every symbol.

These tests pin the fix: a requested symbol survives cap pressure and
accumulates history; the churn is visible in metrics.
"""
from __future__ import annotations

import pytest

from services.live_overlay_daemon import cache, request_hotspots


def _bar(i: int) -> dict[str, float]:
    return {"o": 1.0, "h": 2.0, "low": 0.5, "c": 1.5, "v": 100.0 + i}


@pytest.fixture(autouse=True)
def _fresh_cache():
    request_hotspots.reset()
    # init_bar_cache keeps existing entries, so shrink to 1 and push a throwaway
    # symbol to force every leftover out before each test.
    cache.init_bar_cache(60, max_symbols=1)
    cache.push_bar("ZZZZ", _bar(0))
    cache.init_bar_cache(60, max_symbols=3)
    yield
    request_hotspots.reset()


def test_requested_symbol_survives_cap_pressure_and_accumulates() -> None:
    """The watched symbol must keep its history while the ALL_SYMBOLS firehose
    churns through the remaining slots."""
    request_hotspots.record_request("WATCHED", "5m")
    for i in range(5):
        cache.push_bar("WATCHED", _bar(i))
    # 40 unrelated symbols stream in against a 3-symbol cap.
    for n in range(40):
        cache.push_bar(f"NOISE{n}", _bar(n))

    bars = cache.get_bars_snapshot("WATCHED")
    assert len(bars) == 5, "requested symbol lost history to cap churn"
    assert cache.evicted_protected_total() == 0


def test_unrequested_symbols_are_evicted_first() -> None:
    request_hotspots.record_request("KEEP", "5m")
    cache.push_bar("KEEP", _bar(0))
    cache.push_bar("DROP1", _bar(1))
    cache.push_bar("DROP2", _bar(2))
    # Cap is 3 and full — a new arrival must evict an unrequested symbol.
    cache.push_bar("NEW", _bar(3))
    assert cache.get_bars_snapshot("KEEP"), "requested symbol was evicted first"
    assert cache.evicted_symbols_total() >= 1


def test_cap_stays_a_hard_limit_even_when_all_are_requested() -> None:
    """Protection is a preference, not an exemption: the cap must still hold."""
    for name in ("A", "B", "C"):
        request_hotspots.record_request(name, "5m")
        cache.push_bar(name, _bar(0))
    request_hotspots.record_request("D", "5m")
    cache.push_bar("D", _bar(1))
    assert cache.bar_symbol_count() <= 3
    assert cache.evicted_protected_total() >= 1  # disclosed, not hidden


def test_history_reaches_the_rolling_metric_floor(monkeypatch) -> None:
    """20 bars is the floor the squeeze / relative volume / ATS z-score need."""
    request_hotspots.record_request("HOT", "5m")
    for i in range(25):
        cache.push_bar("HOT", _bar(i))
        for n in range(10):  # continuous cap pressure between bars
            cache.push_bar(f"X{i}_{n}", _bar(n))
    assert len(cache.get_bars_snapshot("HOT")) >= 20


def test_requested_symbols_snapshot_is_defensive() -> None:
    request_hotspots.record_request("AAPL", "5m")
    first = request_hotspots.requested_symbols()
    request_hotspots.record_request("MSFT", "5m")
    assert "AAPL" in first
    assert "MSFT" not in first  # frozenset snapshot, not a live view
