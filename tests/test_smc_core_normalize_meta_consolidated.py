"""Tests for smc_core.normalize_meta — clamping, defaults, and regime fallback.

Consolidated from test_smc_core_meta_normalization.py and
test_smc_core_normalize_meta.py (which had overlapping clamping coverage).
"""
from __future__ import annotations

from smc_core import derive_base_signals, normalize_meta
from smc_core.types import (
    DirectionalStrength,
    SmcMeta,
    TimedDirectionalStrength,
    TimedVolumeInfo,
    VolumeInfo,
)


def test_clamps_strength_and_thin_fraction() -> None:
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


def test_clamps_and_bias_sign() -> None:
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

    nm = normalize_meta(meta)
    assert nm["symbol"] == "AAPL"
    assert nm["timeframe"] == "15m"
    assert nm["thin_fraction"] == 1.0
    assert nm["volume_regime"] == "LOW_VOLUME"
    assert nm["signed_tech"] < 0


def test_missing_and_stale_defaults() -> None:
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


def test_unknown_regime_falls_back_neutral() -> None:
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


def test_news_presence_and_stale_flags() -> None:
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

    nm = normalize_meta(meta)
    assert nm["news_present"] is True
    assert nm["news_stale"] is True
    assert nm["signed_news"] == 0.0
