"""Alert routing: dispatch webhook notifications for high-conviction
candidates and regime changes.

Supports multiple webhook targets (TradersPost, Slack, Discord, generic).
Configuration is loaded from ``artifacts/open_prep/alert_config.json``.
"""
from __future__ import annotations

import json
import ipaddress
import logging
import os
import socket
import ssl
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

logger = logging.getLogger("open_prep.alerts")

ALERT_CONFIG_PATH = Path("artifacts/open_prep/alert_config.json")

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "min_confidence_tier": "HIGH_CONVICTION",
    "targets": [],
    # Throttle: at most 1 alert per symbol per N seconds
    "throttle_seconds": 600,
    # Example target:
    # {
    #     "name": "TradersPost",
    #     "url": "https://traderspost.io/api/v1/...",
    #     "type": "traderspost",
    #     "headers": {"Content-Type": "application/json"},
    # },
}

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def load_alert_config() -> dict[str, Any]:
    """Load alert config from JSON file, falling back to defaults."""
    if ALERT_CONFIG_PATH.exists():
        try:
            with open(ALERT_CONFIG_PATH, "r", encoding="utf-8") as fh:
                return {**DEFAULT_CONFIG, **json.load(fh)}
        except Exception:
            logger.warning("Failed to load alert config, using defaults", exc_info=True)
    return dict(DEFAULT_CONFIG)


def save_alert_config(config: dict[str, Any]) -> Path:
    """Persist alert configuration.

    Public utility — kept for REPL / notebook / external-script use.
    """
    ALERT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(config, indent=2)
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=ALERT_CONFIG_PATH.parent, suffix=".tmp", prefix="alert_config_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, ALERT_CONFIG_PATH)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
    logger.info("Saved alert config → %s", ALERT_CONFIG_PATH)
    return ALERT_CONFIG_PATH


# ---------------------------------------------------------------------------
# Throttle state (in-memory; resets on restart)
# ---------------------------------------------------------------------------

_last_sent: dict[str, float] = {}
_throttle_lock = threading.Lock()

# Maximum entries kept in the throttle dict to prevent unbounded growth
# in long-running processes (e.g. Streamlit).
_LAST_SENT_MAX = 500


def _throttle_key(symbol: str, target_scope: str | None = None) -> str:
    if target_scope:
        return target_scope
    return symbol


def _is_throttled(symbol: str, throttle_seconds: int, *, target_scope: str | None = None) -> bool:
    """Check if we recently sent an alert for this symbol."""
    key = _throttle_key(symbol, target_scope)
    with _throttle_lock:
        last = _last_sent.get(key, 0.0)
    return (time.time() - last) < throttle_seconds


def _mark_sent(symbol: str, *, target_scope: str | None = None) -> None:
    key = _throttle_key(symbol, target_scope)
    with _throttle_lock:
        _last_sent[key] = time.time()


def _prune_stale_entries(throttle_seconds: int) -> None:
    """Remove entries older than throttle window to cap memory usage."""
    with _throttle_lock:
        if len(_last_sent) <= _LAST_SENT_MAX:
            return
        now = time.time()
        stale = [k for k, v in _last_sent.items() if (now - v) >= throttle_seconds]
        for k in stale:
            del _last_sent[k]


# ---------------------------------------------------------------------------
# Payload formatters
# ---------------------------------------------------------------------------

TIER_LABELS = {
    "HIGH_CONVICTION": "🟢 HIGH CONVICTION",
    "STANDARD": "🟡 STANDARD",
    "WATCHLIST": "🔵 WATCHLIST",
}


def _format_traderspost_payload(candidate: dict[str, Any]) -> dict[str, Any]:
    """Format a payload for TradersPost webhook."""
    gap = (candidate.get("gap_pct", 0) or 0)
    return {
        "ticker": candidate.get("symbol", ""),
        "action": "buy" if gap > 0 else "sell",
        "sentiment": "bullish" if gap > 0 else "bearish",
        "price": candidate.get("price") or candidate.get("prev_close"),
    }


