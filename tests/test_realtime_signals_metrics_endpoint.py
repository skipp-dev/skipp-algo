"""Tests for _collect_process_metrics() and the /metrics HTTP endpoint.

Covers:
- _collect_process_metrics() returns valid Prometheus text-format lines
  with the expected metric names and types.
- /metrics requires Bearer token when SIGNALS_INTERNAL_TOKEN is set.
- /metrics is accessible without token when SIGNALS_INTERNAL_TOKEN is unset.
- live_overlay_daemon._collect_process_metrics() returns expected metric names.
"""
from __future__ import annotations

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

    def test_build_info_reads_railway_commit(self, monkeypatch) -> None:
        # The deployed commit must be answerable from Grafana so a no-op
        # redeploy (old image re-run) is visible instead of silent.
        from services.live_overlay_daemon.metrics import _collect_process_metrics as _lo_metrics
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "4450b1049deadbeef")
        monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")
        body = "\n".join(_lo_metrics(startup_ts=time.time() - 5.0))
        assert 'live_overlay_build_info{commit="4450b1049deadbeef",branch="main"} 1' in body

    def test_build_info_defaults_to_unknown(self, monkeypatch) -> None:
        # No Railway env AND no baked stamp -> the gauge still emits a
        # non-empty label, never a blank commit.
        import services.live_overlay_daemon.metrics as metrics_mod
        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
        monkeypatch.delenv("RAILWAY_GIT_BRANCH", raising=False)
        monkeypatch.setattr(metrics_mod, "_read_build_stamp", lambda: ("", ""))
        body = "\n".join(metrics_mod._collect_process_metrics(startup_ts=time.time() - 5.0))
        assert 'live_overlay_build_info{commit="unknown",branch="unknown"} 1' in body

    def test_build_info_reads_stamp_when_env_absent(self, monkeypatch) -> None:
        # `railway up` sets no RAILWAY_GIT_* vars; the deploy wrapper bakes the
        # SHA into build_stamp.txt and the daemon reads it as the fallback.
        import services.live_overlay_daemon.metrics as metrics_mod
        monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
        monkeypatch.delenv("RAILWAY_GIT_BRANCH", raising=False)
        monkeypatch.setattr(metrics_mod, "_read_build_stamp", lambda: ("abc123def456", "feat/x"))
        body = "\n".join(metrics_mod._collect_process_metrics(startup_ts=time.time() - 5.0))
        assert 'live_overlay_build_info{commit="abc123def456",branch="feat/x"} 1' in body

    def test_build_info_env_wins_over_stamp(self, monkeypatch) -> None:
        # A GitHub-connected deploy (RAILWAY_GIT_* present) is authoritative
        # over any baked stamp.
        import services.live_overlay_daemon.metrics as metrics_mod
        monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "envsha")
        monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")
        monkeypatch.setattr(metrics_mod, "_read_build_stamp", lambda: ("stampsha", "stampbranch"))
        body = "\n".join(metrics_mod._collect_process_metrics(startup_ts=time.time() - 5.0))
        assert 'live_overlay_build_info{commit="envsha",branch="main"} 1' in body

    def test_read_build_stamp_placeholder_is_empty(self) -> None:
        # The committed placeholder ("unknown") reads as empty so the gauge
        # shows "unknown", not the literal word as a commit SHA.
        from services.live_overlay_daemon.metrics import _read_build_stamp
        assert _read_build_stamp() == ("", "")


