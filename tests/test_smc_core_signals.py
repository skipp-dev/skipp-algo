from __future__ import annotations

from smc_core import derive_base_signals


def test_derive_base_signals_shape_and_bounds() -> None:
    signals = derive_base_signals(
        {
            "symbol": "AAPL",
            "timeframe": "15m",
            "asof_ts": 1709253580.0,
            "volume_regime": "NORMAL",
            "volume_stale": False,
            "thin_fraction": 0.2,
            "signed_tech": 0.6,
            "signed_news": 0.2,
            "tech_present": True,
            "tech_stale": False,
            "news_present": True,
            "news_stale": False,
            "event_severity": None,
            "event_in_window": False,
            "market_regime": None,
            "enriched_news_heat": 0.0,
            "provenance": ["TEST"],
        }
    )

    assert set(signals.keys()) == {"global_heat", "global_strength", "base_reasons"}
    assert -1.0 <= signals["global_heat"] <= 1.0
    assert 0.0 <= signals["global_strength"] <= 1.0
    assert isinstance(signals["base_reasons"], list)
