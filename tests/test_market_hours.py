from __future__ import annotations

import datetime

import services.live_overlay_daemon.market_hours as mh


def test_zoneinfo_tzdata_is_available_for_market_timezones() -> None:
    """Guard against containers without IANA tzdata that silently fall back to UTC.

    If ZoneInfo cannot resolve America/New_York, market_hours.py falls back to
    a fixed 13:30-20:00 UTC window.  That makes the dashboard report
    MARKET_CLOSED during the real 09:30-16:00 ET session.  This test pins the
    presence of the timezone database (system or tzdata PyPI fallback).
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
