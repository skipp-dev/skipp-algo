"""Tests for ``open_prep.macro._is_permanent_feature_failure`` /
``_log_feature_unavailable_once`` permanent-vs-transient discipline.

Pins the contract Copilot flagged on PR #364: 408/429/5xx must NOT be
deduped via once-per-process INFO (otherwise sustained outages go silent
after the first WARN), while truly permanent surfaces (401/403/404/410,
``UpstreamPayloadError``, deterministic parse errors) MUST be deduped to
avoid log-flooding the on-call dashboard.
"""
from __future__ import annotations

import logging

import pytest

from open_prep import macro as _macro_mod

# Surface the helpers under short names for readability.
_classify = _macro_mod._is_permanent_feature_failure
_log = _macro_mod._log_feature_unavailable_once
UpstreamPayloadError = _macro_mod.UpstreamPayloadError


# ---------------------------------------------------------------------------
# _is_permanent_feature_failure: permanent codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["400", "401", "403", "404", "410", "418", "451"],
)
def test_classifier_permanent_4xx(code: str) -> None:
    exc = RuntimeError(
        f"FMP API HTTP {code} on /stable/foo: permanent failure"
    )
    assert _classify(exc) is True, (
        f"HTTP {code} must be classified as permanent so on-call doesn't "
        f"get log-flooded by deterministic auth/missing/retired errors."
    )


# ---------------------------------------------------------------------------
# _is_permanent_feature_failure: transient codes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "code",
    ["408", "429", "500", "502", "503", "504"],
)
def test_classifier_transient_4xx_5xx(code: str) -> None:
    exc = RuntimeError(
        f"FMP API HTTP {code} on /stable/foo: rate limit / outage"
    )
    assert _classify(exc) is False, (
        f"HTTP {code} must be classified as transient so sustained "
        f"outages stay visible (every occurrence WARNs)."
    )


def test_classifier_circuit_open_is_transient() -> None:
    exc = RuntimeError("FMP API circuit open for /stable/foo")
    assert _classify(exc) is False


def test_classifier_network_error_is_transient() -> None:
    exc = RuntimeError("FMP API network error on /stable/foo: timeout")
    assert _classify(exc) is False


def test_classifier_retries_exhausted_is_transient() -> None:
    exc = RuntimeError("FMP API request exhausted retries on /stable/foo")
    assert _classify(exc) is False


# ---------------------------------------------------------------------------
# _is_permanent_feature_failure: payload + None
# ---------------------------------------------------------------------------


def test_classifier_upstream_payload_error_is_permanent() -> None:
    assert _classify(UpstreamPayloadError("HTML on /stable/foo")) is True


def test_classifier_none_is_permanent_for_legacy_callers() -> None:
    assert _classify(None) is True


def test_classifier_unknown_runtime_error_is_permanent() -> None:
    # Schema drift / parser bug — deterministic, not retry-worthy.
    assert _classify(RuntimeError("payload missing field 'x'")) is True


# ---------------------------------------------------------------------------
# _log_feature_unavailable_once: dedup behaviour
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_dedupe_set():
    """Each test starts with a clean ``_FMP_FEATURE_UNAVAILABLE_LOGGED``
    so dedupe state from one test can't leak into another."""
    _macro_mod._FMP_FEATURE_UNAVAILABLE_LOGGED.clear()
    yield
    _macro_mod._FMP_FEATURE_UNAVAILABLE_LOGGED.clear()


def test_log_permanent_dedup_once(caplog: pytest.LogCaptureFixture) -> None:
    exc = RuntimeError("FMP API HTTP 404 on /stable/retired: gone")
    with caplog.at_level(logging.INFO, logger=_macro_mod.logger.name):
        _log("stable/retired", "feature unavailable", exc=exc)
        _log("stable/retired", "feature unavailable", exc=exc)
        _log("stable/retired", "feature unavailable", exc=exc)
    # Only ONE INFO record.
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1, (
        f"permanent should dedup to one INFO; got {len(info_records)}: "
        f"{[r.getMessage() for r in info_records]}"
    )


def test_log_transient_warns_every_time(caplog: pytest.LogCaptureFixture) -> None:
    exc = RuntimeError("FMP API HTTP 429 on /stable/foo: rate limit")
    with caplog.at_level(logging.WARNING, logger=_macro_mod.logger.name):
        _log("stable/foo", "feature unavailable", exc=exc)
        _log("stable/foo", "feature unavailable", exc=exc)
        _log("stable/foo", "feature unavailable", exc=exc)
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warn_records) == 3, (
        f"transient must WARN every occurrence; got {len(warn_records)}"
    )
    # Each WARN must include the exception type and the underlying message.
    for record in warn_records:
        msg = record.getMessage()
        assert "RuntimeError" in msg
        assert "429" in msg
        assert "transient" in msg


def test_log_permanent_includes_exc_in_message(caplog: pytest.LogCaptureFixture) -> None:
    """Forensic context: the once-only INFO must carry the exception
    type/message so the on-call doesn't have to dig through stack
    traces to know WHY the feature is marked unavailable."""
    exc = RuntimeError("FMP API HTTP 401 on /stable/secret: missing key")
    with caplog.at_level(logging.INFO, logger=_macro_mod.logger.name):
        _log("stable/secret", "feature unavailable", exc=exc)
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1
    msg = info_records[0].getMessage()
    assert "RuntimeError" in msg
    assert "401" in msg
    assert "permanent" in msg


def test_log_legacy_call_without_exc_dedupes(caplog: pytest.LogCaptureFixture) -> None:
    """Backwards compatibility: callers that don't pass ``exc=`` still
    get the original once-per-process INFO behaviour."""
    with caplog.at_level(logging.INFO, logger=_macro_mod.logger.name):
        _log("stable/legacy", "feature unavailable")
        _log("stable/legacy", "feature unavailable")
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) == 1


def test_log_transient_then_permanent_independent_keys(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A 429 burst on feature A must not poison the dedupe set for
    feature B's permanent 404."""
    transient = RuntimeError("FMP API HTTP 429 on /stable/A: throttled")
    permanent = RuntimeError("FMP API HTTP 404 on /stable/B: retired")
    with caplog.at_level(logging.INFO, logger=_macro_mod.logger.name):
        _log("stable/A", "A unavailable", exc=transient)
        _log("stable/A", "A unavailable", exc=transient)
        _log("stable/B", "B unavailable", exc=permanent)
        _log("stable/B", "B unavailable", exc=permanent)
    warn_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(warn_records) == 2  # both transient calls logged
    assert len(info_records) == 1  # permanent deduped
