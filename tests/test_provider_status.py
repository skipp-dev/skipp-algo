"""Tests for ProviderTracker / ProviderStatus health primitives."""
from __future__ import annotations

import threading
import time

import pytest

from smc_tv_bridge.provider_status import (
    ProviderStatus,
    ProviderTracker,
    _DOWN_CONSECUTIVE,
)


# ── Basic lifecycle ─────────────────────────────────────────────────────────

class TestProviderTrackerBasic:
    """Core record / query lifecycle."""

    def test_unknown_before_any_call(self) -> None:
        t = ProviderTracker()
        s = t.status("foo")
        assert s.availability == "unknown"
        assert s.total_calls == 0

    def test_success_records_latency(self) -> None:
        t = ProviderTracker()
        t.record_success("svc", latency_s=0.05)
        s = t.status("svc")
        assert s.availability == "up"
        assert s.total_calls == 1
        assert s.avg_latency_ms == pytest.approx(50.0, abs=1)

    def test_failure_records_error(self) -> None:
        t = ProviderTracker()
        t.record_failure("svc", error="timeout", latency_s=1.0)
        s = t.status("svc")
        assert s.total_failures == 1
        assert "timeout" in s.last_error

    def test_consecutive_failures_count(self) -> None:
        t = ProviderTracker()
        for _ in range(3):
            t.record_failure("svc", error="err")
        assert t.status("svc").consecutive_failures == 3

    def test_success_resets_consecutive(self) -> None:
        t = ProviderTracker()
        t.record_failure("svc", error="err")
        t.record_failure("svc", error="err")
        t.record_success("svc")
        assert t.status("svc").consecutive_failures == 0


# ── Availability classification ─────────────────────────────────────────────

class TestAvailabilityClassification:

    def test_up_after_all_successes(self) -> None:
        t = ProviderTracker()
        for _ in range(10):
            t.record_success("svc", latency_s=0.01)
        s = t.status("svc")
        assert s.availability == "up"
        assert s.reason == "healthy"

    def test_down_after_consecutive_failures(self) -> None:
        t = ProviderTracker()
        for _ in range(_DOWN_CONSECUTIVE):
            t.record_failure("svc", error="conn refused")
        s = t.status("svc")
        assert s.availability == "down"
        assert "consecutive" in s.reason

    def test_degraded_on_partial_failures(self) -> None:
        t = ProviderTracker()
        # 7 successes + 3 failures = 30% failure rate → degraded
        for _ in range(7):
            t.record_success("svc")
        for _ in range(3):
            t.record_failure("svc", error="slow")
        s = t.status("svc")
        assert s.availability == "degraded"

    def test_recovery_after_success(self) -> None:
        t = ProviderTracker()
        for _ in range(_DOWN_CONSECUTIVE):
            t.record_failure("svc", error="x")
        assert t.status("svc").availability == "down"
        # Enough successes to dilute failure ratio
        for _ in range(20):
            t.record_success("svc")
        assert t.status("svc").availability == "up"


# ── Latency metrics ─────────────────────────────────────────────────────────

class TestLatencyMetrics:

    def test_p95_latency(self) -> None:
        t = ProviderTracker()
        for i in range(10):
            t.record_success("svc", latency_s=0.01)
        # Several slow calls so they land above the 95th percentile index
        for _ in range(3):
            t.record_success("svc", latency_s=1.0)
        s = t.status("svc")
        assert s.p95_latency_ms >= 100  # the outlier is captured

    def test_empty_latency_is_zero(self) -> None:
        t = ProviderTracker()
        s = t.status("svc")
        assert s.avg_latency_ms == 0.0
        assert s.p95_latency_ms == 0.0


# ── Context manager ─────────────────────────────────────────────────────────

class TestTrackContextManager:

    def test_success_via_context(self) -> None:
        t = ProviderTracker()
        with t.track("svc"):
            pass  # no exception → success
        s = t.status("svc")
        assert s.availability == "up"
        assert s.total_calls == 1

    def test_failure_via_context(self) -> None:
        t = ProviderTracker()
        with pytest.raises(ValueError):
            with t.track("svc"):
                raise ValueError("boom")
        s = t.status("svc")
        assert s.total_failures == 1
        assert "boom" in s.last_error

    def test_latency_recorded_via_context(self) -> None:
        t = ProviderTracker()
        with t.track("svc"):
            time.sleep(0.01)
        s = t.status("svc")
        assert s.avg_latency_ms > 0


# ── Multi-provider / registry ──────────────────────────────────────────────

class TestMultiProvider:

    def test_all_statuses(self) -> None:
        t = ProviderTracker()
        t.record_success("a")
        t.record_failure("b", error="x")
        statuses = t.all_statuses()
        assert set(statuses.keys()) == {"a", "b"}

    def test_is_degraded(self) -> None:
        t = ProviderTracker()
        for _ in range(6):
            t.record_failure("bad", error="x")
        t.record_success("good")
        assert t.is_degraded("bad")
        assert not t.is_degraded("good")

    def test_summary_lines(self) -> None:
        t = ProviderTracker()
        t.record_success("svc_a")
        lines = t.summary_lines()
        assert len(lines) == 1
        assert "svc_a" in lines[0]

    def test_reset_single(self) -> None:
        t = ProviderTracker()
        t.record_success("a")
        t.record_success("b")
        t.reset("a")
        assert t.status("a").total_calls == 0
        assert t.status("b").total_calls == 1

    def test_reset_all(self) -> None:
        t = ProviderTracker()
        t.record_success("a")
        t.record_success("b")
        t.reset()
        assert t.all_statuses() == {}


# ── Thread safety ───────────────────────────────────────────────────────────

class TestThreadSafety:

    def test_concurrent_recording(self) -> None:
        t = ProviderTracker()
        errors: list[Exception] = []

        def worker(name: str) -> None:
            try:
                for _ in range(100):
                    t.record_success(name, latency_s=0.001)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(f"svc_{i}",)) for i in range(4)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=10)

        assert not errors
        for i in range(4):
            assert t.status(f"svc_{i}").total_calls == 100


# ── ProviderStatus is frozen ───────────────────────────────────────────────

class TestProviderStatusFrozen:

    def test_immutable(self) -> None:
        t = ProviderTracker()
        t.record_success("svc")
        s = t.status("svc")
        with pytest.raises(AttributeError):
            s.availability = "down"  # type: ignore[misc]
