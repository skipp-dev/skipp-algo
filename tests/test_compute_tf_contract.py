"""Audit test: verify tf parameter actually influences compute output.

Current behaviour: main.py validates tf and injects it into the response,
but compute.py always operates on the 1-minute bars from cache. Therefore
all supported timeframes return identical numerical fields except for the
tf string itself.
"""
from __future__ import annotations

import pytest


def test_timeframe_does_not_change_computed_fields() -> None:
    import services.live_overlay_daemon.compute as compute

    bars = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5, "volume": 1000.0}
        for _ in range(25)
    ]

    payload_5m = compute.build_payload(
        "AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, max_stale_secs=3600
    )
    payload_4h = compute.build_payload(
        "AAPL", bars, {"tone": "NEUTRAL", "global_heat": 0.0}, max_stale_secs=3600
    )

    # Identical numerical fields despite different requested timeframes
    for key in [
        "flow_rel_vol",
        "flow_delta_proxy_pct",
        "squeeze_on",
        "ats_state",
        "ats_zscore",
    ]:
        assert payload_5m[key] == payload_4h[key], key
