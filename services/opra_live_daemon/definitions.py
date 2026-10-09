"""UTC-day-aligned OPRA definition bootstrap helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from databento.common.error import BentoClientError

from newsstack_fmp.opra_uoa import OpraDefinitionRecord

_MAX_LOOKBACK_DAYS = 7


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
