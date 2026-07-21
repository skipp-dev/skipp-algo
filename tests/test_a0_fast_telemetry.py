"""Prometheus and health-contract tests for A0-Fast telemetry."""

from __future__ import annotations

from http import HTTPStatus
from types import SimpleNamespace

from open_prep.a0_stream_buffer import BufferSnapshot
from open_prep.pre_a0_model import ModelStatus, ShadowScore
from open_prep.pre_a0_telemetry import PreA0Telemetry
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


def test_health_rejects_connected_source_that_never_processes_records() -> None:
    telemetry = A0FastTelemetry()
    telemetry.set_connected(True)
    for _ in range(10):
        telemetry.record_received()

    assert telemetry.health_status() == (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "no_records_processed",
    )


def test_evidence_readiness_requires_inference_and_persisted_snapshots() -> None:
    pre_a0 = PreA0Telemetry()
    telemetry = A0FastTelemetry(pre_a0=pre_a0)
    telemetry.set_connected(True)
    telemetry.record_received()
    telemetry.record_processed()
    artifact = SimpleNamespace(
        artifact_id="artifact-1",
        calibration=SimpleNamespace(version="platt-v1"),
    )
    pre_a0.set_model(ModelStatus.READY, artifact, None)

    assert telemetry.evidence_status() == (
        HTTPStatus.SERVICE_UNAVAILABLE,
        "no_inference",
    )
    pre_a0.record_score(
        ShadowScore(ModelStatus.READY, 0.7, True, 60, 1.0, (), (), "artifact-1", None)
    )
    pre_a0.record_snapshot(recorded=True, flushed=500)

    assert telemetry.evidence_status() == (HTTPStatus.OK, "evidence_flowing")
    text = telemetry.render_prometheus()
    assert "a0_fast_evidence_ready 1" in text
    assert 'a0_fast_evidence_status_info{reason="evidence_flowing"} 1' in text
