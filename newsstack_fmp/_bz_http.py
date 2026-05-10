"""Shared HTTP helpers for Benzinga API adapters.

Centralises URL/exception sanitisation so that API keys are never logged
in plain text, regardless of which adapter raises the error.

Also provides the canonical ``_request_with_retry`` helper used by all
three Benzinga adapter modules.
"""

from __future__ import annotations

import logging
import math
import random
import re
import threading
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from smc_core.resilient import resilient

logger = logging.getLogger(__name__)


def _rng() -> float:
    """Test seam: full-jitter random source for retry backoff.

    Returns a float in [0.0, 1.0).  Patch this attribute (not
    ``random.random``) in tests that need deterministic jitter.
    """
    return random.random()


def _sleep(seconds: float) -> None:
    """Test seam: sleep used during retry backoff.

    Patch this attribute (not ``time.sleep``) in tests that need to
    capture retry sleep durations.
    """
    time.sleep(seconds)

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|api_key|token|key)=[^&]+", re.IGNORECASE)

# ── Once-per-endpoint error suppression ─────────────────────────
# 400/403/404 responses typically mean the endpoint is not available
# on the user's API tier.  Warn once, then suppress to avoid log spam.
_WARNED_ENDPOINTS: set[str] = set()
_warned_lock = threading.Lock()

# Endpoints that have permanently failed (401/403/404 or repeated 400 from
# a retired URL shape).  After the first such error, callers that pass
# ``label=`` to :func:`_request_with_retry` will short-circuit and avoid
# wasting a network round-trip on every poll cycle.
_DISABLED_ENDPOINTS: set[str] = set()
_disabled_lock = threading.Lock()

# HTTP status codes that indicate a tier/plan limitation rather than
# a transient error.  These are suppressed after the first occurrence.
_TIER_LIMITED_CODES: frozenset[int] = frozenset({400, 401, 403, 404})


class BenzingaEndpointDisabledError(RuntimeError):
    """Raised when an endpoint has been marked disabled after a permanent
    failure (tier-limit, retired URL, or missing entitlement).  Callers
    typically catch :class:`Exception`, log via :func:`log_fetch_warning`,
    and return an empty payload.
    """

    def __init__(self, label: str) -> None:
        super().__init__(
            f"Benzinga endpoint disabled (previously failed with tier-limited "
            f"or retired URL response): {label}"
        )
        self.label = label


def is_endpoint_disabled(label: str) -> bool:
    """Return True if *label* has been marked disabled in this process."""
    with _disabled_lock:
        return label in _DISABLED_ENDPOINTS


def mark_endpoint_disabled(label: str) -> None:
    """Mark *label* disabled so future requests skip the network call."""
    with _disabled_lock:
        _DISABLED_ENDPOINTS.add(label)


def clear_disabled_endpoints() -> None:
    """Clear all disabled endpoint flags (test helper)."""
    with _disabled_lock:
        _DISABLED_ENDPOINTS.clear()
    with _warned_lock:
        _WARNED_ENDPOINTS.clear()


# Repeated transient errors can flood logs during provider/network incidents.
# Keep one warning per key+window and aggregate the suppressed duplicates.
_TRANSIENT_LOG_WINDOW_S = 30.0
_transient_log_state: dict[str, tuple[float, int]] = {}
_transient_log_lock = threading.Lock()


def _log_transient_warning_throttled(key: str, message: str, *args: Any) -> None:
    now = time.time()
    with _transient_log_lock:
        ts, suppressed = _transient_log_state.get(key, (0.0, 0))
        if now - ts < _TRANSIENT_LOG_WINDOW_S:
            _transient_log_state[key] = (ts, suppressed + 1)
            return
        if suppressed > 0:
            logger.warning("Benzinga transient errors: suppressed %d duplicate log(s) for %s", suppressed, key)
        _transient_log_state[key] = (now, 0)
    logger.warning(message, *args)


