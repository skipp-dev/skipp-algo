"""Shared HTTP helpers for Benzinga API adapters.

Centralises URL/exception sanitisation so that API keys are never logged
in plain text, regardless of which adapter raises the error.

Also provides the canonical ``_request_with_retry`` helper used by all
three Benzinga adapter modules.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|api_key|token|key)=[^&]+", re.IGNORECASE)

# ── Once-per-endpoint error suppression ─────────────────────────
# 400/403/404 responses typically mean the endpoint is not available
# on the user's API tier.  Warn once, then suppress to avoid log spam.
_WARNED_ENDPOINTS: set[str] = set()
_warned_lock = threading.Lock()

# HTTP status codes that indicate a tier/plan limitation rather than
# a transient error.  These are suppressed after the first occurrence.
_TIER_LIMITED_CODES: frozenset[int] = frozenset({400, 401, 403, 404})


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
    msg = _sanitize_exc(exc)
    if _is_tier_limited_error(exc):
        with _warned_lock:
            already_warned = label in _WARNED_ENDPOINTS
            _WARNED_ENDPOINTS.add(label)
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


def _request_with_retry(
    client: httpx.Client,
    url: str,
    params: dict[str, Any],
) -> httpx.Response:
    """GET *url* with exponential backoff on retryable status codes.

    Retries up to ``_MAX_ATTEMPTS`` times on 429/5xx responses and on
    transient network errors (``ConnectError``, ``ReadTimeout``).
    """
    last_exc: Exception | None = None
    r: httpx.Response | None = None
    for attempt in range(_MAX_ATTEMPTS):
        try:
            r = client.get(url, params=params)
            if r.status_code in _RETRYABLE and attempt < _MAX_ATTEMPTS - 1:
                logger.warning(
                    "Benzinga HTTP %s (attempt %d/%d) – retrying in %ds",
                    r.status_code,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    2 ** attempt,
                )
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r
        except (httpx.ConnectError, httpx.ReadTimeout) as exc:
            last_exc = exc
            if attempt < _MAX_ATTEMPTS - 1:
                logger.warning(
                    "Benzinga network error (attempt %d/%d): %s – retrying in %ds",
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    _sanitize_exc(exc),
                    2 ** attempt,
                )
                time.sleep(2 ** attempt)
                continue
            raise
        except httpx.HTTPStatusError:
            raise
    if r is not None:
        return r
    raise RuntimeError(
        "Benzinga: no response after retries"
        + (f" (last error: {_sanitize_exc(last_exc)})" if last_exc else "")
    )
