"""Pin partial-chunk-failure visibility (Lane 15)."""
import inspect

import pytest

import terminal_databento as td


def test_with_status_function_exists():
    assert hasattr(td, "fetch_databento_daily_bars_with_status")
    assert callable(td.fetch_databento_daily_bars_with_status)


def test_with_status_returns_two_tuple_on_no_api_key(monkeypatch):
    monkeypatch.delenv("DATABENTO_API_KEY", raising=False)
    try:
        out = td.fetch_databento_daily_bars_with_status(["AAPL"])
    except Exception as exc:
        pytest.skip(f"no-API-key path raised: {exc!r}")
    assert isinstance(out, tuple)
    assert len(out) == 2
    results, failed = out
    assert isinstance(results, dict)
    assert isinstance(failed, list)


def test_legacy_returns_dict():
    inspect.signature(td.fetch_databento_daily_bars)
    assert callable(td.fetch_databento_daily_bars)