# ---------------------------------------------------------------------------
# /metrics HTTP endpoint — auth enforcement
# ---------------------------------------------------------------------------

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
        server = _start_server(0, {}, monkeypatch)
        if server is None:
            return
        try:
            port = int(server.server_port)
            status, body = _get(f"http://127.0.0.1:{port}/metrics")
            assert status == 200
            assert "signals_producer_process_cpu_seconds_total" in body
        finally:
            server.shutdown()

    def test_returns_401_without_token_when_env_var_set(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When SIGNALS_INTERNAL_TOKEN is set, /metrics without token → 401."""
        server = _start_server(0, {"SIGNALS_INTERNAL_TOKEN": "secret-abc"}, monkeypatch)
        if server is None:
            return
        try:
            port = int(server.server_port)
            status, _ = _get(f"http://127.0.0.1:{port}/metrics")
            assert status == 401
        finally:
            server.shutdown()

    def test_returns_401_with_wrong_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Wrong Bearer token → 401."""
        server = _start_server(0, {"SIGNALS_INTERNAL_TOKEN": "correct-token"}, monkeypatch)
        if server is None:
            return
        try:
            port = int(server.server_port)
            status, _ = _get(f"http://127.0.0.1:{port}/metrics", token="wrong-token")
            assert status == 401
        finally:
            server.shutdown()

    def test_returns_200_with_correct_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Correct Bearer token → 200 + Prometheus body."""
        server = _start_server(0, {"SIGNALS_INTERNAL_TOKEN": "correct-token"}, monkeypatch)
        if server is None:
            return
        try:
            port = int(server.server_port)
            status, body = _get(f"http://127.0.0.1:{port}/metrics", token="correct-token")
            assert status == 200
            assert "signals_producer_process_cpu_seconds_total" in body
        finally:
            server.shutdown()


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
    monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
    telemetry = MagicMock()
    telemetry.snapshot.return_value = {}
    server = rs._start_telemetry_server(telemetry, port=0, host="127.0.0.1")
    if server is None:
        return
    try:
        port = int(server.server_port)
        status, body = _get(f"http://127.0.0.1:{port}/readyz")
        assert status == 503
        assert body.strip().startswith("not_ready") or "engine not initialised" in body.strip()
    finally:
        server.shutdown()


def test_readyz_returns_200_when_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SIGNALS_INTERNAL_TOKEN", raising=False)
    engine = SimpleNamespace(
        _watchlist=[{"symbol": "AAPL"}],
        open_prep_snapshot_loaded=1.0,
        last_poll_success_epoch=time.time(),
    )
    telemetry = MagicMock()
    telemetry.snapshot.return_value = {}
    server = rs._start_telemetry_server(telemetry, port=0, host="127.0.0.1", engine=engine)
    if server is None:
        return
    try:
        port = int(server.server_port)
        status, body = _get(f"http://127.0.0.1:{port}/readyz")
        assert status == 200
        assert body.strip() == "ready"
    finally:
        server.shutdown()


# ---------------------------------------------------------------------------
# _mark_poll_success timing contract
# ---------------------------------------------------------------------------

def test_mark_poll_success_sets_duration_before_epoch() -> None:
    """Duration and success epoch must be recorded in one atomic helper."""
    engine = rs.RealtimeEngine()
    engine._watchlist = [{"symbol": "AAPL"}]
    start = time.monotonic() - 0.05
    engine._mark_poll_success(start)
    assert engine.last_poll_duration >= 0.05
    assert engine.last_poll_duration_seconds == engine.last_poll_duration
    assert engine.last_poll_success_epoch > 0


def test_collect_process_metrics_uses_last_poll_duration_seconds() -> None:
    """The duration gauge must reflect the engine\'s last_poll_duration_seconds."""
    engine = SimpleNamespace(
        _watchlist=[{"symbol": "AAPL"}],
        open_prep_snapshot_loaded=1.0,
        open_prep_snapshot_age_seconds=0.0,
        last_poll_success_epoch=time.time(),
        last_poll_duration_seconds=2.5,
    )
    body = rs._collect_process_metrics(engine)
    assert "signals_producer_last_poll_duration_seconds 2.500" in body


# ---------------------------------------------------------------------------
# H3 (2026-07-08): FMP usage counters — the 24/7 producer is the single
# largest FMP consumer and previously ran past every bandwidth-quota check.
# ---------------------------------------------------------------------------


class TestFmpUsageCounters:
    @staticmethod
    def _engine(client: Any) -> SimpleNamespace:
        return SimpleNamespace(
            last_poll_success_epoch=time.time(),
            last_poll_duration_seconds=0.5,
            _watchlist=["AAPL"],
            open_prep_snapshot_loaded=1,
            open_prep_snapshot_age_seconds=10.0,
            _client=client,
        )

    def test_exposes_fmp_totals_when_client_exists(self) -> None:
        class _FakeClient:
            def get_endpoint_usage_stats(self) -> dict[str, dict[str, int]]:
                return {
                    "/stable/quote": {"calls": 7, "errors": 1, "empty_responses": 0, "response_bytes": 1234},
                    "/stable/profile": {"calls": 3, "errors": 0, "empty_responses": 0, "response_bytes": 766},
                }

        body = rs._collect_process_metrics(self._engine(_FakeClient()))
        assert "signals_producer_fmp_requests_total 10" in body
        assert "signals_producer_fmp_request_errors_total 1" in body
        assert "signals_producer_fmp_response_bytes_total 2000" in body
        assert 'signals_producer_fmp_endpoint_requests_total{endpoint="/stable/quote"} 7' in body
        assert 'signals_producer_fmp_endpoint_errors_total{endpoint="/stable/quote"} 1' in body
        assert 'signals_producer_fmp_endpoint_response_bytes_total{endpoint="/stable/profile"} 766' in body
        assert "signals_producer_avg_volume_missing_symbols 0" in body

    def test_fmp_counters_absent_without_client(self) -> None:
        """Lazy client not yet created (no key / never polled) — no series,
        no crash."""
        body = rs._collect_process_metrics(self._engine(None))
        assert "fmp_requests_total" not in body

    def test_fmp_client_bucket_accumulates_response_bytes(self) -> None:
        """The macro.py side of H3: _request_once feeds response_bytes into
        the per-endpoint bucket that /metrics sums up."""
        from open_prep.macro import FMPClient

        client = FMPClient(api_key="k")
        client._record_endpoint_event("/stable/quote", calls=1, response_bytes=100)
        client._record_endpoint_event("/stable/quote", response_bytes=50)
        stats = client.get_endpoint_usage_stats()
        assert stats["/stable/quote"]["response_bytes"] == 150
        assert stats["/stable/quote"]["calls"] == 1


def test_collect_metrics_data_stale_is_market_gated() -> None:
    """last_data_age / data_stale expose data-freshness (vs loop-liveness):
    data_stale=1 only when the market is open AND no non-empty fetch for
    > DATA_STALL_SECONDS, so a market-hours FMP outage is visible even though
    last_poll_age stays ~0. The renderer reads the engine's cached
    _in_market_hours flag (set in poll_once) — it must NOT call the raising
    _is_within_market_hours() probe, so this test never monkeypatches it."""
    import time as _t
    import types

    def _engine(last_data_epoch: float, *, in_market: bool) -> types.SimpleNamespace:
        return types.SimpleNamespace(
            last_poll_success_epoch=_t.time(),
            last_poll_duration_seconds=0.1,
            open_prep_snapshot_loaded=1,
            open_prep_snapshot_age_seconds=10.0,
            _watchlist=[],
            _client=None,
            _last_data_epoch=last_data_epoch,
            _in_market_hours=in_market,
        )

    now = _t.time()
    # market OPEN + fresh data → not stale
    body = rs._collect_process_metrics(_engine(now, in_market=True))
    assert "signals_producer_data_stale 0" in body
    assert "signals_producer_last_data_age_seconds" in body

    # market OPEN + data older than the stall budget → stale
    body = rs._collect_process_metrics(_engine(now - rs.DATA_STALL_SECONDS - 60, in_market=True))
    assert "signals_producer_data_stale 1" in body

    # market CLOSED + same stale data → NOT flagged (empty off-hours is normal)
    body = rs._collect_process_metrics(_engine(now - rs.DATA_STALL_SECONDS - 60, in_market=False))
    assert "signals_producer_data_stale 0" in body

    # missing flag (old engine / pre-first-poll) defaults to not-in-market → 0
    eng = _engine(now - rs.DATA_STALL_SECONDS - 60, in_market=True)
    del eng._in_market_hours
    assert "signals_producer_data_stale 0" in rs._collect_process_metrics(eng)
