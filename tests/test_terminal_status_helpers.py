"""Tests for terminal_status_helpers — pure status rendering logic."""
from __future__ import annotations

import time

import pytest

from terminal_status_helpers import (
    api_key_status,
    cursor_diagnostic,
    degraded_mode_reasons,
    feed_staleness_diagnostic,
    format_poll_ago,
    format_provider_status_line,
    poll_failure_count,
)


class TestApiKeyStatus:

    def test_all_configured(self) -> None:
        result = api_key_status(
            benzinga_key="abc", databento_available=True, openai_key="xyz"
        )
        assert all(r["configured"] for r in result)
        assert all("✅" in r["icon"] for r in result)

    def test_none_configured(self) -> None:
        result = api_key_status(
            benzinga_key="", databento_available=False, openai_key=""
        )
        assert not result[0]["configured"]  # Benzinga
        assert not result[1]["configured"]  # Databento
        assert not result[2]["configured"]  # OpenAI

    def test_partial(self) -> None:
        result = api_key_status(
            benzinga_key="key", databento_available=False, openai_key=""
        )
        assert result[0]["configured"]
        assert not result[1]["configured"]


class TestFeedStaleness:

    def test_none_staleness(self) -> None:
        d = feed_staleness_diagnostic(None, True)
        assert d["severity"] == "ok"
        assert d["label"] == ""

    def test_fresh_during_market(self) -> None:
        d = feed_staleness_diagnostic(1.0, True)
        assert d["severity"] == "ok"

    def test_stale_during_market(self) -> None:
        d = feed_staleness_diagnostic(5.0, True)
        assert d["severity"] == "warn"

    def test_off_hours_mild(self) -> None:
        d = feed_staleness_diagnostic(10.0, False)
        assert d["severity"] == "ok"
        assert "off-hours" in d["label"]

    def test_off_hours_very_stale(self) -> None:
        d = feed_staleness_diagnostic(20.0, False)
        assert d["severity"] == "warn"


class TestCursorDiagnostic:

    def test_none_cursor(self) -> None:
        assert cursor_diagnostic(None) == "Cursor: (initial)"

    def test_empty_cursor(self) -> None:
        assert cursor_diagnostic("") == "Cursor: (initial)"

    def test_timestamp_cursor(self) -> None:
        ts = str(time.time() - 120)
        result = cursor_diagnostic(ts)
        assert "2m ago" in result or "Cursor:" in result

    def test_non_numeric_cursor(self) -> None:
        result = cursor_diagnostic("some_opaque_token_123")
        assert "some_opaque_token_12" in result


class TestPollFailureCount:

    def test_no_failures(self) -> None:
        assert poll_failure_count(10, 10) is None

    def test_some_failures(self) -> None:
        assert poll_failure_count(10, 7) == 3


class TestFormatPollAgo:

    def test_no_ts(self) -> None:
        assert format_poll_ago(0.0) == ""

    def test_recent(self) -> None:
        result = format_poll_ago(time.time() - 5, last_duration_s=0.3)
        assert "5s ago" in result or "Last poll:" in result
        assert "0.3s" in result


class TestProviderStatusLine:

    def test_up(self) -> None:
        line = format_provider_status_line("fmp", "up", "healthy", avg_latency_ms=42.0)
        assert "✅" in line
        assert "42ms" in line

    def test_down(self) -> None:
        line = format_provider_status_line("fmp", "down", "5 consecutive failures")
        assert "🔴" in line
        assert "consecutive" in line


class TestDegradedModeReasons:

    def test_healthy(self) -> None:
        reasons = degraded_mode_reasons()
        assert reasons == []

    def test_provider_down(self) -> None:
        reasons = degraded_mode_reasons(
            provider_statuses=[{"name": "fmp", "availability": "down", "reason": "timeout"}]
        )
        assert len(reasons) == 1
        assert "fmp" in reasons[0]

    def test_stale_feed_during_market(self) -> None:
        reasons = degraded_mode_reasons(feed_staleness_min=10.0, is_market_hours=True)
        assert any("stale" in r.lower() for r in reasons)

    def test_stale_feed_off_hours_ignored(self) -> None:
        reasons = degraded_mode_reasons(feed_staleness_min=10.0, is_market_hours=False)
        assert reasons == []

    def test_empty_polls(self) -> None:
        reasons = degraded_mode_reasons(consecutive_empty_polls=5)
        assert any("empty polls" in r for r in reasons)

    def test_bg_poller_failure(self) -> None:
        reasons = degraded_mode_reasons(
            bg_poller_last_failure={"last_poll_error": "Connection refused"}
        )
        assert any("Connection refused" in r for r in reasons)

    def test_combined(self) -> None:
        reasons = degraded_mode_reasons(
            provider_statuses=[{"name": "x", "availability": "degraded", "reason": "slow"}],
            consecutive_empty_polls=4,
            feed_staleness_min=8.0,
            is_market_hours=True,
        )
        assert len(reasons) == 3
