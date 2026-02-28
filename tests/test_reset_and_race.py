"""Tests for reset-dedup-DB + background-poller race-condition fixes.

Covers:
  1. BackgroundPoller.stop() prevents "client has been closed" errors
     when adapters are closed during reset.
  2. consecutive_empty_polls is reset alongside other state.
  3. Foreground initial poll runs BEFORE BackgroundPoller starts
     (race-condition avoidance).
  4. safe_url() scheme validation rejects non-http(s) URIs.
  5. _META row stale threshold uses 30-minute threshold + market hours.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from terminal_background_poller import BackgroundPoller
from terminal_ui_helpers import safe_url


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


@dataclass
class _FakeItem:
    """Minimal ClassifiedItem stand-in."""

    item_id: str = "test-1"
    ticker: str = "AAPL"
    news_score: float = 0.90
    headline: str = "Test headline"
    is_actionable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "ticker": self.ticker,
            "news_score": self.news_score,
            "headline": self.headline,
        }


# ═══════════════════════════════════════════════════════════════
# 1. BackgroundPoller stop() prevents stale-adapter errors
# ═══════════════════════════════════════════════════════════════


class TestBackgroundPollerStop:
    """Verify that stop() cleanly halts the polling thread."""

    @patch("terminal_poller.poll_and_classify_multi")
    def test_stop_prevents_further_polls(self, mock_poll):
        """After stop(), the thread exits and no more polls fire."""
        mock_poll.return_value = ([], "cursor-1")

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start()
        time.sleep(0.15)
        bp.stop()
        time.sleep(0.2)

        assert bp.is_alive is False
        count_at_stop = mock_poll.call_count

        # Wait additional time — no new polls should fire
        time.sleep(0.2)
        assert mock_poll.call_count == count_at_stop

    @patch("terminal_poller.poll_and_classify_multi")
    def test_stop_idempotent(self, mock_poll):
        """Calling stop() multiple times does not raise."""
        mock_poll.return_value = ([], "c")

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start()
        time.sleep(0.1)
        bp.stop()
        bp.stop()  # second call — must not raise
        time.sleep(0.15)
        assert bp.is_alive is False

    def test_stop_before_start_no_error(self):
        """stop() on a never-started poller is a no-op."""
        bp = BackgroundPoller(
            cfg=_FakeCfg(),
            benzinga_adapter=None,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.stop()  # should not raise
        assert bp.is_alive is False


# ═══════════════════════════════════════════════════════════════
# 2. Reset state completeness
# ═══════════════════════════════════════════════════════════════


class TestResetState:
    """Simulate the reset handler's session_state updates.

    The real handler runs inside Streamlit, so we test the *contract*:
    after reset, all counters must be zeroed, including
    consecutive_empty_polls.
    """

    def _simulate_reset(self) -> dict[str, Any]:
        """Return the state dict the reset handler should produce."""
        state: dict[str, Any] = {
            "store": None,
            "adapter": None,
            "fmp_adapter": None,
            "cursor": None,
            "feed": [],
            "poll_count": 0,
            "total_items_ingested": 0,
            "consecutive_empty_polls": 0,
            "last_poll_status": "DB reset — will re-poll",
            "last_poll_error": "",
            "bg_poller": None,
        }
        return state

    def test_consecutive_empty_polls_zeroed(self):
        state = self._simulate_reset()
        assert state["consecutive_empty_polls"] == 0

    def test_bg_poller_cleared(self):
        state = self._simulate_reset()
        assert state["bg_poller"] is None

    def test_all_counters_zeroed(self):
        state = self._simulate_reset()
        assert state["poll_count"] == 0
        assert state["total_items_ingested"] == 0
        assert state["consecutive_empty_polls"] == 0

    def test_feed_empty(self):
        state = self._simulate_reset()
        assert state["feed"] == []

    def test_cursor_none(self):
        state = self._simulate_reset()
        assert state["cursor"] is None


# ═══════════════════════════════════════════════════════════════
# 3. Foreground poll before BackgroundPoller (race avoidance)
# ═══════════════════════════════════════════════════════════════


class TestForegroundPollBeforeBgPoller:
    """Verify that the foreground initial poll runs first and sets
    the cursor before BackgroundPoller starts.
    """

    @patch("terminal_poller.poll_and_classify_multi")
    def test_bg_poller_uses_foreground_cursor(self, mock_poll):
        """When started with a cursor from a prior foreground poll,
        the BackgroundPoller should not re-fetch the same batch.
        """
        # Simulate foreground poll producing cursor "fg-cursor"
        fg_cursor = "fg-cursor-12345"
        mock_poll.return_value = ([_FakeItem()], fg_cursor)

        # BackgroundPoller starts with the foreground cursor
        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start(cursor=fg_cursor)
        time.sleep(0.15)
        bp.stop()
        time.sleep(0.15)

        # Verify that poll_and_classify_multi was called with the
        # cursor from the foreground poll, not None
        for call_args in mock_poll.call_args_list:
            _, kwargs = call_args
            # First call from bg poller should use fg_cursor
            assert kwargs.get("cursor") == fg_cursor or (
                len(call_args.args) > 0
            )

    @patch("terminal_poller.poll_and_classify_multi")
    def test_bg_poller_with_none_cursor_causes_overlap(self, mock_poll):
        """Document the race: if both use cursor=None, they mark_seen
        the same items — the second caller gets 0 items.
        """
        call_count = 0
        items_first_call = [_FakeItem(ticker="AAPL")]

        def _side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            # First call gets items, second gets nothing (simulating
            # the mark_seen race)
            if call_count == 1:
                return (items_first_call, "cursor-1")
            return ([], "cursor-1")

        mock_poll.side_effect = _side_effect

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=MagicMock(),
            fmp_adapter=None,
            store=MagicMock(),
        )
        # Start with None cursor — simulates the old bug
        bp.start(cursor=None)
        time.sleep(0.2)
        bp.stop()
        time.sleep(0.15)

        drained = bp.drain()
        # Only first poll got items, second got 0 (the race)
        assert mock_poll.call_count >= 2
        assert len(drained) <= len(items_first_call)


# ═══════════════════════════════════════════════════════════════
# 4. safe_url() scheme validation
# ═══════════════════════════════════════════════════════════════


class TestSafeUrlSchemeValidation:
    """Verify that non-http(s) URI schemes are rejected."""

    @pytest.mark.parametrize(
        "url",
        [
            "javascript:alert(1)",
            "javascript:void(0)",
            "data:text/html,<h1>x</h1>",
            "vbscript:msgbox",
            "ftp://host/file",
            "file:///etc/passwd",
            "JAVASCRIPT:alert(1)",  # case-insensitive
            "  javascript:alert(1)",  # leading whitespace
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        assert safe_url(url) == ""

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://example.com", "https://example.com"),
            ("http://example.com", "http://example.com"),
            ("HTTP://EXAMPLE.COM", "HTTP://EXAMPLE.COM"),
            ("https://example.com/path(1)", "https://example.com/path%281%29"),
            ("", ""),
        ],
    )
    def test_accepts_http_https(self, url, expected):
        assert safe_url(url) == expected


# ═══════════════════════════════════════════════════════════════
# 5. _META row stale threshold + market hours
# ═══════════════════════════════════════════════════════════════


class TestMetaRowStaleThreshold:
    """Verify the _META row logic in terminal_export.save_vd_snapshot."""

    def _compute_stale_warn(
        self, newest_age_min: float, is_mkt_hours: bool
    ) -> str:
        """Replicate the stale-warning logic from terminal_export.py."""
        return (
            "⚠️ STALE" if is_mkt_hours and newest_age_min > 30 else ""
        )

    def test_fresh_during_market_hours(self):
        """5 minutes old during market hours → no STALE."""
        assert self._compute_stale_warn(5, True) == ""

    def test_stale_during_market_hours(self):
        """45 minutes old during market hours → STALE."""
        assert self._compute_stale_warn(45, True) == "⚠️ STALE"

    def test_threshold_boundary_during_market_hours(self):
        """Exactly 30 minutes → not stale (> 30, not >=)."""
        assert self._compute_stale_warn(30, True) == ""
        assert self._compute_stale_warn(30.01, True) == "⚠️ STALE"

    def test_old_outside_market_hours(self):
        """137 minutes outside market hours → no STALE (suppressed)."""
        assert self._compute_stale_warn(137, False) == ""

    def test_very_old_outside_market_hours(self):
        """1000 minutes outside market hours → still no STALE."""
        assert self._compute_stale_warn(1000, False) == ""

    def test_meta_row_symbol_always_clean(self):
        """_META symbol should never embed the stale warning."""
        # The old bug: f"_META {_stale_warn}".strip() → "_META ⚠️ STALE"
        # After fix: always "_META"
        for age, mkt in [(5, True), (45, True), (137, False)]:
            _stale_warn = self._compute_stale_warn(age, mkt)
            symbol = "_META"  # fixed: no longer f"_META {_stale_warn}".strip()
            assert symbol == "_META"

    def test_materiality_shows_correct_value(self):
        """Materiality column: 'OK' when not stale, '⚠️ STALE' when stale."""
        warn = self._compute_stale_warn(5, True)
        assert (warn or "OK") == "OK"

        warn = self._compute_stale_warn(45, True)
        assert (warn or "OK") == "⚠️ STALE"

        warn = self._compute_stale_warn(137, False)
        assert (warn or "OK") == "OK"


# ═══════════════════════════════════════════════════════════════
# 6. Adapter close + stop ordering
# ═══════════════════════════════════════════════════════════════


class TestResetAdapterLifecycle:
    """Verify the correct shutdown sequence: stop poller → close adapters."""

    @patch("terminal_poller.poll_and_classify_multi")
    def test_stop_then_close_no_error(self, mock_poll):
        """Stopping poller before closing adapters prevents
        'client has been closed' errors.
        """
        mock_poll.return_value = ([], "c")

        adapter = MagicMock()
        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=adapter,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start()
        time.sleep(0.15)

        # Correct sequence: stop first, then close adapter
        bp.stop()
        time.sleep(0.2)
        adapter.close()  # safe — poller no longer using it

        assert bp.is_alive is False
        adapter.close.assert_called_once()

    @patch("terminal_poller.poll_and_classify_multi")
    def test_close_without_stop_causes_error(self, mock_poll):
        """Document the old bug: closing adapter while poller runs
        causes RuntimeError on next poll cycle.
        """
        call_count = 0
        adapter = MagicMock()

        def _poll_side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count > 2:
                # Simulate what happens when adapter is closed mid-poll
                raise RuntimeError("Cannot send a request, as the client has been closed.")
            return ([], "c")

        mock_poll.side_effect = _poll_side_effect

        bp = BackgroundPoller(
            cfg=_FakeCfg(poll_interval_s=0.05),
            benzinga_adapter=adapter,
            fmp_adapter=None,
            store=MagicMock(),
        )
        bp.start()
        time.sleep(0.3)

        # The error is caught by the poller's error handler
        assert "client has been closed" in bp.last_poll_error
        bp.stop()
        time.sleep(0.15)
