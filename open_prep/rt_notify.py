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
  RT_SIGNAL_NOTIFY_LEVELS    comma list, default "A0,A1" (A2 = early-warning,
                             marked "⚠️early"; add "A2" to include the noisy tier)
  RT_SIGNAL_EARLY_WEBHOOK_URL  optional 2nd webhook (slack/discord/ntfy/generic) —
                             levels in RT_SIGNAL_EARLY_LEVELS route HERE, not the
                             main channel, independent of RT_SIGNAL_NOTIFY_LEVELS
  RT_SIGNAL_EARLY_LEVELS     comma list routed to the early webhook (default "A2")
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

# Calibrated follow-through P (fail-soft; returns None unless RT_CALIBRATION_ARMED
# and enough data exist) — lets measured P replace the ⭐ midpoint heuristic below.
from open_prep.calibration_lookup import follow_through_p as _calibrated_follow_through_p

logger = logging.getLogger(__name__)

# Strength ordering: A0 is the highest bar (most volume+move), A2 the weakest.
_STRENGTH = {"A0": 3, "A1": 2, "A2": 1}
_EMOJI = {"A0": "🔴", "A1": "🟠", "A2": "🟡"}
_VALID_LEVELS = frozenset(_STRENGTH)  # {"A0", "A1", "A2"}

# High-conviction A1 tag. An A1 sits between the A1 floor (vol>=1.0, |Δ|>=0.35%)
# and the A0 floor (vol>=3.0, |Δ|>=1.5%) — see A0/A1 thresholds in
# realtime_signals.py. Empirically A1 rarely *escalates* to A0 (~1% same-day, most
# A0s fire de novo), so this is NOT an "about to be A0" predictor: it marks the A1s
# that already sit in the upper half toward A0 on BOTH momentum axes, i.e. the ones
# worth acting on vs the slow-grinder floor. Constants mirror the A0 floors at the
# midpoint; kept local so this notifier stays import-light (no realtime_signals pull).
_A1_STRONG_VOL_RATIO = 2.0   # midpoint of A1 floor 1.0 and A0 floor 3.0
_A1_STRONG_CHANGE_PCT = 0.9  # ~midpoint of A1 floor 0.35% and A0 floor 1.5%

# Corroboration glyphs — orthogonal context appended to any level's tail so a
# glance sees WHY a breakout has backing beyond price+volume. Both fields are on
# the 0..1 scale carried by RealtimeSignal (default 0.0 / 0.5 respectively), so a
# missing enrichment never false-flags. The technical glyph is DIRECTION-AWARE:
# technical_score is a *signed* 0..1 (0.5 neutral, →1 bullish, →0 bearish), so
# bullish TA only corroborates a LONG and bearish TA only a SHORT — a bullish read
# on a SHORT is a conflict, not backing, and earns no glyph (see
# _corroboration_flags). news_score, by contrast, is a direction-neutral catalyst
# magnitude, so 📰 backs a move in either direction.
_NEWS_CATALYST_MIN = 0.5     # news_score>=0.5 is the directional-upgrade bar in realtime_signals.py
_STRONG_TECHNICAL_MIN = 0.7  # technical_score>=0.7 = strong-bullish TA; symmetric bearish bar = 1-0.7 = 0.3
# direction tokens (mirror _fmt_trade_context; RealtimeSignal.direction ∈ {LONG,SHORT,B_UP,B_DOWN}).
_BULLISH_DIRECTIONS = frozenset({"LONG", "B_UP", "UP"})
_BEARISH_DIRECTIONS = frozenset({"SHORT", "B_DOWN", "DOWN"})

# Per-process dedup state: (symbol, direction) -> (strength, last_notified_epoch).
# Only advanced AFTER a POST is confirmed delivered (see notify_fresh_signals),
# so a webhook outage retries next poll instead of silently suppressing for a
# whole cooldown. In async mode the daemon POST thread writes this on success,
# so every access is guarded by _LOCK.
_NOTIFIED: dict[tuple[str, str], tuple[int, float]] = {}
_STATE_TTL_SECS = 2 * 3600.0
_LOCK = threading.Lock()
# Keys of one-shot config warnings already emitted. _levels()/_cooldown() run on
# every poll, so an unconditional warning on a misconfig would flood the log
# (the very thing we avoid elsewhere). Mutated in place → no `global` needed.
_WARNED: set[str] = set()


