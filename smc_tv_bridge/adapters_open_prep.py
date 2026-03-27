"""Open Prep adapter implementations for the SMC TV bridge.

Wraps ``open_prep.macro.FMPClient``, ``open_prep.realtime_signals.VolumeRegimeDetector``,
and ``open_prep.realtime_signals.TechnicalScorer`` behind the protocol interfaces
declared in ``smc_tv_bridge.adapters``.

All ``open_prep`` imports are lazy so the module can be imported even when
Open Prep is absent — callers get a clear error only when they instantiate.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("smc_api.adapters_open_prep")


class FMPCandleProvider:
    """``CandleProvider`` backed by ``open_prep.macro.FMPClient``."""

    def __init__(self) -> None:
        from open_prep.macro import FMPClient
        self._client = FMPClient.from_env()
        logger.info("FMPCandleProvider initialized")

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            candles = self._client.get_intraday_chart(
                symbol, interval=interval, limit=limit,
            )
            if candles and isinstance(candles, list):
                candles.sort(key=lambda c: c.get("date", ""))
            return candles or []
        except Exception as exc:
            logger.warning(
                "FMPCandleProvider: fetch failed for %s/%s: %s",
                symbol, interval, exc,
            )
            return []


class OpenPrepRegimeProvider:
    """``RegimeProvider`` backed by ``open_prep.realtime_signals.VolumeRegimeDetector``."""

    def __init__(self) -> None:
        from open_prep.realtime_signals import VolumeRegimeDetector
        self._detector = VolumeRegimeDetector()
        logger.info("OpenPrepRegimeProvider initialized")

    @property
    def regime(self) -> str:
        return self._detector.regime

    @property
    def thin_fraction(self) -> float:
        return self._detector.thin_fraction

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        return self._detector.update(quotes)


class OpenPrepTechnicalScoreProvider:
    """``TechnicalScoreProvider`` backed by ``open_prep.realtime_signals.TechnicalScorer``."""

    def __init__(self) -> None:
        from open_prep.realtime_signals import TechnicalScorer
        self._scorer = TechnicalScorer()
        logger.info("OpenPrepTechnicalScoreProvider initialized")

    def get_technical_data(
        self,
        symbol: str,
        interval: str,
    ) -> dict[str, Any]:
        return self._scorer.get_technical_data(symbol, interval)
