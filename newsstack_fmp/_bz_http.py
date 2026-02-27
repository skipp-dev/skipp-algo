"""Shared HTTP helpers for Benzinga API adapters.

Centralises URL/exception sanitisation so that API keys are never logged
in plain text, regardless of which adapter raises the error.
"""

from __future__ import annotations

import re

# Regex to strip API keys/tokens from URLs before logging.
_TOKEN_RE = re.compile(r"(apikey|token)=[^&]+", re.IGNORECASE)


def _sanitize_url(url: str) -> str:
    """Remove apikey/token query params from a URL for safe logging."""
    return _TOKEN_RE.sub(r"\1=***", url)


def _sanitize_exc(exc: Exception) -> str:
    """Strip API keys/tokens from exception text for safe logging."""
    return re.sub(
        r"(apikey|token)=[^&\s]+", r"\1=***", str(exc), flags=re.IGNORECASE
    )
