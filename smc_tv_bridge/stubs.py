"""Deterministic stub providers for the SMC TV bridge.

These stubs satisfy the adapter protocols defined in ``smc_tv_bridge.adapters``
and produce realistic, deterministic payloads for tests.  No network access
or Open Prep dependency required.
"""
from __future__ import annotations

import copy
from typing import Any


# ── Golden candle payloads ──────────────────────────────────────────────────

GOLDEN_CANDLE: dict[str, Any] = {
    "date": "2026-03-27T09:30:00",
    "open": 150.00,
    "high": 151.25,
    "low": 149.50,
    "close": 150.80,
    "volume": 12345,
}

GOLDEN_CANDLES_5: list[dict[str, Any]] = [
    {
        "date": f"2026-03-27T09:{30 + i}:00",
        "open": 150.0 + i * 0.5,
        "high": 151.0 + i * 0.5,
        "low": 149.5 + i * 0.5,
        "close": 150.5 + i * 0.5,
        "volume": 10000 + i * 1000,
    }
    for i in range(5)
]


# ── Golden technical payloads ──────────────────────────────────────────────

GOLDEN_TECH_BULLISH: dict[str, Any] = {
    "technical_score": 0.78,
    "technical_signal": "BULLISH",
    "rsi": 58.3,
    "macd_signal": "BUY",
    "adx": 28.0,
}

GOLDEN_TECH_BEARISH: dict[str, Any] = {
    "technical_score": 0.25,
    "technical_signal": "BEARISH",
    "rsi": 32.1,
    "macd_signal": "SELL",
    "adx": 35.0,
}

GOLDEN_TECH_NEUTRAL: dict[str, Any] = {
    "technical_score": 0.50,
    "technical_signal": "NEUTRAL",
}


# ── Stub CandleProvider ────────────────────────────────────────────────────

class StubCandleProvider:
    """Returns deterministic candle lists. Configurable for edge cases."""

    def __init__(
        self,
        candles: list[dict[str, Any]] | None = None,
        *,
        raise_on_call: Exception | None = None,
    ) -> None:
        self._candles = candles if candles is not None else copy.deepcopy(GOLDEN_CANDLES_5)
        self._raise_on_call = raise_on_call
        self.calls: list[tuple[str, str, int]] = []

    def fetch_candles(self, symbol: str, interval: str, limit: int) -> list[dict[str, Any]]:
        self.calls.append((symbol, interval, limit))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return copy.deepcopy(self._candles[:limit])


# ── Stub RegimeProvider ─────────────────────────────────────────────────────

class StubRegimeProvider:
    """Returns a fixed regime label. Tracks update calls."""

    def __init__(
        self,
        regime_label: str = "NORMAL",
        thin: float = 0.0,
    ) -> None:
        self._regime = regime_label
        self._thin = thin
        self.update_calls: list[dict[str, dict[str, Any]]] = []

    @property
    def regime(self) -> str:
        return self._regime

    @property
    def thin_fraction(self) -> float:
        return self._thin

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        self.update_calls.append(quotes)
        return self._regime


# ── Stub TechnicalScoreProvider ─────────────────────────────────────────────

class StubTechProvider:
    """Returns a configurable technical payload."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        *,
        raise_on_call: Exception | None = None,
    ) -> None:
        self._payload = payload if payload is not None else copy.deepcopy(GOLDEN_TECH_BULLISH)
        self._raise_on_call = raise_on_call
        self.calls: list[tuple[str, str]] = []

    def get_technical_data(self, symbol: str, interval: str) -> dict[str, Any]:
        self.calls.append((symbol, interval))
        if self._raise_on_call is not None:
            raise self._raise_on_call
        return copy.deepcopy(self._payload)
