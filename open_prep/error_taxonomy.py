"""Structured error taxonomy and retry decorator for open_prep.

Provides:
  - A custom exception hierarchy so callers can catch specific failure
    modes (FMP data errors, scoring errors, signal errors) without
    resorting to bare ``Exception``.
  - A ``@retry()`` decorator with exponential backoff, jitter, exception-
    type filtering, and an on_retry callback.

Ported from IB_MON's error_taxonomy pattern and adapted for the
open_prep (FMP-based) context.
"""
from __future__ import annotations

import functools
import logging
import random
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("open_prep.error_taxonomy")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------

class OpenPrepError(Exception):
    """Base error for all open_prep subsystems."""
    pass


class FMPDataError(OpenPrepError):
    """FMP API returned invalid, missing, or rate-limited data."""

    def __init__(self, message: str, *, endpoint: str = "", symbol: str = ""):
        self.endpoint = endpoint
        self.symbol = symbol
        super().__init__(message)


class ScoringError(OpenPrepError):
    """Error during candidate scoring / feature computation."""

    def __init__(self, message: str, *, symbol: str = "", component: str = ""):
        self.symbol = symbol
        self.component = component
        super().__init__(message)


class SignalError(OpenPrepError):
    """Error in realtime signal detection or decay."""

    def __init__(self, message: str, *, symbol: str = ""):
        self.symbol = symbol
        super().__init__(message)


class ConfigError(OpenPrepError):
    """Invalid configuration value."""
    pass


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

def retry(
    attempts: int = 3,
    backoff: float = 1.5,
    max_delay: float = 30.0,
    jitter_pct: float = 0.10,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
    on_retry: Callable[..., Any] | None = None,
):
    """Decorator: retry a function with exponential backoff + jitter.

    Parameters
    ----------
    attempts : int
        Maximum number of tries (including the first).
    backoff : float
        Multiplier applied to the delay after each failure.
    max_delay : float
        Upper cap on the sleep between retries (seconds).
    jitter_pct : float
        ±N % random jitter added to the delay (0.10 = ±10 %).
    retryable_exceptions : tuple
        Only retry if the raised exception is an instance of one of these.
    on_retry : callable, optional
        ``on_retry(attempt, exception)`` called before each retry sleep.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            delay = 1.0
            last_exc: Exception | None = None
            for attempt in range(1, attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retryable_exceptions as exc:
                    last_exc = exc
                    if attempt >= attempts:
                        raise
                    if on_retry is not None:
                        try:
                            on_retry(attempt, exc)
                        except Exception:
                            pass
                    jitter = delay * jitter_pct * (2 * random.random() - 1)
                    sleep_time = min(delay + jitter, max_delay)
                    logger.debug(
                        "retry %d/%d for %s after %.1fs — %s",
                        attempt, attempts, fn.__qualname__, sleep_time, exc,
                    )
                    time.sleep(max(sleep_time, 0))
                    delay = min(delay * backoff, max_delay)
            # Should not reach here, but just in case
            if last_exc:
                raise last_exc
        return wrapper
    return decorator
