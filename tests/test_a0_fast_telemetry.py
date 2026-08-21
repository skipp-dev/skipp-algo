"""Prometheus and health-contract tests for A0-Fast telemetry."""

from __future__ import annotations

import re
import subprocess
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

from open_prep.a0_stream_buffer import BufferSnapshot
from open_prep.pre_a0_model import ModelStatus, ShadowScore
from open_prep.pre_a0_telemetry import PreA0Telemetry
from services.a0_fast_detector.telemetry import (
    SEEDED_REJECTION_REASONS,
    A0FastTelemetry,
)


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


def test_out_of_range_features_are_named_not_just_counted() -> None:
    """The drift alert says "input quality degraded"; telemetry must say WHICH input.

    Until 2026-08-21 record_score() collapsed score.out_of_range_features to a
    length, so a firing pre-a0-input-drift alert was unattributable from
    metrics or logs (measured live: 2.5k OOR/h, feature unknown).
    """
    pre_a0 = PreA0Telemetry()
    pre_a0.record_score(
        ShadowScore(
            ModelStatus.READY,
            0.7,
            True,
            60,
            1.0,
            ("volume_progress",),
            ("price_distance_pct", "volume_distance_pace"),
            "artifact-1",
            "feature_out_of_range",
        )
    )
    body = pre_a0.render_prometheus()
    assert (
        'pre_a0_feature_out_of_range_by_feature_total{feature="price_distance_pct"} 1'
        in body
    )
    assert (
        'pre_a0_feature_out_of_range_by_feature_total{feature="volume_distance_pace"} 1'
        in body
    )
    assert (
        'pre_a0_feature_missing_by_feature_total{feature="volume_progress"} 1' in body
    )
    # The unlabeled totals (the alert's contract) keep counting unchanged.
    assert "pre_a0_feature_out_of_range_total 2" in body
    assert "pre_a0_feature_missing_total 1" in body


def test_per_feature_series_are_seeded_at_zero_once_the_model_is_known() -> None:
    """increase() over an unseeded counter eats its first burst (2026-08-19 lesson).

    Every feature the loaded model declares must be exposed at zero BEFORE its
    first violation, or the first drift burst becomes the baseline.
    """
    pre_a0 = PreA0Telemetry()
    artifact = SimpleNamespace(
        artifact_id="artifact-1",
        calibration=SimpleNamespace(version="platt-v1"),
        model=SimpleNamespace(feature_names=("price_progress", "direction")),
    )
    pre_a0.set_model(ModelStatus.READY, artifact, None)
    body = pre_a0.render_prometheus()
    for name in ("price_progress", "direction"):
        assert (
            f'pre_a0_feature_out_of_range_by_feature_total{{feature="{name}"}} 0'
            in body
        ), f"feature {name!r} not seeded at zero"
        assert (
            f'pre_a0_feature_missing_by_feature_total{{feature="{name}"}} 0' in body
        ), f"missing series for {name!r} not seeded at zero"


def test_rejection_counter_is_seeded_before_the_first_rejection() -> None:
    """increase() over an unseeded counter eats its own first burst.

    a0_fast_records_rejected_total had zero series in grafanacloud-prom on
    2026-08-19 while every neighbouring a0_fast_* gauge had one, because the
    family is rendered per `reason` label out of an empty Counter. The
    a0-fast-record-rejections rule computes increase(...[5m]) > 0, so the very
    first rejection would have become the baseline rather than the alert.
    """
    telemetry = A0FastTelemetry()
    telemetry.set_buffer(_buffer())
    body = telemetry.render_prometheus()
    for reason in SEEDED_REJECTION_REASONS:
        assert (
            f'a0_fast_records_rejected_total{{reason="{reason}"}} 0' in body
        ), f"reason {reason!r} is not exposed at zero before the first rejection"


def test_every_rejection_reason_is_seeded() -> None:
    """The seed list is re-derived from the call sites, never hand-trusted.

    A new record_rejected("...") anywhere in the tree must appear in
    SEEDED_REJECTION_REASONS, otherwise its first burst is invisible for
    exactly the same reason the seed exists.
    """
    repo = Path(__file__).resolve().parents[1]
    tracked = subprocess.run(
        ["git", "ls-files", "*.py"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    called: set[str] = set()
    for relative in tracked:
        if relative.startswith("tests/"):
            continue
        source = (repo / relative).read_text(encoding="utf-8", errors="ignore")
        called.update(re.findall(r"""record_rejected\(\s*["']([a-z0-9_]+)["']""", source))

    assert called, "no record_rejected() call sites found -- the scan broke"
    unseeded = sorted(called - set(SEEDED_REJECTION_REASONS))
    assert not unseeded, (
        f"rejection reason(s) passed to record_rejected() but never seeded: "
        f"{unseeded}. Add them to SEEDED_REJECTION_REASONS in "
        "services/a0_fast_detector/telemetry.py."
    )
    stale = sorted(set(SEEDED_REJECTION_REASONS) - called)
    assert not stale, (
        f"seeded reason(s) that no call site produces any more: {stale}. "
        "Remove them so the seed list keeps describing reality."
    )
