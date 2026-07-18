"""Replayable state machine for source-pure A0 OHLCV-1s stream features."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any
from zoneinfo import ZoneInfo

from newsstack_fmp._market_cal import (
    is_us_equity_trading_day,
    regular_session_close_minutes,
)

from .a0_contract import A0MarketSnapshot, build_market_snapshot

_ET = ZoneInfo("America/New_York")
_OPEN_MINUTES = 9 * 60 + 30


class GapState(StrEnum):
    COMPLETE = "complete"
    BOOTSTRAP_REQUIRED = "bootstrap_required"
    GAP_DETECTED = "gap_detected"


class StreamApplyStatus(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    OUTSIDE_SESSION = "outside_session"
    GAP_DETECTED = "gap_detected"
    REFERENCE_MISSING = "reference_missing"
    REFERENCE_INVALID = "reference_invalid"
    BOOTSTRAP_REQUIRED = "bootstrap_required"


@dataclass(frozen=True, slots=True)
class StreamBar:
    symbol: str
    close: float
    volume: int
    ts_event: float
    ts_recv: float
    sequence: int | None = None


@dataclass(frozen=True, slots=True)
class StreamReference:
    symbol: str
    previous_close: float
    average_daily_volume: float
    source: str
    as_of_session: str
    lookback_sessions: int
    reference_version: str
    corporate_action_version: str

    def is_valid_for(self, symbol: str) -> bool:
        return bool(
            self.symbol.strip().upper() == symbol.strip().upper()
            and self.previous_close > 0
            and self.average_daily_volume >= 1000
            and self.source.strip().lower().startswith("databento")
            and self.lookback_sessions > 0
            and self.reference_version
            and self.corporate_action_version
        )


@dataclass(frozen=True, slots=True)
class A0StreamFeatureSnapshot:
    market: A0MarketSnapshot
    cumulative_regular_volume: int
    gap_state: GapState
    reference_source: str
    reference_as_of_session: str
    reference_version: str
    corporate_action_version: str


@dataclass(frozen=True, slots=True)
class StreamApplyResult:
    status: StreamApplyStatus
    gap_state: GapState
    snapshot: A0StreamFeatureSnapshot | None


@dataclass(slots=True)
class _SymbolState:
    session_date: str
    cumulative_volume: int
    last_ts_event: float
    last_sequence: int | None
    gap_state: GapState


def expected_regular_volume_fraction(ts_event: float) -> float:
    """Session-aware cumulative volume curve, scaled for regular half days."""
    event_et = datetime.fromtimestamp(ts_event, _ET)
    now_minutes = event_et.hour * 60 + event_et.minute + event_et.second / 60.0
    close_minutes = regular_session_close_minutes(event_et.date())
    session_minutes = close_minutes - _OPEN_MINUTES
    elapsed = min(max(now_minutes - _OPEN_MINUTES, 0.0), float(session_minutes))
    progress = elapsed / session_minutes if session_minutes > 0 else 1.0
    first_break = 30.0 / 390.0
    second_break = 90.0 / 390.0
    if progress <= first_break:
        fraction = 0.25 * progress / first_break
    elif progress <= second_break:
        fraction = 0.25 + 0.15 * (progress - first_break) / (second_break - first_break)
    else:
        fraction = 0.40 + 0.60 * (progress - second_break) / (1.0 - second_break)
    return max(0.02, min(1.0, fraction))


class A0StreamState:
    """Accumulate one-second bars and emit features only from complete state."""

    def __init__(self, *, max_gap_seconds: float = 2.0) -> None:
        self._max_gap_seconds = max(1.0, float(max_gap_seconds))
        self._states: dict[str, _SymbolState] = {}
        self._references: dict[str, StreamReference] = {}
        self._invalidated_symbols: set[str] = set()

    def set_reference(self, reference: StreamReference) -> None:
        self._references[reference.symbol.strip().upper()] = reference

    def bootstrap(
        self,
        *,
        symbol: str,
        session_date: str,
        cumulative_volume: int,
        last_ts_event: float,
        last_sequence: int | None = None,
    ) -> None:
        """Install a proven same-session cumulative state after history replay."""
        normalized = symbol.strip().upper()
        if cumulative_volume < 0:
            raise ValueError("cumulative_volume must be non-negative")
        event_date = datetime.fromtimestamp(last_ts_event, _ET).date().isoformat()
        if event_date != session_date:
            raise ValueError("bootstrap timestamp does not match session_date")
        self._states[normalized] = _SymbolState(
            session_date=session_date,
            cumulative_volume=int(cumulative_volume),
            last_ts_event=float(last_ts_event),
            last_sequence=last_sequence,
            gap_state=GapState.COMPLETE,
        )
        self._invalidated_symbols.discard(normalized)

    def invalidate(self, symbol: str) -> None:
        """Force the next bar through historical recovery after a local drop."""
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol must not be empty")
        self._invalidated_symbols.add(normalized)
        state = self._states.get(normalized)
        if state is not None:
            state.gap_state = GapState.GAP_DETECTED

    def apply(self, bar: StreamBar) -> StreamApplyResult:
        symbol = bar.symbol.strip().upper()
        event_et = datetime.fromtimestamp(bar.ts_event, _ET)
        session_date = event_et.date().isoformat()
        minute = event_et.hour * 60 + event_et.minute
        close_minute = regular_session_close_minutes(event_et.date())
        if (
            not is_us_equity_trading_day(event_et.date())
            or minute < _OPEN_MINUTES
            or minute >= close_minute
        ):
            return StreamApplyResult(
                StreamApplyStatus.OUTSIDE_SESSION,
                GapState.BOOTSTRAP_REQUIRED,
                None,
            )
        if not symbol or bar.close <= 0 or bar.volume < 0:
            return StreamApplyResult(
                StreamApplyStatus.REFERENCE_INVALID,
                GapState.BOOTSTRAP_REQUIRED,
                None,
            )

        state = self._states.get(symbol)
        forced_gap = symbol in self._invalidated_symbols
        if state is None or state.session_date != session_date:
            seconds_from_open = (minute - _OPEN_MINUTES) * 60 + event_et.second
            state = _SymbolState(
                session_date=session_date,
                cumulative_volume=0,
                last_ts_event=bar.ts_event,
                last_sequence=bar.sequence,
                gap_state=(
                    GapState.GAP_DETECTED
                    if forced_gap
                    else
                    GapState.COMPLETE
                    if seconds_from_open <= self._max_gap_seconds
                    else GapState.BOOTSTRAP_REQUIRED
                ),
            )
            self._states[symbol] = state
        else:
            is_same_event = (
                bar.ts_event == state.last_ts_event
                and bar.sequence == state.last_sequence
            )
            if is_same_event:
                return StreamApplyResult(StreamApplyStatus.DUPLICATE, state.gap_state, None)
            if bar.ts_event <= state.last_ts_event:
                return StreamApplyResult(StreamApplyStatus.OUT_OF_ORDER, state.gap_state, None)
            if bar.ts_event - state.last_ts_event > self._max_gap_seconds:
                state.gap_state = GapState.GAP_DETECTED
            if forced_gap:
                state.gap_state = GapState.GAP_DETECTED
            state.last_ts_event = bar.ts_event
            state.last_sequence = bar.sequence

        state.cumulative_volume += int(bar.volume)
        if state.gap_state is GapState.GAP_DETECTED:
            return StreamApplyResult(StreamApplyStatus.GAP_DETECTED, state.gap_state, None)
        if state.gap_state is GapState.BOOTSTRAP_REQUIRED:
            return StreamApplyResult(
                StreamApplyStatus.BOOTSTRAP_REQUIRED,
                state.gap_state,
                None,
            )

        reference = self._references.get(symbol)
        if reference is None:
            return StreamApplyResult(StreamApplyStatus.REFERENCE_MISSING, state.gap_state, None)
        if not reference.is_valid_for(symbol):
            return StreamApplyResult(StreamApplyStatus.REFERENCE_INVALID, state.gap_state, None)

        raw_ratio = state.cumulative_volume / reference.average_daily_volume
        expected_fraction = expected_regular_volume_fraction(bar.ts_event)
        market = build_market_snapshot(
            symbol=symbol,
            price=bar.close,
            prev_close=reference.previous_close,
            change_pct=(bar.close / reference.previous_close - 1.0) * 100.0,
            raw_daily_volume_ratio=raw_ratio,
            expected_volume_fraction=expected_fraction,
            normalized_volume_pace=raw_ratio / expected_fraction,
            source=reference.source,
            raw_ts_event=bar.ts_event,
            raw_ts_recv=bar.ts_recv,
            observed_at=bar.ts_recv,
        )
        snapshot = A0StreamFeatureSnapshot(
            market=market,
            cumulative_regular_volume=state.cumulative_volume,
            gap_state=state.gap_state,
            reference_source=reference.source,
            reference_as_of_session=reference.as_of_session,
            reference_version=reference.reference_version,
            corporate_action_version=reference.corporate_action_version,
        )
        return StreamApplyResult(StreamApplyStatus.ACCEPTED, state.gap_state, snapshot)

    def state_snapshot(self, symbol: str) -> dict[str, Any] | None:
        normalized = symbol.strip().upper()
        state = self._states.get(normalized)
        if state is None:
            return (
                {"gap_state": str(GapState.GAP_DETECTED), "invalidated": True}
                if normalized in self._invalidated_symbols
                else None
            )
        return {
            "session_date": state.session_date,
            "cumulative_volume": state.cumulative_volume,
            "last_ts_event": state.last_ts_event,
            "last_sequence": state.last_sequence,
            "gap_state": str(state.gap_state),
            "invalidated": normalized in self._invalidated_symbols,
        }
