"""Kalender-Wahrheit + Horizont-Stolperdraht fuer die US-Fruehschluesse.

Der Kalender in scripts/us_equity_early_closes.py ist handgepflegt; dieser
Test ist der Mechanismus, der ihn am Verrotten hindert (Repo-Regel
"Zukunfts-Prosa braucht Mechanismus"): laeuft der Horizont ab, roetet
test_calendar_horizon_not_expired mit der Verlaengerungs-Anweisung.
"""

from __future__ import annotations

from datetime import date

from scripts.us_equity_early_closes import (
    CALENDAR_HORIZON,
    EARLY_CLOSES_ET_1300,
    close_time_et_hhmm,
    flatten_target_et_hhmm,
    main,
)


def test_known_early_closes_get_the_1300_close() -> None:
    assert close_time_et_hhmm(date(2026, 11, 27)) == (13, 0)
    assert close_time_et_hhmm(date(2026, 12, 24)) == (13, 0)
    assert close_time_et_hhmm(date(2027, 11, 26)) == (13, 0)


def test_a_regular_day_keeps_the_1600_close() -> None:
    assert close_time_et_hhmm(date(2026, 8, 19)) == (16, 0)


def test_flatten_target_is_15_minutes_before_the_close() -> None:
    assert flatten_target_et_hhmm(date(2026, 8, 19)) == (15, 45)
    assert flatten_target_et_hhmm(date(2026, 11, 27)) == (12, 45)


def test_cli_prints_gate_consumable_target(capsys) -> None:
    assert main(["--date", "2026-11-27"]) == 0
    assert capsys.readouterr().out.strip() == "12 45"
    assert main(["--date", "2026-08-19"]) == 0
    assert capsys.readouterr().out.strip() == "15 45"
    assert main(["--date", "2026-12-24", "--print", "close"]) == 0
    assert capsys.readouterr().out.strip() == "13 00"


def test_every_entry_lies_inside_the_maintained_horizon() -> None:
    outside = sorted(d.isoformat() for d in EARLY_CLOSES_ET_1300 if d > CALENDAR_HORIZON)
    assert not outside, (
        f"early-close entries beyond CALENDAR_HORIZON: {outside} — either the "
        "horizon is stale or an entry is a typo."
    )


def test_calendar_horizon_not_expired() -> None:
    """ABSICHTLICHER Stolperdraht, kein Bug: dieser Test wird eines Tages rot.

    Dann ist der Fruehschluss-Kalender nicht mehr gepflegt und das EOD-Flatten
    wuerde am naechsten unbekannten Halbtag seinen Schutzauftrag invertieren
    (GTC-Exits nach 13:00-Close canceln, nichts mehr schliessen koennen).
    Reparatur: NYSE-Kalender pruefen (https://www.nyse.com/markets/hours-calendars),
    EARLY_CLOSES_ET_1300 fuer das Folgejahr ergaenzen, CALENDAR_HORIZON
    weiterschieben — im selben PR.
    """
    assert date.today() <= CALENDAR_HORIZON, (
        "Der US-Fruehschluss-Kalender ist abgelaufen "
        f"(Horizont {CALENDAR_HORIZON.isoformat()}). NYSE-Kalender pruefen, "
        "EARLY_CLOSES_ET_1300 ergaenzen, CALENDAR_HORIZON weiterschieben."
    )
