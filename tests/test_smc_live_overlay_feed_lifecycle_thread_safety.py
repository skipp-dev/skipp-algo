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
    """Fake Thread that becomes alive when the start gate is released."""

    def __init__(self, *args, name: str | None = None, **kwargs):
        self.name = name
        self._alive = False
        self._start_gate: threading.Event | None = kwargs.get("start_gate")

    def start(self) -> None:
        if self._start_gate is not None:
            self._start_gate.wait(timeout=1)
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
    feed_mod._runtime["ingest_thread"] = None
    feed_mod._runtime["supervisor_thread"] = None

    created: queue.Queue[str] = queue.Queue()
    release_start = threading.Event()

    class _InstrumentedThread(_SlowToStartThread):
        def start(self) -> None:
            created.put(self.name or "unknown")
            super().start()

    def _thread_factory(*args, **kwargs):
        kwargs["start_gate"] = release_start
        return _InstrumentedThread(*args, **kwargs)

    monkeypatch.setattr(feed_mod.threading, "Thread", _thread_factory)

    errors: queue.Queue[str] = queue.Queue()

    def _call_start(n: int) -> None:
        try:
            feed_mod.start()
        except Exception as exc:
            errors.put(f"T{n}: {type(exc).__name__}: {exc}")

    t1 = RealThread(target=_call_start, args=(1,))
    t2 = RealThread(target=_call_start, args=(2,))
    t1.start()
    t2.start()
    # Ensure first start() call has created at least one worker while holding
    # lifecycle lock, then release all worker starts together.
    deadline = time.monotonic() + 2.0
    while created.qsize() == 0 and time.monotonic() < deadline:
        time.sleep(0.001)
    assert created.qsize() > 0, "no worker thread creation observed before timeout"
    release_start.set()
    t1.join(timeout=10)
    t2.join(timeout=10)
    assert not t1.is_alive(), "start caller thread #1 did not finish within timeout"
    assert not t2.is_alive(), "start caller thread #2 did not finish within timeout"

    errs = []
    while not errors.empty():
        errs.append(errors.get_nowait())
    created_list = []
    while not created.empty():
        created_list.append(created.get_nowait())

    assert not errs, errs
    # With serialization only one caller creates the 5 workers (4 feed workers
    # + supervisor self-heal thread).
    assert len(created_list) == 5, f"expected 5, got {len(created_list)}: {created_list}"
    assert sorted(created_list) == [
        "flow-refresh", "ingest-processor", "live-feed",
        "live-overlay-supervisor", "overlay-refresh",
    ]

    feed_mod._stop_event.set()
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None
    feed_mod._runtime["ingest_thread"] = None
    feed_mod._runtime["supervisor_thread"] = None


def test_stop_clears_feed_ready_under_lifecycle_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.feed as feed_mod

    last_bar_before = feed_mod._last_bar_at
    feed_mod._feed_ready.set()
    feed_mod._last_bar_at = time.monotonic()
    assert feed_mod.is_ready()

    try:
        monkeypatch.setattr(feed_mod, "_feed_thread", None)
        monkeypatch.setattr(feed_mod, "_refresh_thread", None)
        monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)
        feed_mod.stop()

        assert not feed_mod.is_ready(), "_feed_ready must be cleared after stop()"
    finally:
        feed_mod._last_bar_at = last_bar_before
        feed_mod._stop_event.clear()


def test_worker_liveness_runs_under_lifecycle_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.feed as feed_mod

    RealThread = threading.Thread
    feed_mod._stop_event.clear()
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None
    feed_mod._runtime["ingest_thread"] = None

    liveness_results: list[dict[str, bool]] = []
    errors: list[BaseException] = []
    step_barrier = threading.Barrier(2)
    iterations = 50

    def _poll_liveness() -> None:
        try:
            for _ in range(iterations):
                step_barrier.wait()
                liveness_results.append(feed_mod.worker_liveness())
                step_barrier.wait()
        except Exception as exc:
            errors.append(exc)

    def _flip_state() -> None:
        try:
            for _ in range(iterations):
                with feed_mod._lifecycle_lock:
                    feed_mod._feed_thread = _SlowToStartThread(name="live-feed")
                    feed_mod._runtime["ingest_thread"] = _SlowToStartThread(name="ingest-processor")
                    feed_mod._refresh_thread = _SlowToStartThread(name="overlay-refresh")
                    feed_mod._flow_refresh_thread = _SlowToStartThread(name="flow-refresh")
                step_barrier.wait()
                with feed_mod._lifecycle_lock:
                    feed_mod._feed_thread = None
                    feed_mod._runtime["ingest_thread"] = None
                    feed_mod._refresh_thread = None
                    feed_mod._flow_refresh_thread = None
                step_barrier.wait()
        except Exception as exc:
            errors.append(exc)

    t1 = RealThread(target=_poll_liveness)
    t2 = RealThread(target=_flip_state)
    t1.start()
    t2.start()
    t1.join(timeout=3)
    t2.join(timeout=3)
    assert not t1.is_alive(), "liveness poll thread did not finish within timeout"
    assert not t2.is_alive(), "state flip thread did not finish within timeout"

    assert not errors, errors
    assert len(liveness_results) == iterations
    for result in liveness_results:
        assert set(result.keys()) == {"live_feed", "ingest_processor", "overlay_refresh", "flow_refresh"}
        assert all(isinstance(v, bool) for v in result.values())


