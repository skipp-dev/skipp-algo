"""Stale-batch protection (ENG-WS5-02).

Refresh and Release surfaces must explicitly detect, classify and
fail-fast on stale batch lays. This module produces a structured
verdict so workflows + reports can render the cause and reach of the
problem (DoD: 'Refresh-Berichte zeigen Ursache und Reichweite').
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from collections.abc import Iterable, Mapping


class StaleStatus(str, Enum):
    FRESH = "fresh"
    AGING = "aging"        # warn-only band
    STALE = "stale"        # produktive Laeufe schlagen sauber fehl
    UNKNOWN = "unknown"    # missing or unparsable timestamp


# Default policy bands (hours).
DEFAULT_AGING_HOURS = 18
DEFAULT_STALE_HOURS = 36


@dataclass(frozen=True)
class BatchAge:
    name: str
    age_hours: float
    status: StaleStatus
    reason: str

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "age_hours": round(self.age_hours, 2),
            "status": self.status.value,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class StaleVerdict:
    overall_status: StaleStatus
    blocked: bool
    batches: tuple[BatchAge, ...] = field(default_factory=tuple)
    reason: str = ""

    def as_dict(self) -> dict:
        return {
            "overall_status": self.overall_status.value,
            "blocked": self.blocked,
            "batches": [b.as_dict() for b in self.batches],
            "reason": self.reason,
        }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        # Tolerate trailing Z.
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def classify_batch(
    name: str,
    timestamp: str | None,
    *,
    now: datetime,
    aging_hours: float = DEFAULT_AGING_HOURS,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> BatchAge:
    parsed = _parse_iso(timestamp)
    if parsed is None:
        return BatchAge(
            name=name,
            age_hours=float("inf"),
            status=StaleStatus.UNKNOWN,
            reason=f"missing or unparsable timestamp ({timestamp!r})",
        )
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    age_seconds = (now - parsed).total_seconds()
    age_hours = age_seconds / 3600.0
    if age_hours >= stale_hours:
        return BatchAge(
            name=name, age_hours=age_hours, status=StaleStatus.STALE,
            reason=f"age {age_hours:.1f}h ≥ stale threshold {stale_hours}h",
        )
    if age_hours >= aging_hours:
        return BatchAge(
            name=name, age_hours=age_hours, status=StaleStatus.AGING,
            reason=f"age {age_hours:.1f}h ≥ aging threshold {aging_hours}h",
        )
    return BatchAge(
        name=name, age_hours=age_hours, status=StaleStatus.FRESH,
        reason=f"age {age_hours:.1f}h < aging threshold {aging_hours}h",
    )


def evaluate(
    batches: Iterable[Mapping[str, str | None]],
    *,
    now: datetime,
    aging_hours: float = DEFAULT_AGING_HOURS,
    stale_hours: float = DEFAULT_STALE_HOURS,
) -> StaleVerdict:
    """Produce a single verdict for a collection of batch entries.

    Each entry needs ``name`` and ``timestamp``. Block on STALE or
    UNKNOWN — production runs must fail cleanly when freshness
    cannot be established.
    """
    classified = tuple(
        classify_batch(b["name"] or "<unnamed>", b.get("timestamp"),
                       now=now, aging_hours=aging_hours, stale_hours=stale_hours)
        for b in batches
    )
    if not classified:
        return StaleVerdict(overall_status=StaleStatus.UNKNOWN, blocked=True,
                            batches=(), reason="no batches to evaluate")

    stale = [b for b in classified if b.status is StaleStatus.STALE]
    unknown = [b for b in classified if b.status is StaleStatus.UNKNOWN]
    aging = [b for b in classified if b.status is StaleStatus.AGING]

    if stale:
        names = ", ".join(b.name for b in stale)
        return StaleVerdict(
            overall_status=StaleStatus.STALE, blocked=True, batches=classified,
            reason=f"{len(stale)} stale batch(es): {names}",
        )
    if unknown:
        names = ", ".join(b.name for b in unknown)
        return StaleVerdict(
            overall_status=StaleStatus.UNKNOWN, blocked=True, batches=classified,
            reason=f"{len(unknown)} batch(es) with unknown freshness: {names}",
        )
    if aging:
        names = ", ".join(b.name for b in aging)
        return StaleVerdict(
            overall_status=StaleStatus.AGING, blocked=False, batches=classified,
            reason=f"{len(aging)} aging batch(es): {names}",
        )
    return StaleVerdict(
        overall_status=StaleStatus.FRESH, blocked=False, batches=classified,
        reason="all batches fresh",
    )
