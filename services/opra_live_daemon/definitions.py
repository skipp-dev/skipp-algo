"""UTC-day-aligned OPRA definition bootstrap helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from newsstack_fmp.opra_uoa import OpraDefinitionRecord


def utc_day_window(instant: datetime) -> tuple[datetime, datetime]:
    """Return the UTC day containing *instant* as a half-open range."""
    value = instant.astimezone(UTC)
    start = value.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def previous_complete_utc_day(instant: datetime) -> tuple[datetime, datetime]:
    current_start, _ = utc_day_window(instant)
    return current_start - timedelta(days=1), current_start


def bootstrap_definitions(
    provider: Any,
    *,
    symbols: list[str],
    instant: datetime,
) -> list[OpraDefinitionRecord]:
    """Load definitions from the last complete UTC day for live startup."""
    start, end = previous_complete_utc_day(instant)
    store = provider.get_range(
        context="opra-live.definition-bootstrap",
        dataset="OPRA.PILLAR",
        symbols=symbols,
        schema="definition",
        start=start.isoformat(),
        end=end.isoformat(),
    )
    frame = store.to_df().reset_index()
    return [OpraDefinitionRecord.from_row(row) for row in frame.to_dict(orient="records")]
