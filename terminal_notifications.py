"""Push notifications for high-score terminal entries.

Dispatches alerts to Telegram, Discord, and/or Pushover when a symbol
with ``news_score >= threshold`` enters the rankings during market hours.

Configuration is read from environment variables:

    TERMINAL_NOTIFY_ENABLED=1
    TERMINAL_NOTIFY_MIN_SCORE=0.85
    TERMINAL_NOTIFY_THROTTLE_S=600

    # Telegram
    TERMINAL_TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
    TERMINAL_TELEGRAM_CHAT_ID=-1001234567890

    # Discord
    TERMINAL_DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

    # Pushover
    TERMINAL_PUSHOVER_APP_TOKEN=...
    TERMINAL_PUSHOVER_USER_KEY=...

All channels are optional — only configured channels receive alerts.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NotifyConfig:
    """Push-notification settings (reads env at instantiation)."""

    enabled: bool = field(
        default_factory=lambda: os.getenv("TERMINAL_NOTIFY_ENABLED", "0") == "1",
    )
    min_score: float = field(
        default_factory=lambda: float(os.getenv("TERMINAL_NOTIFY_MIN_SCORE", "0.85")),
    )
    throttle_s: int = field(
        default_factory=lambda: int(os.getenv("TERMINAL_NOTIFY_THROTTLE_S", "600")),
    )
    max_age_minutes: float = field(
        default_factory=lambda: float(os.getenv("TERMINAL_NOTIFY_MAX_AGE_MIN", "20")),
    )
    # Telegram
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TERMINAL_TELEGRAM_BOT_TOKEN", ""),
        repr=False,
    )
    telegram_chat_id: str = field(
        default_factory=lambda: os.getenv("TERMINAL_TELEGRAM_CHAT_ID", ""),
    )
    # Discord
    discord_webhook_url: str = field(
        default_factory=lambda: os.getenv("TERMINAL_DISCORD_WEBHOOK_URL", ""),
        repr=False,
    )
    # Pushover
    pushover_app_token: str = field(
        default_factory=lambda: os.getenv("TERMINAL_PUSHOVER_APP_TOKEN", ""),
        repr=False,
    )
    pushover_user_key: str = field(
        default_factory=lambda: os.getenv("TERMINAL_PUSHOVER_USER_KEY", ""),
        repr=False,
    )

    @property
    def has_any_channel(self) -> bool:
        return bool(
            (self.telegram_bot_token and self.telegram_chat_id)
            or self.discord_webhook_url
            or (self.pushover_app_token and self.pushover_user_key)
        )


# ---------------------------------------------------------------------------
# Market hours gate
# ---------------------------------------------------------------------------


def _is_market_hours() -> bool:
    """Return True during US extended hours (Mon-Fri 04:00-20:00 ET)."""
    try:
        from zoneinfo import ZoneInfo

        now_et = datetime.now(ZoneInfo("America/New_York"))
    except Exception:
        try:
            from dateutil.tz import gettz

            now_et = datetime.now(gettz("America/New_York"))
        except Exception:
            from datetime import timedelta, timezone

            now_et = datetime.now(timezone.utc) - timedelta(hours=4)

    if now_et.weekday() >= 5:
        return False
    return 4 <= now_et.hour < 20


# ---------------------------------------------------------------------------
# Throttle state
# ---------------------------------------------------------------------------

_last_notified: dict[str, float] = {}
_throttle_lock = threading.Lock()
_THROTTLE_DICT_MAX = 500


def _is_throttled(symbol: str, throttle_s: int) -> bool:
    now = time.time()
    with _throttle_lock:
        last = _last_notified.get(symbol, 0.0)
    return (now - last) < throttle_s


def _mark_notified(symbol: str) -> None:
    with _throttle_lock:
        _last_notified[symbol] = time.time()
        # Evict old entries
        if len(_last_notified) > _THROTTLE_DICT_MAX:
            now = time.time()
            stale = [k for k, v in _last_notified.items() if (now - v) > 3600]
            for k in stale:
                del _last_notified[k]


def reset_throttle() -> None:
    """Clear the throttle state (used on session reset)."""
    with _throttle_lock:
        _last_notified.clear()


# ---------------------------------------------------------------------------
# Channel dispatchers
# ---------------------------------------------------------------------------


def _mask_url(url: str) -> str:
    """Mask query params for safe logging."""
    return url.split("?")[0] + ("?***" if "?" in url else "")


def _send_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send a Telegram message via Bot API. Returns True on success."""
    import urllib.error
    import urllib.request

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode()

    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Telegram notification sent to %s", chat_id)
                return True
            logger.warning("Telegram HTTP %d", resp.status)
            return False
    except urllib.error.HTTPError as exc:
        logger.warning("Telegram HTTP error %d: %s", exc.code, exc.read()[:200])
        return False
    except Exception as exc:
        logger.warning("Telegram send failed: %s", type(exc).__name__)
        return False


