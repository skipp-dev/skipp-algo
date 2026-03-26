from __future__ import annotations

from smc_core import derive_base_signals, normalize_meta
from smc_core.types import (
    DirectionalStrength,
    SmcMeta,
    TimedDirectionalStrength,
    TimedVolumeInfo,
    VolumeInfo,
)


def test_normalize_meta_clamps_strength_and_thin_fraction() -> None:
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1.0,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="LOW_VOLUME", thin_fraction=1.9), asof_ts=1.0, stale=False),
        technical=TimedDirectionalStrength(value=DirectionalStrength(strength=2.2, bias="BULLISH"), asof_ts=1.0, stale=False),
        news=TimedDirectionalStrength(value=DirectionalStrength(strength=2.5, bias="BEARISH"), asof_ts=1.0, stale=False),
    )

    nm = normalize_meta(meta)
    assert nm["thin_fraction"] == 1.0
    assert nm["signed_tech"] == 1.0
    assert nm["signed_news"] == -1.0


def test_normalize_meta_missing_and_stale_defaults() -> None:
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1.0,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="NORMAL", thin_fraction=0.2), asof_ts=1.0, stale=True),
        technical=None,
        news=None,
    )

    nm = normalize_meta(meta)
    signals = derive_base_signals(nm)

    assert nm["volume_stale"] is True
    assert nm["signed_tech"] == 0.0
    assert nm["signed_news"] == 0.0
    assert signals["global_heat"] == 0.0
    assert "VOLUME_STALE" in signals["base_reasons"]
    assert "TECH_MISSING" in signals["base_reasons"]
    assert "NEWS_MISSING" in signals["base_reasons"]


def test_normalize_meta_unknown_regime_falls_back_neutral() -> None:
    meta = SmcMeta(
        symbol="AAPL",
        timeframe="15m",
        asof_ts=1.0,
        volume=TimedVolumeInfo(value=VolumeInfo(regime="BROKEN", thin_fraction=0.3), asof_ts=1.0, stale=False),  # type: ignore[arg-type]
    )

    nm = normalize_meta(meta)
    signals = derive_base_signals(nm)

    assert nm["volume_regime"] == "NORMAL"
    assert nm["volume_stale"] is True
    assert signals["global_heat"] == 0.0
    assert "VOLUME_STALE" in signals["base_reasons"]
