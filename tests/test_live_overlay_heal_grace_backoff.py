"""The post-heal grace window must cover the reconnect the feed is actually doing.

`_POST_HEAL_GRACE_SECS` is built from `_RECONNECT_DELAY_SECS` (10 s) plus one
ohlcv-1m interval plus margin = 85 s. But the feed loop does not always wait
10 s: from `_MAX_RECONNECT_ATTEMPTS` consecutive failures onward it waits
`_RECONNECT_BACKOFF_SECS` = 120 s, so the real cost of a reconnect is 120 s plus
up to one bar interval = 180 s — more than double the grace.

#4476 fixed this for the 10 s path. The 120 s path is still open, and in it the
consequences compound: while the feed sleeps there is no `active_client`, so
`_supervisor_break_stalled_client()` cannot do anything, yet the attempt is
counted and `last_heal_at` is stamped. Three counted no-ops later the supervisor
calls `_escalate_to_platform_restart()`. `railway.toml` allows
`restartPolicyMaxRetries = 3`, so roughly four process lives exhaust the platform
budget and the daemon stays down — including after the upstream has recovered.
There are no frozen bars in that outcome; there are no bars at all.

These tests pin the two invariants that make the difference, both as pure
functions so they need no threads and no live feed.
"""

from __future__ import annotations

import services.live_overlay_daemon.feed as feed


def test_the_grace_window_covers_the_backoff_the_feed_can_actually_take() -> None:
    """The arithmetic that #4476 got right for one path and not the other."""
    worst_case = feed._RECONNECT_BACKOFF_SECS + 60.0
    assert worst_case > feed._POST_HEAL_GRACE_SECS, (
        "premise gone: the fixed grace already covers the backoff, so the rest "
        "of this file is testing nothing"
    )

    now = 1_000.0
    # The feed announced it will not reconnect before now + 110 s.
    grace_until = feed._grace_deadline(last_heal_at=now, reconnect_wait_until=now + 110.0)
    assert grace_until >= now + 110.0 + 60.0, (
        "the supervisor would re-break the client while the feed is still "
        f"sleeping out its backoff (grace ends {grace_until - now:.0f}s in)"
    )


def test_a_short_reconnect_does_not_buy_a_long_grace() -> None:
    """The counter-test: precision, not a blanket widening.

    Simply raising the constant to the worst case would delay every legitimate
    escalation by ~110 s. The deadline must follow what the feed is really
    doing, so with no reconnect pending the window stays the measured 85 s.
    """
    now = 1_000.0
    assert feed._grace_deadline(last_heal_at=now, reconnect_wait_until=0.0) == (
        now + feed._POST_HEAL_GRACE_SECS
    )


def test_a_heal_that_cannot_act_is_not_counted_against_the_escalation() -> None:
    """`_supervisor_break_stalled_client` is a no-op with no active client.

    During the reconnect sleep `_runtime["active_client"]` is None, so the break
    does nothing — but the attempt was still counted. Three of those escalate to
    `os._exit(1)` without a single remediation having been attempted.
    """
    with feed._active_client_lock:
        feed._runtime["active_client"] = None
    assert feed._supervisor_break_stalled_client() is False, (
        "a break with no active client reported success, so the supervisor "
        "counts it as a heal attempt and escalates on nothing"
    )


def test_a_heal_that_does_act_is_counted() -> None:
    """The other direction, so the fix cannot be 'always return False'."""

    class _Client:
        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    client = _Client()
    with feed._active_client_lock:
        feed._runtime["active_client"] = client
    try:
        assert feed._supervisor_break_stalled_client() is True
        assert client.stopped, "the client was not actually stopped"
    finally:
        with feed._active_client_lock:
            feed._runtime["active_client"] = None
