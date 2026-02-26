"""Tests for terminal_feed_lifecycle.py — overnight/weekend feed management."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from terminal_feed_lifecycle import (
    FeedLifecycleManager,
    feed_staleness_minutes,
    is_feed_stale,
    is_market_hours,
    is_off_hours,
    is_premarket_window,
    is_weekend,
)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------


def _make_et(weekday: int, hour: int, minute: int = 0) -> datetime:
    """Create a mock ET datetime with a specific weekday/time.

    weekday: 0=Monday, 5=Saturday, 6=Sunday
    """
    # Start from a known Monday: 2026-02-23 is a Monday
    base = datetime(2026, 2, 23, hour, minute, tzinfo=timezone.utc)
    delta = weekday  # 0=Mon
    return base + timedelta(days=delta)


class TestIsWeekend:
    def test_monday(self):
        assert is_weekend(_make_et(0, 10)) is False

    def test_friday(self):
        assert is_weekend(_make_et(4, 15)) is False

    def test_saturday(self):
        assert is_weekend(_make_et(5, 10)) is True

    def test_sunday(self):
        assert is_weekend(_make_et(6, 10)) is True


class TestIsPremarketWindow:
    def test_within_window(self):
        """09:00-09:30 ET is the pre-seed window."""
        assert is_premarket_window(_make_et(0, 9, 15)) is True

    def test_before_window(self):
        assert is_premarket_window(_make_et(0, 8, 59)) is False

    def test_after_window(self):
        assert is_premarket_window(_make_et(0, 9, 30)) is False

    def test_weekend(self):
        assert is_premarket_window(_make_et(5, 9, 15)) is False


class TestIsMarketHours:
    def test_regular_hours(self):
        assert is_market_hours(_make_et(1, 10)) is True  # Tuesday 10am

    def test_premarket(self):
        assert is_market_hours(_make_et(1, 4)) is True  # 4am ET

    def test_after_hours(self):
        assert is_market_hours(_make_et(1, 19)) is True  # 7pm ET

    def test_off_hours_late(self):
        assert is_market_hours(_make_et(1, 21)) is False  # 9pm ET

    def test_off_hours_early(self):
        assert is_market_hours(_make_et(1, 3)) is False  # 3am ET

    def test_weekend(self):
        assert is_market_hours(_make_et(5, 10)) is False


class TestIsOffHours:
    def test_during_market(self):
        assert is_off_hours(_make_et(1, 10)) is False

    def test_weekend(self):
        assert is_off_hours(_make_et(5, 10)) is True

    def test_late_night(self):
        assert is_off_hours(_make_et(1, 22)) is True


# ---------------------------------------------------------------------------
# Feed staleness
# ---------------------------------------------------------------------------


class TestFeedStaleness:
    def test_empty_feed(self):
        assert feed_staleness_minutes([]) is None
        assert is_feed_stale([]) is True

    def test_fresh_feed(self):
        now = time.time()
        feed = [{"published_ts": now - 300}]  # 5 minutes
        age = feed_staleness_minutes(feed)
        assert age is not None
        assert 4.5 < age < 5.5

    def test_stale_feed(self):
        now = time.time()
        feed = [{"published_ts": now - 7200}]  # 2 hours
        assert is_feed_stale(feed, max_age_min=60) is True
        assert is_feed_stale(feed, max_age_min=180) is False

    def test_uses_newest(self):
        now = time.time()
        feed = [
            {"published_ts": now - 7200},
            {"published_ts": now - 60},
        ]
        age = feed_staleness_minutes(feed)
        assert age is not None
        assert age < 2  # should use the 1-min-old item


# ---------------------------------------------------------------------------
# FeedLifecycleManager
# ---------------------------------------------------------------------------


class TestFeedLifecycleManager:
    def test_init(self):
        mgr = FeedLifecycleManager()
        assert mgr._weekend_cleared is False
        assert mgr._preseed_done is False

    @patch("terminal_feed_lifecycle._now_et")
    def test_should_clear_weekend_monday_morning(self, mock_now):
        mock_now.return_value = _make_et(0, 4)  # Monday 4am
        mgr = FeedLifecycleManager()
        assert mgr.should_clear_weekend_data() is True

    @patch("terminal_feed_lifecycle._now_et")
    def test_should_not_clear_tuesday(self, mock_now):
        mock_now.return_value = _make_et(1, 4)  # Tuesday 4am
        mgr = FeedLifecycleManager()
        assert mgr.should_clear_weekend_data() is False

    @patch("terminal_feed_lifecycle._now_et")
    def test_should_not_clear_after_open(self, mock_now):
        mock_now.return_value = _make_et(0, 10)  # Monday 10am (after open)
        mgr = FeedLifecycleManager()
        assert mgr.should_clear_weekend_data() is False

    @patch("terminal_feed_lifecycle._now_et")
    def test_clear_weekend_data(self, mock_now):
        mock_now.return_value = _make_et(0, 4)  # Monday 4am
        mgr = FeedLifecycleManager(jsonl_path="fake.jsonl")
        store = MagicMock()

        with patch("terminal_feed_lifecycle.os.path.isfile", return_value=False):
            result = mgr.clear_weekend_data(store)

        assert result["cleared"] is True
        store.prune_seen.assert_called_once_with(keep_seconds=0.0)
        store.prune_clusters.assert_called_once_with(keep_seconds=0.0)
        assert mgr._weekend_cleared is True

    @patch("terminal_feed_lifecycle._now_et")
    def test_clear_only_once_per_monday(self, mock_now):
        mock_now.return_value = _make_et(0, 4)
        mgr = FeedLifecycleManager(jsonl_path="fake.jsonl")
        store = MagicMock()

        with patch("terminal_feed_lifecycle.os.path.isfile", return_value=False):
            mgr.clear_weekend_data(store)

        # Second call should return False
        assert mgr.should_clear_weekend_data() is False

    @patch("terminal_feed_lifecycle._now_et")
    def test_should_preseed(self, mock_now):
        mock_now.return_value = _make_et(0, 9, 15)  # 9:15 ET
        mgr = FeedLifecycleManager()
        assert mgr.should_preseed() is True

    @patch("terminal_feed_lifecycle._now_et")
    def test_preseed_only_once(self, mock_now):
        mock_now.return_value = _make_et(0, 9, 15)
        mgr = FeedLifecycleManager()
        mgr.mark_preseed_done()
        assert mgr.should_preseed() is False

    # ── Off-hours interval ──────────────────────────────────

    @patch("terminal_feed_lifecycle._now_et")
    def test_interval_regular_hours(self, mock_now):
        mock_now.return_value = _make_et(1, 10)  # Tuesday 10am
        mgr = FeedLifecycleManager()
        assert mgr.get_off_hours_poll_interval(5.0) == 5.0

    @patch("terminal_feed_lifecycle._now_et")
    def test_interval_premarket(self, mock_now):
        mock_now.return_value = _make_et(1, 8)  # Tuesday 8am
        mgr = FeedLifecycleManager()
        assert mgr.get_off_hours_poll_interval(5.0) == 10.0

    @patch("terminal_feed_lifecycle._now_et")
    def test_interval_after_hours(self, mock_now):
        mock_now.return_value = _make_et(1, 17)  # Tuesday 5pm
        mgr = FeedLifecycleManager()
        assert mgr.get_off_hours_poll_interval(5.0) == 15.0

    @patch("terminal_feed_lifecycle._now_et")
    def test_interval_weekend(self, mock_now):
        mock_now.return_value = _make_et(5, 10)  # Saturday 10am
        mgr = FeedLifecycleManager()
        assert mgr.get_off_hours_poll_interval(5.0) == 120.0

    @patch("terminal_feed_lifecycle._now_et")
    def test_interval_off_hours_night(self, mock_now):
        mock_now.return_value = _make_et(1, 22)  # Tuesday 10pm
        mgr = FeedLifecycleManager()
        assert mgr.get_off_hours_poll_interval(5.0) == 60.0

    # ── manage() ────────────────────────────────────────────

    def test_manage_throttled(self):
        mgr = FeedLifecycleManager()
        mgr._last_lifecycle_check = time.time()  # just checked
        result = mgr.manage([], MagicMock())
        assert result["action"] == "throttled"

    @patch("terminal_feed_lifecycle._now_et")
    def test_manage_weekend_clear(self, mock_now):
        mock_now.return_value = _make_et(0, 4)
        mgr = FeedLifecycleManager(jsonl_path="fake.jsonl")
        mgr._last_lifecycle_check = 0  # force check

        store = MagicMock()
        with patch("terminal_feed_lifecycle.os.path.isfile", return_value=False):
            result = mgr.manage([], store)

        assert result.get("feed_action") == "cleared"

    # ── Status display ──────────────────────────────────────

    @patch("terminal_feed_lifecycle._now_et")
    def test_status_market_hours(self, mock_now):
        mock_now.return_value = _make_et(1, 10)
        mgr = FeedLifecycleManager()
        status = mgr.get_status_display()
        assert "Market hours" in status["phase"]

    @patch("terminal_feed_lifecycle._now_et")
    def test_status_weekend(self, mock_now):
        mock_now.return_value = _make_et(5, 10)
        mgr = FeedLifecycleManager()
        status = mgr.get_status_display()
        assert "Weekend" in status["phase"]

    @patch("terminal_feed_lifecycle._now_et")
    def test_status_preseed(self, mock_now):
        mock_now.return_value = _make_et(0, 9, 15)
        mgr = FeedLifecycleManager()
        status = mgr.get_status_display()
        assert "pre-seed" in status["phase"]
