"""Push notifications for fresh realtime breakout signals (A0/A1/A2).

Fires the instant the poll loop sees a NEW (or strengthened) signal — strictly
faster than the snapshot -> Prometheus scrape -> Grafana eval path, and it is
*push*, not pull. Fully opt-in: does nothing unless a destination is configured
via env. Fail-soft: any error is logged at debug and swallowed so a webhook
outage can never stall the poll loop, and the actual HTTP POST runs on a daemon
thread so a slow endpoint never adds latency to polling.

Destinations (env ``RT_SIGNAL_WEBHOOK_MODE``):
  generic  POST {"text": msg} to RT_SIGNAL_WEBHOOK_URL (optional Bearer token)
  slack    POST {"text": msg}       to the Slack incoming-webhook URL
  discord  POST {"content": msg}    to the Discord webhook URL
  ntfy     POST the plain-text body to an ntfy topic URL
  telegram POST to the Bot API (RT_SIGNAL_TELEGRAM_BOT_TOKEN / _CHAT_ID)
  twilio_whatsapp  Twilio Messages API (SID/AUTH/FROM/TO) — WhatsApp
  meta_whatsapp    Meta WhatsApp Cloud API (TOKEN/PHONE_ID/TO)

WhatsApp note: there is NO plain webhook URL for WhatsApp like Telegram has.
Use twilio_whatsapp (easiest — Twilio sandbox works immediately) or meta_whatsapp
(official). Both are a single authenticated HTTPS POST from this module once you
hold a provider account; neither is a bridge/relay.

Config (env):
  RT_SIGNAL_WEBHOOK_MODE     one of the modes above (default: generic)
  RT_SIGNAL_WEBHOOK_URL      destination URL (generic/slack/discord/ntfy)
  RT_SIGNAL_WEBHOOK_TOKEN    optional Bearer token for the generic mode
  RT_SIGNAL_NOTIFY_LEVELS    comma list, default "A0,A1,A2" (A2 = early-warning,
                             marked "⚠️early"; set "A0,A1" to mute the noisy tier)
  RT_SIGNAL_NOTIFY_COOLDOWN_SECS  re-notify a still-active signal only after this
                                  many seconds (default 1800 = 30 min)
  RT_SIGNAL_WEBHOOK_SYNC     "1" to POST inline instead of on a thread (tests)
  RT_SIGNAL_TELEGRAM_BOT_TOKEN / RT_SIGNAL_TELEGRAM_CHAT_ID
  RT_SIGNAL_TWILIO_SID / _AUTH / _FROM / _TO       (FROM/TO like "whatsapp:+49…")
  RT_SIGNAL_META_TOKEN / _PHONE_ID / _TO
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

# Strength ordering: A0 is the highest bar (most volume+move), A2 the weakest.
_STRENGTH = {"A0": 3, "A1": 2, "A2": 1}
_EMOJI = {"A0": "🔴", "A1": "🟠", "A2": "🟡"}

# Per-process dedup state: (symbol, direction) -> (strength, last_notified_epoch).
_NOTIFIED: dict[tuple[str, str], tuple[int, float]] = {}
_STATE_TTL_SECS = 2 * 3600.0


def reset_state() -> None:
    """Clear the dedup state (tests / a manual re-arm)."""
    _NOTIFIED.clear()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _levels() -> set[str]:
    # Default includes A2 (early-warning) — it is marked "⚠️early" in the
    # message so it reads as unconfirmed, not a confirmed breakout. Set
    # RT_SIGNAL_NOTIFY_LEVELS="A0,A1" to mute the noisy tier.
    raw = _env("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1,A2")
    return {p.strip().upper() for p in raw.split(",") if p.strip()}


def _cooldown() -> float:
    try:
        return max(0.0, float(_env("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", "1800")))
    except ValueError:
        return 1800.0


def is_enabled() -> bool:
    """True iff a destination is configured. Cheap — checked every poll."""
    mode = _env("RT_SIGNAL_WEBHOOK_MODE", "generic")
    if mode in {"generic", "slack", "discord", "ntfy"}:
        return bool(_env("RT_SIGNAL_WEBHOOK_URL"))
    if mode == "telegram":
        return bool(_env("RT_SIGNAL_TELEGRAM_BOT_TOKEN") and _env("RT_SIGNAL_TELEGRAM_CHAT_ID"))
    if mode == "twilio_whatsapp":
        return bool(_env("RT_SIGNAL_TWILIO_SID") and _env("RT_SIGNAL_TWILIO_AUTH")
                    and _env("RT_SIGNAL_TWILIO_FROM") and _env("RT_SIGNAL_TWILIO_TO"))
    if mode == "meta_whatsapp":
        return bool(_env("RT_SIGNAL_META_TOKEN") and _env("RT_SIGNAL_META_PHONE_ID")
                    and _env("RT_SIGNAL_META_TO"))
    return False


def _fmt_signal(s: Any) -> str:
    lvl = str(getattr(s, "level", "") or "")
    # A2 is the early-warning tier (building momentum, not confirmed) — flag it
    # so a glance never mistakes it for a confirmed A0/A1 breakout.
    tail = " ⚠️early" if lvl == "A2" else ""
    return (
        f"{_EMOJI.get(lvl, '•')} {lvl} {getattr(s, 'symbol', '?')} "
        f"{getattr(s, 'direction', '')} ${float(getattr(s, 'price', 0.0)):.2f} "
        f"vol×{float(getattr(s, 'volume_ratio', 0.0)):.1f} "
        f"Δ{float(getattr(s, 'change_pct', 0.0)):+.1f}%{tail}"
    )


def _build_request(mode: str, msg: str) -> tuple[str, dict[str, Any]]:
    """Return ``(url, httpx_kwargs)`` for the configured destination.

    A single point of truth so every mode funnels through the one HTTP egress
    site in :func:`_http_post`.
    """
    if mode == "slack":
        return _env("RT_SIGNAL_WEBHOOK_URL"), {"json": {"text": msg}}
    if mode == "discord":
        return _env("RT_SIGNAL_WEBHOOK_URL"), {"json": {"content": msg}}
    if mode == "ntfy":
        return _env("RT_SIGNAL_WEBHOOK_URL"), {
            "content": msg.encode("utf-8"),
            "headers": {"Title": "Fresh breakout signal"},
        }
    if mode == "telegram":
        token = _env("RT_SIGNAL_TELEGRAM_BOT_TOKEN")
        return (
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"json": {"chat_id": _env("RT_SIGNAL_TELEGRAM_CHAT_ID"), "text": msg}},
        )
    if mode == "twilio_whatsapp":
        sid = _env("RT_SIGNAL_TWILIO_SID")
        return (
            f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
            {
                "data": {
                    "From": _env("RT_SIGNAL_TWILIO_FROM"),
                    "To": _env("RT_SIGNAL_TWILIO_TO"),
                    "Body": msg,
                },
                "auth": (sid, _env("RT_SIGNAL_TWILIO_AUTH")),
            },
        )
    if mode == "meta_whatsapp":
        return (
            f"https://graph.facebook.com/v20.0/{_env('RT_SIGNAL_META_PHONE_ID')}/messages",
            {
                "json": {
                    "messaging_product": "whatsapp",
                    "to": _env("RT_SIGNAL_META_TO"),
                    "type": "text",
                    "text": {"body": msg},
                },
                "headers": {"Authorization": f"Bearer {_env('RT_SIGNAL_META_TOKEN')}"},
            },
        )
    # generic
    kwargs: dict[str, Any] = {"json": {"text": msg}}
    token = _env("RT_SIGNAL_WEBHOOK_TOKEN")
    if token:
        kwargs["headers"] = {"Authorization": f"Bearer {token}"}
    return _env("RT_SIGNAL_WEBHOOK_URL"), kwargs


def _http_post(url: str, *, timeout: float = 5.0, **kwargs: Any) -> bool:
    """The single outbound-POST egress site for realtime signal pushes.

    Sends a user-configured breakout notification (see RT_SIGNAL_WEBHOOK_MODE).
    Fail-soft: never raises — a webhook/provider outage must not stall polling.
    """
    try:
        import httpx

        resp = httpx.post(url, timeout=timeout, **kwargs)
        if resp.status_code >= 400:
            logger.debug("rt_notify POST %s -> HTTP %d", url.split("?")[0], resp.status_code)
            return False
        return True
    except Exception:  # best-effort notifier — never break the poll loop
        logger.debug("rt_notify POST failed", exc_info=True)
        return False


def _dispatch(msg: str) -> None:
    mode = _env("RT_SIGNAL_WEBHOOK_MODE", "generic")
    url, kwargs = _build_request(mode, msg)
    if not url:
        return
    if _env("RT_SIGNAL_WEBHOOK_SYNC") == "1":
        _http_post(url, **kwargs)
    else:
        threading.Thread(target=_http_post, args=(url,), kwargs=kwargs, daemon=True).start()


def notify_fresh_signals(signals: list[Any], *, now: float | None = None) -> list[str]:
    """Notify for signals that are newly-fresh or newly-strengthened.

    Deduplicates per (symbol, direction): a still-active signal is re-notified
    only when it upgrades to a stronger level (A2->A1->A0) or after the cooldown.
    Returns the list of ``"SYMBOL DIRECTION LEVEL"`` keys that were notified
    (empty when disabled or nothing fresh). Never raises.
    """
    if not is_enabled() or not signals:
        return []
    ts = time.time() if now is None else now
    levels = _levels()
    cooldown = _cooldown()

    fresh: list[Any] = []
    for s in signals:
        lvl = str(getattr(s, "level", "") or "")
        if lvl not in levels:
            continue
        key = (str(getattr(s, "symbol", "")), str(getattr(s, "direction", "")))
        strength = _STRENGTH.get(lvl, 0)
        prev = _NOTIFIED.get(key)
        if prev is None or strength > prev[0] or (ts - prev[1]) >= cooldown:
            fresh.append(s)
            _NOTIFIED[key] = (strength, ts)

    # Evict stale dedup entries so the map cannot grow unbounded.
    for k in [k for k, (_st, t) in _NOTIFIED.items() if ts - t > _STATE_TTL_SECS]:
        _NOTIFIED.pop(k, None)

    if not fresh:
        return []

    header = f"📈 {len(fresh)} fresh breakout signal{'s' if len(fresh) != 1 else ''}"
    msg = header + "\n" + "\n".join(_fmt_signal(s) for s in fresh)
    try:
        _dispatch(msg)
    except Exception:  # dispatch is best-effort
        logger.debug("rt_notify dispatch failed", exc_info=True)
    return [f"{getattr(s, 'symbol', '?')} {getattr(s, 'direction', '')} {getattr(s, 'level', '')}" for s in fresh]
