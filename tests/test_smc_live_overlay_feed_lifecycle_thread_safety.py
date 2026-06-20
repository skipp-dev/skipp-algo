"""Thread-safety tests for feed.start() / stop() / worker_liveness().

The legacy implementation allowed two concurrent start() calls to each create
a full set of worker threads because the lifecycle handles were read and
written without synchronization. The current implementation serializes start(),
stop(), and worker_liveness() under _lifecycle_lock.
"""
from __future__ import annotations

import queue
import threading
import time

import pytest


class _SlowToStartThread:
    """Fake Thread that becomes alive only after a short delay."""

    def __init__(self, *args, name: str | None = None, **kwargs):
        self.name = name
        self._alive = False

    def start(self) -> None:
        time.sleep(0.05)
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def join(self, timeout: float | None = None) -> None:
        self._alive = False


def test_concurrent_start_serializes_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.feed as feed_mod

    # Capture real Thread class BEFORE patching feed_mod.threading.Thread.
    RealThread = threading.Thread

    feed_mod._stop_event.clear()
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None

    created: queue.Queue[str] = queue.Queue()

    class _InstrumentedThread(_SlowToStartThread):
        def start(self) -> None:
            created.put(self.name or "unknown")
            super().start()

    monkeypatch.setattr(feed_mod.threading, "Thread", _InstrumentedThread)

    log_queue: queue.Queue[str] = queue.Queue()
    errors: queue.Queue[str] = queue.Queue()

    def _call_start(n: int) -> None:
        log_queue.put(f"T{n}: entered")
        try:
            feed_mod.start()
            log_queue.put(f"T{n}: returned")
        except BaseException as exc:
            errors.put(f"T{n}: {type(exc).__name__}: {exc}")

    t1 = RealThread(target=_call_start, args=(1,))
    t2 = RealThread(target=_call_start, args=(2,))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    errs = []
    while not errors.empty():
        errs.append(errors.get_nowait())
    created_list = []
    while not created.empty():
        created_list.append(created.get_nowait())

    assert not errs, errs
    # With serialization only one caller creates the 3 workers.
    assert len(created_list) == 3, f"expected 3, got {len(created_list)}: {created_list}"
    assert sorted(created_list) == ["flow-refresh", "live-feed", "overlay-refresh"]

    feed_mod._stop_event.set()
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None


def test_stop_clears_feed_ready_under_lifecycle_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.feed as feed_mod

    feed_mod._feed_ready.set()
    feed_mod._last_bar_at = time.monotonic()
    assert feed_mod.is_ready()

    monkeypatch.setattr(feed_mod, "_feed_thread", None)
    monkeypatch.setattr(feed_mod, "_refresh_thread", None)
    monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)
    feed_mod.stop()

    assert not feed_mod.is_ready(), "_feed_ready must be cleared after stop()"
    feed_mod._stop_event.clear()


def test_worker_liveness_runs_under_lifecycle_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.feed as feed_mod

    RealThread = threading.Thread
    feed_mod._stop_event.clear()
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None

    liveness_results: list[dict[str, bool]] = []
    errors: list[BaseException] = []

    def _poll_liveness() -> None:
        try:
            for _ in range(100):
                liveness_results.append(feed_mod.worker_liveness())
                time.sleep(0.001)
        except BaseException as exc:
            errors.append(exc)

    def _flip_state() -> None:
        try:
            for _ in range(50):
                feed_mod._feed_thread = _SlowToStartThread(name="live-feed")
                feed_mod._refresh_thread = _SlowToStartThread(name="overlay-refresh")
                feed_mod._flow_refresh_thread = _SlowToStartThread(name="flow-refresh")
                time.sleep(0.001)
                feed_mod._feed_thread = None
                feed_mod._refresh_thread = None
                feed_mod._flow_refresh_thread = None
                time.sleep(0.001)
        except BaseException as exc:
            errors.append(exc)

    t1 = RealThread(target=_poll_liveness)
    t2 = RealThread(target=_flip_state)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)

    assert not errors, errors
    assert len(liveness_results) == 100
    for result in liveness_results:
        assert set(result.keys()) == {"live_feed", "overlay_refresh", "flow_refresh"}
        assert all(isinstance(v, bool) for v in result.values())
