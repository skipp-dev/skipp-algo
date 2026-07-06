"""State-machine and contract tests for live_overlay_daemon.compute loaders.

Focuses on cache TTL semantics, max_days edge cases, file fallback,
concurrent access, and the interaction between URL fetch and local snapshot.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from services.live_overlay_daemon import compute


@pytest.fixture(autouse=True)
def _reset_loader_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force every loader to perform a fresh fetch by clearing module caches."""
    monkeypatch.setattr(compute, "_news_cache", {})
    monkeypatch.setattr(compute, "_news_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_news_checked_at", 0.0)
    monkeypatch.setattr(compute, "_signals_cache", {})
    monkeypatch.setattr(compute, "_signals_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_signals_checked_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_cache", {})
    monkeypatch.setattr(compute, "_experiment_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_checked_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_history_cache", [])
    monkeypatch.setattr(compute, "_experiment_history_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_experiment_history_checked_at", 0.0)
    monkeypatch.setattr(compute, "_tradingview_credential_cache", {})
    monkeypatch.setattr(compute, "_tradingview_credential_loaded_at", 0.0)
    monkeypatch.setattr(compute, "_tradingview_credential_checked_at", 0.0)


# ---------------------------------------------------------------------------
# _parse_history_lines edge cases
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    lines=st.lists(
        st.dictionaries(
            st.text(min_size=1),
            st.one_of(
                st.text(),
                st.integers(),
                st.floats(allow_nan=True, allow_infinity=True),
                st.booleans(),
            ),
        ),
        min_size=0,
        max_size=30,
    ),
    max_days=st.integers(min_value=0, max_value=50),
)
def test_parse_history_lines_jsonl_variety(lines: list[dict[str, Any]], max_days: int) -> None:
    """Any JSONL-like input must not crash; captured_at presence controls inclusion."""
    text = "\n".join(json.dumps(line) for line in lines)
    rows = compute._parse_history_lines(text, max_days)
    assert isinstance(rows, list)
    assert len(rows) <= max_days or max_days <= 0
    assert all(_captured_at_is_present(r) for r in rows)


def _captured_at_is_present(row: dict[str, Any]) -> bool:
    return compute._has_captured_at(row.get("captured_at"))


def test_parse_history_lines_max_days_zero_returns_empty() -> None:
    body = '\n{"captured_at": 100}\n{"captured_at": 200}\n'
    assert compute._parse_history_lines(body, max_days=0) == []


def test_parse_history_lines_max_days_negative_returns_empty() -> None:
    body = '\n{"captured_at": 100}\n{"captured_at": 200}\n'
    assert compute._parse_history_lines(body, max_days=-5) == []


def test_parse_history_lines_keeps_zero_timestamp() -> None:
    """A captured_at of 0 is a valid numeric timestamp and must NOT be treated
    as missing."""
    body = '{"captured_at": 0, "v": 1}\n{"captured_at": 1, "v": 2}\n'
    rows = compute._parse_history_lines(body, max_days=10)
    assert len(rows) == 2
    assert rows[0]["captured_at"] == 0


# ---------------------------------------------------------------------------
# _load_experiment_history snapshot fallback contract
# ---------------------------------------------------------------------------


def test_experiment_history_persists_and_reloads(tmp_path, monkeypatch) -> None:
    """A successful URL fetch must persist the JSONL body; a subsequent load
    without URL must read the persisted file."""
    dest = tmp_path / "experiment_history.jsonl"
    body = '\n{"captured_at": "2026-04-20T00:00:00Z", "v": 1}\n{"captured_at": "2026-04-21T00:00:00Z", "v": 2}\n'

    monkeypatch.setattr(compute.config, "experiment_history_url", lambda: "https://example.test/history")
    monkeypatch.setattr(compute.config, "experiment_history_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "experiment_history_path", lambda: dest)
    monkeypatch.setattr(compute.config, "experiment_cache_ttl_secs", lambda: 0)
    monkeypatch.setattr(compute.config, "experiment_history_max_days", lambda: 10)
    monkeypatch.setattr(compute, "_fetch_experiment_url", lambda url, token, **kw: body)

    first = compute._load_experiment_history()
    assert len(first) == 2
    assert dest.exists()

    # Second call with URL disabled must read the persisted file, not refetch.
    monkeypatch.setattr(compute.config, "experiment_history_url", lambda: "")
    compute._experiment_history_loaded_at = 0.0
    compute._experiment_history_checked_at = 0.0
    second = compute._load_experiment_history()
    assert second == first


# ---------------------------------------------------------------------------
# TTL / cache semantics
# ---------------------------------------------------------------------------


def test_experiment_history_ttl_returns_cached_copy(monkeypatch) -> None:
    dest = Path("/nonexistent/history.jsonl")
    monkeypatch.setattr(compute.config, "experiment_history_url", lambda: "")
    monkeypatch.setattr(compute.config, "experiment_history_path", lambda: dest)
    monkeypatch.setattr(compute.config, "experiment_cache_ttl_secs", lambda: 60)
    monkeypatch.setattr(compute.config, "experiment_history_max_days", lambda: 10)

    compute._experiment_history_cache = [{"captured_at": 100, "v": 1}]
    compute._experiment_history_loaded_at = time.monotonic()
    compute._experiment_history_checked_at = time.monotonic()

    result = compute._load_experiment_history()
    assert result == [{"captured_at": 100, "v": 1}]
    # Must return a defensive copy, not the internal list.
    result.append({"captured_at": 200, "v": 2})
    assert compute._experiment_history_cache == [{"captured_at": 100, "v": 1}]


# ---------------------------------------------------------------------------
# Concurrent access
# ---------------------------------------------------------------------------


def test_experiment_history_thread_safety(tmp_path, monkeypatch) -> None:
    """Parallel loads must not corrupt the shared cache or crash."""
    dest = tmp_path / "experiment_history.jsonl"
    body = '\n'.join(f'{{"captured_at": {i + 1}, "v": {i + 1}}}' for i in range(50)) + "\n"
    monkeypatch.setattr(compute.config, "experiment_history_url", lambda: "https://example.test/history")
    monkeypatch.setattr(compute.config, "experiment_history_url_token", lambda: "")
    monkeypatch.setattr(compute.config, "experiment_history_path", lambda: dest)
    monkeypatch.setattr(compute.config, "experiment_cache_ttl_secs", lambda: 0)
    monkeypatch.setattr(compute.config, "experiment_history_max_days", lambda: 100)
    monkeypatch.setattr(compute, "_fetch_experiment_url", lambda url, token, **kw: body)

    results: list[list[dict[str, Any]]] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(compute._load_experiment_history())
        except BaseException as exc:  # pragma: no cover
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(results) == 20
    for r in results:
        assert len(r) == 50


# ---------------------------------------------------------------------------
# _signals_service_url_to_full + _is_valid_service_url integration
# ---------------------------------------------------------------------------


@settings(max_examples=1000)
@given(base=st.text())
def test_valid_service_url_implies_url_to_full_is_valid(base: str) -> None:
    """If _is_valid_service_url accepts a base, _signals_service_url_to_full
    must produce a non-empty endpoint containing /signals.json."""
    if compute._is_valid_service_url(base):
        endpoint = compute._signals_service_url_to_full(base)
        assert endpoint
        assert "/signals.json" in endpoint
