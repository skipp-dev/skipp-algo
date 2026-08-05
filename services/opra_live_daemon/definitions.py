"""UTC-day-aligned OPRA definition bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from databento.common.error import BentoClientError

from newsstack_fmp.opra_uoa import OpraDefinitionRecord

_MAX_LOOKBACK_DAYS = 7


@dataclass
class BootstrapPlanner:
    """Decides when the definition bootstrap must be (re-)attempted.

    Pure and clock-free — the caller passes a monotonic reading — so the two
    production failures it exists for are testable without a live feed:

    * a bootstrap that failed (Databento Historical answered 504 for hours on
      2026-08-04) must be retried with a growing, bounded delay rather than
      leaving the replica definition-less for the rest of the day;
    * a UTC session roll clears ``OpraShadowState._definitions``, so the
      bootstrap owes the NEW session a full load even though live records may
      already have re-learned a handful of instruments.
    """

    retry_seconds: float = 30.0
    max_retry_seconds: float = 900.0
    _last_attempt: float | None = field(default=None, init=False)
    _consecutive_failures: int = field(default=0, init=False)
    _satisfied_session: str | None = field(default=None, init=False)
    _satisfied: bool = field(default=False, init=False)

    def _delay(self) -> float:
        if self._consecutive_failures <= 0:
            return self.retry_seconds
        grown = self.retry_seconds * 2.0 ** (self._consecutive_failures - 1)
        return min(grown, self.max_retry_seconds)

    def due(self, now: float, *, session_date: str | None, definition_count: int) -> bool:
        """True when a bootstrap attempt should run at *now*."""
        rolled = (
            session_date is not None
            and self._satisfied_session is not None
            and session_date != self._satisfied_session
        )
        if self._satisfied and definition_count > 0 and not rolled:
            return False
        if self._last_attempt is None:
            return True
        return now - self._last_attempt >= self._delay()

    def record_attempt(self, now: float, *, ok: bool, session_date: str | None) -> None:
        """Register the outcome of an attempt started for *session_date*."""
        self._last_attempt = now
        if ok:
            self._consecutive_failures = 0
            self._satisfied = True
            self._satisfied_session = session_date
        else:
            self._consecutive_failures += 1
            self._satisfied = False


def utc_day_window(instant: datetime) -> tuple[datetime, datetime]:
    """Return the UTC day containing *instant* as a half-open range."""
    value = instant.astimezone(UTC)
    start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def previous_complete_utc_day(instant: datetime) -> tuple[datetime, datetime]:
    """Return the most recent complete weekday as a half-open UTC range."""
    current_start, _ = utc_day_window(instant)
    for days_ago in range(1, _MAX_LOOKBACK_DAYS + 1):
        start = current_start - timedelta(days=days_ago)
        if start.weekday() < 5:
            return start, start + timedelta(days=1)
    raise RuntimeError("no complete weekday found in OPRA bootstrap lookback")


def _complete_weekday_windows(instant: datetime):
    current_start, _ = utc_day_window(instant)
    for days_ago in range(1, _MAX_LOOKBACK_DAYS + 1):
        start = current_start - timedelta(days=days_ago)
        if start.weekday() < 5:
            yield start, start + timedelta(days=1)


def bootstrap_definitions(
    provider: Any,
    *,
    symbols: list[str],
    instant: datetime,
) -> list[OpraDefinitionRecord]:
    """Load definitions from the latest available complete OPRA weekday."""
    for start, end in _complete_weekday_windows(instant):
        try:
            store = provider.get_range(
                context="opra-live.definition-bootstrap",
                dataset="OPRA.PILLAR",
                symbols=symbols,
                schema="definition",
                start=start.isoformat(),
                end=end.isoformat(),
                stype_in="parent",
            )
        except BentoClientError as exc:
            if "data_start_after_available_end" not in str(exc):
                raise
            continue
        frame = store.to_df().reset_index()
        if frame.empty:
            continue
        return [
            OpraDefinitionRecord.from_row(row)
            for row in frame.to_dict(orient="records")
        ]
    raise RuntimeError("no OPRA definitions found in seven-day bootstrap lookback")
