"""EV-04 — point-in-time (lookahead) integrity guard.

The largest edge-illusion in any backtest is lookahead bias: a feature,
news item or label that carries a timestamp *later* than the moment a
decision was actually taken. ``databento_reference`` already filters
reference events to ``cutoff <= effective_date <= as_of`` inline, but
that boundary check lives in one function. The whole edge-validation
pipeline (EV-06 ``build_family_metrics`` feature assembly, news/catalyst
joins) needs the *same* invariant — so this module promotes it to a
reusable, test-guarded primitive.

Contract: a record is point-in-time-valid for an ``as_of`` boundary iff
its timestamp is **at or before** ``as_of``. A timestamp strictly after
``as_of`` is a lookahead leak and must fail loudly, never be silently
dropped — silent dropping hides a data-assembly bug that would otherwise
inflate measured edge.

Roadmap pointer: Edge-Validation Roadmap, Phase 1 / story EV-04.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date, datetime
from typing import Any

# Accepted timestamp representations. Strings must be ISO-8601.
TimestampLike = datetime | date | str


class LookaheadError(ValueError):
    """Raised when one or more records carry a timestamp after the as-of boundary.

    ``violations`` holds the offending (index, parsed-timestamp) pairs so a
    caller can log exactly which records leaked future information.
    """

    def __init__(
        self,
        as_of: datetime,
        violations: Sequence[tuple[int, datetime]],
        *,
        label: str = "record",
    ) -> None:
        self.as_of = as_of
        self.violations = list(violations)
        self.label = label
        preview = ", ".join(
            f"#{idx}@{ts.isoformat()}" for idx, ts in self.violations[:5]
        )
        more = "" if len(self.violations) <= 5 else f" (+{len(self.violations) - 5} more)"
        super().__init__(
            f"{len(self.violations)} {label}(s) carry a timestamp after "
            f"as_of={as_of.isoformat()} (lookahead leak): {preview}{more}"
        )


def _to_datetime(value: TimestampLike) -> datetime:
    """Coerce a supported timestamp representation to a ``datetime``.

    ``date`` is widened to midnight. Naive and tz-aware values are compared
    as-is; callers MUST keep both sides in the same convention (the guard
    refuses to silently mix the two — see :func:`_compare`).
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    raise TypeError(f"unsupported timestamp type: {type(value).__name__}")


def _compare(ts: datetime, as_of: datetime) -> bool:
    """Return True iff ``ts`` is strictly after ``as_of`` (a leak).

    Refuses to compare a naive timestamp against a tz-aware boundary (or
    vice versa): a silent naive/aware mismatch is itself a latent
    correctness bug, so we surface it loudly rather than guess.
    """
    if (ts.tzinfo is None) != (as_of.tzinfo is None):
        raise ValueError(
            "cannot compare naive and tz-aware timestamps; normalise both "
            f"to the same convention (ts.tzinfo={ts.tzinfo!r}, "
            f"as_of.tzinfo={as_of.tzinfo!r})"
        )
    return ts > as_of


def assert_point_in_time(
    timestamps: Iterable[TimestampLike],
    as_of: TimestampLike,
    *,
    label: str = "record",
) -> None:
    """Raise :class:`LookaheadError` if any timestamp is after ``as_of``.

    A no-op on an empty iterable. Use this as a tripwire around any
    sequence of feature/news/label timestamps before they feed a
    backtest metric.
    """
    boundary = _to_datetime(as_of)
    violations: list[tuple[int, datetime]] = []
    for idx, raw in enumerate(timestamps):
        ts = _to_datetime(raw)
        if _compare(ts, boundary):
            violations.append((idx, ts))
    if violations:
        raise LookaheadError(boundary, violations, label=label)


def assert_records_point_in_time(
    records: Iterable[Mapping[str, Any]],
    as_of: TimestampLike,
    *,
    timestamp_key: str,
    label: str = "record",
) -> None:
    """Mapping-aware variant of :func:`assert_point_in_time`.

    Extracts ``timestamp_key`` from each record. A record missing the key
    or carrying ``None`` is treated as a hard error (a record whose
    point-in-time validity cannot be established must not pass silently).
    """
    boundary = _to_datetime(as_of)
    violations: list[tuple[int, datetime]] = []
    for idx, record in enumerate(records):
        if timestamp_key not in record or record[timestamp_key] is None:
            raise ValueError(
                f"{label} #{idx} is missing required timestamp key "
                f"{timestamp_key!r}; cannot establish point-in-time validity"
            )
        ts = _to_datetime(record[timestamp_key])
        if _compare(ts, boundary):
            violations.append((idx, ts))
    if violations:
        raise LookaheadError(boundary, violations, label=label)


def filter_point_in_time[T](
    records: Sequence[T],
    as_of: TimestampLike,
    *,
    key: Any,
) -> list[T]:
    """Return only records whose timestamp is at or before ``as_of``.

    ``key`` is a callable mapping a record to its :data:`TimestampLike`
    timestamp. Unlike the ``assert_*`` guards this *intentionally* drops
    future records — use it only for deliberate windowing (mirroring
    ``databento_reference``'s inline ``date <= as_of`` filter), never as a
    substitute for the tripwire on data that should already be clean.
    """
    boundary = _to_datetime(as_of)
    kept: list[T] = []
    for record in records:
        ts = _to_datetime(key(record))
        if not _compare(ts, boundary):
            kept.append(record)
    return kept


__all__ = [
    "LookaheadError",
    "TimestampLike",
    "assert_point_in_time",
    "assert_records_point_in_time",
    "filter_point_in_time",
]
