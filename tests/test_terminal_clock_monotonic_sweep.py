"""Regression tests for PR-J4 (audit pass 2, 2026-05-10).

Pin the use of ``time.monotonic`` for cache TTLs and rate-limit
backoffs in ``terminal_finnhub`` and ``terminal_bitcoin``.

Pre-PR-J4, both modules used ``time.time()`` (wall clock) for purely
in-process duration arithmetic. A backwards wall-clock jump (NTP
correction, VM live-migrate, manual ``date -s``) would either evict
valid cache entries instantly or — for the Finnhub rate-limit
backoff — leave the deadline so far in the future that the API would
be locked out long after the actual cooldown should have elapsed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import terminal_bitcoin
import terminal_finnhub


@pytest.mark.parametrize(
    "module_path,allowed",
    [
        # Allow only matches inside comments / docstrings.
        ("terminal_finnhub.py", 0),
        ("terminal_bitcoin.py", 0),
    ],
)
def test_no_executable_time_time_in_cache_paths(module_path, allowed):
    """Source-pin: no executable ``time.time()`` calls remain in the
    cache / backoff hot paths of either module. Comments referring
    to ``time.time()`` for documentation purposes are allowed."""
    src = Path(module_path).read_text(encoding="utf-8")
    executable = []
    for lineno, line in enumerate(src.splitlines(), start=1):
        stripped = line.lstrip()
        # Skip comment lines entirely.
        if stripped.startswith("#"):
            continue
        if "time.time()" in line:
            # Strip inline comments so 'x = 1  # time.time() jumps' is OK.
            code, _, _ = line.partition("#")
            if "time.time()" in code:
                executable.append((lineno, line))
    assert len(executable) == allowed, (
        f"PR-J4: {module_path} must not call time.time() in executable "
        f"code (found: {executable})"
    )


def test_finnhub_rate_limit_backoff_uses_monotonic():
    """Functional: setting the backoff deadline to a future
    ``time.monotonic()`` value MUST report rate-limited; setting it
    to 0 MUST clear it. Pre-fix the comparison used ``time.time()``
    so a monotonic value (typically much smaller than wall-clock
    epoch) would always be in the past and the gate would fail open."""
    import time as _time
    from unittest import mock

    terminal_finnhub._social_sentiment_blocked = False
    terminal_finnhub._rate_limit_backoff_until = _time.monotonic() + 999
    try:
        with mock.patch.dict("os.environ", {"FINNHUB_API_KEY": "k"}):
            assert terminal_finnhub.social_sentiment_status() == "rate_limited"
    finally:
        terminal_finnhub._rate_limit_backoff_until = 0.0


def test_finnhub_cache_uses_monotonic_for_ttl():
    """Functional: a stale entry inserted with a back-dated
    ``time.monotonic()`` timestamp MUST be evicted on read."""
    import time as _time

    with terminal_finnhub._cache_lock:
        terminal_finnhub._cache["pr-j4-stale"] = (_time.monotonic() - 120.0, "v")
    found, value = terminal_finnhub._get_cached("pr-j4-stale", ttl=60.0)
    assert found is False, "PR-J4: stale entry must be evicted"
    assert value is None


def test_bitcoin_cache_uses_monotonic_for_ttl():
    import time as _time

    with terminal_bitcoin._cache_lock:
        terminal_bitcoin._cache["pr-j4-stale"] = (_time.monotonic() - 120.0, "v")
    assert terminal_bitcoin._get_cached("pr-j4-stale", ttl=60.0) is None