def _is_tier_limited_error(exc: Exception) -> bool:
    """Return True if *exc* is an httpx.HTTPStatusError with a tier-limited code."""
    return (
        isinstance(exc, httpx.HTTPStatusError)
        and exc.response.status_code in _TIER_LIMITED_CODES
    )


def log_fetch_warning(label: str, exc: Exception) -> None:
    """Log a fetch failure, suppressing repeated tier-limited errors.

    On the first occurrence of a 400/401/403/404 for a given *label*,
    the error is logged at WARNING level with a note that further
    occurrences will be suppressed.  Subsequent occurrences for the
    same *label* are logged at DEBUG only.

    Other errors (network, 5xx, etc.) are always logged at WARNING.
    """
    # Skip logging entirely for the synthetic disabled-endpoint exception:
    # the original failure was already logged on first occurrence and we
    # don't want a fresh WARNING line every poll cycle just to say "still
    # disabled".
    if isinstance(exc, BenzingaEndpointDisabledError):
        logger.debug("%s skipped (endpoint disabled)", label)
        return
    msg = _sanitize_exc(exc)
    if _is_tier_limited_error(exc):
        with _warned_lock:
            already_warned = label in _WARNED_ENDPOINTS
            _WARNED_ENDPOINTS.add(label)
        # Once a tier-limited response is seen, mark the endpoint disabled
        # so callers that pass ``label=`` to ``_request_with_retry`` can
        # skip future network round-trips.
        mark_endpoint_disabled(label)
        if not already_warned:
            code = exc.response.status_code  # type: ignore
            logger.warning(
                "%s fetch failed (HTTP %d) – endpoint not available on "
                "your API plan; suppressing further warnings: %s",
                label, code, msg,
            )
        else:
            logger.debug("%s fetch failed (tier-limited, suppressed): %s", label, msg)
    else:
        logger.warning("%s fetch failed: %s", label, msg)

# Status codes eligible for automatic retry with backoff.
_RETRYABLE: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Maximum number of retry attempts (including the first request).
_MAX_ATTEMPTS: int = 3


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _TOKEN_RE.sub(r"\1=***", url)


def _sanitize_exc(exc: Exception) -> str:
    """Strip API keys/tokens from exception text for safe logging."""
    return re.sub(
        r"(apikey|api_key|token|key)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE
    )


def _parse_retry_after_seconds(raw_value: Any) -> float | None:
    """Parse an HTTP ``Retry-After`` header into seconds (RFC 9110 §10.2.3).

    Accepts both the integer-seconds form (``"30"``) and the HTTP-date
    form (``"Wed, 21 Oct 2026 07:28:00 GMT"``). Returns ``None`` when
    the value is empty or unparseable so the caller can fall back to
    its own backoff schedule.
    """
    if raw_value is None or raw_value == "":
        return None
    try:
        v = float(raw_value)
    except (TypeError, ValueError):
        v = None
    if v is not None:
        # Reject NaN/Inf — ``time.sleep(NaN)`` raises ValueError and
        # ``time.sleep(inf)`` would wedge the retry loop. Falling through
        # to ``None`` lets the caller use its own exponential backoff.
        if math.isnan(v) or math.isinf(v):
            return None
        return max(v, 0.0)
    try:
        parsed = parsedate_to_datetime(str(raw_value))
    except (TypeError, ValueError, IndexError, OverflowError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(
        (parsed.astimezone(UTC) - datetime.now(UTC)).total_seconds(),
        0.0,
    )


def _request_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
    label: str | None = None,
) -> httpx.Response:
    """GET *url* with exponential backoff on retryable status codes.

    Retries up to ``_MAX_ATTEMPTS`` times on 429/5xx responses and on
    transient network errors (``ConnectError``, ``ReadTimeout``) via the
    canonical :func:`smc_core.resilient.resilient` decorator (full
    jitter; honors ``Retry-After`` hints from 429/5xx responses).

    If *label* is provided and that label has previously failed with a
    tier-limited status code (400/401/403/404), this function raises
    :class:`BenzingaEndpointDisabledError` immediately without making a
    network call.  Tier-limited responses returned from this call also
    auto-mark the endpoint disabled so subsequent polls short-circuit.
    """
    if label is not None and is_endpoint_disabled(label):
        raise BenzingaEndpointDisabledError(label)
    try:
        return _attempt_bz_get(client, url, params)
    except httpx.HTTPStatusError as exc:
        # Auto-disable on tier-limited / retired-URL responses so the
        # next poll skips the wasted round-trip.
        if label is not None and exc.response.status_code in _TIER_LIMITED_CODES:
            mark_endpoint_disabled(label)
        raise


