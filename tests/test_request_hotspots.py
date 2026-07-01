from __future__ import annotations

import services.live_overlay_daemon.request_hotspots as hotspots


def test_request_hotspots_tracks_top_symbols_and_tfs() -> None:
    hotspots.reset()
    hotspots.record_request("nvda", "5m")
    hotspots.record_request("NVDA", "5m")
    hotspots.record_request("AAPL", "1H")

    snap = hotspots.snapshot(top_n=3)

    assert snap["symbol_count"] == 2
    assert snap["tf_count"] == 2
    assert ("NVDA", 2) in snap["top_symbols"]
    assert ("5m", 2) in snap["top_tfs"]


def test_symbol_counter_is_bounded_under_distinct_symbol_flood() -> None:
    """An authenticated client probing many distinct symbols must not grow the
    in-process counter without limit (symbol is only capped at 10 chars).
    """
    hotspots.reset()
    flood = hotspots._MAX_TRACKED_KEYS * 3
    for i in range(flood):
        hotspots.record_request(f"PRB{i:07d}"[:10], "5m")

    snap = hotspots.snapshot()
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS


def test_hot_symbol_survives_probe_flood() -> None:
    """A genuinely hot symbol (high count) must survive eviction caused by a
    flood of one-off probe symbols.
    """
    hotspots.reset()
    for _ in range(100):
        hotspots.record_request("NVDA", "5m")
    for i in range(hotspots._MAX_TRACKED_KEYS * 2):
        hotspots.record_request(f"PRB{i:07d}"[:10], "5m")

    snap = hotspots.snapshot(top_n=1)
    assert snap["symbol_count"] <= hotspots._MAX_TRACKED_KEYS
    assert ("NVDA", 100) in snap["top_symbols"]
