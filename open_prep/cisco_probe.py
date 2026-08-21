"""Cisco AI Defense inspection-key self-probe for the signals producer.

The Terminal AI path is deliberately fail-closed: when the Cisco Inspection
API rejects the key (revoked, rotated away underneath us, region change) or
is unreachable, ``inspect_messages`` blocks the provider call and users see
errors — but nothing alerted an operator.  ``scripts/credential_health_check``
cannot cover this credential without duplicating the Inspection key into a
second secret store, so the producer probes itself: a background thread runs
one synthetic, content-free inspection per interval and exposes the outcome
as ``signals_producer_cisco_probe_*`` gauges on the existing ``/metrics``
surface, which Alloy already scrapes into Grafana (job ``signals_producer``).
The paired alert rules live in
``services/live_overlay_daemon/infra/grafana/alert-rules.yaml``
(``sp-cisco-probe-stale`` + ``sp-cisco-probe-missing``).

A *blocked* decision counts as success: Cisco answered, so the key works and
the policy is enforcing.  Only configuration errors, transport failures, and
malformed decisions count as probe failures — exactly the states in which
the runtime guard fails closed.

No prompt, response, key, or Cisco explanation is logged or exported; the
probe emits decision-metadata-free numeric gauges only.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

# Sentinel age exported until the first successful probe, mirroring the
# poll-age idiom in realtime_signals: the series exists from the first
# scrape (no absent() window on a healthy boot) and reads as "stale" when
# the key is dead from the start.
SENTINEL_AGE_SECONDS = 999999.0

# Exported series names. tests/test_cisco_probe_alert_rules.py pins these
# strings against the Grafana rules file so metric and alert cannot drift
# apart silently.
METRIC_LAST_SUCCESS_AGE = "cisco_probe_last_success_age_seconds"
METRIC_CONSECUTIVE_FAILURES = "cisco_probe_consecutive_failures"
METRIC_ATTEMPTS_TOTAL = "cisco_probe_attempts_total"
METRIC_FAILURES_TOTAL = "cisco_probe_failures_total"
METRIC_OK = "cisco_probe_ok"

_PROBE_MESSAGE = {"role": "user", "content": "ping"}


def probe_once() -> tuple[bool, str]:
    """Run one synthetic inspection; return ``(ok, error_type)``.

    ``ok`` is ``True`` when Cisco returned any complete decision — ALLOW or
    BLOCK — because either proves the key authenticates and the policy runs.
    ``error_type`` carries only an exception class name, never content.
    """
    from cisco_ai_defense import AIDefenseBlockedError, inspect_messages

    try:
        inspect_messages(
            [dict(_PROBE_MESSAGE)],
            phase="request",
            source="cisco-self-probe",
            model="self-probe",
        )
        return True, ""
    except AIDefenseBlockedError:
        return True, "AIDefenseBlockedError"
    except Exception as exc:  # AIDefenseUnavailableError, AIDefenseConfigurationError, defensive rest
        return False, type(exc).__name__


class CiscoKeyProber:
    """Background self-probe with thread-safe, exportable state."""

    def __init__(
        self,
        interval_s: float = 3600.0,
        probe_fn: Callable[[], tuple[bool, str]] = probe_once,
    ) -> None:
        self._interval = max(float(interval_s), 300.0)
        self._probe_fn = probe_fn
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.attempts = 0
        self.failures = 0
        self.consecutive_failures = 0
        self.last_attempt_epoch = 0.0
        self.last_success_epoch = 0.0
        self.last_ok: bool | None = None
        self.last_error_type = ""

    def start(self) -> None:
        """Start the probe thread (daemon). Idempotent under the lock."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True, name="cisco-probe-bg")
            self._thread.start()
        logger.info("Cisco key self-probe started (interval=%.0fs)", self._interval)

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def _loop(self) -> None:
        # First probe runs immediately so a fresh deploy replaces the
        # sentinel age within seconds instead of one full interval later.
        while not self._stop.is_set():
            try:
                ok, error_type = self._probe_fn()
            except Exception as exc:  # defensive: a raising probe_fn must not kill the thread
                ok, error_type = False, type(exc).__name__
            now = time.time()
            with self._lock:
                self.attempts += 1
                self.last_attempt_epoch = now
                self.last_ok = ok
                self.last_error_type = error_type if not ok else ""
                if ok:
                    self.last_success_epoch = now
                    self.consecutive_failures = 0
                else:
                    self.failures += 1
                    self.consecutive_failures += 1
            if ok:
                logger.info("Cisco key self-probe ok")
            else:
                logger.warning(
                    "Cisco key self-probe failed error_type=%s consecutive=%d",
                    error_type,
                    self.consecutive_failures,
                )
            self._stop.wait(self._interval)

    def metrics_lines(self, prefix: str) -> list[str]:
        """Prometheus exposition lines for this prober (HELP/TYPE + values)."""
        with self._lock:
            attempts = self.attempts
            failures = self.failures
            consecutive = self.consecutive_failures
            last_success = self.last_success_epoch
            last_ok = self.last_ok
        age = (
            max(0.0, time.time() - last_success)
            if last_success > 0
            else SENTINEL_AGE_SECONDS
        )
        ok_value = 1 if last_ok else 0
        return [
            f"# HELP {prefix}_{METRIC_LAST_SUCCESS_AGE} Seconds since the last successful Cisco AI Defense self-probe ({SENTINEL_AGE_SECONDS:.0f} until the first success).",
            f"# TYPE {prefix}_{METRIC_LAST_SUCCESS_AGE} gauge",
            f"{prefix}_{METRIC_LAST_SUCCESS_AGE} {age:.1f}",
            f"# TYPE {prefix}_{METRIC_CONSECUTIVE_FAILURES} gauge",
            f"{prefix}_{METRIC_CONSECUTIVE_FAILURES} {consecutive}",
            f"# TYPE {prefix}_{METRIC_ATTEMPTS_TOTAL} counter",
            f"{prefix}_{METRIC_ATTEMPTS_TOTAL} {attempts}",
            f"# TYPE {prefix}_{METRIC_FAILURES_TOTAL} counter",
            f"{prefix}_{METRIC_FAILURES_TOTAL} {failures}",
            f"# TYPE {prefix}_{METRIC_OK} gauge",
            f"{prefix}_{METRIC_OK} {ok_value}",
        ]
