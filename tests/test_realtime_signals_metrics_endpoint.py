"""Tests for _collect_process_metrics() and the /metrics HTTP endpoint.

Covers:
- _collect_process_metrics() returns valid Prometheus text-format lines
  with the expected metric names and types.
- /metrics requires Bearer token when SIGNALS_INTERNAL_TOKEN is set.
- /metrics is accessible without token when SIGNALS_INTERNAL_TOKEN is unset.
- live_overlay_daemon._collect_process_metrics() returns expected metric names.
"""
from __future__ import annotations

import socket
import time
import urllib.request
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

import open_prep.realtime_signals as rs

# ---------------------------------------------------------------------------
# _collect_process_metrics() unit tests
# ---------------------------------------------------------------------------

class TestCollectProcessMetrics:
    def test_returns_string(self) -> None:
        result = rs._collect_process_metrics()
        assert isinstance(result, str)

    def test_contains_cpu_seconds(self) -> None:
        body = rs._collect_process_metrics()
        assert "signals_producer_process_cpu_seconds_total" in body

    def test_contains_resident_memory(self) -> None:
        body = rs._collect_process_metrics()
        assert "signals_producer_process_resident_memory_bytes" in body

    def test_contains_uptime(self) -> None:
        body = rs._collect_process_metrics()
        assert "signals_producer_process_uptime_seconds" in body

    def test_contains_gc_collections(self) -> None:
        body = rs._collect_process_metrics()
        assert "signals_producer_python_gc_collections_total" in body

    def test_contains_type_declarations(self) -> None:
        body = rs._collect_process_metrics()
        assert "# TYPE" in body

    def test_values_are_numeric(self) -> None:
        """Every non-comment, non-HELP, non-TYPE line must parse as 'name value'."""
        body = rs._collect_process_metrics()
        for line in body.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.rsplit(" ", 1)
            assert len(parts) == 2, f"Unexpected line format: {line!r}"
            float(parts[1])  # must be numeric


# ---------------------------------------------------------------------------
# live_overlay _collect_process_metrics() unit tests
# ---------------------------------------------------------------------------

class TestLiveOverlayCollectProcessMetrics:
    def test_returns_string(self) -> None:
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        result = _lo_metrics(startup_ts=time.time() - 10.0)
        assert isinstance(result, list)

    def test_contains_cpu(self) -> None:
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        lines = _lo_metrics(startup_ts=time.time() - 10.0)
        body = "\n".join(lines)
        assert "live_overlay_process_cpu_seconds_total" in body

    def test_contains_resident_memory(self) -> None:
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        lines = _lo_metrics(startup_ts=time.time() - 10.0)
        body = "\n".join(lines)
        assert "live_overlay_process_resident_memory_bytes" in body

    def test_contains_gc_collections(self) -> None:
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        lines = _lo_metrics(startup_ts=time.time() - 10.0)
        body = "\n".join(lines)
        assert "live_overlay_process_python_gc_collections_total" in body

    def test_contains_uptime_positive(self) -> None:
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        lines = _lo_metrics(startup_ts=time.time() - 5.0)
        body = "\n".join(lines)
        assert "live_overlay_process_uptime_seconds" in body


# ---------------------------------------------------------------------------
# /metrics HTTP endpoint — auth enforcement
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_server(port: int, env_overrides: dict[str, str], monkeypatch: Any) -> Any:
    """Start _start_telemetry_server on *port* with mocked telemetry."""
    for k, v in env_overrides.items():
        monkeypatch.setenv(k, v)

    telemetry = MagicMock()
    telemetry.snapshot.return_value = {}
    server = rs._start_telemetry_server(telemetry, port=port, host="127.0.0.1")
    return server


def _get(url: str, token: str | None = None) -> tuple[int, str]:
    req = urllib.request.Request(url)
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status, resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