def reset_state() -> None:
    """Clear the dedup state (tests / a manual re-arm)."""
    with _LOCK:
        _NOTIFIED.clear()
    _WARNED.clear()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _warn_once(key: str, msg: str, *args: Any) -> None:
    """Emit a config warning at most once per process (keyed) — the callers run
    every poll, so warning unconditionally would itself flood the log."""
    if key not in _WARNED:
        _WARNED.add(key)
        logger.warning(msg, *args)


def _levels() -> set[str]:
    # Default is A0,A1 — the noisy A2 early-warning tier is opt-in. When enabled
    # A2 is marked "⚠️early" in the message so it reads as unconfirmed, not a
    # confirmed breakout. Set RT_SIGNAL_NOTIFY_LEVELS="A0,A1,A2" to include it.
    raw = _env("RT_SIGNAL_NOTIFY_LEVELS", "A0,A1")
    tokens = {p.strip().upper() for p in raw.split(",") if p.strip()}
    unknown = tokens - _VALID_LEVELS
    if unknown:
        _warn_once(
            f"levels:{raw}",
            "RT_SIGNAL_NOTIFY_LEVELS has unrecognised level(s) %s (valid: A0,A1,A2); "
            "they are ignored — check for a typo like 'AO' vs 'A0'",
            sorted(unknown),
        )
    return tokens & _VALID_LEVELS


# Modes whose destination is a plain webhook URL (vs a token+chat_id API), so a
# secondary early-warning channel can reuse the same payload shape at a 2nd URL.
_EARLY_CAPABLE_MODES = frozenset({"slack", "discord", "ntfy", "generic"})


def _early_url() -> str:
    """Secondary webhook for early-warning levels — a dedicated channel so A2s do
    not clutter the main breakout feed. Empty (feature off) unless set."""
    return _env("RT_SIGNAL_EARLY_WEBHOOK_URL")


def _early_levels() -> set[str]:
    """Levels routed to the early webhook (default A2), independent of
    RT_SIGNAL_NOTIFY_LEVELS so an A2 still reaches its own channel even when the
    main feed is muted to A0. Only consulted when RT_SIGNAL_EARLY_WEBHOOK_URL is set."""
    raw = _env("RT_SIGNAL_EARLY_LEVELS", "A2")
    tokens = {p.strip().upper() for p in raw.split(",") if p.strip()}
    unknown = tokens - _VALID_LEVELS
    if unknown:
        _warn_once(
            f"early_levels:{raw}",
            "RT_SIGNAL_EARLY_LEVELS has unrecognised level(s) %s (valid: A0,A1,A2); "
            "they are ignored",
            sorted(unknown),
        )
    return tokens & _VALID_LEVELS


def _cooldown() -> float:
    raw = _env("RT_SIGNAL_NOTIFY_COOLDOWN_SECS", "1800")
    try:
        secs = float(raw)
    except ValueError:
        return 1800.0
    if secs <= 0:
        # A non-positive cooldown re-fires the same still-active signal on every
        # poll (webhook spam) — treat as misconfig and fall back to the default.
        _warn_once(
            f"cooldown:{raw}",
            "RT_SIGNAL_NOTIFY_COOLDOWN_SECS=%r is non-positive; using default 1800s",
            raw,
        )
        return 1800.0
    return secs


def is_enabled() -> bool:
    """True iff a destination is configured. Cheap — checked every poll."""
    mode = _env("RT_SIGNAL_WEBHOOK_MODE", "generic").lower()
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
    # An unknown/typo'd mode silently disabled the whole notifier with zero
    # log signal — warn once so the misconfig is visible (house style: the
    # levels/cooldown misconfigs already _warn_once).
    _warn_once("unknown_mode", "RT_SIGNAL_WEBHOOK_MODE=%r is not a known mode — notifier disabled", mode)
    return False


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce to float, never raising — a single corrupt signal field (None,
    ``"n/a"``, …) must not blow up the whole batch notification."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# P(follow-through) at/above which a calibrated A1 earns the ⭐ (armed only).
try:
    _CALIBRATION_P_THRESHOLD = float(_env("RT_CALIBRATION_P_THRESHOLD", "0.5"))
