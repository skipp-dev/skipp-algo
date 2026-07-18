"""Fail-closed historical reconstruction for A0-Fast stream gaps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from zoneinfo import ZoneInfo

from .a0_stream_state import A0StreamState, StreamApplyResult, StreamBar

_ET = ZoneInfo("America/New_York")


class RecoveryStatus(StrEnum):
    RECOVERED = "recovered"
    INCOMPLETE_COVERAGE = "incomplete_coverage"
    INVALID_HISTORY = "invalid_history"
    FETCH_FAILED = "fetch_failed"


@dataclass(frozen=True, slots=True)
class HistoricalBootstrapBatch:
    symbol: str
    request_start: float
    request_end: float
    coverage_complete: bool
    bars: tuple[StreamBar, ...]


class HistoricalBarsProvider(Protocol):
    def fetch_before(self, bar: StreamBar) -> HistoricalBootstrapBatch: ...


@dataclass(frozen=True, slots=True)
class RecoveryOutcome:
    status: RecoveryStatus
    apply_result: StreamApplyResult | None
    recovered_volume: int
    historical_bars: int
    error: str | None = None


def recover_before_bar(
    state: A0StreamState,
    current_bar: StreamBar,
    provider: HistoricalBarsProvider,
) -> RecoveryOutcome:
    """Rebuild open-to-current-minus-one-second state, then replay current bar."""
    try:
        batch = provider.fetch_before(current_bar)
    except Exception as exc:
        return RecoveryOutcome(
            RecoveryStatus.FETCH_FAILED,
            None,
            0,
            0,
            f"{type(exc).__name__}: {exc}",
        )
    symbol = current_bar.symbol.strip().upper()
    event_et = datetime.fromtimestamp(current_bar.ts_event, _ET)
    session_open = event_et.replace(hour=9, minute=30, second=0, microsecond=0).timestamp()
    if (
        not batch.coverage_complete
        or batch.symbol.strip().upper() != symbol
        or batch.request_start > session_open
        or batch.request_end < current_bar.ts_event
    ):
        return RecoveryOutcome(
            RecoveryStatus.INCOMPLETE_COVERAGE,
            None,
            0,
            len(batch.bars),
            "historical batch does not prove full session coverage",
        )

    unique: dict[tuple[float, int | None], StreamBar] = {}
    for bar in batch.bars:
        if (
            bar.symbol.strip().upper() != symbol
            or bar.ts_event < session_open
            or bar.ts_event >= current_bar.ts_event
            or bar.volume < 0
            or bar.close <= 0
        ):
            return RecoveryOutcome(
                RecoveryStatus.INVALID_HISTORY,
                None,
                0,
                len(batch.bars),
                "historical batch contains an invalid or cross-session bar",
            )
        unique[(bar.ts_event, bar.sequence)] = bar
    ordered = sorted(unique.values(), key=lambda bar: (bar.ts_event, bar.sequence or -1))
    cumulative_volume = sum(bar.volume for bar in ordered)
    covered_through = max(session_open, current_bar.ts_event - 1.0)
    state.bootstrap(
        symbol=symbol,
        session_date=event_et.date().isoformat(),
        cumulative_volume=cumulative_volume,
        last_ts_event=covered_through,
    )
    result = state.apply(current_bar)
    return RecoveryOutcome(
        RecoveryStatus.RECOVERED,
        result,
        cumulative_volume,
        len(ordered),
    )
