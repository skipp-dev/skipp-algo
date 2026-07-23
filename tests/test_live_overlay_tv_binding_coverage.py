"""Zero verified dropdowns must never render as "no drift".

Measured in production on 2026-07-23, straight off the live Prometheus:

    live_overlay_tv_binding_snapshot_loaded   1
    live_overlay_tv_bindings_checked          0
    live_overlay_tv_binding_mismatches        0
    live_overlay_tv_binding_drift             0     <-- green, no alert

The snapshot behind it (``bot/live-tradingview-bindings``) said
``bindings.expectedConsumers=7``, ``checkedConsumers=0`` and, at the top level,
``ok=false``: the run had proven nothing at all. ``binding_drift`` was derived
from ``mismatches``/``failed`` alone, and a run that opens no consumer produces
zero of both — so "verified, all correct" and "never looked" were the same
number. The saved-source half of the very same snapshot already folded
``checked != expected`` into its drift term and was correctly firing.

These tests pin the coverage terms that close the gap.
"""
from __future__ import annotations

from services.live_overlay_daemon import tradingview_binding_bridge as bridge


def _snapshot(**bindings) -> dict:
    payload = {"expectedConsumers": 7, "checkedConsumers": 7, "checkedBindings": 108,
               "mismatches": 0, "consumers": [], "failed": []}
    payload.update(bindings)
    return bridge._coerce({"generated_at_unix": 1.0, "ok": True, "bindings": payload})


def test_unverified_run_is_drift_not_silence() -> None:
    """The exact production payload: 7 expected, 0 checked, 0 mismatches."""
    snap = _snapshot(expectedConsumers=7, checkedConsumers=0, checkedBindings=0)

    assert snap["binding_drift"] == 1.0, "zero verified consumers reported as clean"
    assert snap["binding_check_known"] == 1.0
    assert snap["binding_expected_consumers"] == 7.0
    assert snap["binding_checked_consumers"] == 0.0


def test_partial_coverage_is_drift() -> None:
    """A run that stops halfway proves nothing about the consumers it skipped."""
    assert _snapshot(checkedConsumers=6)["binding_drift"] == 1.0


def test_full_clean_coverage_stays_green() -> None:
    """Fail-closed must not mean permanently red — the happy path still passes."""
    snap = _snapshot()
    assert snap["binding_drift"] == 0.0
    assert snap["binding_check_known"] == 1.0


def test_real_mismatches_still_drift() -> None:
    assert _snapshot(mismatches=2)["binding_drift"] == 1.0
    assert _snapshot(failed=[{"scriptName": "SMC Long-Dip Suite"}])["binding_drift"] == 1.0


def test_snapshot_without_an_expectation_is_unknown_not_healthy() -> None:
    """No ``expectedConsumers`` at all: coverage is unprovable, so the drift
    gauge is meaningless and ``check_known`` must say so — lo-tv-binding-drift
    is gated on it and lo-tv-binding-check-missing takes over."""
    snap = bridge._coerce({"generated_at_unix": 1.0, "bindings": {"mismatches": 0}})
    assert snap["binding_check_known"] == 0.0


def test_empty_snapshot_exposes_the_same_keys() -> None:
    """The metrics exporter reads these keys unconditionally; a load failure
    must not make them vanish from the payload."""
    empty = bridge._empty("missing_snapshot")
    for key in ("binding_drift", "binding_check_known",
                "binding_expected_consumers", "binding_checked_consumers"):
        assert key in empty, key
        assert empty[key] == 0.0


def test_exporter_publishes_the_coverage_gauges(monkeypatch) -> None:
    from services.live_overlay_daemon import metrics

    monkeypatch.setattr(
        bridge, "snapshot",
        lambda: _snapshot(expectedConsumers=7, checkedConsumers=0, checkedBindings=0),
    )
    body = "\n".join(metrics._render_tradingview_binding_metrics())

    assert "live_overlay_tv_binding_drift 1.0" in body
    assert "live_overlay_tv_binding_check_known 1.0" in body
    assert "live_overlay_tv_binding_consumers_expected 7.0" in body
    assert "live_overlay_tv_binding_consumers_checked 0.0" in body
