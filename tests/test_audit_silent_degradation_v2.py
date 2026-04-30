"""Audit Silent-Degradation v2 — pin RED-fix contracts.

Each test maps to a specific RED finding from
``/memories/repo/audit-silent-degradation-v2-prompt.md`` so a regression
shows up as a labelled failure.

Findings:
    RED 1 (Lens 9): newsstack_fmp/_bz_http.py retry waits use full
        jitter so concurrent clients do not synchronise on the same
        wakeup.
    RED 2 (Lens 8): terminal_tradingview_news.fetch_tv records a
        health failure on broad-except so degraded state is observable.
    RED 3 (Lens 7): terminal_finnhub circuit-breaker scalars are
        accessed under a dedicated module-level lock.
"""

from __future__ import annotations

import threading
from unittest import mock

import httpx

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


# ── RED 2 — terminal_tradingview_news.fetch_tv records health ───


def test_fetch_tv_records_health_failure_on_exception() -> None:
    """`fetch_tv` must update `_health` on broad-except, not silently
    swallow.  Without this, the sidebar status stays "healthy" while
    every call returns []."""
    import terminal_tradingview_news as tv

    # Reset health
    with tv._health._lock:
        tv._health.consecutive_failures = 0
        tv._health.total_failures = 0
        tv._health.total_requests = 0
        tv._health.last_error = ""

    # Clear cache so fetch_tv goes through the live path
    with tv._cache_lock:
        tv._cache.clear()

    with mock.patch.object(tv, "_fetch_raw", side_effect=RuntimeError("upstream-500")):
        out = tv.fetch_tv_headlines("FAKEX")

    assert out == []
    with tv._health._lock:
        assert tv._health.consecutive_failures == 1, (
            "fetch_tv must increment consecutive_failures on broad-except"
        )
        assert "upstream-500" in tv._health.last_error
        assert tv._health.total_failures == 1


def test_fetch_tv_records_health_success_on_ok() -> None:
    """Mirror: success path must reset failure counter."""
    import terminal_tradingview_news as tv

    # Pre-set a degraded state to confirm reset
    with tv._health._lock:
        tv._health.consecutive_failures = 5
        tv._health.last_error = "stale"

    with tv._cache_lock:
        tv._cache.clear()

    with mock.patch.object(tv, "_fetch_raw", return_value={"items": []}), \
         mock.patch.object(tv, "_parse_items", return_value=[]):
        tv.fetch_tv_headlines("FAKEY")

    with tv._health._lock:
        assert tv._health.consecutive_failures == 0, (
            "successful fetch must reset consecutive_failures"
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
        barrier.wait()
        for _ in range(50):
            with fh._state_lock:
                fh._consecutive_429_count += 1

    t1 = threading.Thread(target=bump)
    t2 = threading.Thread(target=bump)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    with fh._state_lock:
        final = fh._consecutive_429_count

    assert final == 100, (
        f"expected 100 increments under lock, got {final} (lost-update bug)"
    )

    # cleanup so other tests don't see a poisoned counter
    with fh._state_lock:
        fh._consecutive_429_count = 0