except (TypeError, ValueError):
    _CALIBRATION_P_THRESHOLD = 0.5


def _is_high_conviction_a1(s: Any) -> bool:
    """True for an A1 already leaning into A0 territory — volume AND move both
    past the midpoint between the A1 and A0 floors, so it reads as conviction
    rather than a slow grinder. Core fields only (always present); never raises.

    Calibrated path (opt-in via RT_CALIBRATION_ARMED): once the nightly job has
    enough follow-through data for this (level, vol_bucket), the measured P
    replaces the hard-coded midpoints; otherwise it falls back to them."""
    vol_ratio = _safe_float(getattr(s, "volume_ratio", 0.0))
    abs_change = abs(_safe_float(getattr(s, "change_pct", 0.0)))
    p = _calibrated_follow_through_p("A1", vol_ratio)
    if p is not None:
        return p >= _CALIBRATION_P_THRESHOLD
    return vol_ratio >= _A1_STRONG_VOL_RATIO and abs_change >= _A1_STRONG_CHANGE_PCT


def _a1_conviction_label(s: Any) -> str:
    """⭐ tail for a high-conviction A1: the measured follow-through P when the
    calibration is armed and populated (e.g. " ⭐P58%"), else " ⭐near-A0"."""
    p = _calibrated_follow_through_p("A1", _safe_float(getattr(s, "volume_ratio", 0.0)))
    return f" ⭐P{round(p * 100)}%" if p is not None else " ⭐near-A0"


def _corroboration_flags(s: Any) -> str:
    """Glyphs for corroborating context, orthogonal to the level tail: 📰 a news
    catalyst (news_score>=0.5, direction-neutral), plus a DIRECTION-AWARE technical
    glyph — 📈 strong bullish technicals (technical_score>=0.7) on a LONG, 📉 strong
    bearish technicals (technical_score<=0.3) on a SHORT. Bullish TA on a SHORT (or
    bearish on a LONG) is a conflict, not backing, so it earns NO glyph rather than
    a misleading one. A missing technical_score defaults to the neutral 0.5, so an
    unenriched signal never false-flags in either direction. Never raises."""
    flags = ""
    if _safe_float(getattr(s, "news_score", 0.0)) >= _NEWS_CATALYST_MIN:
        flags += " 📰"
    tech = _safe_float(getattr(s, "technical_score", 0.5), 0.5)
    direction = str(getattr(s, "direction", "")).upper()
    if direction in _BULLISH_DIRECTIONS and tech >= _STRONG_TECHNICAL_MIN:
        flags += " 📈"
    elif direction in _BEARISH_DIRECTIONS and tech <= 1.0 - _STRONG_TECHNICAL_MIN:
        flags += " 📉"
    return flags


def _fmt_signal(s: Any) -> str:
    lvl = str(getattr(s, "level", "") or "")
    # A2 is the early-warning tier (building momentum, not confirmed) — flag it
    # so a glance never mistakes it for a confirmed A0/A1 breakout. A high-conviction
    # A1 (upper half toward A0) gets ⭐ so the eye can triage the A1 stream at a glance.
    if lvl == "A2":
        tail = " ⚠️early"
    elif lvl == "A1" and _is_high_conviction_a1(s):
        tail = _a1_conviction_label(s)
    else:
        tail = ""
    # Corroboration glyphs (📰 news / 📈📉 direction-aware technicals) append after the level tail.
    tail += _corroboration_flags(s)
    # _safe_float so a None/garbage price/volume/change on one signal renders as
    # 0.0 instead of raising and killing the entire batch push (which would also
    # leave those signals marked-but-never-sent — see the delivery gate below).
    return (
        f"{_EMOJI.get(lvl, '•')} {lvl} {getattr(s, 'symbol', '?')} "
        f"{getattr(s, 'direction', '')} ${_safe_float(getattr(s, 'price', 0.0)):.2f} "
        f"vol×{_safe_float(getattr(s, 'volume_ratio', 0.0)):.1f} "
        f"Δ{_safe_float(getattr(s, 'change_pct', 0.0)):+.1f}%{tail}"
    )


