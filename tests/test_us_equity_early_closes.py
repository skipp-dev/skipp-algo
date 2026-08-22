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
    FULL_CLOSURES_ET,
    close_time_et_hhmm,
    flatten_target_et_hhmm,
    is_trading_day,
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


def test_full_closures_are_not_trading_days() -> None:
    """Die Menge, die den Grenzgaenger-Sweep 2026-08-22 ausgeloest hat.

    Vor dem Fix lieferte close_time_et_hhmm hier 16:00, 15:45 lag davor, und
    der EOD-Flatten feuerte am Feiertag: reqGlobalCancel toetet die GTC-Exits,
    schliessen kann er nichts. Ueber die VOLLE Menge pruefen, nicht an einem
    Beispiel — genau ein vergessener Tag reicht fuer den Schaden.
    """
    open_on_a_holiday = sorted(d.isoformat() for d in FULL_CLOSURES_ET if is_trading_day(d))
    assert not open_on_a_holiday, (
        f"is_trading_day meldet Handel an Ganztags-Schliessungen: {open_on_a_holiday}"
    )


def test_a_regular_weekday_is_a_trading_day() -> None:
    """Positivkontrolle: der Guard darf nicht einfach immer 'zu' sagen."""
    assert is_trading_day(date(2026, 8, 19))
    assert is_trading_day(date(2026, 11, 27))  # Halbtag handelt, nur kuerzer


def test_weekends_are_not_trading_days() -> None:
    assert not is_trading_day(date(2026, 8, 22))  # Samstag
    assert not is_trading_day(date(2026, 8, 23))  # Sonntag


def test_cli_exposes_the_trading_day_predicate_to_the_shell(capsys) -> None:
    """run-c13-eod-flatten.sh entscheidet daran, ob es ueberhaupt startet."""
    assert main(["--date", "2026-09-07", "--print", "trading-day"]) == 0
    assert capsys.readouterr().out.strip() == "0"
    assert main(["--date", "2026-08-19", "--print", "trading-day"]) == 0
    assert capsys.readouterr().out.strip() == "1"


def test_no_full_closure_is_also_listed_as_an_early_close() -> None:
    """Ein Tag kann nicht gleichzeitig halb und ganz geschlossen sein."""
    both = sorted(d.isoformat() for d in FULL_CLOSURES_ET & EARLY_CLOSES_ET_1300)
    assert not both, f"Tag steht in beiden Mengen: {both}"


def test_every_entry_lies_inside_the_maintained_horizon() -> None:
    outside = sorted(
        d.isoformat() for d in (EARLY_CLOSES_ET_1300 | FULL_CLOSURES_ET) if d > CALENDAR_HORIZON
    )
    assert not outside, (
        f"calendar entries beyond CALENDAR_HORIZON: {outside} — either the "
        "horizon is stale or an entry is a typo."
    )


def test_calendar_horizon_not_expired() -> None:
    """ABSICHTLICHER Stolperdraht, kein Bug: dieser Test wird eines Tages rot.

    Dann ist der Kalender nicht mehr gepflegt und das EOD-Flatten wuerde am
    naechsten unbekannten Halbtag ODER Feiertag seinen Schutzauftrag
    invertieren (GTC-Exits canceln, nichts mehr schliessen koennen).
    Reparatur: NYSE-Kalender pruefen (https://www.nyse.com/markets/hours-calendars),
    EARLY_CLOSES_ET_1300 UND FULL_CLOSURES_ET fuers Folgejahr ergaenzen,
    CALENDAR_HORIZON weiterschieben — im selben PR.
    """
    assert date.today() <= CALENDAR_HORIZON, (
        "Der US-Handelskalender ist abgelaufen "
        f"(Horizont {CALENDAR_HORIZON.isoformat()}). NYSE-Kalender pruefen, "
        "EARLY_CLOSES_ET_1300 und FULL_CLOSURES_ET ergaenzen, "
        "CALENDAR_HORIZON weiterschieben."
    )
