from __future__ import annotations

from smc_core import derive_base_signals


def test_derive_base_signals_shape_and_bounds() -> None:
    signals = derive_base_signals(
        {
            "volume_regime": "NORMAL",
            "liquidity_pressure": 0.8,
            "volume_zscore": 0.2,
            "event_risk": 0.1,
            "options_pin_pressure": 0.0,
            "gamma_tilt": 0.0,
            "signed_tech": 0.6,
            "signed_news": 0.2,
            "tech_present": True,
            "tech_stale": False,
            "news_present": True,
            "news_stale": False,
            "net_bias": "neutral",
        }
    )

    assert set(signals.keys()) == {"global_heat", "global_strength", "base_reasons"}
    assert -1.0 <= signals["global_heat"] <= 1.0
    assert 0.0 <= signals["global_strength"] <= 1.0
    assert isinstance(signals["base_reasons"], list)