def _fmt_trade_context(s: Any) -> str:
    """Indented trade-context line (ATR bracket from open_prep/trade_context.py),
    or "" when the signal carries no usable context — the alert line stays as-is.
    Rendered as its own line so the level line above never gets pushed off-screen."""
    entry = getattr(s, "trade_entry", None)
    stop = getattr(s, "trade_stop", None)
    target = getattr(s, "trade_target", None)
    r_mult = getattr(s, "trade_r", None)
    if entry is None or stop is None or target is None or not entry:
        return ""
    stop_pct = (stop - entry) / entry * 100.0
    target_pct = (target - entry) / entry * 100.0
    bullish = str(getattr(s, "direction", "")).upper() in ("LONG", "B_UP", "UP")
    entry_op = "≤" if bullish else "≥"
    return (
        f"\n   ↳ entry {entry_op}{entry:.2f} · stop {stop:.2f} ({stop_pct:+.1f}%) · "
        f"target {target:.2f} ({target_pct:+.1f}%) · R {_safe_float(r_mult, 0.0):.1f}"
    )


def _build_request(mode: str, msg: str, url: str = "") -> tuple[str, dict[str, Any]]:
    """Return ``(url, httpx_kwargs)`` for the configured destination.

    A single point of truth so every mode funnels through the one HTTP egress
    site in :func:`_http_post`. ``url`` overrides the destination for the
    URL-based modes (slack/discord/ntfy/generic) — used to send early-warning
    levels to RT_SIGNAL_EARLY_WEBHOOK_URL; token-based modes ignore it.
    """
    if mode == "slack":
        return (url or _env("RT_SIGNAL_WEBHOOK_URL")), {"json": {"text": msg}}
    if mode == "discord":
        return (url or _env("RT_SIGNAL_WEBHOOK_URL")), {"json": {"content": msg}}
    if mode == "ntfy":
        return (url or _env("RT_SIGNAL_WEBHOOK_URL")), {
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
    return (url or _env("RT_SIGNAL_WEBHOOK_URL")), kwargs


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


def _post_and_mark(url: str, *, marks: list[tuple[tuple[str, str], int]],
                   ts: float, **kwargs: Any) -> bool:
    """POST, and record the dedup ``marks`` ONLY on a confirmed delivery.

    Runs inline (sync mode) or on the daemon thread (async) — either way the
    dedup state advances solely on a successful POST, so a webhook outage is
    retried on the next poll instead of being silently swallowed for a whole
    cooldown. Writes ``_NOTIFIED`` under ``_LOCK`` since the async caller is a
    separate thread.
    """
    ok = _http_post(url, **kwargs)
    if ok and marks:
        with _LOCK:
            for key, strength in marks:
                _NOTIFIED[key] = (strength, ts)
    return ok


def _dispatch(msg: str, marks: list[tuple[tuple[str, str], int]], ts: float,
              url_override: str = "") -> bool:
    """Deliver ``msg`` and, on success, record ``marks`` in the dedup state.

    ``url_override`` (early-warning route) sends this batch to a secondary
    webhook instead of the main one; empty means the configured main destination.

    Sync mode (RT_SIGNAL_WEBHOOK_SYNC=1): POST inline; returns True iff delivered.
    Async mode (default): hand the POST to a daemon thread and return True to
    mean *dispatched* — the thread performs the POST and marks state on success,
    so a slow endpoint adds zero polling latency while a failure still retries.
    """
    mode = _env("RT_SIGNAL_WEBHOOK_MODE", "generic").lower()
    url, kwargs = _build_request(mode, msg, url_override)
    if not url:
        return False
    if _env("RT_SIGNAL_WEBHOOK_SYNC") == "1":
        return _post_and_mark(url, marks=marks, ts=ts, **kwargs)
    threading.Thread(
        target=_post_and_mark, args=(url,),
        kwargs={"marks": marks, "ts": ts, **kwargs}, daemon=True,
    ).start()
    return True


def notify_fresh_signals(signals: list[Any], *, now: float | None = None) -> list[str]:
    """Notify for signals that are newly-fresh or newly-strengthened.

    Deduplicates per (symbol, direction): a still-active signal is re-notified
    only when it upgrades to a stronger level (A2->A1->A0) or after the cooldown.
    The dedup state advances only once delivery is confirmed, so a webhook
    outage retries on the next poll rather than suppressing the signal for a
    whole cooldown. Trade-off: in async mode a poll arriving while the previous
    POST is still in flight (<= the 5s timeout) sees no dedup mark yet and can
    dispatch the same signal again — a bounded duplicate-push window accepted
    in exchange for the outage-retry behavior.

    Returns the ``"SYMBOL DIRECTION LEVEL"`` keys that were delivered — in sync
    mode (``RT_SIGNAL_WEBHOOK_SYNC=1``) that means a confirmed POST; in the
    default async mode it means *dispatched* to the delivery thread. The return
    is advisory: the main poll ignores it, but the fast-lane re-poller counts
    it into ``a0_pushed`` (so that counter reads dispatched, not delivered).
    Empty when disabled, nothing is fresh, or delivery failed. Never raises.
    """
    mode = _env("RT_SIGNAL_WEBHOOK_MODE", "generic").lower()
    early_url = _early_url()
    early_active = bool(early_url) and mode in _EARLY_CAPABLE_MODES
    if early_url and not early_active:
        _warn_once(
            "early_url_inert",
            "RT_SIGNAL_EARLY_WEBHOOK_URL is set but mode %r is not early-capable — early (A2) notifications are dropped",
            mode,
        )
    # The early webhook is a valid destination on its own, so A2 still delivers
    # even when the main channel has no webhook configured.
    if not is_enabled() and not early_active:
        return []
    ts = time.time() if now is None else now
    levels = _levels()
    early_levels = _early_levels() if early_active else frozenset()
    cooldown = _cooldown()

    # Partition candidates by destination WITHOUT touching _NOTIFIED — the state
    # advances only after _dispatch confirms delivery, so a failed POST re-fires
    # next poll. Early levels win over the main feed, so an A2 goes to its own
    # channel and is never double-posted to both.
    main_fresh: list[Any] = []
    main_marks: list[tuple[tuple[str, str], int]] = []
    early_fresh: list[Any] = []
    early_marks: list[tuple[tuple[str, str], int]] = []
    with _LOCK:
        for s in signals or ():
            lvl = str(getattr(s, "level", "") or "")
            if early_active and lvl in early_levels:
                bucket_fresh, bucket_marks = early_fresh, early_marks
            elif lvl in levels:
                bucket_fresh, bucket_marks = main_fresh, main_marks
            else:
                continue
            key = (str(getattr(s, "symbol", "")), str(getattr(s, "direction", "")))
            strength = _STRENGTH.get(lvl, 0)
            prev = _NOTIFIED.get(key)
            if prev is None or strength > prev[0] or (ts - prev[1]) >= cooldown:
                bucket_fresh.append(s)
                bucket_marks.append((key, strength))
        # Evict stale dedup entries so the map cannot grow unbounded. Runs even
        # when `signals` is empty, so a stale entry can't outlive its TTL merely
        # because no new signal happened to arrive on later polls. The horizon
        # is max(TTL, cooldown): evicting at the bare TTL silently capped any
        # cooldown > 2h (entry evicted -> prev is None -> premature re-push).
        eviction_horizon = max(_STATE_TTL_SECS, cooldown)
        for k in [k for k, (_st, t) in _NOTIFIED.items() if ts - t > eviction_horizon]:
            _NOTIFIED.pop(k, None)

    delivered_keys: list[str] = []
    for bucket, bucket_marks, dst, noun, emoji in (
        (main_fresh, main_marks, "", "breakout", "🚨"),  # neutral header: the batch can be all-SHORT; per-line glyphs carry direction (#3344)
        (early_fresh, early_marks, early_url, "early-warning", "⚠️"),
    ):
        if not bucket:
            continue
        header = f"{emoji} {len(bucket)} fresh {noun} signal{'s' if len(bucket) != 1 else ''}"
        msg = header + "\n" + "\n".join(
            _fmt_signal(s) + _fmt_trade_context(s) for s in bucket)
        try:
            ok = _dispatch(msg, bucket_marks, ts, dst)
        except Exception:  # dispatch is best-effort — never break the poll loop
            logger.debug("rt_notify dispatch failed", exc_info=True)
            continue
        if ok:
            delivered_keys.extend(
                f"{getattr(s, 'symbol', '?')} {getattr(s, 'direction', '')} "
                f"{getattr(s, 'level', '')}" for s in bucket)
    return delivered_keys