def test_stop_does_not_raise_on_closed_logging_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: stop() must not raise when a logging handler's stream is
    already closed (e.g. pytest capture teardown or atexit ordering).

    Before the fix, ``logger.info("All feed threads stopped.")`` would
    trigger ``ValueError: I/O operation on closed file`` during late
    interpreter shutdown.
    """
    import io
    import logging as _logging

    import services.live_overlay_daemon.feed as feed_mod

    feed_mod._stop_event.clear()
    monkeypatch.setattr(feed_mod, "_feed_thread", None)
    monkeypatch.setattr(feed_mod, "_refresh_thread", None)
    monkeypatch.setattr(feed_mod, "_flow_refresh_thread", None)
    feed_mod._runtime["ingest_thread"] = None

    # Attach a handler whose stream is already closed.
    closed_stream = io.StringIO()
    closed_stream.close()
    handler = _logging.StreamHandler(closed_stream)
    _feed_logger = _logging.getLogger("services.live_overlay_daemon.feed")
    _feed_logger.addHandler(handler)
    try:
        # Must not raise ValueError.
        feed_mod.stop()
    finally:
        _feed_logger.removeHandler(handler)
        feed_mod._stop_event.clear()


def test_start_does_not_clear_set_stop_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """A supervisor heal must not resurrect workers after shutdown started."""
    import services.live_overlay_daemon.feed as feed_mod

    created: list[str] = []

    class _Thread:
        def __init__(self, *args, name: str | None = None, **kwargs):
            self.name = name
            self._alive = False

        def start(self) -> None:
            created.append(self.name or "unknown")
            self._alive = True

        def is_alive(self) -> bool:
            return self._alive

    monkeypatch.setattr(feed_mod.threading, "Thread", _Thread)
    monkeypatch.setattr(feed_mod.atexit, "register", lambda _fn: None)
    monkeypatch.setattr(feed_mod.atexit, "unregister", lambda _fn: None)
    feed_mod._feed_thread = None
    feed_mod._refresh_thread = None
    feed_mod._flow_refresh_thread = None
    feed_mod._runtime["ingest_thread"] = None
    feed_mod._runtime["supervisor_thread"] = None
    feed_mod._stop_event.set()

    try:
        feed_mod.start()

        assert feed_mod._stop_event.is_set()
        assert created == []
    finally:
        feed_mod._stop_event.clear()


def test_reset_lifecycle_for_restart_explicitly_clears_stop_event() -> None:
    import services.live_overlay_daemon.feed as feed_mod

    feed_mod._stop_event.set()
    feed_mod.reset_lifecycle_for_restart()
    assert not feed_mod._stop_event.is_set()


# ── Supervisor self-heal (WP1) ───────────────────────────────────────────────


def test_supervisor_break_stalled_client_calls_stop() -> None:
    """A stall must break the active client's blocked iterator via stop()."""
    import services.live_overlay_daemon.feed as feed_mod

    calls: list[str] = []

    class _FakeClient:
        def stop(self) -> None:
            calls.append("stop")

    with feed_mod._active_client_lock:
        feed_mod._runtime["active_client"] = _FakeClient()
    try:
        feed_mod._supervisor_break_stalled_client()
    finally:
        with feed_mod._active_client_lock:
            feed_mod._runtime["active_client"] = None
    assert calls == ["stop"]


def test_supervisor_break_stalled_client_noop_without_client() -> None:
    """No active client → break is a safe no-op (must not raise)."""
    import services.live_overlay_daemon.feed as feed_mod

    with feed_mod._active_client_lock:
        feed_mod._runtime["active_client"] = None
    feed_mod._supervisor_break_stalled_client()


