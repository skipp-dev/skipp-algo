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

    assert normalized["symbol"] == "AAPL"
    assert normalized["timeframe"] == "15m"
    assert normalized["thin_fraction"] == 1.0
    assert normalized["volume_regime"] == "LOW_VOLUME"
    assert normalized["signed_tech"] < 0


def test_normalize_meta_news_presence_and_stale_flags() -> None:
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1709253580,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.1), asof_ts=1709253580, stale=False),
        news=TimedDirectionalStrength(
            value=DirectionalStrength(strength=0.6, bias="BULLISH"),
            asof_ts=1709253570,
            stale=True,
        ),
    )

    normalized = normalize_meta(meta)
    assert normalized["news_present"] is True
    assert normalized["news_stale"] is True
    assert normalized["signed_news"] == 0.0
