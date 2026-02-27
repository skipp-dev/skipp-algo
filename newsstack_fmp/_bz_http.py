"""Shared HTTP helpers for Benzinga API adapters.

Centralises URL/exception sanitisation so that API keys are never logged
in plain text, regardless of which adapter raises the error.

Also provides the canonical ``_request_with_retry`` helper used by all
three Benzinga adapter modules.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|token)=[^&]+", re.IGNORECASE)

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
        r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE
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
