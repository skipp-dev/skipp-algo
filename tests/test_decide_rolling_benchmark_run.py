"""Die Kadenz-Entscheidung des Rolling-Benchmarks, tabellengetrieben.

Der Workflow feuerte bis zu neunmal je Werktag (``workflow_run`` je
Producer-Tick), obwohl sein Kopfkommentar von zwei Laeufen ausgeht — eine
Praemisse aus der Zeit, als der Producer 2x lief. Gemessen 2026-08-29: acht
Laeufe an einem Werktag, 366 Runner-Minuten.

Zwei Laeufe genuegen, aber es muessen die richtigen zwei sein: einer im
Fenster 11:00-12:30 UTC fuer die drei Tages-Gates (13:30/14:00/15:00), einer
ab 20:00 UTC fuer die nachgereiften Labels des 5-Tage-Ankerfensters.

Diese Datei prueft die ENTSCHEIDUNG, nicht den Shell-Code drumherum — sie ist
eine reine Funktion, damit genau das moeglich ist.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from scripts.decide_rolling_benchmark_run import decide

UTC = _dt.UTC


def _at(hhmm: str) -> _dt.datetime:
    h, m = hhmm.split(":")
    return _dt.datetime(2026, 8, 31, int(h), int(m), tzinfo=UTC)


def _run(hhmm: str, conclusion: str = "success") -> dict:
    return {"conclusion": conclusion, "created_at": f"2026-08-31T{hhmm}:00Z"}


@pytest.mark.parametrize(
    ("label", "now", "runs", "expect_run", "expect_window"),
    [
        # --- Fenster A -----------------------------------------------------
        ("leerer Tag, mitten in A", "11:30", [], True, "A"),
        ("leerer Tag, A-Untergrenze", "11:00", [], True, "A"),
        ("A bereits bedient", "12:00", [_run("11:10")], False, "A"),
        # --- vor A ---------------------------------------------------------
        ("zu frueh: 08-Tick", "09:05", [], False, "none"),
        ("zu frueh: knapp davor", "10:59", [], False, "none"),
        # --- Netz ----------------------------------------------------------
        ("A verpasst, Nachmittag", "14:10", [], True, "net"),
        ("A verpasst, Sicherheits-Cron", "16:30", [], True, "net"),
        ("A bedient, Nachmittag", "16:30", [_run("11:10")], False, "A"),
        # --- Fenster B -----------------------------------------------------
        ("B offen, A war bedient", "20:30", [_run("11:10")], True, "B"),
        ("B offen, Tag war leer", "21:05", [], True, "B"),
        ("B bereits bedient", "22:10", [_run("11:10"), _run("20:30")], False, "B"),
        # Ein FEHLGESCHLAGENER Lauf zaehlt nicht als bedient.
        ("nur Fehlschlag in A", "12:00", [_run("11:10", "failure")], True, "A"),
    ],
)
def test_the_two_windows(label, now, runs, expect_run, expect_window) -> None:
    d = decide(
        now=_at(now), event_name="workflow_run",
        producer_conclusion="success", todays_runs=runs,
    )
    assert d.run is expect_run, f"{label}: {d.reason}"
    assert d.window == expect_window, f"{label}: {d.reason}"


def test_a_failed_producer_never_runs() -> None:
    """Bestehende Bedingung, unveraendert: kein Producer-Erfolg, kein Lauf."""
    for conclusion in ("failure", "cancelled", "skipped", None):
        d = decide(
            now=_at("11:30"), event_name="workflow_run",
            producer_conclusion=conclusion, todays_runs=[],
        )
        assert d.run is False, conclusion


def test_a_manual_dispatch_always_runs() -> None:
    """Das Gate steht nicht zwischen Operator und Werkzeug."""
    d = decide(
        now=_at("03:00"), event_name="workflow_dispatch",
        producer_conclusion=None, todays_runs=[_run("11:10"), _run("20:30")],
    )
    assert d.run is True
    assert d.window == "manual"


# ---------------------------------------------------------------------------
# Positivkontrollen — ohne sie waere der Rest wertlos.
# ---------------------------------------------------------------------------


def test_blindness_runs_rather_than_skips() -> None:
    """Die wichtigste Eigenschaft: bei Unwissen wird GELAUFEN.

    Ein Gate, das ueberspringt, wenn es den Tageszustand nicht lesen kann,
    stoppt den Benchmark still und dauerhaft — und das Freshness-Budget stand
    bis 2026-08-29 auf ``:any``, haette also nichts gemeldet. Ein
    ueberfluessiger Lauf kostet 46 Minuten; ein stiller Stopp kostet die
    Drift-Erkennung, fuer die dieser Workflow existiert.
    """
    for when in ("03:00", "11:30", "16:30", "22:00"):
        d = decide(
            now=_at(when), event_name="workflow_run",
            producer_conclusion="success", todays_runs=None,
        )
        assert d.run is True, when
        assert d.window == "blind"


def test_a_day_without_any_success_always_gets_a_run_after_window_a_opens() -> None:
    """Kein Tag darf still ohne Schnappschuss bleiben.

    Ab Fenster-A-Beginn muss JEDE Stunde bis Mitternacht zu einem Lauf
    fuehren, solange der Tag keinen Erfolg trug — sonst koennte eine
    unglueckliche Fire-Verteilung einen ganzen Tag verschlucken.
    """
    for hour in range(11, 24):
        d = decide(
            now=_at(f"{hour:02d}:15"), event_name="workflow_run",
            producer_conclusion="success", todays_runs=[],
        )
        assert d.run is True, f"{hour}:15 wuerde einen leeren Tag durchlassen"


def test_the_happy_path_costs_exactly_two_runs() -> None:
    """Die Zusage des Entwurfs, an der Regel selbst geprueft.

    Neun Producer-Ticks, alle erfolgreich, Fires jeweils ~60 min spaeter.
    Genau zwei duerfen durchkommen.
    """
    fires = ["09:00", "11:00", "13:00", "15:00", "17:00", "19:00", "21:00", "22:00", "23:00"]
    runs: list[dict] = []
    ran: list[str] = []
    for fire in fires:
        d = decide(
            now=_at(fire), event_name="workflow_run",
            producer_conclusion="success", todays_runs=list(runs),
        )
        if d.run:
            ran.append(f"{fire}/{d.window}")
            runs.append(_run(fire))
    assert ran == ["11:00/A", "21:00/B"], ran
