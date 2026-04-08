"""Open Prep adapter implementations for the SMC TV bridge.

Wraps Open Prep-backed providers behind the protocol interfaces declared in
``smc_tv_bridge.adapters``.

All Open Prep runtime loading is delegated to ``open_prep_boundary`` so the
module can be imported even when Open Prep is absent.
"""
from __future__ import annotations

import logging
from typing import Any, cast

from open_prep_boundary import (
    make_fmp_client_from_env,
    make_technical_scorer,
    make_volume_regime_detector,
)

logger = logging.getLogger("smc_api.adapters_open_prep")


class FMPCandleProvider:
    """``CandleProvider`` backed by ``open_prep.macro.FMPClient``."""

    def __init__(self) -> None:
        self._client = make_fmp_client_from_env()
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
        self._detector = make_volume_regime_detector()
        logger.info("OpenPrepRegimeProvider initialized")

    @property
    def regime(self) -> str:
        return cast(str, self._detector.regime)

    @property
    def thin_fraction(self) -> float:
        return cast(float, self._detector.thin_fraction)

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        return cast(str, self._detector.update(quotes))


class OpenPrepTechnicalScoreProvider:
    """``TechnicalScoreProvider`` backed by ``open_prep.realtime_signals.TechnicalScorer``."""

    def __init__(self) -> None:
        self._scorer = make_technical_scorer()
        logger.info("OpenPrepTechnicalScoreProvider initialized")

    def get_technical_data(
        self,
        symbol: str,
        interval: str,
    ) -> dict[str, Any]:
        return cast(dict[str, Any], self._scorer.get_technical_data(symbol, interval))