def _format_slack_payload(candidate: dict[str, Any], regime: str | None = None) -> dict[str, Any]:
    """Format a Slack-compatible payload."""
    sym = candidate.get("symbol", "?")
    gap = candidate.get("gap_pct", 0) or 0
    score = candidate.get("score", 0) or 0
    tier = candidate.get("confidence_tier", "STANDARD")
    tier_label = TIER_LABELS.get(tier, tier)

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{tier_label}*\n"
                    f"*{sym}*  gap {gap:+.1f}%  score {score:.2f}\n"
                    f"Regime: {regime or 'N/A'}"
                ),
            },
        }
    ]
    return {"blocks": blocks, "text": f"{tier_label}: {sym} gap {gap:+.1f}%"}


def _format_discord_payload(candidate: dict[str, Any], regime: str | None = None) -> dict[str, Any]:
    """Format a Discord-compatible webhook payload."""
    sym = candidate.get("symbol", "?")
    gap = candidate.get("gap_pct", 0) or 0
    score = candidate.get("score", 0) or 0
    tier = candidate.get("confidence_tier", "STANDARD")
    tier_label = TIER_LABELS.get(tier, tier)

    return {
        "content": f"{tier_label}\n**{sym}** — gap {gap:+.1f}% — score {score:.2f} — regime: {regime or 'N/A'}",
    }


def _format_generic_payload(candidate: dict[str, Any], regime: str | None = None) -> dict[str, Any]:
    """Format a generic JSON webhook payload."""
    return {
        "event": "open_prep_signal",
        "symbol": candidate.get("symbol"),
        "gap_pct": candidate.get("gap_pct"),
        "score": candidate.get("score"),
        "confidence_tier": candidate.get("confidence_tier"),
        "gap_bucket": candidate.get("gap_bucket") or candidate.get("gap_class"),
        "regime": regime,
        "timestamp": time.time(),
    }


_FORMATTERS = {
    "traderspost": _format_traderspost_payload,
    "slack": _format_slack_payload,
    "discord": _format_discord_payload,
    "generic": _format_generic_payload,
}