class TestMetricsEndpointAuth:
    def test_accessible_without_token_when_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SIGNALS_INTERNAL_TOKEN is not set, /metrics is open."""
        monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
        port = _free_port()
        _start_server(port, {}, monkeypatch)
        status, body = _get(f"http://127.0.0.1:{port}/metrics")
        assert status == 200
        assert "signals_producer_process_cpu_seconds_total" in body

    def test_returns_401_without_token_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SIGNALS_INTERNAL_TOKEN is set, /metrics without token → 401."""
        port = _free_port()
        _start_server(port, {"SIGNALS_INTERNAL_TOKEN": "secret-abc"}, monkeypatch)
        status, _ = _get(f"http://127.0.0.1:{port}/metrics")
        assert status == 401

    def test_returns_401_with_wrong_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wrong Bearer token → 401."""
        port = _free_port()
        _start_server(port, {"SIGNALS_INTERNAL_TOKEN": "correct-token"}, monkeypatch)
        status, _ = _get(f"http://127.0.0.1:{port}/metrics", token="wrong-token")
        assert status == 401

    def test_returns_200_with_correct_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Correct Bearer token → 200 + Prometheus body."""
        port = _free_port()
        _start_server(port, {"SIGNALS_INTERNAL_TOKEN": "correct-token"}, monkeypatch)
        status, body = _get(f"http://127.0.0.1:{port}/metrics", token="correct-token")
        assert status == 200
        assert "signals_producer_process_cpu_seconds_total" in body


# ---------------------------------------------------------------------------
# Semantic readiness gauges
# ---------------------------------------------------------------------------

def test_extract_snapshot_epoch_parses_iso() -> None:
    ts = datetime(2026, 6, 28, 12, 0, 0, tzinfo=UTC).timestamp()
    assert rs._extract_snapshot_epoch({"generated_at": "2026-06-28T12:00:00+00:00"}) == ts


def test_extract_snapshot_epoch_parses_numeric() -> None:
    assert rs._extract_snapshot_epoch({"generated_at": 1751112000.0}) == 1751112000.0
    assert rs._extract_snapshot_epoch({"generated_at": 1751112000}) == 1751112000.0


def test_extract_snapshot_epoch_returns_zero_when_missing() -> None:
    assert rs._extract_snapshot_epoch({}) == 0.0
    assert rs._extract_snapshot_epoch(None) == 0.0


def test_collect_process_metrics_includes_semantic_readiness_gauges() -> None:
    engine = SimpleNamespace(
        _watchlist=[{"symbol": "AAPL"}],
        open_prep_snapshot_loaded=1.0,
        open_prep_snapshot_age_seconds=12.5,
        last_poll_success_epoch=1_700_000_000.0,
        last_poll_duration_seconds=0.123,
    )
    body = rs._collect_process_metrics(engine)
    assert "signals_producer_watchlist_symbols 1" in body
    assert "signals_producer_open_prep_snapshot_loaded 1.0" in body
    assert "signals_producer_open_prep_snapshot_age_seconds 12.5" in body
    assert "signals_producer_last_poll_age_seconds" in body
    assert "signals_producer_last_poll_duration_seconds 0.123" in body


def test_collect_process_metrics_defaults_last_poll_age_to_max_when_never_polled() -> None:
    engine = SimpleNamespace(
        _watchlist=[],
        open_prep_snapshot_loaded=0.0,
        open_prep_snapshot_age_seconds=0.0,
        last_poll_success_epoch=0.0,
        last_poll_duration_seconds=0.0,
    )
    body = rs._collect_process_metrics(engine)
    assert "signals_producer_last_poll_age_seconds 999999.0" in body


def test_readyz_returns_503_when_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
    telemetry = MagicMock()
    telemetry.snapshot.return_value = {}
    server = rs._start_telemetry_server(telemetry, port=port, host="127.0.0.1")
    try:
        status, body = _get(f"http://127.0.0.1:{port}/readyz")
        assert status == 503
        assert body.strip() == "not_ready"
    finally:
        server.shutdown()


def test_readyz_returns_200_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    port = _free_port()
    monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
    engine = SimpleNamespace(
        _watchlist=[{"symbol": "AAPL"}],
        open_prep_snapshot_loaded=1.0,
        last_poll_success_epoch=time.time(),
    )
    telemetry = MagicMock()
    telemetry.snapshot.return_value = {}
    server = rs._start_telemetry_server(telemetry, port=port, host="127.0.0.1", engine=engine)
    try:
        status, body = _get(f"http://127.0.0.1:{port}/readyz")
        assert status == 200
        assert body.strip() == "ready"
    finally:
        server.shutdown()
