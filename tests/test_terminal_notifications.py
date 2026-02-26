"""Tests for terminal_notifications.py — push notification module."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from terminal_notifications import (
    NotifyConfig,
    _format_discord_message,
    _format_message,
    _is_market_hours,
    _is_throttled,
    _mark_notified,
    _send_discord,
    _send_pushover,
    _send_telegram,
    notify_high_score_items,
    reset_throttle,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_throttle():
    """Reset throttle state before each test."""
    reset_throttle()
    yield
    reset_throttle()


def _make_item(
    ticker: str = "AAPL",
    score: float = 0.90,
    sentiment: str = "bullish",
    age_minutes: float = 5.0,
    url: str = "https://example.com/article",
) -> dict:
    return {
        "ticker": ticker,
        "news_score": score,
        "sentiment_label": sentiment,
        "headline": f"Test headline for {ticker}",
        "event_label": "earnings",
        "materiality": "HIGH",
        "age_minutes": age_minutes,
        "url": url,
    }


def _disabled_config() -> NotifyConfig:
    return NotifyConfig.__new__(NotifyConfig)


# ---------------------------------------------------------------------------
# NotifyConfig
# ---------------------------------------------------------------------------


class TestNotifyConfig:
    def test_defaults(self):
        cfg = NotifyConfig()
        assert cfg.enabled is False
        assert cfg.min_score == 0.85
        assert cfg.throttle_s == 600

    def test_has_any_channel_false(self):
        cfg = NotifyConfig()
        assert cfg.has_any_channel is False

    @patch.dict("os.environ", {"TERMINAL_TELEGRAM_BOT_TOKEN": "tok", "TERMINAL_TELEGRAM_CHAT_ID": "123"})
    def test_has_telegram_channel(self):
        cfg = NotifyConfig()
        assert cfg.has_any_channel is True

    @patch.dict("os.environ", {"TERMINAL_DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/test"})
    def test_has_discord_channel(self):
        cfg = NotifyConfig()
        assert cfg.has_any_channel is True

    @patch.dict("os.environ", {"TERMINAL_PUSHOVER_APP_TOKEN": "tok", "TERMINAL_PUSHOVER_USER_KEY": "usr"})
    def test_has_pushover_channel(self):
        cfg = NotifyConfig()
        assert cfg.has_any_channel is True


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------


class TestThrottle:
    def test_not_throttled_initially(self):
        assert _is_throttled("AAPL", 600) is False

    def test_throttled_after_mark(self):
        _mark_notified("AAPL")
        assert _is_throttled("AAPL", 600) is True

    def test_different_symbol_not_throttled(self):
        _mark_notified("AAPL")
        assert _is_throttled("TSLA", 600) is False

    def test_throttle_expires(self):
        from terminal_notifications import _last_notified

        _last_notified["AAPL"] = time.time() - 700
        assert _is_throttled("AAPL", 600) is False

    def test_reset_clears(self):
        _mark_notified("AAPL")
        reset_throttle()
        assert _is_throttled("AAPL", 600) is False


# ---------------------------------------------------------------------------
# Message formatting
# ---------------------------------------------------------------------------


class TestFormatting:
    def test_format_message_basic(self):
        item = _make_item()
        msg = _format_message(item)
        assert "AAPL" in msg
        assert "0.900" in msg
        assert "bullish" in msg
        assert "ALERT" in msg

    def test_format_message_with_url(self):
        item = _make_item(url="https://example.com/article")
        msg = _format_message(item)
        assert "[Article]" in msg

    def test_format_message_no_url(self):
        item = _make_item(url="")
        msg = _format_message(item)
        assert "[Article]" not in msg

    def test_format_discord_message(self):
        item = _make_item()
        msg = _format_discord_message(item)
        assert "**AAPL**" in msg
        assert "**ALERT**" in msg

    def test_format_truncates_headline(self):
        item = _make_item()
        item["headline"] = "A" * 200
        msg = _format_message(item)
        # Headline truncated to 120 chars
        assert "A" * 120 in msg
        assert "A" * 121 not in msg


# ---------------------------------------------------------------------------
# Channel senders (mocked HTTP)
# ---------------------------------------------------------------------------


class TestSendTelegram:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert _send_telegram("tok", "123", "test") is True

    @patch("urllib.request.urlopen")
    def test_failure(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 400, "Bad Request", {}, None
        )
        assert _send_telegram("tok", "123", "test") is False


class TestSendDiscord:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 204
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert _send_discord("https://discord.com/api/webhooks/test", "msg") is True

    @patch("urllib.request.urlopen")
    def test_204_http_error(self, mock_urlopen):
        import urllib.error

        mock_urlopen.side_effect = urllib.error.HTTPError(
            "url", 204, "No Content", {}, None
        )
        assert _send_discord("https://discord.com/api/webhooks/test", "msg") is True


class TestSendPushover:
    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        resp = MagicMock()
        resp.status = 200
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = resp

        assert _send_pushover("app", "usr", "title", "msg") is True


# ---------------------------------------------------------------------------
# Main dispatch
# ---------------------------------------------------------------------------


class TestNotifyHighScoreItems:
    def test_disabled(self):
        cfg = NotifyConfig()  # enabled=False
        items = [_make_item(score=0.95)]
        result = notify_high_score_items(items, config=cfg)
        assert result == []

    @patch("terminal_notifications._is_market_hours", return_value=False)
    def test_outside_market_hours(self, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        result = notify_high_score_items([_make_item(score=0.95)], config=cfg)
        assert result == []

    @patch("terminal_notifications._is_market_hours", return_value=True)
    @patch("terminal_notifications._send_telegram", return_value=True)
    def test_telegram_dispatch(self, mock_send, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        items = [_make_item(ticker="TSLA", score=0.92)]
        result = notify_high_score_items(items, config=cfg)
        assert len(result) == 1
        assert result[0]["ticker"] == "TSLA"
        mock_send.assert_called_once()

    @patch("terminal_notifications._is_market_hours", return_value=True)
    @patch("terminal_notifications._send_telegram", return_value=True)
    def test_below_threshold_skipped(self, mock_send, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        items = [_make_item(score=0.50)]
        result = notify_high_score_items(items, config=cfg)
        assert result == []
        mock_send.assert_not_called()

    @patch("terminal_notifications._is_market_hours", return_value=True)
    @patch("terminal_notifications._send_telegram", return_value=True)
    def test_stale_item_skipped(self, mock_send, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        items = [_make_item(score=0.92, age_minutes=60)]
        result = notify_high_score_items(items, config=cfg)
        assert result == []
        mock_send.assert_not_called()

    @patch("terminal_notifications._is_market_hours", return_value=True)
    @patch("terminal_notifications._send_telegram", return_value=True)
    def test_throttled_skipped(self, mock_send, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        _mark_notified("AAPL")
        items = [_make_item(ticker="AAPL", score=0.95)]
        result = notify_high_score_items(items, config=cfg)
        assert result == []

    @patch("terminal_notifications._is_market_hours", return_value=True)
    @patch("terminal_notifications._send_telegram", return_value=True)
    @patch("terminal_notifications._send_discord", return_value=True)
    def test_multi_channel(self, mock_discord, mock_tg, _):
        cfg = NotifyConfig.__new__(NotifyConfig)
        object.__setattr__(cfg, "enabled", True)
        object.__setattr__(cfg, "min_score", 0.85)
        object.__setattr__(cfg, "throttle_s", 600)
        object.__setattr__(cfg, "max_age_minutes", 20.0)
        object.__setattr__(cfg, "telegram_bot_token", "tok")
        object.__setattr__(cfg, "telegram_chat_id", "123")
        object.__setattr__(cfg, "discord_webhook_url", "https://discord.com/api/webhooks/test")
        object.__setattr__(cfg, "pushover_app_token", "")
        object.__setattr__(cfg, "pushover_user_key", "")

        items = [_make_item(score=0.92)]
        result = notify_high_score_items(items, config=cfg)
        assert len(result) == 1
        assert len(result[0]["channels"]) == 2
        mock_tg.assert_called_once()
        mock_discord.assert_called_once()
