"""Audit test: verify tf parameter does not influence computed numeric fields.

Current behaviour: main.py validates tf and injects it into the response,
but compute.py always operates on the 1-minute bars from cache. Therefore
all supported timeframes return identical numerical fields except for the
tf string itself.
"""
from __future__ import annotations

import pytest


def test_timeframe_does_not_change_computed_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    import services.live_overlay_daemon.main as main

    base_payload = {
        "schema": "smc-live-overlay/1",
        "symbol": "AAPL",
        "asof_ts": 1,
        "stale": False,
        "news_strength": 0.2,
        "news_bias": "NEUTRAL",
        "flow_rel_vol": 1.5,
        "flow_delta_proxy_pct": 0.1,
        "squeeze_on": 0,
        "ats_state": "neutral",
        "ats_zscore": 0.0,
        "vix_level": 13.2,
        "tone": "NEUTRAL",
        "global_heat": 0.0,
        "event_window_state": "normal",
        "event_risk_level": "low",
        "next_event_name": None,
        "next_event_time": None,
        "market_event_blocked": False,
        "symbol_event_blocked": False,
        "event_provider_status": "unavailable",
    }
    monkeypatch.setattr(main.config, "overlay_secret_token", lambda: "tok")
    monkeypatch.setattr(main.cache, "get_overlay", lambda _sym: dict(base_payload))
    monkeypatch.setattr(main.cache, "overlay_age_secs", lambda: 0.0)
    monkeypatch.setattr(main.config, "max_stale_secs", lambda: 3600)

    payload_5m = main.smc_live(token="tok", symbol="AAPL", tf="5m").body
    payload_4h = main.smc_live(token="tok", symbol="AAPL", tf="4H").body

    import json

    p5 = json.loads(payload_5m)
    p4 = json.loads(payload_4h)

    # Identical numerical fields despite different requested timeframes
    for key in [
        "flow_rel_vol",
        "flow_delta_proxy_pct",
        "squeeze_on",
        "ats_state",
        "ats_zscore",
    ]:
        assert p5[key] == p4[key], key
