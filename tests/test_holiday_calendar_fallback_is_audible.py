"""Der Feiertagskalender darf nicht STILL nach "offen" ausfallen.

2026-08-20 (Deep-Review des Serve-Pfads, Nebenfund zu (a)).
``_holiday_dates_for_year`` gibt eine leere Menge zurueck, wenn das Paket
fehlt ODER die Bibliothek wirft — beides ohne ein Wort. Der Rueckfall selbst
ist richtig: ein fehlender Kalender darf den Daemon nicht abschiessen. Aber er
ist fail-OPEN, und diese Richtung ist teuer:

    leerer Kalender -> is_us_regular_session_open() ist an Weihnachten True
    -> der Self-Heal-Supervisor sieht eine "stehende" Leitung auf einem
       geschlossenen Markt
    -> drei Heilversuche, dann os._exit
    -> Railway gibt nach restartPolicyMaxRetries = 3 auf
    -> der Dienst bleibt unten, an einem Tag, an dem niemand hinschaut.

Produktiv ist das Paket da (``holidays==0.102`` steht in beiden
requirements.txt UND im requirements.lock — gemessen), der Defekt ist also
latent: ein Import-Fehler, ein API-Bruch beim naechsten Bump oder eine
Ausnahme in ``financial_holidays`` wuerde heute lautlos passieren.

Mess-Falle, die diesen Fund fast verdeckt haette: im Repo-``.venv`` ist
``holidays`` GAR NICHT installiert. Jeder lokale Lauf faehrt also den
Rueckfallpfad, und alle 17 Tests in ``tests/test_market_hours.py`` bleiben
gruen, weil sie ``_holiday_dates_for_year`` monkeypatchen. Ein Test, der sich
auf die Umgebung verlaesst, misst hier nichts — deshalb setzt dieser die
Zustaende ausdruecklich selbst.
"""

from __future__ import annotations

import logging

import pytest

from services.live_overlay_daemon import market_hours


@pytest.fixture(autouse=True)
def _reset_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Das Degradations-Flag ist Modulzustand — jeder Test startet gesund."""
    monkeypatch.setitem(market_hours._holiday_calendar_state, "degraded", False)
    market_hours._holiday_dates_for_year.cache_clear()
    yield
    market_hours._holiday_dates_for_year.cache_clear()


def test_a_healthy_lookup_leaves_the_calendar_reported_as_loaded() -> None:
    """Positivkontrolle. Ohne sie waere der Test unten auch dann gruen, wenn
    das Flag schlicht immer auf "kaputt" stuende."""

    class _Calendar(dict):
        pass

    fake = type(
        "_FakeHolidays",
        (),
        {"financial_holidays": staticmethod(lambda *a, **k: _Calendar())},
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(market_hours, "_holidays", fake)
        market_hours._holiday_dates_for_year("NYSE", 2026)
    assert market_hours.holiday_calendar_loaded() is True


def test_a_missing_package_is_reported_and_logged(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING), pytest.MonkeyPatch.context() as mp:
        mp.setattr(market_hours, "_holidays", None)
        assert market_hours._holiday_dates_for_year("NYSE", 2026) == frozenset()

    assert market_hours.holiday_calendar_loaded() is False, (
        "der Rueckfall auf einen leeren Kalender blieb unsichtbar"
    )
    assert any("Holiday calendar unavailable" in record.message for record in caplog.records)


def test_a_throwing_library_is_reported_too() -> None:
    """Nicht nur das fehlende Paket — auch ein API-Bruch beim naechsten Bump."""

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("financial_holidays signature changed")

    fake = type("_FakeHolidays", (), {"financial_holidays": staticmethod(_boom)})
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(market_hours, "_holidays", fake)
        assert market_hours._holiday_dates_for_year("NYSE", 2026) == frozenset()

    assert market_hours.holiday_calendar_loaded() is False


def test_the_flag_reaches_the_metrics_surface() -> None:
    """Ein Flag, das niemand exportiert, ist gruen ohne Beobachtung."""
    from services.live_overlay_daemon import metrics

    source = metrics.__file__
    with open(source, encoding="utf-8") as handle:
        text = handle.read()
    assert "live_overlay_market_holiday_calendar_loaded" in text, (
        "die Kennzahl fehlt im Exporter — der Alarm koennte nie feuern"
    )
