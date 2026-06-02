"""EV-04 — point-in-time / lookahead integrity guard tests.

Includes the critical *negative control*: injecting a future timestamp
MUST raise, proving the tripwire actually bites. Lives in the fast
(``not slow``) partition.
"""
from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from governance.point_in_time import (
    LookaheadError,
    assert_point_in_time,
    assert_records_point_in_time,
    filter_point_in_time,
    observed_span_seconds,
)

AS_OF = datetime(2026, 5, 31, 16, 0, 0)


# ── assert_point_in_time ────────────────────────────────────────────────


def test_clean_timestamps_pass() -> None:
    assert_point_in_time(
        [datetime(2026, 5, 31, 15, 59), datetime(2026, 5, 30)], AS_OF
    )


def test_timestamp_exactly_at_boundary_passes() -> None:
    # at-or-before contract: equality is valid, not a leak.
    assert_point_in_time([AS_OF], AS_OF)


def test_empty_is_noop() -> None:
    assert_point_in_time([], AS_OF)


def test_future_timestamp_raises_negative_control() -> None:
    with pytest.raises(LookaheadError) as exc:
        assert_point_in_time(
            [datetime(2026, 5, 31, 15, 0), datetime(2026, 5, 31, 16, 0, 1)],
            AS_OF,
        )
    assert exc.value.violations == [(1, datetime(2026, 5, 31, 16, 0, 1))]


def test_iso_string_and_date_inputs() -> None:
    assert_point_in_time(["2026-05-30T12:00:00", date(2026, 5, 29)], AS_OF)
    with pytest.raises(LookaheadError):
        assert_point_in_time(["2026-06-01T00:00:00"], AS_OF)


def test_bare_date_as_of_includes_same_day_intraday() -> None:
    # A bare-date as_of means "through end of that day"; same-day intraday
    # timestamps must NOT be flagged as future leaks (EOD boundary semantics).
    assert_point_in_time(
        [datetime(2026, 5, 31, 15, 0), datetime(2026, 5, 31, 23, 59, 59)],
        date(2026, 5, 31),
    )
    # A date-only ISO string boundary behaves identically.
    assert_point_in_time([datetime(2026, 5, 31, 15, 0)], "2026-05-31")
    # The next calendar day is still a leak.
    with pytest.raises(LookaheadError):
        assert_point_in_time([datetime(2026, 6, 1, 0, 0, 1)], date(2026, 5, 31))


def test_naive_vs_aware_mismatch_is_loud() -> None:
    aware = datetime(2026, 5, 31, 12, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="naive and tz-aware"):
        assert_point_in_time([aware], AS_OF)


# ── assert_records_point_in_time ────────────────────────────────────────


def test_records_clean_pass() -> None:
    records = [{"ts": "2026-05-30T09:30:00"}, {"ts": "2026-05-31T15:00:00"}]
    assert_records_point_in_time(records, AS_OF, timestamp_key="ts")


def test_records_future_raises() -> None:
    records = [{"ts": "2026-05-31T15:00:00"}, {"ts": "2026-06-02T09:30:00"}]
    with pytest.raises(LookaheadError):
        assert_records_point_in_time(records, AS_OF, timestamp_key="ts")


def test_records_missing_key_is_hard_error() -> None:
    with pytest.raises(ValueError, match="missing required timestamp key"):
        assert_records_point_in_time([{"other": 1}], AS_OF, timestamp_key="ts")


def test_records_none_timestamp_is_hard_error() -> None:
    with pytest.raises(ValueError, match="missing required timestamp key"):
        assert_records_point_in_time([{"ts": None}], AS_OF, timestamp_key="ts")


# ── filter_point_in_time ────────────────────────────────────────────────


def test_filter_drops_future_keeps_boundary() -> None:
    records = [
        {"ts": datetime(2026, 5, 30)},
        {"ts": AS_OF},                       # boundary kept
        {"ts": datetime(2026, 6, 1)},        # future dropped
    ]
    kept = filter_point_in_time(records, AS_OF, key=lambda r: r["ts"])
    assert [r["ts"] for r in kept] == [datetime(2026, 5, 30), AS_OF]


def test_filter_empty() -> None:
    assert filter_point_in_time([], AS_OF, key=lambda r: r) == []


# ── observed_span_seconds ───────────────────────────────────────────────


def test_observed_span_seconds_measures_range() -> None:
    span = observed_span_seconds(
        [datetime(2026, 5, 1), datetime(2026, 5, 3), datetime(2026, 5, 2)]
    )
    assert span == 2 * 24 * 60 * 60  # 1 May → 3 May = 2 days


def test_observed_span_seconds_iso_strings() -> None:
    span = observed_span_seconds(
        ["2026-05-01T00:00:00", "2026-05-01T01:00:00"]
    )
    assert span == 60 * 60  # one hour


def test_observed_span_seconds_single_instant_is_none() -> None:
    assert observed_span_seconds([datetime(2026, 5, 1)]) is None


def test_observed_span_seconds_zero_span_is_none() -> None:
    # All identical timestamps → collapsed span → None (no cadence).
    same = datetime(2026, 5, 1, 12, 0, 0)
    assert observed_span_seconds([same, same, same]) is None


def test_observed_span_seconds_empty_is_none() -> None:
    assert observed_span_seconds([]) is None
