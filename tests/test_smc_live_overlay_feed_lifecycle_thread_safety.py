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
import types

import pytest

# 2026-08-20: jede Barriere braucht eine Frist.
#
# ``threading.Barrier.wait()`` ohne Timeout blockiert UNBEGRENZT, sobald eine
# der Parteien die Barriere nicht erreicht — der Test haengt dann, statt zu
# scheitern. Ein haengender Test sagt nichts; ein fehlgeschlagener nennt seinen
# Namen. Was das kostet, ist an diesem Tag gemessen worden: ein Hang derselben
# Klasse (geborgte Uhr, #4935) verbrannte 45 Minuten Job-Zeit ohne eine einzige
# Zeile Diagnose — validate (4), Lauf 32369549784.
#
# 15 s statt der 5 s, die ``tests/test_alerts_throttle.py`` fuer dieselbe Form
# benutzt: dreifacher Spielraum fuer den 2-Kern-Runner. Zugleich eine
# Groessenordnung UNTER ``faulthandler_timeout = 180`` (#4933), damit ein echter
# Hang eine saubere ``BrokenBarrierError``-Zusicherung erzeugt statt eines
# Thread-Dumps.
_BARRIER_TIMEOUT_SECS = 15.0


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
                step_barrier.wait(timeout=_BARRIER_TIMEOUT_SECS)
                liveness_results.append(feed_mod.worker_liveness())
                step_barrier.wait(timeout=_BARRIER_TIMEOUT_SECS)
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
                step_barrier.wait(timeout=_BARRIER_TIMEOUT_SECS)
                with feed_mod._lifecycle_lock:
                    feed_mod._feed_thread = None
                    feed_mod._runtime["ingest_thread"] = None
                    feed_mod._refresh_thread = None
                    feed_mod._flow_refresh_thread = None
                step_barrier.wait(timeout=_BARRIER_TIMEOUT_SECS)
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
    assert liveness_results, "no liveness polls recorded — this pin would pass vacuously"
    assert len(liveness_results) == iterations
    for result in liveness_results:
        # Must stay in step with the workers _do_start() actually starts — this
        # set pinned four while five were started, which is how the missing
        # supervisor flag survived.
        assert set(result.keys()) == {
            "live_feed", "ingest_processor", "overlay_refresh", "flow_refresh", "supervisor",
        }
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


