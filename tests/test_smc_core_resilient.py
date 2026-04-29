"""Contract tests for ``smc_core.resilient.resilient``.

These tests pin the **observable contract** of the decorator so that
future per-adapter migrations have a deterministic API to target. Any
behavior change here is a deliberate API change and must update the
audit plan / E-3 follow-up doc accordingly.
"""

from __future__ import annotations

import pytest

from smc_core.resilient import resilient

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class FakeSleep:
    """Deterministic ``time.sleep`` stand-in that records every delay."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def constant_rng(value: float):
    """Return a callable that always returns ``value`` (kills jitter)."""

    def _rng() -> float:
        return value

    return _rng


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestArgumentValidation:
    def test_rejects_negative_retries(self):
        with pytest.raises(ValueError, match="retries"):
            resilient(retries=-1)

    def test_rejects_negative_base_delay(self):
        with pytest.raises(ValueError, match="base_delay"):
            resilient(base_delay=-0.1)

    def test_rejects_negative_max_delay(self):
        with pytest.raises(ValueError, match="max_delay"):
            resilient(max_delay=-1.0)

    def test_rejects_max_below_base(self):
        with pytest.raises(ValueError, match="max_delay must be >= base_delay"):
            resilient(base_delay=2.0, max_delay=1.0)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestSuccess:
    def test_first_call_succeeds_no_sleep(self):
        sleep = FakeSleep()

        @resilient(retries=3, sleep=sleep, rng=constant_rng(1.0))
        def f() -> int:
            return 42

        assert f() == 42
        assert sleep.calls == []

    def test_retry_then_success(self):
        sleep = FakeSleep()
        attempts: list[int] = []

        @resilient(retries=3, base_delay=1.0, sleep=sleep, rng=constant_rng(1.0))
        def f() -> str:
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("transient")
            return "ok"

        assert f() == "ok"
        assert len(attempts) == 3
        # Two delays, doubling: 1.0 then 2.0 (rng=1.0 → no jitter cut).
        assert sleep.calls == [1.0, 2.0]

    def test_kwargs_and_args_pass_through(self):
        @resilient(retries=0)
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(2, b=3) == 5

    def test_preserves_metadata(self):
        @resilient(retries=2)
        def documented():
            """My docstring."""

        assert documented.__name__ == "documented"
        assert documented.__doc__ == "My docstring."


# ---------------------------------------------------------------------------
# Retry / backoff semantics
# ---------------------------------------------------------------------------


class TestBackoff:
    def test_delays_double_until_max(self):
        sleep = FakeSleep()
        calls: list[int] = []

        @resilient(
            retries=4,
            base_delay=1.0,
            max_delay=4.0,
            sleep=sleep,
            rng=constant_rng(1.0),
        )
        def always_fail() -> None:
            calls.append(1)
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            always_fail()
        assert len(calls) == 5  # initial + 4 retries
        # Capped doubling: 1, 2, 4, 4 (max_delay reached).
        assert sleep.calls == [1.0, 2.0, 4.0, 4.0]

    def test_full_jitter_scales_with_rng(self):
        sleep = FakeSleep()

        @resilient(
            retries=2,
            base_delay=10.0,
            sleep=sleep,
            rng=constant_rng(0.25),
        )
        def fail() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            fail()
        # Each delay = capped * rng = 10 * 0.25 then 20 * 0.25.
        assert sleep.calls == [2.5, 5.0]

    def test_zero_base_delay_skips_sleep(self):
        sleep = FakeSleep()

        @resilient(
            retries=2,
            base_delay=0.0,
            max_delay=0.0,
            sleep=sleep,
            rng=constant_rng(1.0),
        )
        def fail() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            fail()
        # delay = 0 → no sleep call.
        assert sleep.calls == []


# ---------------------------------------------------------------------------
# Exception filtering
# ---------------------------------------------------------------------------


class TestExceptionFiltering:
    def test_unselected_exception_propagates_immediately(self):
        sleep = FakeSleep()
        calls: list[int] = []

        @resilient(
            retries=5,
            exceptions=(ValueError,),
            sleep=sleep,
            rng=constant_rng(1.0),
        )
        def fail() -> None:
            calls.append(1)
            raise TypeError("not a ValueError")

        with pytest.raises(TypeError):
            fail()
        # No retries — exception not in selected set.
        assert len(calls) == 1
        assert sleep.calls == []

    def test_selected_exception_subclass_retries(self):
        sleep = FakeSleep()
        calls: list[int] = []

        class CustomError(RuntimeError):
            pass

        @resilient(
            retries=2,
            base_delay=0.0,
            exceptions=(RuntimeError,),
            sleep=sleep,
            rng=constant_rng(1.0),
        )
        def fail() -> None:
            calls.append(1)
            raise CustomError("subclass should retry")

        with pytest.raises(CustomError):
            fail()
        assert len(calls) == 3  # initial + 2 retries


# ---------------------------------------------------------------------------
# Failure substitution
# ---------------------------------------------------------------------------


class TestOnFailure:
    def test_on_failure_value_substituted(self):
        @resilient(
            retries=1,
            base_delay=0.0,
            on_failure=lambda exc: f"fallback:{type(exc).__name__}",
            rng=constant_rng(1.0),
        )
        def fail() -> str:
            raise RuntimeError("boom")

        assert fail() == "fallback:RuntimeError"

    def test_on_failure_not_called_on_success(self):
        called: list[BaseException] = []

        @resilient(
            retries=1,
            on_failure=lambda exc: called.append(exc),
            rng=constant_rng(1.0),
        )
        def f() -> int:
            return 1

        assert f() == 1
        assert called == []


# ---------------------------------------------------------------------------
# Observation hook
# ---------------------------------------------------------------------------


class TestOnRetry:
    def test_on_retry_invoked_per_attempt(self):
        events: list[tuple[type, int, float]] = []
        sleep = FakeSleep()

        def hook(exc, attempt, delay):
            events.append((type(exc), attempt, delay))

        @resilient(
            retries=2,
            base_delay=1.0,
            on_retry=hook,
            sleep=sleep,
            rng=constant_rng(1.0),
        )
        def fail() -> None:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError):
            fail()
        # Two retries → two hook events.
        assert events == [(RuntimeError, 1, 1.0), (RuntimeError, 2, 2.0)]


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestIntrospection:
    def test_resilient_metadata_attached(self):
        @resilient(
            retries=4,
            base_delay=2.0,
            max_delay=10.0,
            exceptions=(ValueError, TypeError),
        )
        def f() -> None:
            pass

        meta = f.__resilient__  # type: ignore[attr-defined]
        assert meta == {
            "retries": 4,
            "base_delay": 2.0,
            "max_delay": 10.0,
            "exceptions": (ValueError, TypeError),
        }
