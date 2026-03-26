from __future__ import annotations

from smc_core import normalize_meta
from smc_core.types import DirectionalStrength, SmcMeta, TimedDirectionalStrength, TimedVolumeInfo, VolumeInfo


def test_normalize_meta_from_smcmeta_clamps_and_bias() -> None:
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(
            value=VolumeInfo(regime="LOW_VOLUME", thin_fraction=1.25),
            asof_ts=1709253580,
            stale=False,
        ),
        technical=TimedDirectionalStrength(
            value=DirectionalStrength(strength=0.4, bias="BEARISH"),
            asof_ts=1709253570,
            stale=False,
        ),
    )

    normalized = normalize_meta(meta)

    assert normalized["liquidity_pressure"] == 1.0
    assert normalized["volume_zscore"] == 1.0
    assert normalized["net_bias"] == "bearish"


def test_normalize_meta_from_dict_defaults_safe() -> None:
    normalized = normalize_meta({"volume": {"regime": "NORMAL", "thin_fraction": "bad"}})
    assert normalized["liquidity_pressure"] == 0.0
    assert normalized["volume_zscore"] == 0.0
    assert normalized["net_bias"] == "bullish"
