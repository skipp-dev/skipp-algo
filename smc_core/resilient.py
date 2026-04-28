"""Resilience decorator for IO adapter calls (E-3 pilot).

Audit reference: ``docs/TEMPORAL_NUMERICAL_IMPROVEMENT_PLAN_2026-04-24.md``
backlog item **E-3** (`@resilient` decorator refactor).

Status
------
Pilot / foundation. Ships the decorator + a contract test suite so that
future per-adapter migrations have a single, agreed API to wrap their
HTTP / IO call sites against. **No production call site is migrated by
the PR introducing this module** — that is intentional. Per-adapter
moves happen in dedicated follow-up PRs after the contract is reviewed.

Design
------
The decorator implements bounded exponential backoff with full jitter:

* ``retries``: total number of *additional* attempts after the first
  call (``retries=3`` → up to 4 attempts in total).
* ``base_delay``: seconds before the first retry; doubled per attempt
  up to ``max_delay``.
* ``max_delay``: per-attempt cap so backoff cannot grow unbounded.
* ``exceptions``: tuple of exception classes that trigger a retry.
  Anything else propagates immediately.
* ``on_failure``: optional callable returning the value to substitute
  when all attempts fail. ``None`` re-raises the last exception.
* ``on_retry``: optional observer hook called as
  ``on_retry(exc, attempt, delay)`` so callers can route to their own
  logger without coupling the decorator to a specific logging library.

Pure stdlib. Thread- and async-agnostic — sync only by design (the
audited adapter hot-path is sync).
"""

from __future__ import annotations

import functools
import random
import time
from typing import Any, Callable, TypeVar


F = TypeVar("F", bound=Callable[..., Any])


def resilient(
    *,
    retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 30.0,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    on_failure: Callable[[BaseException], Any] | None = None,
    on_retry: Callable[[BaseException, int, float], None] | None = None,
    delay_from_exc: Callable[[BaseException], float | None] | None = None,
    sleep: Callable[[float], None] | None = None,
    rng: Callable[[], float] | None = None,
) -> Callable[[F], F]:
    """Wrap ``func`` so that selected exceptions trigger bounded retries.

    Parameters are keyword-only on purpose so call sites read like
    documentation: ``@resilient(retries=2, base_delay=0.25, ...)``.

    ``delay_from_exc`` lets the wrapped exception override the default
    full-jitter delay (e.g. honoring an HTTP ``Retry-After`` hint).
    Returning ``None`` falls back to the default jittered delay. The
    returned value is still capped at ``max_delay``.

    The ``sleep`` and ``rng`` parameters are injected for testing — pass
    a fake clock to make the decorator deterministic in unit tests.
    """
    if retries < 0:
        raise ValueError("retries must be >= 0")
    if base_delay < 0:
        raise ValueError("base_delay must be >= 0")
    if max_delay < 0:
        raise ValueError("max_delay must be >= 0")
    if max_delay < base_delay:
        raise ValueError("max_delay must be >= base_delay")

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            attempt = 0
            last_exc: BaseException | None = None
            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    attempt += 1
                    if attempt > retries:
                        if on_failure is not None:
                            return on_failure(exc)
                        raise
                    override = delay_from_exc(exc) if delay_from_exc is not None else None
                    if override is not None:
                        delay = max(0.0, min(float(override), max_delay))
                    else:
                        # Full jitter: random in [0, capped_delay)
                        capped = min(base_delay * (2 ** (attempt - 1)), max_delay)
                        rng_fn = rng if rng is not None else random.random
                        delay = capped * rng_fn()
                    if on_retry is not None:
                        on_retry(exc, attempt, delay)
                    if delay > 0:
                        sleep_fn = sleep if sleep is not None else time.sleep
                        sleep_fn(delay)

        # Expose configuration for introspection (helps tests + ops).
        wrapper.__resilient__ = {  # type: ignore[attr-defined]
            "retries": retries,
            "base_delay": base_delay,
            "max_delay": max_delay,
            "exceptions": exceptions,
        }
        return wrapper  # type: ignore[return-value]

    return decorator


__all__ = ["resilient"]
