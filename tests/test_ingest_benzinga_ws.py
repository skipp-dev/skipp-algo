"""PR-F (audit 2026-05-10): bounded enqueue race-hardening for BenzingaWsAdapter.

Pre-PR-F, the inline enqueue inside ``_ws_loop`` had a ``put_nowait`` /
``get_nowait`` ``Full``->``Empty`` race followed by an UNGUARDED retry
``put_nowait(item)``. Under load this either silently dropped fresh
items or raised ``queue.Full`` from the unguarded retry and killed the
WS reader thread. These tests pin the new ``_enqueue_item`` method.
"""

from __future__ import annotations

import queue

from newsstack_fmp.ingest_benzinga import BenzingaWsAdapter


def _make_adapter(maxsize: int = 2) -> BenzingaWsAdapter:
    """Construct an adapter and shrink its queue for race tests."""
    a = BenzingaWsAdapter(api_key="test-key", ws_url="wss://example.test")
    a.queue = queue.Queue(maxsize=maxsize)
    return a


class TestEnqueueItemRaceHardening:
    def test_simple_enqueue_when_room_available(self):
        a = _make_adapter(maxsize=2)
        assert a._enqueue_item("item-A") is True
        assert a.queue.qsize() == 1
        assert a.total_items_dropped == 0
        assert a.total_enqueue_drops == 0

    def test_evicts_oldest_when_full(self):
        a = _make_adapter(maxsize=1)
        a.queue.put_nowait("old")
        assert a._enqueue_item("new") is True
        assert a.total_items_dropped == 1
        assert a.total_enqueue_drops == 0
        assert a.queue.get_nowait() == "new"

    def test_no_silent_drop_when_consumer_drains_during_full(self):
        """Race-window regression: consumer drains between Full and get_nowait."""
        a = _make_adapter(maxsize=1)
        a.queue.put_nowait("existing")

        real_get = a.queue.get_nowait
        calls = {"n": 0}

        def racing_get():
            calls["n"] += 1
            if calls["n"] == 1:
                # Simulate consumer winning the slot just before us.
                raise queue.Empty
            return real_get()

        a.queue.get_nowait = racing_get  # type: ignore[method-assign]

        result = a._enqueue_item("fresh")

        assert result is True, "Race-window drop must not happen silently"
        assert a.total_enqueue_drops == 0
        # The retry succeeded after the consumer drained; no eviction needed.

    def test_unguarded_retry_does_not_propagate_full(self):
        """Pre-PR-F killer: legacy code raised ``queue.Full`` from the
        unguarded retry, which propagated out of ``_ws_loop`` and tore
        down the WS daemon thread silently.

        The fix MUST swallow it and return False instead.
        """
        a = _make_adapter(maxsize=1)
        a.queue.put_nowait("existing")

        def always_full(_x):
            raise queue.Full

        def always_empty():
            raise queue.Empty

        a.queue.put_nowait = always_full  # type: ignore[method-assign]
        a.queue.get_nowait = always_empty  # type: ignore[method-assign]

        # The whole point: this MUST NOT raise.
        result = a._enqueue_item("doomed")

        assert result is False
        assert a.total_enqueue_drops == 1
        assert a.total_items_dropped == 1

    def test_explicit_drop_increments_counter_per_call(self):
        a = _make_adapter(maxsize=1)
        a.queue.put_nowait("x")

        def always_full(_x):
            raise queue.Full

        def always_empty():
            raise queue.Empty

        a.queue.put_nowait = always_full  # type: ignore[method-assign]
        a.queue.get_nowait = always_empty  # type: ignore[method-assign]

        a._enqueue_item("first")
        a._enqueue_item("second")

        assert a.total_enqueue_drops == 2
        assert a.total_items_dropped == 2
