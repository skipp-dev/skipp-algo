"""Tests for scripts/databento_safe_fetch.py (F-V4-E1).

We monkeypatch a fake Databento client so the test suite never imports the
real ``databento`` package.  The helper's contract is exception-classification
by string-match, so the fakes just raise exceptions whose messages match the
documented markers.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load module via importlib so we don't require scripts/ on sys.path.
_HERE = Path(__file__).resolve().parent
_MODULE_PATH = _HERE.parent / "scripts" / "databento_safe_fetch.py"
_spec = importlib.util.spec_from_file_location("databento_safe_fetch", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["databento_safe_fetch"] = _module  # required if dataclasses used
_spec.loader.exec_module(_module)

safe_get_range = _module.safe_get_range
STATUS_OK = _module.STATUS_OK
STATUS_SKIPPED_DATA_AFTER_END = _module.STATUS_SKIPPED_DATA_AFTER_END
STATUS_SKIPPED_OTHER_422 = _module.STATUS_SKIPPED_OTHER_422


class _FakeTimeseries:
    def __init__(self, behavior):
        self._behavior = behavior

    def get_range(self, **_kw):
        if isinstance(self._behavior, Exception):
            raise self._behavior
        return self._behavior


class _FakeClient:
    def __init__(self, behavior):
        self.timeseries = _FakeTimeseries(behavior)


def test_safe_get_range_returns_store_on_success():
    sentinel = object()
    client = _FakeClient(sentinel)
    store, status = safe_get_range(
        client,
        dataset="DBEQ.BASIC",
        schema="ohlcv-1d",
        symbols=["AAPL"],
        start="2026-05-01T00:00:00Z",
        end="2026-05-02T00:00:00Z",
    )
    assert store is sentinel
    assert status == STATUS_OK


def test_safe_get_range_swallows_data_after_end():
    """Databento HTTP 422 with `data_start_after_available_end` -> skipped, no raise."""
    client = _FakeClient(
        RuntimeError(
            "BentoClientError: HTTP 422 data_start_after_available_end "
            "(start 2026-05-01T15:30:00Z is after the available end "
            "2026-04-30T20:00:00Z for dataset DBEQ.BASIC)"
        )
    )
    store, status = safe_get_range(
        client,
        dataset="DBEQ.BASIC",
        schema="ohlcv-1d",
        symbols=["AAPL"],
        start="2026-05-01T15:30:00Z",
        end="2026-05-01T16:30:00Z",
    )
    assert store is None
    assert status == STATUS_SKIPPED_DATA_AFTER_END


def test_safe_get_range_classifies_generic_422():
    """Generic 422 (without data-after-end marker) -> skipped_other_422, no raise."""
    client = _FakeClient(
        RuntimeError("BentoClientError: HTTP 422 invalid symbol set")
    )
    store, status = safe_get_range(
        client,
        dataset="DBEQ.BASIC",
        schema="ohlcv-1d",
        symbols=["???"],
        start="2026-05-01T00:00:00Z",
        end="2026-05-02T00:00:00Z",
    )
    assert store is None
    assert status == STATUS_SKIPPED_OTHER_422


def test_safe_get_range_reraises_unclassified():
    """Network/auth/etc. errors must continue to fail loudly."""
    client = _FakeClient(ConnectionError("connection refused"))
    with pytest.raises(ConnectionError):
        safe_get_range(
            client,
            dataset="DBEQ.BASIC",
            schema="ohlcv-1d",
            symbols=["AAPL"],
            start="2026-05-01T00:00:00Z",
            end="2026-05-02T00:00:00Z",
        )


def test_safe_get_range_emits_actions_warning(monkeypatch, capsys):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    client = _FakeClient(
        RuntimeError("HTTP 422 data_start_after_available_end ...")
    )
    _store, status = safe_get_range(
        client,
        dataset="X",
        schema="ohlcv-1d",
        symbols=["A"],
        start="s",
        end="e",
    )
    assert status == STATUS_SKIPPED_DATA_AFTER_END
    out = capsys.readouterr().out
    assert "::warning::" in out
    assert "Databento data not yet available" in out