def test_supervisor_escalates_on_fatal_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-retryable config error must escalate to a process restart, never
    loop forever trying to self-heal."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    escalated: list[int] = []

    def _fake_escalate(code: int = 1) -> None:
        escalated.append(code)
        stop.set()  # emulate os._exit ending the loop

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    monkeypatch.setattr(feed_mod, "_escalate_to_platform_restart", _fake_escalate)
    feed_mod._fatal_config_error.set()
    try:
        feed_mod._run_supervisor_loop(stop)
    finally:
        feed_mod._fatal_config_error.clear()
    assert escalated == [1]


def test_supervisor_heals_dead_worker_via_partial_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead worker thread must trigger the idempotent start() partial restart."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    started: list[int] = []
    escalated: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    monkeypatch.setattr(
        feed_mod, "worker_liveness",
        lambda: {"live_feed": False, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: False)

    def _fake_start() -> None:
        started.append(1)
        stop.set()

    monkeypatch.setattr(feed_mod, "start", _fake_start)
    monkeypatch.setattr(feed_mod, "_escalate_to_platform_restart", lambda code=1: escalated.append(code))
    feed_mod._fatal_config_error.clear()
    feed_mod._run_supervisor_loop(stop)
    assert started == [1]
    assert escalated == []


def test_supervisor_does_not_heal_dead_worker_after_stop_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """The final stop check closes the resurrection race before partial restart."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    started: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    def _dead_worker_then_shutdown() -> dict[str, bool]:
        stop.set()
        return {"live_feed": False, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True}

    monkeypatch.setattr(feed_mod, "worker_liveness", _dead_worker_then_shutdown)
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: False)

    def _fake_start() -> None:
        started.append(1)

    monkeypatch.setattr(feed_mod, "start", _fake_start)
    feed_mod._fatal_config_error.clear()
    feed_mod._run_supervisor_loop(stop)
    assert started == []


def test_supervisor_breaks_stall_during_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A silent feed stall during RTH must break the client (not restart, since
    the worker threads are still alive)."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    broke: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    monkeypatch.setattr(
        feed_mod, "worker_liveness",
        lambda: {"live_feed": True, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: True)
    monkeypatch.setattr(feed_mod, "last_bar_age_secs", lambda: feed_mod._STALL_MAX_BAR_AGE_SECS + 10.0)

    def _fake_break() -> None:
        broke.append(1)
        stop.set()

    monkeypatch.setattr(feed_mod, "_supervisor_break_stalled_client", _fake_break)
    monkeypatch.setattr(feed_mod, "start", lambda: None)
    monkeypatch.setattr(feed_mod, "_escalate_to_platform_restart", lambda code=1: None)
    feed_mod._fatal_config_error.clear()
    feed_mod._run_supervisor_loop(stop)
    assert broke == [1]


def test_supervisor_breaks_never_first_bar_stall(monkeypatch: pytest.MonkeyPatch) -> None:
    """Connected RTH feeds that never deliver the first bar are stale too."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    broke: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    monkeypatch.setattr(
        feed_mod,
        "worker_liveness",
        lambda: {"live_feed": True, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: True)
    monkeypatch.setattr(feed_mod, "last_bar_age_secs", lambda: None)
    monkeypatch.setattr(feed_mod, "_feed_connected_at", time.monotonic() - feed_mod._STALL_MAX_BAR_AGE_SECS - 10.0)

    def _fake_break() -> None:
        broke.append(1)
        stop.set()

    monkeypatch.setattr(feed_mod, "_supervisor_break_stalled_client", _fake_break)
    monkeypatch.setattr(feed_mod, "start", lambda: None)
    monkeypatch.setattr(feed_mod, "_escalate_to_platform_restart", lambda code=1: None)
    feed_mod._fatal_config_error.clear()
    try:
        feed_mod._run_supervisor_loop(stop)
    finally:
        feed_mod._feed_connected_at = 0.0
    assert broke == [1]


def test_supervisor_escalates_after_max_heal_attempts(monkeypatch: pytest.MonkeyPatch) -> None:
    """When partial restarts keep failing, the supervisor escalates to a
    process restart after _SELF_HEAL_MAX_ATTEMPTS."""
    import services.live_overlay_daemon.feed as feed_mod

    stop = threading.Event()
    escalated: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.001)
    monkeypatch.setattr(
        feed_mod, "worker_liveness",
        lambda: {"live_feed": False, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: False)
    monkeypatch.setattr(feed_mod, "start", lambda: None)  # heal never fixes it

    def _fake_escalate(code: int = 1) -> None:
        escalated.append(code)
        stop.set()

    monkeypatch.setattr(feed_mod, "_escalate_to_platform_restart", _fake_escalate)
    feed_mod._fatal_config_error.clear()
    feed_mod._run_supervisor_loop(stop)
    assert escalated == [1]