def _send_discord(webhook_url: str, text: str) -> bool:
    """Send a Discord webhook message. Returns True on success."""
    import urllib.error
    import urllib.request

    payload = json.dumps({"content": text}).encode()
    req = urllib.request.Request(webhook_url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if 200 <= resp.status < 300:
                logger.info("Discord notification sent (%s)", _mask_url(webhook_url))
                return True
            logger.warning("Discord HTTP %d", resp.status)
            return False
    except urllib.error.HTTPError as exc:
        # Discord returns 204 No Content on success — urllib may still
        # raise for other HTTP errors
        if exc.code == 204:
            logger.info("Discord notification sent (204)")
            return True
        logger.warning("Discord HTTP error %d", exc.code)
        return False
    except Exception as exc:
        logger.warning("Discord send failed: %s", type(exc).__name__)
        return False


def _send_pushover(app_token: str, user_key: str, title: str, message: str, url: str = "") -> bool:
    """Send a Pushover notification. Returns True on success."""
    import urllib.error
    import urllib.parse
    import urllib.request

    data = urllib.parse.urlencode({
        "token": app_token,
        "user": user_key,
        "title": title,
        "message": message,
        "url": url,
        "priority": 0,
        "sound": "cashregister",
    }).encode()

    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data, method="POST")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                logger.info("Pushover notification sent")
                return True
            logger.warning("Pushover HTTP %d", resp.status)
            return False
    except urllib.error.HTTPError as exc:
        logger.warning("Pushover HTTP error %d", exc.code)
        return False
    except Exception as exc:
        logger.warning("Pushover send failed: %s", type(exc).__name__, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Format message
# ---------------------------------------------------------------------------

_SENTIMENT_EMOJI = {"bullish": "🟢", "bearish": "🔴", "neutral": "🟡"}


def _format_message(item: dict[str, Any]) -> str:
    """Format a classified item dict into a notification message."""
    ticker = item.get("ticker", "?")
    score = item.get("news_score", 0)
    sentiment = item.get("sentiment_label", "neutral")
    headline = item.get("headline", "")[:120]
    event = item.get("event_label", "N/A")
    materiality = item.get("materiality", "?")
    age = item.get("age_minutes")
    url = item.get("url", "")

    emoji = _SENTIMENT_EMOJI.get(sentiment, "⚪")
    age_str = f"{age:.0f}m" if age is not None else "N/A"

    lines = [
        f"📡 *ALERT* — {ticker}",
        f"Score: *{score:.3f}* | {emoji} {sentiment} | {materiality}",
        f"Event: {event} | Age: {age_str}",
        f"_{headline}_",
    ]
    if url:
        lines.append(f"[Article]({url})")
    return "\n".join(lines)


def _format_discord_message(item: dict[str, Any]) -> str:
    """Discord uses different markdown syntax."""
    ticker = item.get("ticker", "?")
    score = item.get("news_score", 0)
    sentiment = item.get("sentiment_label", "neutral")
    headline = item.get("headline", "")[:120]
    event = item.get("event_label", "N/A")
    materiality = item.get("materiality", "?")
    age = item.get("age_minutes")
    url = item.get("url", "")

    emoji = _SENTIMENT_EMOJI.get(sentiment, "⚪")
    age_str = f"{age:.0f}m" if age is not None else "N/A"

    lines = [
        f"📡 **ALERT** — **{ticker}**",
        f"Score: **{score:.3f}** | {emoji} {sentiment} | {materiality}",
        f"Event: {event} | Age: {age_str}",
        f"*{headline}*",
    ]
    if url:
        lines.append(url)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def notify_high_score_items(
    items: list[dict[str, Any]],
    config: NotifyConfig | None = None,
) -> list[dict[str, Any]]:
    """Check new items and dispatch push notifications for high-score entries.

    Only fires during market hours. Respects per-symbol throttle.

    Parameters
    ----------
    items : list[dict]
        List of classified item dicts (as stored in session feed).
    config : NotifyConfig, optional
        Override config (default: reads env vars).

    Returns
    -------
    list[dict]
        List of result dicts for each notification sent.
    """
    if config is None:
        config = NotifyConfig()

    if not config.enabled:
        return []

    if not config.has_any_channel:
        logger.debug("Notifications enabled but no channels configured")
        return []

    if not _is_market_hours():
        return []

    results: list[dict[str, Any]] = []
    now = time.time()

    for item in items:
        score = item.get("news_score", 0)
        if score < config.min_score:
            continue

        # Only notify fresh entries
        age_min = item.get("age_minutes")
        if age_min is not None and age_min > config.max_age_minutes:
            continue

        ticker = item.get("ticker", "UNKNOWN")
        if _is_throttled(ticker, config.throttle_s):
            continue

        # Dispatch to all configured channels
        sent_any = False
        result: dict[str, Any] = {
            "ticker": ticker,
            "score": score,
            "channels": [],
        }

        if config.telegram_bot_token and config.telegram_chat_id:
            msg = _format_message(item)
            ok = _send_telegram(config.telegram_bot_token, config.telegram_chat_id, msg)
            result["channels"].append({"name": "telegram", "ok": ok})
            sent_any = sent_any or ok

        if config.discord_webhook_url:
            msg = _format_discord_message(item)
            ok = _send_discord(config.discord_webhook_url, msg)
            result["channels"].append({"name": "discord", "ok": ok})
            sent_any = sent_any or ok

        if config.pushover_app_token and config.pushover_user_key:
            title = f"📡 {ticker} — Score {score:.2f}"
            body = _format_message(item).replace("*", "")  # Pushover uses HTML, strip markdown
            article_url = item.get("url", "")
            ok = _send_pushover(
                config.pushover_app_token,
                config.pushover_user_key,
                title,
                body,
                url=article_url or "",
            )
            result["channels"].append({"name": "pushover", "ok": ok})
            sent_any = sent_any or ok

        if sent_any:
            _mark_notified(ticker)
            results.append(result)
            logger.info(
                "Push notification sent for %s (score=%.3f) → %s",
                ticker,
                score,
                ", ".join(c["name"] for c in result["channels"] if c["ok"]),
            )

    return results