class _BoundedStop(threading.Event):
    """Ein Stop-Event, das sich nach ``limit`` Runden selbst setzt.

    Jeder Supervisor-Test hier faehrt die ECHTE Schleife
    (``while not stop.wait(_SUPERVISOR_INTERVAL_SECS)``) und verlaesst sich
    darauf, dass ein Stub ``stop.set()`` ruft, sobald das erwartete Verhalten
    eintritt. Tritt es NICHT ein, laeuft die Schleife fuer immer: der Test
    haengt, statt zu scheitern — und ein haengender Test sagt nichts, waehrend
    ein fehlgeschlagener seinen Namen nennt.

    Was das kostet, ist gemessen: am 2026-08-20 blockierte
    ``test_supervisor_breaks_never_first_bar_stall`` auf einem frisch
    gebooteten Runner (geborgte ``monotonic()``-Uptime, siehe dort) und
    verbrannte 45 Minuten Job-Zeit ohne eine einzige Zeile Diagnose
    (validate (4), Lauf 32369549784). Erst der faulthandler-Dump aus #4933
    nannte den Test.

    Die Schranke ist grosszuegig: bei ``_SUPERVISOR_INTERVAL_SECS = 0.01``
    sind 200 Runden zwei Sekunden, waehrend der langsamste dieser Tests vier
    Runden braucht (``_SELF_HEAL_MAX_ATTEMPTS`` = 3 plus Eskalation). Sie
    aendert also an keinem gruenen Lauf etwas — sie verwandelt nur einen
    stillen Hang in eine laute Zusicherung.
    """

    def __init__(self, limit: int = 200) -> None:
        super().__init__()
        self._rounds_left = limit

    def wait(self, timeout: float | None = None) -> bool:
        self._rounds_left -= 1
        if self._rounds_left <= 0:
            self.set()
        return super().wait(timeout)


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

    stop = _BoundedStop()
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

    stop = _BoundedStop()
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

    stop = _BoundedStop()
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

    stop = _BoundedStop()
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

    stop = _BoundedStop()
    broke: list[int] = []

    monkeypatch.setattr(feed_mod, "_SUPERVISOR_INTERVAL_SECS", 0.01)
    monkeypatch.setattr(
        feed_mod,
        "worker_liveness",
        lambda: {"live_feed": True, "ingest_processor": True, "overlay_refresh": True, "flow_refresh": True},
    )
    monkeypatch.setattr(feed_mod.market_hours, "is_us_regular_session_open", lambda: True)
    monkeypatch.setattr(feed_mod, "last_bar_age_secs", lambda: None)
    # 2026-08-20: BEIDE Seiten des Vergleichs liefern, statt eine von der
    # Maschine zu borgen.
    #
    # Vorher stand hier ``time.monotonic() - _STALL_MAX_BAR_AGE_SECS - 10``.
    # ``monotonic()`` zaehlt ab BOOT. Auf einem Entwicklerrechner mit Tagen
    # Uptime ist das eine grosse Zahl und die Differenz bleibt positiv — auf
    # einem frisch gestarteten GitHub-Runner mit unter 190 s Uptime wird sie
    # NEGATIV. Und ``feed.py`` gated die Erkennung mit
    # ``elif _feed_connected_at > 0:``, greift bei einem negativen Wert also
    # nicht: kein Stall, kein ``_fake_break``, kein ``stop.set()`` — und
    # ``while not stop.wait(0.01)`` drehte sich, bis das Job-Limit sie erschlug.
    # Gekostet hat das am 20.8. 45 Minuten Runner-Zeit ohne eine einzige Zeile
    # Diagnose (validate (4), Lauf 32369549784); benannt hat es erst der
    # faulthandler-Dump aus #4933.
    fake_now = 10_000.0
    monkeypatch.setattr(feed_mod, "time", types.SimpleNamespace(monotonic=lambda: fake_now))
    monkeypatch.setattr(
        feed_mod, "_feed_connected_at", fake_now - feed_mod._STALL_MAX_BAR_AGE_SECS - 10.0
    )

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

    stop = _BoundedStop()
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


class _FixedLivenessThread:
    """Thread stand-in with a fixed is_alive() answer."""

    def __init__(self, alive: bool) -> None:
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


def _patch_workers(
    monkeypatch: pytest.MonkeyPatch, feed_mod, *, supervisor_alive: bool
) -> None:
    monkeypatch.setattr(feed_mod, "_feed_thread", _FixedLivenessThread(True))
    monkeypatch.setattr(feed_mod, "_refresh_thread", _FixedLivenessThread(True))
    monkeypatch.setattr(feed_mod, "_flow_refresh_thread", _FixedLivenessThread(True))
    monkeypatch.setitem(feed_mod._runtime, "ingest_thread", _FixedLivenessThread(True))
    monkeypatch.setitem(
        feed_mod._runtime, "supervisor_thread", _FixedLivenessThread(supervisor_alive)
    )


def test_worker_liveness_reports_dead_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead supervisor must not be reported healthy — it heals the other workers.

    _do_start() starts five threads; worker_liveness() reported only four, so a
    supervisor that died silently left /ready at 200 and
    live_overlay_workers_healthy at 1 — the gauge an alert watches with lt 1.
    """
    import services.live_overlay_daemon.feed as feed_mod

    _patch_workers(monkeypatch, feed_mod, supervisor_alive=False)
    liveness = feed_mod.worker_liveness()

    assert liveness["supervisor"] is False
    others = {name: alive for name, alive in liveness.items() if name != "supervisor"}
    assert len(others) == 4, (
        f"worker_liveness() reported {sorted(others)} beside the supervisor — "
        "_do_start() starts five threads and all five must be graded"
    )
    assert all(others.values()), "only the supervisor may be down in this scenario"
    assert not all(liveness.values()), (
        "/ready and live_overlay_workers_healthy must go unhealthy on a dead supervisor"
    )


def test_worker_liveness_reports_live_supervisor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Guards the other direction so the supervisor flag is not pinned to False."""
    import services.live_overlay_daemon.feed as feed_mod

    _patch_workers(monkeypatch, feed_mod, supervisor_alive=True)
    liveness = feed_mod.worker_liveness()

    assert liveness["supervisor"] is True
    assert all(liveness.values())
