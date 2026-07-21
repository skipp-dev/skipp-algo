"""Prometheus and health-contract tests for A0-Fast telemetry."""

from __future__ import annotations

from http import HTTPStatus

from open_prep.a0_stream_buffer import BufferSnapshot
from services.a0_fast_detector.telemetry import A0FastTelemetry


def _buffer(*, dirty: tuple[str, ...] = ()) -> BufferSnapshot:
    return BufferSnapshot(
        capacity=100,
        depth=4,
        high_watermark=8,
        dropped_total=2,
        resync_required_symbols=dirty,
        closed=False,
        close_reason=None,
    )


def test_metrics_expose_bounded_queue_disconnect_recovery_and_usage() -> None:
    telemetry = A0FastTelemetry(record_wire_bytes=104)
    telemetry.set_connected(True)
    telemetry.record_received()
    telemetry.record_rejected("invalid_record")
    telemetry.record_rejected("unmapped_symbol")
    telemetry.record_processed()
    telemetry.record_queue_drop()
    telemetry.record_queue_drop()
    telemetry.record_recovery("recovered", historical_bars=20)
    telemetry.record_decision()
    telemetry.set_buffer(_buffer())
    text = telemetry.render_prometheus()
    assert "a0_fast_stream_connected 1" in text
    assert "a0_fast_queue_capacity 100" in text
    assert "a0_fast_queue_dropped_total 2" in text
    assert 'a0_fast_records_rejected_total{reason="invalid_record"} 1' in text
    assert 'a0_fast_records_rejected_total{reason="unmapped_symbol"} 1' in text
    assert "a0_fast_wire_bytes_total 104" in text
    assert 'a0_fast_recoveries_total{status="recovered"} 1' in text
    assert telemetry.health_status() == (HTTPStatus.OK, "ok")


def test_health_fails_for_disconnect_or_pending_resync() -> None:
    telemetry = A0FastTelemetry()
    assert telemetry.health_status() == (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "disconnected",
    )
    telemetry.set_connected(True)
    telemetry.require_resync("NVDA")
    telemetry.acknowledge_resync("NVDA")
    telemetry.set_buffer(_buffer(dirty=("NVDA",)))
    assert telemetry.health_status() == (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "resync_required",
    )
    telemetry.record_disconnect("socket closed")
    text = telemetry.render_prometheus()
    assert "a0_fast_disconnects_total 1" in text
    assert 'reason="socket_closed"' in text
