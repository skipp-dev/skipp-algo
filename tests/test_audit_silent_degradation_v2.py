"""Audit Silent-Degradation v2 — pin RED-fix contracts.

Each test maps to a specific RED finding from
``/memories/repo/audit-silent-degradation-v2-prompt.md`` so a regression
shows up as a labelled failure.

Findings:
    RED 1 (Lens 9): newsstack_fmp/_bz_http.py retry waits use full
        jitter so concurrent clients do not synchronise on the same
        wakeup.
    RED 3 (Lens 7): terminal_finnhub circuit-breaker scalars are
        accessed under a dedicated module-level lock.
"""

from __future__ import annotations

import threading
from unittest import mock

import httpx

# 2026-08-20: siehe tests/test_smc_live_overlay_feed_lifecycle_thread_safety.py
# — ``Barrier.wait()`` ohne Frist haengt statt zu scheitern. 15 s, damit ein
# echter Hang eine ``BrokenBarrierError``-Zusicherung erzeugt statt eines
# Thread-Dumps aus ``faulthandler_timeout = 180``.
_BARRIER_TIMEOUT_SECS = 15.0

# ── RED 1 — _bz_http.py: full-jitter retry ──────────────────────


def test_bz_http_retry_uses_full_jitter() -> None:
    """`time.sleep` must be called with jitter in [0, computed_delay].

    Pattern guard: enforces full-jitter across both retry branches
    (HTTP retryable status + transient network error).  Without
    jitter, every adapter client wakes up at the same instant after
    a Benzinga 429 burst and re-overwhelms the upstream.
    """
    from newsstack_fmp import _bz_http

    # Force deterministic jitter pick via the _bz_http seams.
    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)

    def fake_rng() -> float:
        return 0.5  # mid-jitter -> delay = capped * 0.5

    # Build a fake client that returns 429 then 200
    responses = [
        mock.Mock(spec=httpx.Response, status_code=429, headers={}),
        mock.Mock(spec=httpx.Response, status_code=200, headers={}),
    ]
    responses[1].raise_for_status = mock.Mock()
    client = mock.Mock(spec=httpx.Client)
    client.get = mock.Mock(side_effect=responses)

    with mock.patch.object(_bz_http, "_sleep", side_effect=fake_sleep), \
         mock.patch.object(_bz_http, "_rng", side_effect=fake_rng):
        out = _bz_http._request_with_retry(
            client,
            "https://example.test/feed",
            {},
            label=None,
        )

    assert out is responses[1]
    # On attempt=0, wait=2**0=1.0; jittered = 0.5 * 1.0 = 0.5
    assert sleeps == [0.5], (
        f"expected single jittered sleep of 0.5s, got {sleeps!r}"
    )


def test_bz_http_jitter_used_for_network_errors() -> None:
    """Transient network errors also retry with full-jitter."""
    from newsstack_fmp import _bz_http

    sleeps: list[float] = []

    def fake_sleep(s: float) -> None:
        sleeps.append(s)

    def fake_rng() -> float:
        return 0.25  # quarter-jitter -> delay = capped * 0.25

    success = mock.Mock(spec=httpx.Response, status_code=200, headers={})
    success.raise_for_status = mock.Mock()
    err = httpx.ConnectError("boom")
    client = mock.Mock(spec=httpx.Client)
    client.get = mock.Mock(side_effect=[err, success])

    with mock.patch.object(_bz_http, "_sleep", side_effect=fake_sleep), \
         mock.patch.object(_bz_http, "_rng", side_effect=fake_rng):
        out = _bz_http._request_with_retry(
            client,
            "https://example.test/feed",
            {},
            label=None,
        )

    assert out is success
    assert sleeps == [0.25], (
        f"expected single jittered network-retry sleep of 0.25s, got {sleeps!r}"
    )


# ── RED 3 — terminal_finnhub: locked scalar state ───────────────


def test_finnhub_state_lock_exists() -> None:
    """Verify the dedicated state lock is present (regression: the
    rate-limit / breaker scalars were previously written without
    coordination)."""
    import terminal_finnhub

    assert hasattr(terminal_finnhub, "_state_lock"), (
        "terminal_finnhub must expose a module-level _state_lock"
    )
    # threading.Lock is a factory; isinstance check uses the type of an
    # instance to avoid relying on the private _thread.lock class name
    assert isinstance(
        terminal_finnhub._state_lock, type(threading.Lock())
    )


def test_finnhub_social_sentiment_status_uses_lock() -> None:
    """`social_sentiment_status` must read the breaker flags under
    `_state_lock`. We verify by patching the lock with a counter."""
    import terminal_finnhub

    real_lock = terminal_finnhub._state_lock
    acquire_count = {"n": 0}

    class CountingLock:
        def __enter__(self) -> CountingLock:
            acquire_count["n"] += 1
            real_lock.acquire()
            return self

        def __exit__(self, *exc: object) -> None:
            real_lock.release()

    with mock.patch.object(terminal_finnhub, "_state_lock", CountingLock()):
        terminal_finnhub.social_sentiment_status()

    assert acquire_count["n"] >= 1, (
        "social_sentiment_status must acquire _state_lock at least once"
    )


def test_finnhub_concurrent_429s_do_not_corrupt_counter() -> None:
    """Two threads simulating 429 responses must produce a coherent
    final `_consecutive_429_count` (no torn writes)."""
    import terminal_finnhub as fh

    # Reset
    with fh._state_lock:
        fh._consecutive_429_count = 0
        fh._rate_limit_backoff_until = 0.0

    barrier = threading.Barrier(2)

    def bump() -> None:
        barrier.wait(timeout=_BARRIER_TIMEOUT_SECS)
        for _ in range(50):
            with fh._state_lock:
                fh._consecutive_429_count += 1

    t1 = threading.Thread(target=bump)
    t2 = threading.Thread(target=bump)
    t1.start()
    t2.start()
    t1.join(timeout=_BARRIER_TIMEOUT_SECS + 5.0)
    t2.join(timeout=_BARRIER_TIMEOUT_SECS + 5.0)
    assert not t1.is_alive() and not t2.is_alive(), (
        "ein Zaehler-Thread lief nicht zu Ende — ohne diese Zusicherung haette "
        "der unbegrenzte join() hier gehangen statt zu scheitern"
    )

    with fh._state_lock:
        final = fh._consecutive_429_count

    assert final == 100, (
        f"expected 100 increments under lock, got {final} (lost-update bug)"
    )

    # cleanup so other tests don't see a poisoned counter
    with fh._state_lock:
        fh._consecutive_429_count = 0
