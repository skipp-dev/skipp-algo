"""Source-pure Databento reference construction for A0-Fast shadow replay."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from .a0_stream_state import StreamReference


@dataclass(frozen=True, slots=True)
class DatabentoDailyBar:
    symbol: str
    session_date: str
    close: float
    volume: int
    source: str
    corporate_action_adjusted: bool


def build_databento_reference(
    *,
    symbol: str,
    bars: list[DatabentoDailyBar],
    as_of_session: str,
    lookback_sessions: int,
    reference_version: str,
    corporate_action_version: str,
) -> StreamReference:
    """Build previous-close and ADV from adjusted Databento daily history."""
    normalized_symbol = symbol.strip().upper()
    as_of = date.fromisoformat(as_of_session)
    eligible = sorted(
        (
            bar for bar in bars
            if bar.symbol.strip().upper() == normalized_symbol
            and date.fromisoformat(bar.session_date) < as_of
        ),
        key=lambda bar: bar.session_date,
    )
    if lookback_sessions <= 0:
        raise ValueError("lookback_sessions must be positive")
    if len(eligible) < lookback_sessions:
        raise ValueError("insufficient Databento daily history")
    selected = eligible[-lookback_sessions:]
    if any(not bar.source.strip().lower().startswith("databento") for bar in selected):
        raise ValueError("reference history is not source-pure Databento")
    if any(not bar.corporate_action_adjusted for bar in selected):
        raise ValueError("reference history is not corporate-action adjusted")
    if any(bar.close <= 0 or bar.volume < 1000 for bar in selected):
        raise ValueError("reference history contains invalid close or volume")
    if not reference_version or not corporate_action_version:
        raise ValueError("reference and corporate-action versions are required")
    average_volume = sum(bar.volume for bar in selected) / len(selected)
    return StreamReference(
        symbol=normalized_symbol,
        previous_close=selected[-1].close,
        average_daily_volume=average_volume,
        source="databento:daily",
        as_of_session=selected[-1].session_date,
        lookback_sessions=lookback_sessions,
        reference_version=reference_version,
        corporate_action_version=corporate_action_version,
    )