def _is_safe_webhook_url(url: str) -> tuple[bool, str]:
    """Best-effort SSRF guard for outbound webhook targets."""
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False, "invalid_url"

    if parsed.scheme not in {"https", "http"}:
        return False, "unsupported_scheme"

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False, "missing_host"

    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False, "local_host"

    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
            return False, "private_or_local_ip"
    except ValueError:
        # Not an IP literal. Resolve and block clearly local/private answers.
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
            for info in infos:
                addr = info[4][0]
                ip = ipaddress.ip_address(addr)
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                    return False, "resolved_to_private_or_local_ip"
        except Exception:
            # DNS failures are surfaced by sender path.
            pass

    return True, ""


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_alerts(
    ranked: list[dict[str, Any]],
    regime: str | None = None,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Send alerts for qualifying candidates.

    Returns a list of result dicts (one per sent alert) for logging.
    """
    if config is None:
        config = load_alert_config()

    if not config.get("enabled", False):
        return []

    targets = config.get("targets", [])
    if not targets:
        return []

    min_tier = config.get("min_confidence_tier", "HIGH_CONVICTION")
    throttle = config.get("throttle_seconds", 600)
    tier_priority = ["HIGH_CONVICTION", "STANDARD", "WATCHLIST"]

    try:
        min_idx = tier_priority.index(min_tier)
    except ValueError:
        min_idx = 0

    results: list[dict[str, Any]] = []

    _prune_stale_entries(throttle)

    for candidate in ranked:
        tier = candidate.get("confidence_tier", "STANDARD")
        try:
            tier_idx = tier_priority.index(tier)
        except ValueError:
            tier_idx = 99

        if tier_idx > min_idx:
            continue

        symbol = candidate.get("symbol", "")
        if _is_throttled(symbol, throttle):
            logger.debug("Throttled alert for %s", symbol)
            continue

        for target in targets:
            target_type = target.get("type", "generic")
            url = target.get("url", "")
            if not url:
                continue
            target_name = str(target.get("name", target_type) or target_type)
            target_scope = f"{symbol}::{target_name}"
            if _is_throttled(symbol, throttle, target_scope=target_scope):
                logger.debug("Throttled alert for %s/%s", symbol, target_name)
                continue

            try:
                if target_type == "traderspost":
                    payload = _format_traderspost_payload(candidate)
                elif target_type == "slack":
                    payload = _format_slack_payload(candidate, regime=regime)
                elif target_type == "discord":
                    payload = _format_discord_payload(candidate, regime=regime)
                else:
                    payload = _format_generic_payload(candidate, regime=regime)
            except Exception:
                logger.warning("Failed to format alert payload for %s/%s", symbol, target_type, exc_info=True)
                continue

            result = _send_webhook(url, payload, target.get("headers"))
            status = result.get("status", 0)
            if 200 <= status < 300:
                _mark_sent(symbol, target_scope=target_scope)
            results.append({
                "symbol": symbol,
                "target": target_name,
                "status": status,
            })

    if results:
        logger.info("Dispatched %d alert(s)", len(results))
    return results


def _send_webhook(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    *,
    _max_retries: int = 2,
) -> dict[str, Any]:
    """Send a webhook POST request.  Uses urllib to avoid hard dependency.

    Retries up to *_max_retries* times on retryable failures
    (429, 5xx, and transient network errors).
    """
    import urllib.error
    import urllib.request

    safe, reason = _is_safe_webhook_url(url)
    if not safe:
        logger.warning("Blocked webhook URL (%s)", reason)
        return {"status": 0, "error": f"unsafe_url:{reason}"}

    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)

    data = json.dumps(payload, allow_nan=False, default=str).encode("utf-8")

    # Build an SSL context — prefer certifi if installed, else default.
    try:
        import certifi
        ssl_ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        ssl_ctx = ssl.create_default_context()

    # Mask URL for logging to avoid leaking auth tokens in query params.
    masked_url = url.split("?")[0] + ("?***" if "?" in url else "")

    class _NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
            return None

    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_ctx),
        _NoRedirect(),
    )

    last_exc: Exception | None = None
    retryable_http = {429, 500, 502, 503, 504}
    for attempt in range(_max_retries + 1):
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        try:
            with opener.open(req, timeout=10) as resp:
                return {"status": resp.status, "body": resp.read().decode("utf-8", errors="replace")[:500]}
        except urllib.error.HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                logger.warning("Webhook redirect blocked for %s", masked_url)
                return {"status": exc.code, "error": "redirect_blocked"}
            if exc.code in retryable_http and attempt < _max_retries:
                wait = (attempt + 1) * 1.0  # 1s, 2s
                logger.info("Webhook HTTP %d for %s — retrying in %.0fs (attempt %d/%d)",
                            exc.code,
                            masked_url, wait, attempt + 1, _max_retries)
                time.sleep(wait)
                last_exc = exc
                continue
            logger.warning("Webhook HTTP error %d for %s", exc.code, masked_url)
            return {"status": exc.code, "error": type(exc).__name__}
        except urllib.error.URLError as exc:
            if attempt < _max_retries:
                wait = (attempt + 1) * 1.0
                logger.info("Webhook network error for %s — retrying in %.0fs (attempt %d/%d)",
                            masked_url, wait, attempt + 1, _max_retries)
                time.sleep(wait)
                last_exc = exc
                continue
            logger.warning("Webhook network error for %s: %s", masked_url, exc)
            return {"status": 0, "error": type(exc).__name__}
        except Exception as exc:
            logger.warning("Webhook error for %s: %s", masked_url, exc)
            return {"status": 0, "error": type(exc).__name__}

    # All retries exhausted (should only reach here after 429 retries)
    logger.warning("Webhook retries exhausted for %s", masked_url)
    return {"status": 429, "error": type(last_exc).__name__ if last_exc else "retries exhausted"}


# ---------------------------------------------------------------------------
# Regime-change alert (one-shot per run)
# ---------------------------------------------------------------------------

def alert_regime_change(
    prev_regime: str | None,
    new_regime: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fire an alert if the regime changed since last run."""
    if prev_regime is None or prev_regime == new_regime:
        return []

    if config is None:
        config = load_alert_config()

    if not config.get("enabled", False):
        return []

    results: list[dict[str, Any]] = []
    regime_payload = {
        "event": "regime_change",
        "previous": prev_regime,
        "current": new_regime,
        "timestamp": time.time(),
    }

    for target in config.get("targets", []):
        url = target.get("url", "")
        if url:
            r = _send_webhook(url, regime_payload, target.get("headers"))
            results.append({"target": target.get("name"), "status": r.get("status")})

    return results
