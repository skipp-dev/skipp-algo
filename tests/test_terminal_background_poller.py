"""Tests for terminal_background_poller.py — background polling thread."""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from terminal_background_poller import BackgroundPoller
from terminal_feed_state import merge_live_feed_rows
from terminal_live_story_state import live_story_key


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
    feed_max_age_s: float = 14400.0
    live_story_ttl_s: float = 7200.0
    live_story_cooldown_s: float = 900.0
    max_items: int = 50


@dataclass
class _FakeItem:
    """Minimal ClassifiedItem stand-in."""

    item_id: str = "test-1"
    ticker: str = "AAPL"
    news_score: float = 0.90
    headline: str = "Test"
    is_actionable: bool = True
    provider: str = "benzinga_rest"
    source: str = "Benzinga"
    source_rank: int = 1
    materiality: str = "HIGH"
    published_ts: float = 1000.0
    updated_ts: float = 1000.0
    sentiment_label: str = "bullish"

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "ticker": self.ticker,
            "news_score": self.news_score,
            "headline": self.headline,
            "provider": self.provider,
            "source": self.source,
            "source_rank": self.source_rank,
            "materiality": self.materiality,
            "published_ts": self.published_ts,
            "updated_ts": self.updated_ts,
            "sentiment_label": self.sentiment_label,
            "event_label": "product",
            "is_actionable": self.is_actionable,
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
        assert bp.provider_cursors == {
            "benzinga": "12345",
            "fmp_stock": "12345",
            "fmp_press": "12345",
            "tv": "12345",
        }

    def test_update_interval(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.update_interval(10.0)
        assert bp._get_interval() == 10.0

    @patch("terminal_poller.poll_and_classify_live_bus")
    def test_start_and_stop(self, mock_poll):
        """Test that start/stop lifecycle works."""
        fake_items = [_FakeItem()]
        mock_poll.return_value = (fake_items, {"benzinga": "100"}, {"benzinga": 1})

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

        bp.stop_and_join(timeout=1.0)

        # Should have polled at least once
        assert bp.poll_count >= 1
        assert mock_poll.called

    @patch("terminal_poller.poll_and_classify_live_bus")
    def test_items_enqueued(self, mock_poll):
        """Test that polled items are enqueued for drain."""
        fake_items = [_FakeItem(ticker="NVDA")]
        mock_poll.return_value = (fake_items, {"benzinga": "200"}, {"benzinga": 1})

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )

        bp.start()
        time.sleep(0.3)
        bp.stop_and_join(timeout=1.0)

        drained = bp.drain()
        assert len(drained) >= 1
        assert any(item.ticker == "NVDA" for item in drained)

    def test_drained_items_can_merge_into_feed_state(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        item = _FakeItem(item_id="nvda-1", ticker="NVDA", headline="Nvidia expands AI chip supply")
        story_key = live_story_key(item.to_dict())
        bp._queue.put_nowait([item])

        drained = bp.drain()
        result = merge_live_feed_rows(
            [],
            [queued_item.to_dict() for queued_item in drained],
            cfg=_FakeCfg(),
            previous_reaction_state={
                "NVDA": {
                    "reaction_state": "CONFIRMED",
                    "reaction_score": 0.87,
                    "reaction_confidence": 0.78,
                    "reaction_actionable": True,
                    "reaction_anchor_story_key": story_key,
                    "reaction_anchor_price": 100.0,
                    "reaction_anchor_ts": 900.0,
                    "reaction_peak_impulse_pct": 1.3,
                    "catalyst_direction": "BULLISH",
                },
            },
            previous_resolution_state={
                "NVDA": {
                    "resolution_state": "OPEN",
                    "resolution_anchor_story_key": story_key,
                    "resolution_anchor_price": 100.0,
                    "resolution_anchor_ts": 900.0,
                    "resolution_peak_impulse_pct": 1.3,
                    "resolution_last_update_ts": 950.0,
                    "catalyst_direction": "BULLISH",
                },
            },
            rt_quotes={"NVDA": {"price": 101.0, "chg_pct": 1.0, "vol_ratio": 1.9}},
            now=1500.0,
        )

        assert result.new_count == 1
        assert result.feed[0]["ticker"] == "NVDA"
        assert result.ticker_reaction_state["NVDA"]["reaction_state"] == "CONFIRMED"
        assert result.ticker_resolution_state["NVDA"]["resolution_state"] == "FOLLOW_THROUGH"
        assert result.ticker_posture_state["NVDA"]["posture_state"] == "LONG"

    @patch("terminal_poller.poll_and_classify_live_bus")
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
        bp.stop_and_join(timeout=1.0)

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
        bp.stop_and_join(timeout=1.0)

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
        bp.update_adapters(benzinga_adapter=None, fmp_adapter="fmp-live")
        assert bp._benzinga is None
        assert bp._fmp == "fmp-live"

    def test_start_accepts_provider_cursor_dict(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )

        bp.start(cursor={"benzinga": "111", "fmp_stock": "222"})
        try:
            assert bp.provider_cursors == {"benzinga": "111", "fmp_stock": "222"}
        finally:
            bp.stop_and_join(timeout=1.0)

    def test_update_live_news_symbols(self):
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.update_live_news_symbols(["aapl", " MSFT ", ""])
        assert bp._tv_symbols == ["AAPL", "MSFT"]

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
