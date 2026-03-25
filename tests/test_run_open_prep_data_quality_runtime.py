from __future__ import annotations

from datetime import date

import open_prep.run_open_prep as rop


class _FakeUDClient:
    def __init__(self, rows):
        self._rows = rows

    def get_upgrades_downgrades(self, *, date_from, date_to):
        return list(self._rows)


class _FakeHouseClient:
    def __init__(self, rows):
        self._rows = rows

    def get_house_trading(self, *, limit):
        return list(self._rows)


def test_tomorrow_outlook_matches_us_and_iso_date_formats() -> None:
    today = date(2026, 3, 25)
    earnings_calendar = [
        {"date": "03/26/2026", "earnings_timing": "bmo"},
        {"date": "2026-03-26T20:00:00Z", "earnings_timing": "amc"},
        {"date": "2026-03-25", "earnings_timing": "bmo"},
    ]
    all_range_events = [
        {"date": "03/26/2026 08:30:00", "impact": "High", "event": "PCE"},
        {"date": "2026-03-25 14:00:00", "impact": "High", "event": "Old"},
    ]

    outlook = rop._compute_tomorrow_outlook(
        today=today,
        macro_bias=0.0,
        earnings_calendar=earnings_calendar,
        ranked=[{"long_allowed": True}],
        all_range_events=all_range_events,
    )

    assert outlook["next_trading_day"] == "2026-03-26"
    assert outlook["earnings_tomorrow_count"] == 2
    assert outlook["earnings_bmo_tomorrow_count"] == 1
    assert outlook["high_impact_events_tomorrow"] == 1


def test_upgrades_downgrades_selects_latest_by_date_not_row_position() -> None:
    client = _FakeUDClient(
        [
            {
                "symbol": "AAPL",
                "action": "downgraded",
                "gradingCompany": "Older Firm",
                "publishedDate": "2026-03-24 09:00:00",
            },
            {
                "symbol": "AAPL",
                "action": "upgrade",
                "gradingCompany": "Newer Firm",
                "publishedDate": "2026-03-25 15:30:00",
            },
        ]
    )

    data = rop._fetch_upgrades_downgrades(
        client=client,  # type: ignore[arg-type]
        symbols=["AAPL"],
        today=date(2026, 3, 25),
    )

    assert "AAPL" in data
    assert data["AAPL"]["upgrade_downgrade_label"] == "upgrade"
    assert data["AAPL"]["upgrade_downgrade_firm"] == "Newer Firm"
    assert data["AAPL"]["upgrade_downgrade_count"] == 2


def test_house_trading_filters_stale_disclosures_by_lookback_window() -> None:
    today = date(2026, 3, 25)
    client = _FakeHouseClient(
        [
            {
                "symbol": "AAPL",
                "transactionType": "Purchase",
                "transactionDate": "2026-03-20",
            },
            {
                "symbol": "AAPL",
                "transactionType": "Sale",
                "transactionDate": "2025-08-01",
            },
            {
                "symbol": "MSFT",
                "transactionType": "Sale",
                "transactionDate": "2025-07-15",
            },
        ]
    )

    data = rop._fetch_house_trading(
        client=client,  # type: ignore[arg-type]
        symbols=["AAPL", "MSFT"],
        today=today,
        lookback_days=90,
    )

    assert data["AAPL"]["house_buys"] == 1
    assert data["AAPL"]["house_sells"] == 0
    assert data["AAPL"]["house_net"] == 1
    assert "MSFT" not in data
