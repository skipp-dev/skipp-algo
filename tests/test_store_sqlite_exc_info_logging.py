"""Pin: SQLite retry decorator must surface root-cause tracebacks.

Found via SMC bug-hunt v2 phase 6 (Observability Symmetry).

The ``_retry_on_locked`` decorator in newsstack_fmp/store_sqlite.py
catches ``sqlite3.ProgrammingError`` (connection closed) and
``sqlite3.OperationalError`` (db locked, disk full, permission denied,
etc.). When the retry budget is exhausted the failure is logged via
``logger.error(...)`` and the original exception is re-raised.

The RED before fix: both ``logger.error`` calls omitted
``exc_info=True``, so the traceback that diagnoses *why* the underlying
SQLite primitive failed (PermissionError, disk full, lock contention)
is irretrievably lost from the log stream. Operations sees only the
short message and has to reconstruct the cause from OS-level traces.

This test asserts that ``exc_info=True`` is passed when the retry
budget is exhausted, so the actual root cause survives in the log.
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Any
from unittest.mock import patch

import pytest

from newsstack_fmp.store_sqlite import _retry_on_locked


class _Dummy:
    """Minimal stand-in for SqliteStore exposing only what the decorator needs."""

    def __init__(self, raises: type[Exception], *, reconnect_raises: type[Exception] | None = None) -> None:
        self._raises = raises
        self._reconnect_raises = reconnect_raises
        self.attempts = 0

    def _reconnect(self) -> None:
        if self._reconnect_raises is not None:
            raise self._reconnect_raises("simulated reconnect failure")

    @_retry_on_locked
    def _fn(self, *args: Any, **kwargs: Any) -> None:  # noqa: D401, ANN401
        self.attempts += 1
        raise self._raises("simulated SQLite primitive failure")


def _has_exc_info(record: logging.LogRecord) -> bool:
    return record.exc_info is not None


def test_reconnect_failure_logs_with_exc_info(caplog: pytest.LogCaptureFixture) -> None:
    """`_reconnect failed` log must carry exc_info so PermissionError, disk-full,
    and OS-level details survive in the log stream."""
    caplog.set_level(logging.ERROR, logger="newsstack_fmp.store_sqlite")

    # Patch sleep to keep the test fast.
    with patch("newsstack_fmp.store_sqlite.time.sleep", lambda *_: None):
        dummy = _Dummy(sqlite3.ProgrammingError, reconnect_raises=PermissionError)
        with pytest.raises(sqlite3.ProgrammingError):
            dummy._fn()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR and "_reconnect failed" in r.getMessage()]
    assert error_records, "expected at least one '_reconnect failed' ERROR log"
    assert any(_has_exc_info(r) for r in error_records), (
        "logger.error('_reconnect failed', ...) must include exc_info=True so the "
        "underlying PermissionError traceback survives — currently the root cause is lost."
    )


def test_operational_error_exhausted_logs_with_exc_info(caplog: pytest.LogCaptureFixture) -> None:
    """`SQLite OperationalError after N retries` log must carry exc_info so
    the underlying disk-full / locked-db cause survives."""
    caplog.set_level(logging.ERROR, logger="newsstack_fmp.store_sqlite")

    with patch("newsstack_fmp.store_sqlite.time.sleep", lambda *_: None):
        dummy = _Dummy(sqlite3.OperationalError)
        with pytest.raises(sqlite3.OperationalError):
            dummy._fn()

    error_records = [r for r in caplog.records if r.levelno == logging.ERROR and "OperationalError after" in r.getMessage()]
    assert error_records, "expected one 'OperationalError after N retries' ERROR log"
    assert any(_has_exc_info(r) for r in error_records), (
        "logger.error('SQLite OperationalError after %d retries ...', ...) must include "
        "exc_info=True so the underlying sqlite3.OperationalError traceback survives."
    )
