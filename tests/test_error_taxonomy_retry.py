from __future__ import annotations

import pytest

from open_prep.error_taxonomy import retry


def test_retry_attempts_zero_raises_without_calling_function() -> None:
    calls = 0

    @retry(attempts=0)
    def should_not_run() -> str:
        nonlocal calls
        calls += 1
        return "unexpected"

    with pytest.raises(ValueError, match="attempts must be >= 1"):
        should_not_run()

    assert calls == 0


def test_retry_attempts_negative_raises_without_calling_function() -> None:
    calls = 0

    @retry(attempts=-2)
    def should_not_run() -> str:
        nonlocal calls
        calls += 1
        return "unexpected"

    with pytest.raises(ValueError, match="attempts must be >= 1"):
        should_not_run()

    assert calls == 0


def test_retry_exhaustion_raises_last_exception(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr("open_prep.error_taxonomy.time.sleep", sleeps.append)

    @retry(attempts=3, backoff=2.0, jitter_pct=0.0, retryable_exceptions=(RuntimeError,))
    def always_fails() -> None:
        nonlocal calls
        calls += 1
        raise RuntimeError(f"boom-{calls}")

    with pytest.raises(RuntimeError, match="boom-3"):
        always_fails()

    assert calls == 3
    assert sleeps == [1.0, 2.0]


def test_retry_success_after_two_failures(monkeypatch) -> None:
    calls = 0
    sleeps: list[float] = []
    monkeypatch.setattr("open_prep.error_taxonomy.time.sleep", sleeps.append)

    @retry(attempts=3, backoff=2.0, jitter_pct=0.0, retryable_exceptions=(RuntimeError,))
    def eventually_succeeds() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("try again")
        return "ok"

    assert eventually_succeeds() == "ok"
    assert calls == 3
    assert sleeps == [1.0, 2.0]


def test_retry_only_catches_configured_exceptions(monkeypatch) -> None:
    calls = 0
    monkeypatch.setattr("open_prep.error_taxonomy.time.sleep", lambda _seconds: None)

    @retry(attempts=3, retryable_exceptions=(RuntimeError,))
    def raises_unconfigured_exception() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("not retryable")

    with pytest.raises(ValueError, match="not retryable"):
        raises_unconfigured_exception()

    assert calls == 1


def test_retry_callback_failure_does_not_abort(monkeypatch) -> None:
    calls = 0
    callback_attempts: list[int] = []
    monkeypatch.setattr("open_prep.error_taxonomy.time.sleep", lambda _seconds: None)

    def on_retry(attempt: int, _exc: Exception) -> None:
        callback_attempts.append(attempt)
        raise RuntimeError("callback failed")

    @retry(attempts=2, jitter_pct=0.0, retryable_exceptions=(RuntimeError,), on_retry=on_retry)
    def succeeds_after_callback_failure() -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("transient")
        return "ok"

    assert succeeds_after_callback_failure() == "ok"
    assert calls == 2
    assert callback_attempts == [1]
