from __future__ import annotations

from smc_core import derive_base_signals


def test_derive_base_signals_shape_and_bounds() -> None:
    signals = derive_base_signals(
        {
            "liquidity_pressure": 0.8,
            "volume_zscore": 0.2,
            "event_risk": 0.1,
            "options_pin_pressure": 0.0,
            "gamma_tilt": 0.0,
            "net_bias": "neutral",
        }
    )

    assert set(signals.keys()) == {"ifvg_score", "ob_score", "sweep_risk", "confidence"}
    assert -1.0 <= signals["ifvg_score"] <= 1.0
    assert -1.0 <= signals["ob_score"] <= 1.0
    assert -1.0 <= signals["sweep_risk"] <= 1.0
    assert 0.0 <= signals["confidence"] <= 1.0
