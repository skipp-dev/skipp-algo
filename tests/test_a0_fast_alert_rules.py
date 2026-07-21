"""Static alert coverage for A0-Fast slow-reader and disconnect states."""

from __future__ import annotations

from pathlib import Path


def test_a0_fast_alert_rules_cover_required_degraded_states() -> None:
    path = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "a0_fast_detector"
        / "alert-rules.yml"
    )
    text = path.read_text(encoding="utf-8")
    assert "A0FastStreamDisconnected" in text
    assert "increase(a0_fast_queue_dropped_total[5m]) > 0" in text
    assert "increase(a0_fast_records_rejected_total[5m]) > 0" in text
    assert "increase(a0_fast_records_received_total[5m]) > 100" in text
    assert "a0_fast_evidence_ready == 0" in text
    assert "a0_fast_resync_required_symbols > 0" in text
    assert "a0_fast_queue_depth / clamp_min(a0_fast_queue_capacity, 1) > 0.8" in text
    assert "a0_fast_last_record_age_seconds > 8" in text
