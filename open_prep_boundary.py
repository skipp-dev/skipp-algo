"""Lazy runtime boundary for Open Prep-backed integrations.

This module centralizes runtime construction of Open Prep clients so that
non-Open-Prep consumers do not need to import ``open_prep`` directly.
"""

from __future__ import annotations

from typing import Any


FMPClientLike = Any
VolumeRegimeDetectorLike = Any
TechnicalScorerLike = Any


def make_fmp_client(
    api_key: str,
    *,
    retry_attempts: int = 1,
    timeout_seconds: float = 12.0,
) -> FMPClientLike:
    from open_prep.macro import FMPClient

    return FMPClient(
        api_key=api_key,
        retry_attempts=retry_attempts,
        timeout_seconds=timeout_seconds,
    )


def make_fmp_client_from_env() -> FMPClientLike:
    from open_prep.macro import FMPClient

    return FMPClient.from_env()


def make_volume_regime_detector() -> VolumeRegimeDetectorLike:
    from open_prep.realtime_signals import VolumeRegimeDetector

    return VolumeRegimeDetector()


def make_technical_scorer() -> TechnicalScorerLike:
    from open_prep.realtime_signals import TechnicalScorer

    return TechnicalScorer()


__all__ = [
    "FMPClientLike",
    "TechnicalScorerLike",
    "VolumeRegimeDetectorLike",
    "make_fmp_client",
    "make_fmp_client_from_env",
    "make_technical_scorer",
    "make_volume_regime_detector",
]