"""Adapter protocols for the SMC TV bridge enrichment layer.

These protocols define the contracts that candle-data, volume-regime, and
technical-score providers must satisfy.  The bridge imports exclusively
through these interfaces; concrete implementations live in separate
modules (e.g. ``adapters_open_prep``).

See docs/ADR-001-open-prep-integration-boundary.md for rationale.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CandleProvider(Protocol):
    """Fetch intraday OHLCV candle dicts for a symbol."""

    def fetch_candles(
        self,
        symbol: str,
        interval: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return candle dicts sorted oldest-first.

        Each dict must contain at least: ``open``, ``high``, ``low``,
        ``close``, ``volume`` and either ``date`` or ``timestamp``.
        """
        ...


@runtime_checkable
class RegimeProvider(Protocol):
    """Classify volume regime from recent quote data."""

    @property
    def regime(self) -> str:
        """Current regime label (``NORMAL``, ``LOW_VOLUME``, ``HOLIDAY_SUSPECT``)."""
        ...

    @property
    def thin_fraction(self) -> float:
        """Fraction of symbols classified as thin-volume (0.0–1.0)."""
        ...

    def update(self, quotes: dict[str, dict[str, Any]]) -> str:
        """Ingest latest quotes and return the updated regime label."""
        ...


@runtime_checkable
class TechnicalScoreProvider(Protocol):
    """Provide technical indicator scores for a symbol."""

    def get_technical_data(
        self,
        symbol: str,
        interval: str,
    ) -> dict[str, Any]:
        """Return a dict with at least ``technical_score`` (float 0–1)
        and ``technical_signal`` (str).
        """
        ...