class _BzRetryableStatusError(Exception):
    """Internal sentinel: a 429/5xx status that ``@resilient`` should retry."""

    def __init__(self, response: httpx.Response) -> None:
        super().__init__(f"Benzinga retryable HTTP {response.status_code}")
        self.response = response
        self.status_code = response.status_code
        self.retry_after_hint = _parse_retry_after_seconds(
            response.headers.get("Retry-After")
        )


def _bz_delay_from_exc(exc: BaseException) -> float | None:
    """Honor ``Retry-After`` hints when present; otherwise fall back to jitter."""
    if isinstance(exc, _BzRetryableStatusError) and exc.retry_after_hint is not None:
        return float(exc.retry_after_hint)
    return None


def _bz_on_retry(exc: BaseException, attempt: int, delay: float) -> None:
    if isinstance(exc, _BzRetryableStatusError):
        _log_transient_warning_throttled(
            f"http_{exc.status_code}",
            "Benzinga HTTP %s (attempt %d/%d) – retrying in %.1fs",
            exc.status_code,
            attempt,
            _MAX_ATTEMPTS,
            delay,
        )
    else:
        _log_transient_warning_throttled(
            f"network_{type(exc).__name__}",
            "Benzinga network error (attempt %d/%d): %s – retrying in %.1fs",
            attempt,
            _MAX_ATTEMPTS,
            _sanitize_exc(exc),  # type: ignore[arg-type]
            delay,
        )


def _bz_on_failure(exc: BaseException) -> httpx.Response:
    """After exhausted retries, surface the underlying HTTP error."""
    if isinstance(exc, _BzRetryableStatusError):
        exc.response.raise_for_status()
    raise exc


@resilient(
    retries=_MAX_ATTEMPTS - 1,
    base_delay=1.0,
    max_delay=60.0,
    exceptions=(httpx.ConnectError, httpx.ReadTimeout, _BzRetryableStatusError),
    delay_from_exc=_bz_delay_from_exc,
    on_retry=_bz_on_retry,
    on_failure=_bz_on_failure,
    # Route jitter + sleep through module-level seams so tests can
    # patch ``_bz_http._rng`` / ``_bz_http._sleep`` directly. The
    # lambdas resolve the names at call time so monkey-patching the
    # module attributes works as expected.
    rng=lambda: _rng(),
    sleep=lambda s: _sleep(s),
)
def _request_with_status_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
) -> httpx.Response:
    """GET with retry on 429/5xx and transient network errors.

    Returns the final :class:`httpx.Response` *without* calling
    ``raise_for_status``, so callers can inspect non-retryable 4xx
    codes (e.g. 401/403/404 used by UW for tier-limited endpoints).

    Audit-fix (2026-05-10, F2): extracted from ``_attempt_bz_get`` so
    the Unusual Whales adapter can share the same retry primitive
    without duplicating the backoff/Retry-After/jitter logic.
    """
    r = client.get(url, params=params)
    if r.status_code in _RETRYABLE:
        raise _BzRetryableStatusError(r)
    return r


def _attempt_bz_get(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
) -> httpx.Response:
    """GET with retry + ``raise_for_status`` for non-retryable 4xx."""
    r = _request_with_status_retry(client, url, params)
    r.raise_for_status()
    return r
