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
