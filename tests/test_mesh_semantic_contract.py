"""Truth guards for the Live Decision Mesh semantic boundary."""

from __future__ import annotations

from services.live_overlay_daemon import compute


def test_event_placeholder_is_unknown_not_neutral() -> None:
    fields = compute._event_fields_for("AAPL")

    assert fields == {
        "event_window_state": None,
        "event_risk_level": None,
        "next_event_name": None,
        "next_event_time": None,
        "market_event_blocked": None,
        "symbol_event_blocked": None,
        "event_provider_status": "unknown",
    }


def test_legacy_flow_names_are_explicitly_mirrored_by_canonical_names() -> None:
    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(4)
    ]
    bars.append({"open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0, "volume": 130.0})

    flow = compute.compute_flow_fields(bars)
    ats = compute.compute_ats_fields(bars)
    assert flow["flow_delta_proxy_pct"] == 1.0
    assert ats["ats_state"] in {"accumulation", "distribution", "neutral"}
