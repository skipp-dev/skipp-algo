from __future__ import annotations

import datetime

import pytest

import services.live_overlay_daemon.market_hours as mh


def test_zoneinfo_tzdata_is_available_for_market_timezones() -> None:
    """Guard against containers without IANA tzdata that silently fall back to UTC.

    Market-hours code fails closed if this database is unavailable; it never
    substitutes a fixed UTC offset.
    """
    from zoneinfo import ZoneInfo

    tz = ZoneInfo("America/New_York")
    # A concrete timezone must know DST transitions; fixed-offset fallbacks do not.
    assert str(tz) == "America/New_York"
    dt = datetime.datetime(2026, 6, 15, 12, 0, tzinfo=tz)
    assert dt.tzname() in ("EDT", "EST")


def test_us_session_closed_on_holiday_during_regular_hours(monkeypatch) -> None:
    holiday_date = datetime.date(2026, 7, 3)

    monkeypatch.setattr(
        mh,
        "_holiday_dates_for_year",
        lambda code, year: frozenset({holiday_date}) if code == "NYSE" and year == 2026 else frozenset(),
    )

    # 15:00 UTC -> 11:00 ET (inside regular session window).
    now_utc = datetime.datetime(2026, 7, 3, 15, 0, tzinfo=datetime.UTC)
    assert mh.is_us_regular_session_open(now_utc) is False


def test_us_session_open_on_non_holiday_during_regular_hours(monkeypatch) -> None:
    monkeypatch.setattr(mh, "_holiday_dates_for_year", lambda code, year: frozenset())

    # 15:00 UTC -> 11:00 ET (inside regular session window).
    now_utc = datetime.datetime(2026, 7, 2, 15, 0, tzinfo=datetime.UTC)
    assert mh.is_us_regular_session_open(now_utc) is True


def test_us_and_europe_dst_are_resolved_independently_in_march(monkeypatch) -> None:
    monkeypatch.setattr(mh, "_holiday_dates_for_year", lambda code, year: frozenset())

    # 2026-03-20: US is already on EDT, UK is still on GMT. At 13:45 UTC
    # New York is open (09:45), while treating both regions as if they switched
    # together would place the US open one hour late.
    instant = datetime.datetime(2026, 3, 20, 13, 45, tzinfo=datetime.UTC)
    assert mh.is_us_regular_session_open(instant) is True
    assert mh.is_europe_regular_session_open(instant) is True
    # London is still on GMT, so 07:30 UTC is before its 08:00 local open.
    assert mh.is_europe_regular_session_open(
        datetime.datetime(2026, 3, 20, 7, 30, tzinfo=datetime.UTC)
    ) is False


def test_us_and_europe_dst_are_resolved_independently_in_autumn(monkeypatch) -> None:
    monkeypatch.setattr(mh, "_holiday_dates_for_year", lambda code, year: frozenset())

    # 2026-10-30: UK is back on GMT while New York remains on EDT until Nov 1.
    instant = datetime.datetime(2026, 10, 30, 13, 45, tzinfo=datetime.UTC)
    assert mh.is_us_regular_session_open(instant) is True
    assert mh.is_europe_regular_session_open(instant) is True
    # Europe has already left summer time; New York has not.
    assert mh.is_europe_regular_session_open(
        datetime.datetime(2026, 10, 30, 7, 30, tzinfo=datetime.UTC)
    ) is False


def test_market_hours_reject_naive_datetime() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        mh.is_us_regular_session_open(datetime.datetime(2026, 7, 2, 15, 0))


def test_market_hours_fail_closed_without_iana_tzdata(monkeypatch) -> None:
    def missing(_zone_name: str):
        raise mh.ZoneInfoNotFoundError("missing test tzdata")

    monkeypatch.setattr(mh, "ZoneInfo", missing)
    with pytest.raises(RuntimeError, match="fixed UTC"):
        mh.is_us_regular_session_open(
            datetime.datetime(2026, 7, 2, 15, 0, tzinfo=datetime.UTC)
        )


def test_europe_session_closed_on_holiday_during_regular_hours(monkeypatch) -> None:
    holiday_date = datetime.date(2026, 12, 25)

    monkeypatch.setattr(
        mh,
        "_holiday_dates_for_year",
        lambda code, year: frozenset({holiday_date}) if code == "GB" and year == 2026 else frozenset(),
    )

    # 10:00 UTC -> 10:00 London (inside regular session window).
    now_utc = datetime.datetime(2026, 12, 25, 10, 0, tzinfo=datetime.UTC)
    assert mh.is_europe_regular_session_open(now_utc) is False


def test_asia_session_closed_on_holiday_during_regular_hours(monkeypatch) -> None:
    holiday_date = datetime.date(2026, 1, 1)

    monkeypatch.setattr(
        mh,
        "_holiday_dates_for_year",
        lambda code, year: frozenset({holiday_date}) if code == "JP" and year == 2026 else frozenset(),
    )

    # 01:00 UTC -> 10:00 Tokyo (inside regular session window).
    now_utc = datetime.datetime(2026, 1, 1, 1, 0, tzinfo=datetime.UTC)
    assert mh.is_asia_regular_session_open(now_utc) is False
