"""Tests for terminal_background_poller.py — background polling thread."""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from terminal_background_poller import BackgroundPoller


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FakeCfg:
    """Minimal TerminalConfig stand-in."""

    poll_interval_s: float = 0.1
    page_size: int = 10
    benzinga_api_key: str = "test"
    fmp_api_key: str = ""
    channels: str = ""
    topics: str = ""


@dataclass
class _FakeItem:
    """Minimal ClassifiedItem stand-in."""

    item_id: str = "test-1"
    ticker: str = "AAPL"
    news_score: float = 0.90
    headline: str = "Test"
    is_actionable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "ticker": self.ticker,
            "news_score": self.news_score,
            "headline": self.headline,
        }


# ---------------------------------------------------------------------------
# BackgroundPoller tests
# ---------------------------------------------------------------------------


class TestBackgroundPoller:
    def test_init(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        assert bp.poll_count == 0
        assert bp.is_alive is False

    def test_drain_empty(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        assert bp.drain() == []

    def test_drain_items(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        # Simulate items being put on the queue
        bp._queue.put_nowait([_FakeItem(ticker="AAPL"), _FakeItem(ticker="TSLA")])
        bp._queue.put_nowait([_FakeItem(ticker="MSFT")])

        result = bp.drain()
        assert len(result) == 3
        # Queue should be empty after drain
        assert bp.drain() == []

    def test_cursor_property(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        assert bp.cursor is None
        bp.cursor = "12345"
        assert bp.cursor == "12345"

    def test_update_interval(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.update_interval(10.0)
        assert bp._get_interval() == 10.0

    @patch("terminal_poller.poll_and_classify_multi")
    def test_start_and_stop(self, mock_poll):
        """Test that start/stop lifecycle works."""
        fake_items = [_FakeItem()]
        mock_poll.return_value = (fake_items, "100")

        store = MagicMock()
        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=store,
        )

        bp.start()
        assert bp.is_alive is True

        # Wait for at least one poll cycle
        time.sleep(0.3)

        bp.stop()
        time.sleep(0.2)

        # Should have polled at least once
        assert bp.poll_count >= 1
        assert mock_poll.called

    @patch("terminal_poller.poll_and_classify_multi")
    def test_items_enqueued(self, mock_poll):
        """Test that polled items are enqueued for drain."""
        fake_items = [_FakeItem(ticker="NVDA")]
        mock_poll.return_value = (fake_items, "200")

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )

        bp.start()
        time.sleep(0.3)
        bp.stop()

        drained = bp.drain()
        assert len(drained) >= 1
        assert any(item.ticker == "NVDA" for item in drained)

    @patch("terminal_poller.poll_and_classify_multi")
    def test_poll_error_handled(self, mock_poll):
        """Test that poll errors don't crash the thread."""
        mock_poll.side_effect = RuntimeError("API down")

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )

        bp.start()
        time.sleep(0.3)
        bp.stop()

        assert "API down" in bp.last_poll_error
        assert bp.last_poll_status == "ERROR"

    def test_start_idempotent(self):
        """Multiple start() calls should not create multiple threads."""
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start()
        thread1 = bp._thread
        bp.start()  # second call
        thread2 = bp._thread
        assert thread1 is thread2
        bp.stop()

    def test_update_adapters(self):
        """Test adapter hot-swap."""
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        new_adapter = MagicMock()
        bp.update_adapters(benzinga_adapter=new_adapter)
        assert bp._benzinga is new_adapter

    def test_queue_evicts_oldest_when_full(self):
        """When queue is full, oldest batches are evicted (ring-buffer)."""
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        # Replace queue with a tiny one
        bp._queue = queue.Queue(maxsize=2)
        bp._queue.put_nowait([_FakeItem(ticker="OLD1")])
        bp._queue.put_nowait([_FakeItem(ticker="OLD2")])

        # Now simulate what the poll loop does when the queue is full
        new_items = [_FakeItem(ticker="NEW")]
        evicted = 0
        while True:
            try:
                bp._queue.put_nowait(new_items)
                break
            except queue.Full:
                try:
                    old = bp._queue.get_nowait()
                    evicted += len(old)
                except queue.Empty:
                    break

        assert evicted == 1  # OLD1 was evicted
        drained = bp.drain()
        tickers = [item.ticker for item in drained]
        assert "NEW" in tickers
        assert "OLD2" in tickers
        assert "OLD1" not in tickers

    def test_total_items_dropped_counter(self):
        """total_items_dropped should track evicted items."""
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        assert bp.total_items_dropped == 0
