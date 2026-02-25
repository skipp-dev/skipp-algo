"""Secret redaction for log output — ported from IB_monitoring.

Provides:
  - ``redact_secrets(msg)``          — strip sensitive patterns from a string
  - ``LogRedactionFilter``           — ``logging.Filter`` that auto-redacts
  - ``apply_log_redaction(logger)``  — attach the filter to all handlers
  - ``apply_global_log_redaction()`` — attach the filter to the root logger

Usage::

    from open_prep.log_redaction import apply_global_log_redaction
    apply_global_log_redaction()  # call once at startup
"""
from __future__ import annotations

import logging
import re
from typing import Any

# ---------------------------------------------------------------------------
# Sensitive patterns (name, compiled regex)
# ---------------------------------------------------------------------------
_SENSITIVE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # Email addresses
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    ),
    # API keys / tokens / secrets (key=value style)
    (
        "api_token",
        re.compile(
            r"(?:api[_-]?key|token|secret|password|fmp[_-]?key)\s*[:=]\s*[\"']?([^\s'\"]+)[\"']?",
            re.IGNORECASE,
        ),
    ),
    # AWS access-key IDs
    ("aws_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    # Generic password assignments
    (
        "password",
        re.compile(
            r"password\s*[:=]\s*[\"']?([^\s'\"]+)[\"']?",
            re.IGNORECASE,
        ),
    ),
    # Authorization / Bearer headers
    (
        "auth_header",
        re.compile(r"(?:Authorization|Bearer|Token)\s*[:=]\s*\S+", re.IGNORECASE),
    ),
    # Twilio SID / auth-token patterns
    ("twilio_sid", re.compile(r"AC[a-zA-Z0-9]{32}")),
    ("twilio_token", re.compile(r"SK[a-zA-Z0-9]{32}")),
    # FMP API key (32-char hex is typical)
    ("fmp_key", re.compile(r"\b[a-fA-F0-9]{32}\b")),
]

_REPLACEMENT = "***REDACTED***"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def redact_secrets(msg: str, replacement: str = _REPLACEMENT) -> str:
    """Return *msg* with all recognised secret patterns replaced."""
    if not msg:
        return msg
    result = msg
    for _name, pattern in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


class LogRedactionFilter(logging.Filter):
    """Logging filter that automatically redacts sensitive data.

    Attach to a handler (not a logger) for best results::

        handler.addFilter(LogRedactionFilter())
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if record.msg and isinstance(record.msg, str):
            record.msg = redact_secrets(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {
                    k: redact_secrets(str(v)) if isinstance(v, str) else v
                    for k, v in record.args.items()
                }
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    redact_secrets(str(v)) if isinstance(v, str) else v
                    for v in record.args
                )
        return True


def apply_log_redaction(logger: logging.Logger) -> None:
    """Attach :class:`LogRedactionFilter` to every handler of *logger*."""
    filt = LogRedactionFilter()
    for handler in logger.handlers:
        handler.addFilter(filt)


def apply_global_log_redaction() -> None:
    """Attach :class:`LogRedactionFilter` to the **root** logger's handlers."""
    apply_log_redaction(logging.getLogger())
